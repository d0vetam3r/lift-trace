"""Opt-in native renderer transport; observes the existing Bridge without altering it.

The real InputClient/TrailEngine run in a separate Node process. No pipe I/O or
native renderer operation runs on the controller polling thread. Windows only;
standard library only. The packet format is documented in live-protocol.h.
"""
from __future__ import annotations

from collections import deque
import ctypes
from ctypes import wintypes
import json
import math
import os
from pathlib import Path
import queue
import re
import secrets
import struct
import subprocess
import threading
import time

MAGIC = b"LIFTNV01"
HEADER_BYTES = 168
MAX_EVENTS = 4096
EVENT_BYTES = 24
PACKET_BYTES = HEADER_BYTES + MAX_EVENTS * EVENT_BYTES
MAX_LINE_BYTES = 2 * 1024 * 1024
SETTING_FIELDS = (
    "greenNumber", "suddenNumber", "liftNumber", "width", "overlayHeight",
    "scratchWidth", "blackKeyRatio", "noteHeight", "speedScale", "delayMs",
    "shortInputThresholdMs", "shortInputPercent", "trailOpacity",
)
CHANNEL_RE = re.compile(r"[A-Za-z0-9_-]{1,48}\Z")


def validate_channel(channel: str) -> str:
    if not isinstance(channel, str) or not CHANNEL_RE.fullmatch(channel):
        raise ValueError("Channel must contain 1 to 48 ASCII letters, digits, '_' or '-'.")
    return channel


