"""Read-only SSE sidecar tests; no real OBS, controller, settings or videos."""
from __future__ import annotations

import copy
import ctypes
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from live_bridge import NativePipeline
from live_observer import DuplicateObserver, ObserverLease, SSEBridge, WindowsOwner, acquire_lease, observe, write_status

NODE = os.environ.get("LIFT_NATIVE_TEST_NODE") or shutil.which("node")


def wait_for(predicate, timeout=5):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("Timed out waiting for the isolated test condition")


class ExistingServer:
    """HTTPConnection boundary fixture, including Connection: close ownership.

    No TCP permission is needed for these tests. Real SSE integration is checked
    separately by the isolated OBS deployment test.
    """
    def __init__(self):
        self.events = queue.Queue()
        self.requests = []
        self.connected = 0
        self.app = "lift-trace"
        self.stop = threading.Event()
        self.port = 18865
        fixture = self
        class Socket:
            def __init__(self): self.stopped = threading.Event()
            def shutdown(self, _how): self.stopped.set()
        class Response:
            status = 200
            def __init__(self, connection, path):
                self.transport = connection.sock
                self.path = path
                self.pending = b'data: {"type":"settings","settings":{"inputMode":"native"}}\n\n'
            def getheader(self, _key, _default): return "text/event-stream; charset=utf-8"
            def read(self, size): return json.dumps({"app": fixture.app, "apiVersion": 1}).encode()[:size]
            def readline(self, size):
                while not self.pending:
                    if fixture.stop.is_set() or self.transport.stopped.is_set(): return b""
                    try: event = fixture.events.get(timeout=.05)
                    except queue.Empty: event = b": keepalive\n\n"
                    if event is None: return b""
                    if event == "silent":
                        self.transport.stopped.wait(4); return b""
                    self.pending = event if isinstance(event, bytes) else b"data: " + json.dumps(event).encode() + b"\n\n"
                index = self.pending.find(b"\n")
                length = min(size, index + 1 if index >= 0 else len(self.pending))
                result, self.pending = self.pending[:length], self.pending[length:]
                return result
            def close(self): self.transport.stopped.set()
        class Connection:
            def __init__(self, host, port, timeout):
                assert host == "127.0.0.1" and port == fixture.port
                self.sock, self.path = Socket(), None
            def request(self, method, path):
                assert method == "GET"
                fixture.requests.append((method, path)); self.path = path
            def getresponse(self):
                response = Response(self, self.path)
                if self.path == "/api/events":
                    fixture.connected += 1
                    self.sock = None  # Match http.client's Connection: close.
                return response
            def close(self):
                if self.sock: self.sock.shutdown(2)
        self.connection = Connection
        self.patch = patch("live_observer.http.client.HTTPConnection", Connection)
        self.patch.start()

    def close(self):
        self.stop.set(); self.patch.stop()


class SSETests(unittest.TestCase):
    def setUp(self):
        self.server = ExistingServer()
        self.bridge = SSEBridge(self.server.port)
    def tearDown(self):
        self.bridge.close(); self.server.close()

    def test_get_only_preserves_timestamp_and_existing_ui_settings(self):
        channel = self.bridge.subscribe()
        self.assertEqual(channel.get(timeout=2)["type"], "settings")
        event = {"type": "input", "time": 123456.7890123, "buttons": [True], "axes": [.25]}
        self.server.events.put(event)
        self.assertEqual(channel.get(timeout=2), event)
        self.assertEqual(self.server.requests, [("GET", "/api/status"), ("GET", "/api/events")])

    def test_close_interrupts_silent_connection_close_response(self):
        self.bridge.subscribe().get(timeout=2)
        self.server.events.put("silent")
        time.sleep(.05)
        started = time.monotonic(); self.bridge.close()
        self.assertLess(time.monotonic() - started, 1)
        self.assertFalse(self.bridge.thread.is_alive())

    def test_wrong_server_is_not_consumed(self):
        self.server.app = "unrelated"
        self.bridge.subscribe(); wait_for(lambda: self.bridge.failure)
        self.assertEqual(self.server.requests, [("GET", "/api/status")])

    def test_oversized_line_and_queue_overflow_fail_closed(self):
        channel = self.bridge.subscribe(); channel.get(timeout=2)
        self.server.events.put(b"data: " + b"x" * (128 * 1024) + b"\n\n")
        wait_for(lambda: self.bridge.failure)
        self.bridge.close(); self.bridge = SSEBridge(self.server.port)
        channel = self.bridge.subscribe()
        for _ in range(300): self.server.events.put({"type": "reset"})
        wait_for(lambda: self.bridge.failure)
        self.assertLessEqual(channel.qsize(), 256)

    def test_nonfinite_or_incomplete_json_is_rejected(self):
        channel = self.bridge.subscribe(); channel.get(timeout=2)
        self.server.events.put(b'data: {"type":"input","time":NaN}\n\n')
        wait_for(lambda: self.bridge.failure)


