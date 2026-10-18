"""Optional native output observer for an already running Lift Trace server.

Reads only loopback GET /api/status and /api/events. It creates no HTTP server,
controller poller, UI, settings file, automation or recording controller. The
existing application remains usable when this observer is absent or fails.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import http.client
import json
import os
from pathlib import Path
import queue
import socket
import threading
import time

from live_bridge import NativePipeline, validate_channel

MAX_LINE = 128 * 1024
QUEUE_SIZE = 256


def reject_constant(_value):
    raise ValueError("Non-finite JSON number.")


class DuplicateObserver(RuntimeError):
    pass


class ObserverLease:
    """A process-owned object lease held across every network reconnect."""

    def __init__(self, channel):
        validate_channel(channel)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel.CloseHandle.restype = wintypes.BOOL
        ctypes.set_last_error(0)
        self.handle = self.kernel.CreateMutexW(None, False, "Local\\LiftTraceNative-" + channel + "-observer")
        error = ctypes.get_last_error()
        if not self.handle:
            raise OSError("Could not acquire the optional observer lease.")
        if error == 183:
            self.close()
            raise DuplicateObserver("This channel already has an observer.")

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def acquire_lease(channel, owner, *, factory=ObserverLease, clock=time.monotonic, wait=time.sleep):
    # A quickly reopened OBS can overlap the old observer's bounded cleanup.
    # Wait briefly without any status/network/Node side effects. Standalone
    # duplicates still return immediately, and an exited new owner cancels it.
    deadline = clock() + 5
    while True:
        if owner is not None and not owner.alive():
            raise RuntimeError("The original OBS process has exited.")
        try:
            return factory(channel)
        except DuplicateObserver:
            remaining = deadline - clock()
            if owner is None or remaining <= 0:
                raise
            wait(min(.1, remaining))


class WindowsOwner:
    """Hold the exact original process, not a PID that can later be reused."""

    def __init__(self, pid: int, expected_start_ticks: int):
        if os.name != "nt":
            raise RuntimeError("OBS process ownership currently requires Windows.")
        self.pid = pid
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
        self.kernel.GetProcessTimes.restype = wintypes.BOOL
        self.kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.OpenProcess(0x100000 | 0x1000, False, pid)
        if not self.handle:
            raise RuntimeError("Could not observe the original OBS process without elevation.")
        try:
            created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
            if not self.kernel.GetProcessTimes(self.handle, ctypes.byref(created), ctypes.byref(exited),
                                               ctypes.byref(kernel), ctypes.byref(user)):
                raise RuntimeError("Could not verify the original OBS process.")
            actual = (created.dwHighDateTime << 32) | created.dwLowDateTime
            if actual != expected_start_ticks or not self.alive():
                raise RuntimeError("The original OBS process has already exited or changed.")
        except BaseException:
            self.close()
            raise

    def alive(self) -> bool:
        return bool(self.handle) and self.kernel.WaitForSingleObject(self.handle, 0) == 258

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class SSEBridge:
    """Duck-typed read-only Bridge subscriber, with one bounded network worker.

    A lost/invalid/overflowing stream ends this connection. The owner loop closes
    the pipeline (clearing the shared snapshot), then reconnects with a new Node
    engine and the server's initial status/settings/demo/latest sequence. Never
    drop arbitrary input events and continue with potentially stuck keys.
    """

    def __init__(self, port: int):
        if not 1 <= port <= 65535:
            raise ValueError("Invalid loopback port.")
        self.port = port
        self.failure: str | None = None
        self.stopping = threading.Event()
        self.queue = queue.Queue(maxsize=QUEUE_SIZE)
        self.thread = None
        self.connection = None
        self.socket = None
        self._connection_lock = threading.Lock()

    def subscribe(self):
        if self.thread is not None:
            raise RuntimeError("This observer supports one owned subscriber.")
        self.thread = threading.Thread(target=self._read, name="native-loopback-observer", daemon=True)
        self.thread.start()
        return self.queue

    def unsubscribe(self, channel):
        if channel is self.queue:
            self.stopping.set()
            self._interrupt_connection()

    def _interrupt_connection(self):
        with self._connection_lock:
            connection = self.connection
            transport = self.socket
        if connection is not None:
            if transport is not None:
                try:
                    transport.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            connection.close()

    def _connect(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2.5)
        with self._connection_lock:
            if self.stopping.is_set():
                connection.close()
                raise OSError("Observer stopped.")
            self.connection = connection
        return connection

    def _request(self, connection, path):
        connection.request("GET", path)
        # The server intentionally sends Connection: close for SSE. http.client
        # then clears connection.sock while its response file still owns the
        # socket. Keep this handle so shutdown interrupts that pending read.
        with self._connection_lock:
            self.socket = connection.sock
        if self.stopping.is_set():
            self._interrupt_connection()
            raise OSError("Observer stopped.")
        return connection.getresponse()

    def _read(self):
        try:
            connection = self._connect()
            response = self._request(connection, "/api/status")
            payload = response.read(32769)
            if response.status != 200 or len(payload) > 32768:
                raise ValueError("Unrecognized local server.")
            status = json.loads(payload)
            if not isinstance(status, dict) or status.get("app") != "lift-trace" or status.get("apiVersion") != 1:
                raise ValueError("Unrecognized local server.")
            connection.close()
            connection = self._connect()
            response = self._request(connection, "/api/events")
            if response.status != 200 or response.getheader("Content-Type", "").split(";", 1)[0].strip() != "text/event-stream":
                raise ValueError("Expected the existing event stream.")
            pieces, length = [], 0
            while not self.stopping.is_set():
                line = response.readline(MAX_LINE + 1)
                if not line or len(line) > MAX_LINE or not line.endswith(b"\n"):
                    raise ValueError("Closed or oversized event stream.")
                line = line.rstrip(b"\r\n")
                if not line:
                    if pieces:
                        event = json.loads(b"\n".join(pieces), parse_constant=reject_constant)
                        if not isinstance(event, dict):
                            raise ValueError("Expected an event object.")
                        self.queue.put_nowait(event)
                    pieces, length = [], 0
                elif line.startswith(b"data:"):
                    piece = line[5:]
                    if piece.startswith(b" "):
                        piece = piece[1:]
                    length += len(piece) + 1
                    if length > MAX_LINE:
                        raise ValueError("Oversized event.")
                    pieces.append(piece)
                # Comments and SSE metadata carry no controller events.
        except Exception:
            if not self.stopping.is_set():
                self.failure = "upstream-stream-unavailable"
        finally:
            self._interrupt_connection()
            if "response" in locals():
                response.close()

    def close(self):
        self.stopping.set()
        self._interrupt_connection()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)


def write_status(path: Path | None, phase: str, *, error: str | None = None, snapshots: int = 0,
                 owned_obs_pid=None, child_pid=None, connected=False):
    """Small optional diagnostics; never include settings, paths or input history."""
    if path is None:
        return
    body = json.dumps({"app": "lift-trace-native-observer", "phase": phase, "pid": os.getpid(),
                       "updatedAt": time.time(), "failure": error, "snapshots": snapshots,
                       "ownedObsPid": owned_obs_pid, "childPid": child_pid,
                       "connected": connected}, separators=(",", ":"))
    temporary = path.with_name(path.name + "." + str(os.getpid()) + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(body, encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        # Diagnostics are optional, including in a read-only installation.
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def observe(node: Path, channel: str, port: int, *, owner=None, status_file=None,
            stopping=None, pipeline_factory=NativePipeline, bridge_factory=SSEBridge):
    stopping = stopping if stopping is not None else threading.Event()
    backoff = .5
    def alive():
        return not stopping.is_set() and (owner is None or owner.alive())
    owner_pid = getattr(owner, "pid", None)
    write_status(status_file, "connecting", owned_obs_pid=owner_pid)
    try:
        while alive():
            bridge, pipeline = bridge_factory(port), None
            started = time.monotonic()
            try:
                pipeline = pipeline_factory(bridge, node, channel)
                pipeline.start()
                next_status = 0.0
                while alive() and not bridge.failure and not pipeline.failure:
                    now = time.monotonic()
                    if now >= next_status:
                        write_status(status_file, "ready" if pipeline.snapshots else "connecting",
                                     snapshots=pipeline.snapshots, owned_obs_pid=owner_pid,
                                     child_pid=pipeline.process.pid, connected=bool(pipeline.snapshots))
                        next_status = now + 1
                    stopping.wait(.1)
            finally:
                # Shared notes are invalidated before closing the network worker.
                if pipeline is not None:
                    pipeline.close()
                bridge.close()
            if not alive():
                break
            error = bridge.failure or (pipeline.failure if pipeline else None) or "observer-unavailable"
            write_status(status_file, "reconnecting", error=error, owned_obs_pid=owner_pid)
            if time.monotonic() - started >= 10:
                backoff = .5
            until = time.monotonic() + backoff
            while alive() and time.monotonic() < until:
                stopping.wait(min(.1, max(0, until - time.monotonic())))
            backoff = min(2, backoff * 2)
    finally:
        write_status(status_file, "stopped", owned_obs_pid=owner_pid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--channel", required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--obs-pid", type=int)
    parser.add_argument("--obs-start-ticks", type=int)
    parser.add_argument("--status-file", type=Path)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Native shared-memory output currently requires Windows.")
    if not 1 <= args.port <= 65535 or not args.node.is_file():
        parser.error("Provide an existing Node executable and a valid loopback port.")
    if (args.obs_pid is None) != (args.obs_start_ticks is None):
        parser.error("--obs-pid and --obs-start-ticks must be supplied together.")
    if args.obs_pid is not None and (args.obs_pid <= 0 or args.obs_start_ticks <= 0):
        parser.error("Invalid original OBS process identity.")
    try:
        validate_channel(args.channel)
    except ValueError as error:
        parser.error(str(error))
    owner, lease = None, None
    try:
        if args.obs_pid is not None:
            owner = WindowsOwner(args.obs_pid, args.obs_start_ticks)
        # Duplicate starts cannot overwrite a healthy instance's diagnostics,
        # create another Node child, or open a second SSE connection.
        lease = acquire_lease(args.channel, owner)
        observe(args.node.resolve(), args.channel, args.port, owner=owner, status_file=args.status_file)
        return 0
    except DuplicateObserver:
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        write_status(args.status_file, "failed", error="observer-start-failed", owned_obs_pid=args.obs_pid)
        return 1
    finally:
        if lease is not None:
            lease.close()
        if owner is not None:
            owner.close()


if __name__ == "__main__":
    raise SystemExit(main())