def finite_number(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"Invalid numeric {label}.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"Non-finite {label}.")
    return result


def pack_snapshot(snapshot: dict, *, session: int, sequence: int,
                  qpc_ns: int, epoch_ms: float, alive: bool = True) -> bytes:
    """Copy raw JS event doubles without shortening, rounding or remapping input."""
    if not isinstance(snapshot, dict) or snapshot.get("type") != "snapshot":
        raise ValueError("Expected a snapshot.")
    settings = snapshot.get("settings")
    events = snapshot.get("events")
    if not isinstance(settings, dict) or not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ValueError("Invalid settings or bounded event list.")
    if not 0 < session < 2**64 or not 0 < sequence < 2**64 or not 0 < qpc_ns < 2**64:
        raise ValueError("Invalid clock or session identity.")
    epoch_ms = finite_number(epoch_ms, "epoch")
    if epoch_ms < 0:
        raise ValueError("Invalid epoch.")
    numbers = [finite_number(settings.get(name), name) for name in SETTING_FIELDS]
    flags = (int(settings.get("side") == "2P")
             | (int(settings.get("heightMode") == "auto") << 1)
             | (int(settings.get("inputBodyEnabled") is True) << 2)
             | (int(settings.get("shortInputEnabled") is True) << 3)
             | (int(settings.get("showGuides") is True) << 4)
             | (int(settings.get("background") == "transparent") << 5))
    packet = bytearray(PACKET_BYTES)
    struct.pack_into("<8sIIQQQdII", packet, 0, MAGIC, 1, PACKET_BYTES,
                     session, sequence, qpc_ns, epoch_ms, int(alive), len(events) if alive else 0)
    struct.pack_into("<13dII", packet, 56, *numbers, flags, 0)
    if alive:
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                raise ValueError("Invalid event.")
            lane, direction = event.get("lane"), event.get("direction", 0)
            if type(lane) is not int or not 0 <= lane <= 7:
                raise ValueError("Invalid lane.")
            if type(direction) is not int or direction not in (-1, 0, 1):
                raise ValueError("Invalid direction.")
            start = finite_number(event.get("start"), "event start")
            end = -1.0 if event.get("end") is None else finite_number(event["end"], "event end")
            if start < 0 or (event.get("end") is not None and end < start):
                raise ValueError("Invalid event interval.")
            struct.pack_into("<iidd", packet, HEADER_BYTES + index * EVENT_BYTES,
                             lane, direction, start, end)
    return bytes(packet)


class SharedPublisher:
    """A unique producer lease plus a nonblocking, mutex-protected shared view."""

    def __init__(self, channel: str):
        if os.name != "nt":
            raise OSError("The native renderer experiment requires Windows.")
        self.channel = validate_channel(channel)
        self.session = secrets.randbits(64) or 1
        self.sequence = 0
        self._lock = threading.Lock()
        self._closed = False
        self._view = self._mapping = self._mutex = self._lease = None
        self._last_packet = None
        self._api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateMutexW": ([ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
            "CreateFileMappingW": ([wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR], wintypes.HANDLE),
            "MapViewOfFile": ([wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                wintypes.DWORD, ctypes.c_size_t], ctypes.c_void_p),
            "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            "ReleaseMutex": ([wintypes.HANDLE], wintypes.BOOL),
            "UnmapViewOfFile": ([ctypes.c_void_p], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self._api, name)
            function.argtypes, function.restype = args, result
        name = "Local\\LiftTraceNative-" + self.channel
        try:
            # Consumers never open this handle. Their stale data views cannot
            # prevent a new producer session after this producer has exited.
            ctypes.set_last_error(0)
            self._lease = self._api.CreateMutexW(None, False, name + "-publisher")
            error = ctypes.get_last_error()
            if not self._lease:
                raise ctypes.WinError(error)
            if error == 183:  # ERROR_ALREADY_EXISTS
                raise RuntimeError("Another publisher already owns this channel.")
            self._mutex = self._api.CreateMutexW(None, False, name + "-mutex")
            if not self._mutex:
                raise ctypes.WinError(ctypes.get_last_error())
            self._mapping = self._api.CreateFileMappingW(
                wintypes.HANDLE(-1), None, 0x04, 0, PACKET_BYTES, name)  # PAGE_READWRITE
            if not self._mapping:
                raise ctypes.WinError(ctypes.get_last_error())
            self._view = self._api.MapViewOfFile(self._mapping, 0x0002, 0, 0, PACKET_BYTES)
            if not self._view:
                raise ctypes.WinError(ctypes.get_last_error())
            # An existing consumer can retain the prior shared view; clear it
            # under its lock so stale input cannot survive a producer restart.
            self._write(bytes(PACKET_BYTES))
        except BaseException:
            self.close()
            raise

    def _write(self, packet: bytes) -> bool:
        if not self._view or not self._mutex:
            return False
        wait = self._api.WaitForSingleObject(self._mutex, 0)
        if wait == 258:  # WAIT_TIMEOUT: never wait on the OBS consumer.
            return False
        if wait not in (0, 128):  # WAIT_OBJECT_0 / abandoned owner
            raise OSError("Could not acquire native snapshot mutex.")
        try:
            ctypes.memmove(self._view, packet, PACKET_BYTES)
        finally:
            self._api.ReleaseMutex(self._mutex)
        return True

    def publish(self, snapshot: dict) -> bool:
        with self._lock:
            if self._closed:
                return False
            self.sequence += 1
            # perf_counter_ns uses raw Windows QPC converted to nanoseconds,
            # matching OBS os_gettime_ns. Epoch events remain JS doubles.
            before = time.perf_counter_ns()
            epoch = time.time_ns() / 1_000_000
            after = time.perf_counter_ns()
            node_epoch = finite_number(snapshot.get("epochMs"), "snapshot epoch")
            if abs(epoch - node_epoch) > 1000:
                raise ValueError("Stale snapshot or discontinuous wall clock.")
            packet = pack_snapshot(snapshot, session=self.session, sequence=self.sequence,
                                   qpc_ns=(before + after) // 2, epoch_ms=epoch)
            result = self._write(packet)
            if result:
                self._last_packet = packet
            return result

    def invalidate(self) -> None:
        with self._lock:
            if not self._closed and self._view:
                packet = bytearray(self._last_packet or bytes(PACKET_BYTES))
                struct.pack_into("<II", packet, 48, 0, 0)
                self._write(bytes(packet))

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                if self._view:
                    packet = bytearray(self._last_packet or bytes(PACKET_BYTES))
                    struct.pack_into("<II", packet, 48, 0, 0)
                    try:
                        self._write(bytes(packet))
                    except OSError:
                        pass  # Consumer also expires missing heartbeat in 1 s.
                    self._api.UnmapViewOfFile(self._view)
                    self._view = None
                for name in ("_mapping", "_mutex", "_lease"):
                    handle = getattr(self, name, None)
                    if handle:
                        self._api.CloseHandle(handle)
                        setattr(self, name, None)
            finally:
                self._closed = True


class NativePipeline:
    """Subscriber/Node adapter. Pipeline failures cannot stop Bridge or its UI."""

    def __init__(self, bridge, node: Path, channel: str, *, publisher_factory=SharedPublisher):
        self.bridge = bridge
        self.node = Path(node).resolve()
        if not self.node.is_file():
            raise ValueError("Provide an existing Node executable with --node.")
        self.channel_name = validate_channel(channel)
        self.publisher_factory = publisher_factory
        self.stopping = threading.Event()
        self.failure: str | None = None
        self.stderr_tail: deque[str] = deque(maxlen=16)
        self.snapshots = 0
        self.process = None
        self.publisher = None
        self.channel = None
        self._threads = []
        self._failure_lock = threading.Lock()

    def start(self) -> None:
        try:
            self.publisher = self.publisher_factory(self.channel_name)
            # Existing Bridge.subscribe owns its bounded queue and recovery
            # sequence (reset/status/settings/demo/latest) when it overflows.
            self.channel = self.bridge.subscribe()
            self.process = subprocess.Popen(
                [str(self.node), str(Path(__file__).with_name("live-input.mjs"))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=64 * 1024, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for name, target in (("native-input-writer", self._write_events),
                                 ("native-snapshot-reader", self._read_snapshots),
                                 ("native-node-errors", self._read_errors)):
                thread = threading.Thread(target=target, name=name, daemon=True)
                self._threads.append(thread)
                thread.start()
        except BaseException:
            self.close()
            raise

    def _fail(self, reason: str) -> None:
        with self._failure_lock:
            if self.stopping.is_set():
                return
            self.failure = reason
            self.stopping.set()
            if self.channel is not None:
                self.bridge.unsubscribe(self.channel)
            if self.publisher:
                try:
                    self.publisher.invalidate()
                except Exception:
                    pass
            if self.process and self.process.poll() is None:
                try:
                    self.process.terminate()
                except OSError:
                    pass

    def _write_events(self) -> None:
        channel = self.channel
        try:
            while not self.stopping.is_set():
                try:
                    event = channel.get(timeout=0.1)
                except queue.Empty:
                    continue
                data = (json.dumps(event, ensure_ascii=False, allow_nan=False,
                                   separators=(",", ":")) + "\n").encode("utf-8")
                if len(data) > MAX_LINE_BYTES:
                    raise ValueError("Oversized input event.")
                # Only this worker can block on pipe pressure, never Bridge.
                view = memoryview(data)
                while view and not self.stopping.is_set():
                    written = self.process.stdin.write(view)
                    if not written:
                        raise OSError("Node input pipe closed.")
                    view = view[written:]
                self.process.stdin.flush()
        except Exception:
            self._fail("node-input-unavailable")
        finally:
            # EOF is the normal, graceful Node shutdown signal. If a blocked
            # pipe prevents reaching here, close() has an owned-child timeout.
            try:
                self.process.stdin.close()
            except (OSError, ValueError):
                pass

    def _read_snapshots(self) -> None:
        try:
            while not self.stopping.is_set():
                line = self.process.stdout.readline(MAX_LINE_BYTES + 1)
                if not line:
                    raise OSError("Node snapshot pipe closed.")
                if len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
                    raise ValueError("Oversized or incomplete snapshot.")
                snapshot = json.loads(line)
                if self.stopping.is_set():
                    break
                if self.publisher.publish(snapshot):
                    self.snapshots += 1
        except Exception:
            self._fail("node-snapshot-unavailable")

    def _read_errors(self) -> None:
        try:
            while not self.stopping.is_set():
                line = self.process.stderr.readline(4096)
                if not line:
                    break
                self.stderr_tail.append(line.decode("utf-8", errors="replace")[:512].rstrip())
        except (OSError, ValueError):
            pass

    def close(self) -> None:
        self.stopping.set()
        if self.channel is not None:
            self.bridge.unsubscribe(self.channel)
        if self.publisher is not None:
            try:
                self.publisher.invalidate()
            except Exception:
                pass
        process = self.process
        if process is not None and process.poll() is None:
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                # The child is owned by this object. Never search for or stop
                # unrelated Node, Lift Trace, OBS, Core or Remote processes.
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
                except OSError:
                    pass
            except OSError:
                pass
        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join(timeout=2)
        self.channel = None
        if process is not None:
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe:
                    try:
                        pipe.close()
                    except OSError:
                        pass
        if self.publisher is not None:
            try:
                self.publisher.close()
            except Exception:
                self.failure = self.failure or "native-close-unavailable"
            finally:
                self.publisher = None