class TCPIntegrationTests(unittest.TestCase):
    def test_real_loopback_sse_when_network_permission_is_available(self):
        stop = threading.Event()
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *args): pass
            def do_GET(self):
                if self.path == "/api/status":
                    payload = b'{"app":"lift-trace","apiVersion":1}'
                    self.send_response(200); self.send_header("Content-Length", str(len(payload))); self.end_headers()
                    self.wfile.write(payload); return
                self.send_response(200); self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close"); self.end_headers(); self.close_connection = True
                try:
                    self.wfile.write(b'data: {"type":"settings","settings":{}}\n\n'); self.wfile.flush()
                    while not stop.wait(.05):
                        self.wfile.write(b": keepalive\n\n"); self.wfile.flush()
                except OSError: pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
        thread.start()
        bridge = SSEBridge(server.server_port)
        try:
            try:
                with socket.create_connection(("127.0.0.1", server.server_port), timeout=1): pass
            except OSError as error:
                if getattr(error, "winerror", None) == 10013 or error.errno == 13:
                    self.skipTest("Sandbox denies loopback TCP (permission error); HTTP boundary tests still run.")
                raise
            self.assertEqual(bridge.subscribe().get(timeout=2), {"type": "settings", "settings": {}})
            started = time.monotonic(); bridge.close()
            self.assertLess(time.monotonic() - started, 1)
        finally:
            bridge.close(); stop.set(); server.shutdown(); server.server_close(); thread.join(2)


@unittest.skipUnless(NODE, "Set LIFT_NATIVE_TEST_NODE to test the owned Node child")
class ObserverLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.server = ExistingServer()
        self.stopping = threading.Event()
        self.pipelines, self.publishers = [], []
        fixture = self
        class Publisher:
            def __init__(self, channel):
                self.snapshots, self.invalidations, self.closed = [], 0, False
                fixture.publishers.append(self)
            def publish(self, snapshot):
                self.snapshots.append(copy.deepcopy(snapshot)); return True
            def invalidate(self): self.invalidations += 1
            def close(self): self.closed = True
        def factory(bridge, node, channel):
            pipeline = NativePipeline(bridge, node, channel, publisher_factory=Publisher)
            self.pipelines.append(pipeline); return pipeline
        self.factory = factory
        self.owner = type("Owner", (), {"pid": 123, "active": True, "alive": lambda value: value.active})()
        self.errors = []
        def run():
            try:
                observe(Path(NODE), "test-sidecar", self.server.port, owner=self.owner,
                        stopping=self.stopping, pipeline_factory=self.factory)
            except Exception as error:
                self.errors.append(error)
        self.thread = threading.Thread(target=run)
        self.thread.start()
        try:
            wait_for(lambda: self.publishers and self.publishers[0].snapshots)
        except BaseException:
            self.stopping.set(); self.thread.join(5); self.server.close()
            raise

    def tearDown(self):
        self.stopping.set(); self.thread.join(5); self.server.close()
        self.assertFalse(self.thread.is_alive())
        self.assertFalse(self.errors)
        self.assertTrue(all(p.process.poll() is not None for p in self.pipelines))
        self.assertTrue(all(not t.is_alive() for p in self.pipelines for t in p._threads))

    def test_disconnect_invalidates_and_reconnects_without_stuck_input(self):
        stamp = time.time_ns() / 1_000_000
        self.server.events.put({"type": "input", "time": stamp, "buttons": [True] + [False] * 6, "axes": [0]})
        wait_for(lambda: any(snapshot["events"] for snapshot in self.publishers[0].snapshots))
        original = self.pipelines[0]
        self.server.events.put(None)
        wait_for(lambda: len(self.publishers) >= 2 and self.publishers[1].snapshots)
        self.assertGreater(self.publishers[0].invalidations, 0)
        self.assertTrue(self.publishers[0].closed)
        self.assertIsNotNone(original.process.poll())
        self.assertEqual(self.publishers[1].snapshots[0]["events"], [])
        self.assertNotEqual(original.process.pid, self.pipelines[1].process.pid)

    def test_original_obs_exit_stops_owned_children_only(self):
        self.owner.active = False
        self.thread.join(3)
        self.assertFalse(self.thread.is_alive())
        self.assertTrue(self.publishers[0].closed)
        connection = self.server.connection("127.0.0.1", self.server.port, timeout=1)
        connection.request("GET", "/api/status")
        self.assertEqual(json.loads(connection.getresponse().read(32768))["app"], "lift-trace")
        connection.close()


class StatusTests(unittest.TestCase):
    def test_rapid_obs_restart_waits_for_old_lease_without_other_side_effects(self):
        now, calls = [0.0], []
        owner = type("Owner", (), {"alive": lambda _self: True})()
        lease = object()
        def factory(channel):
            calls.append(channel)
            if len(calls) < 3: raise DuplicateObserver()
            return lease
        result = acquire_lease("test", owner, factory=factory, clock=lambda: now[0], wait=lambda duration: now.__setitem__(0, now[0] + duration))
        self.assertIs(result, lease); self.assertEqual(len(calls), 3); self.assertAlmostEqual(now[0], .2)

    def test_duplicate_owner_wait_is_bounded_and_cancelled_on_owner_exit(self):
        now = [0.0]
        owner = type("Owner", (), {"alive": lambda _self: True})()
        def busy(_channel): raise DuplicateObserver()
        with self.assertRaises(DuplicateObserver):
            acquire_lease("test", owner, factory=busy, clock=lambda: now[0], wait=lambda duration: now.__setitem__(0, now[0] + duration))
        self.assertAlmostEqual(now[0], 5)
        now[0] = 0
        owner.alive = lambda: now[0] < .2
        with self.assertRaises(RuntimeError):
            acquire_lease("test", owner, factory=busy, clock=lambda: now[0], wait=lambda duration: now.__setitem__(0, now[0] + duration))
        self.assertAlmostEqual(now[0], .2)

    def test_bounded_status_contains_no_settings_or_input(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "status.json"
            write_status(path, "ready", snapshots=42, owned_obs_pid=10, child_pid=11, connected=True)
            value = json.loads(path.read_text("utf-8"))
            self.assertEqual(value["ownedObsPid"], 10)
            self.assertEqual(value["childPid"], 11)
            self.assertTrue(value["connected"])
            self.assertLess(path.stat().st_size, 1024)
            self.assertNotIn("settings", value); self.assertNotIn("events", value)


@unittest.skipUnless(os.name == "nt", "Windows process handle ownership")
class WindowsOwnerTests(unittest.TestCase):
    def test_observer_lease_survives_reconnect_and_allows_restart(self):
        channel = "observer-test-" + secrets.token_hex(12)
        lease = ObserverLease(channel)
        try:
            with self.assertRaises(DuplicateObserver): ObserverLease(channel)
            with self.assertRaises(DuplicateObserver): ObserverLease(channel)
        finally:
            lease.close()
        replacement = ObserverLease(channel)
        replacement.close()

    def test_duplicate_cli_start_has_no_status_or_pipeline_side_effect(self):
        from unittest.mock import patch
        import live_observer
        channel = "observer-test-" + secrets.token_hex(12)
        lease = ObserverLease(channel)
        try:
            with patch.object(sys, "argv", ["live_observer.py", "--node", sys.executable, "--channel", channel]), \
                    patch.object(live_observer, "observe") as observe_mock, patch.object(live_observer, "write_status") as status:
                self.assertEqual(live_observer.main(), 0)
                observe_mock.assert_not_called(); status.assert_not_called()
        finally:
            lease.close()

    def test_exact_process_creation_time_and_exit(self):
        process = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"],
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        owner = None
        try:
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
            kernel.GetProcessTimes.restype = wintypes.BOOL
            created, exited, cpu, user = (wintypes.FILETIME() for _ in range(4))
            self.assertTrue(kernel.GetProcessTimes(int(process._handle), ctypes.byref(created), ctypes.byref(exited), ctypes.byref(cpu), ctypes.byref(user)))
            ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
            with self.assertRaises(RuntimeError): WindowsOwner(process.pid, ticks + 1)
            owner = WindowsOwner(process.pid, ticks); self.assertTrue(owner.alive())
            process.terminate(); process.wait(timeout=3); self.assertFalse(owner.alive())
        finally:
            if owner: owner.close()
            if process.poll() is None: process.terminate(); process.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
