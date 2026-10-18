"""Local HTTP/SSE bridge for Lift Input. Python 3.10+, standard library only."""
from __future__ import annotations

import argparse
from collections import deque
import json
import math
import mimetypes
import os
from pathlib import Path
import platform
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from native_input import NativeInput
from automation import Automation, AutomationError

MAX_BODY = 32 * 1024
CLIENT_QUEUE_SIZE = 256
ROOT = Path(__file__).resolve().parent
DEMO = json.loads((ROOT / "web" / "demo.json").read_text("utf-8"))


def encode_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def reject_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


class Bridge:
    def __init__(self, data_dir: Path, native: NativeInput | None = None, *, automation=None):
        self.data_dir = data_dir
        self.automation = automation if automation is not None else Automation(data_dir)
        self.native = native if native is not None else NativeInput()
        self.lock = threading.RLock()
        self._settings_write_lock = threading.Lock()
        self.clients: set[queue.Queue] = set()
        self.selected: int | None = None
        self.devices = self.native.scan()
        self.latest: dict[str, Any] | None = None
        self.demo_running = False
        self.demo_start = 0.0
        self.demo_cycle = 0
        self.demo_index = 0
        self.demo_last_advance: float | None = None
        self.demo_recent: deque = deque(maxlen=128)
        self.demo_events = []
        for note in DEMO["notes"]:
            for down in (True, False):
                event = {"type": "key", "lane": note["lane"], "down": down,
                         "time": note["start"] + (0 if down else note["duration"])}
                if "direction" in note:
                    event["direction"] = note["direction"]
                self.demo_events.append(event)
        self.demo_events.sort(key=lambda event: (event["time"], event["down"], event["lane"]))
        self.stopping = threading.Event()
        self.poll_thread: threading.Thread | None = None
        self.settings: dict[str, Any] = {}
        try:
            path = data_dir / "settings.json"
            if path.stat().st_size <= MAX_BODY:
                loaded = json.loads(path.read_text("utf-8"), parse_constant=reject_constant)
                if isinstance(loaded, dict):
                    self.settings = loaded
        except (OSError, ValueError, RecursionError):
            pass

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {"app": "lift-trace", "apiVersion": 1,
                    "platform": platform.system(), "nativeSupported": self.native.supported,
                    "devices": list(self.devices), "selectedDevice": self.selected}

    def subscribe(self) -> queue.Queue:
        with self.lock:
            channel: queue.Queue = queue.Queue(maxsize=CLIENT_QUEUE_SIZE)
            self.clients.add(channel)
            channel.put_nowait({"type": "status", **self.status()})
            channel.put_nowait({"type": "settings", "settings": self.settings})
            channel.put_nowait(self.demo_status())
            if self.latest is not None:
                channel.put_nowait(self.latest)
            if self.demo_running:
                for event in self.demo_recent:
                    channel.put_nowait(event)
            return channel

    def demo_status(self) -> dict[str, Any]:
        with self.lock:
            return {"type": "demo", "running": self.demo_running, "startTime": self.demo_start,
                    "period": DEMO["period"], "notes": DEMO["notes"]}

    def set_demo(self, running: bool, now_ms: float | None = None) -> dict[str, Any]:
        with self.lock:
            if running and self.settings.get("inputMode") == "native":
                raise ValueError("Switch to demo input mode before starting the demo.")
            if running and self.demo_running:
                return self.demo_status()
            self.demo_running = running
            self.demo_recent.clear()
            if running:
                now_ms = time.time_ns() / 1_000_000 if now_ms is None else now_ms
                self.demo_start = now_ms + 200
                self.demo_cycle = 0
                self.demo_index = 0
                self.demo_last_advance = now_ms
            else:
                self.demo_last_advance = None
            self.broadcast({"type": "reset"})
            state = self.demo_status()
            self.broadcast(state)
            return state

    def advance_demo(self, now_ms: float) -> None:
        """Advance the shared simulator clock; explicit time supports deterministic tests."""
        with self.lock:
            if not self.demo_running:
                return
            if self.demo_last_advance is not None and (
                    now_ms < self.demo_last_advance or now_ms - self.demo_last_advance > 1000):
                # Never flood observers with cycles missed during sleep or a long stall.
                self.demo_cycle = max(0, int((now_ms - self.demo_start) // DEMO["period"]))
                self.demo_index = 0
                self.demo_recent.clear()
                self.broadcast({"type": "reset"})
                self.broadcast(self.demo_status())
            self.demo_last_advance = now_ms
            while self.demo_running:
                relative = self.demo_events[self.demo_index]
                event_time = self.demo_start + self.demo_cycle * DEMO["period"] + relative["time"]
                if event_time > now_ms:
                    break
                event = {**relative, "time": event_time}
                self.demo_recent.append(event)
                self.broadcast(event)
                self.demo_index += 1
                if self.demo_index == len(self.demo_events):
                    self.demo_index = 0
                    self.demo_cycle += 1

    def unsubscribe(self, channel: queue.Queue) -> None:
        with self.lock:
            self.clients.discard(channel)

    def broadcast(self, event: dict[str, Any]) -> None:
        with self.lock:
            for channel in tuple(self.clients):
                try:
                    channel.put_nowait(event)
                except queue.Full:
                    while True:
                        try:
                            channel.get_nowait()
                        except queue.Empty:
                            break
                    # A slow observer may also have lost settings or status
                    # changes. Restore those before interpreting new input.
                    channel.put_nowait({"type": "reset"})
                    channel.put_nowait({"type": "status", **self.status()})
                    channel.put_nowait({"type": "settings", "settings": self.settings})
                    channel.put_nowait(self.demo_status())
                    if self.latest is not None and event.get("type") != "input":
                        channel.put_nowait(self.latest)
                    if event.get("type") != "reset":
                        channel.put_nowait(event)

    def select(self, device_id: int | None) -> None:
        with self.lock:
            if device_id is not None and device_id not in {d["id"] for d in self.devices}:
                raise ValueError("Device is unavailable. Rescan and select a connected controller.")
            self.selected = device_id
            self.latest = None
            self.set_demo(False)
            self.broadcast({"type": "status", **self.status()})

    def rescan(self) -> dict[str, Any]:
        with self.lock:
            previous = self.devices
            self.devices = self.native.scan()
            if self.selected is not None and self.selected not in {d["id"] for d in self.devices}:
                if self.latest is not None:
                    self.latest = None
                    self.broadcast({"type": "reset"})
            if self.devices != previous:
                self.broadcast({"type": "status", **self.status()})
            return self.status()

    def save_settings(self, value: dict[str, Any]) -> None:
        contents = encode_json(value)
        if len(contents) > MAX_BODY:
            raise ValueError("Settings exceed the 32 KiB limit.")
        # Own the exact serialized snapshot. Published settings are replaced,
        # never mutated, so readers may retain one while a later save completes.
        settings = json.loads(contents)
        # Serialize persistence through publication without blocking input on
        # disk I/O. Only this path takes both locks, always in this order.
        with self._settings_write_lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            temporary = self.data_dir / "settings.json.tmp"
            temporary.write_bytes(contents)
            os.replace(temporary, self.data_dir / "settings.json")
            with self.lock:
                self.settings = settings
                if settings.get("inputMode") == "native" and self.demo_running:
                    self.set_demo(False)
                self.broadcast({"type": "settings", "settings": settings})
                if self.latest is not None:
                    self.broadcast(self.latest)

    def start(self) -> None:
        self.poll_thread = threading.Thread(target=self._poll, name="controller-input", daemon=True)
        self.poll_thread.start()

    def close(self) -> None:
        self.stopping.set()
        self.broadcast({"type": "reset"})
        self.automation.close()
        if self.poll_thread is not None:
            self.poll_thread.join(timeout=2)

    def _poll(self) -> None:
        next_scan = time.monotonic() + 2
        while not self.stopping.is_set():
            start = time.monotonic()
            with self.lock:
                self.advance_demo(time.time_ns() / 1_000_000)
                if self.selected is not None:
                    sample = self.native.poll(self.selected)
                    if sample is None:
                        if self.latest is not None:
                            self.latest = None
                            self.broadcast({"type": "reset"})
                            self.devices = [d for d in self.devices if d["id"] != self.selected]
                            self.broadcast({"type": "status", **self.status()})
                    else:
                        changed = self.latest is None or any(
                            sample[key] != self.latest[key] for key in ("device", "buttons", "axes"))
                        self.latest = sample
                        if changed:
                            self.broadcast(sample)
            if start >= next_scan:
                self.rescan()
                next_scan = start + 2
            self.stopping.wait(max(0.001, 0.004 - (time.monotonic() - start)))


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    # Windows SO_REUSEADDR can admit two listeners on the same address.
    allow_reuse_address = os.name != "nt"

    def __init__(self, address: tuple[str, int], web_dir: Path, bridge: Bridge):
        self.web_dir = web_dir.resolve()
        self.bridge = bridge
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: LocalServer

    def log_message(self, format: str, *args: Any) -> None:
        # SSE is long lived; suppress routine request noise, retain errors.
        if args and str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
            super().log_message(format, *args)

    def _send(self, status: int, payload: Any) -> None:
        body = encode_json(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _trusted(self) -> bool:
        try:
            hosts = self.headers.get_all("Host", [])
            if len(hosts) != 1:
                raise ValueError
            host = urlsplit("http://" + hosts[0])
            if (host.hostname not in {"127.0.0.1", "localhost"}
                    or host.port != self.server.server_port
                    or host.username is not None or host.password is not None
                    or host.path or host.query or host.fragment):
                raise ValueError
            origin_header = self.headers.get("Origin")
            if origin_header:
                origin = urlsplit(origin_header)
                if (origin.scheme != "http" or origin.hostname != host.hostname
                        or origin.port != host.port or origin.path or origin.query
                        or origin.fragment or origin.username is not None):
                    raise ValueError
        except ValueError:
            self.close_connection = True
            self._send(403, {"error": "Only same-origin requests to the local server are accepted."})
            return False
        return True

    def do_GET(self) -> None:
        if not self._trusted():
            return
        path = urlsplit(self.path).path
        if path == "/api/status":
            self._send(200, self.server.bridge.status())
        elif path == "/api/settings":
            with self.server.bridge.lock:
                settings = self.server.bridge.settings
            self._send(200, settings)
        elif path == "/api/automation":
            self._send(200, self.server.bridge.automation.status())
        elif path == "/api/automation/catalog":
            automation = self.server.bridge.automation
            try:
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                scenes = query.get("sceneUuid", [None])
                if len(scenes) != 1:
                    raise AutomationError("Select one OBS scene.")
                self._send(200, automation.catalog(scenes[0]))
            except AutomationError as exc:
                self._send(400, {"error": str(exc), "code": exc.code,
                                 "status": automation.status(), "scenes": [], "items": []})
        elif path == "/api/events":
            self._events()
        elif path.startswith("/api/"):
            self._send(404, {"error": "Unknown API route."})
        else:
            self._static(path)

    def _static(self, raw_path: str) -> None:
        try:
            path = unquote(raw_path, errors="strict")
            parts = path.strip("/").split("/")
            if any(part.startswith(".") for part in parts) or any(c in path for c in ("\\", ":", "\x00")):
                raise ValueError
            relative = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (self.server.web_dir / relative).resolve()
            target.relative_to(self.server.web_dir)
            if not target.is_file():
                self._send(404, {"error": "File not found."})
                return
            body = target.read_bytes()
        except (ValueError, UnicodeError, OSError):
            self._send(404, {"error": "File not found."})
            return
        media_type = {".js": "application/javascript", ".css": "text/css", ".html": "text/html"}.get(
            target.suffix, mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        if target.suffix in {".html", ".js", ".css"}:
            media_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True
        self.connection.settimeout(10)
        channel = self.server.bridge.subscribe()
        try:
            self.wfile.write(b"retry: 1000\n\n")
            self.wfile.flush()
            while not self.server.bridge.stopping.is_set():
                try:
                    event = channel.get(timeout=1)
                    payload = b"data: " + encode_json(event) + b"\n\n"
                except queue.Empty:
                    payload = b": keepalive\n\n"
                self.wfile.write(payload)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionError, TimeoutError, OSError):
            pass
        finally:
            self.server.bridge.unsubscribe(channel)

    def _body(self) -> dict[str, Any] | None:
        try:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Chunked request bodies are unsupported.")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1:
                raise ValueError("One Content-Length header is required.")
            size = int(lengths[0])
            if size < 0 or size > MAX_BODY:
                self.close_connection = True
                self._send(413, {"error": "Request body exceeds the 32 KiB limit."})
                return None
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Content-Type must be application/json.")
            self.connection.settimeout(5)
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError("Incomplete request body.")
            value = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
            if not isinstance(value, dict):
                raise ValueError("A JSON object is required.")
            # Validate nesting and numeric finiteness before any state changes.
            encode_json(value)
            return value
        except (ValueError, UnicodeError, RecursionError, TimeoutError, OSError) as exc:
            self.close_connection = True
            self._send(400, {"error": str(exc) or "Invalid JSON."})
            return None

    def do_POST(self) -> None:
        if not self._trusted():
            return
        value = self._body()
        if value is None:
            return
        path = urlsplit(self.path).path
        bridge = self.server.bridge
        try:
            if path.startswith("/api/automation/"):
                automation = bridge.automation
                action = path.removeprefix("/api/automation/")
                if action == "connect":
                    result = automation.connect(value)
                elif action == "discover":
                    result = automation.discover(value.get("sceneUuid"))
                elif action == "config":
                    result = automation.configure(value)
                elif action == "template":
                    result = automation.template()
                elif action == "start":
                    result = automation.start()
                elif action == "stop":
                    result = automation.stop()
                else:
                    self._send(404, {"error": "Unknown API route."})
                    return
                self._send(200, result)
            elif path == "/api/device":
                if "id" not in value or (value["id"] is not None and type(value["id"]) is not int):
                    raise ValueError("id must be a device number or null.")
                bridge.select(value["id"])
                self._send(200, bridge.status())
            elif path == "/api/rescan":
                self._send(200, bridge.rescan())
            elif path == "/api/reset":
                with bridge.lock:
                    bridge.set_demo(False)
                    if bridge.latest is not None:
                        bridge.broadcast(bridge.latest)
                self._send(200, {"ok": True})
            elif path == "/api/demo":
                if type(value.get("running")) is not bool:
                    raise ValueError("running must be a boolean.")
                self._send(200, bridge.set_demo(value["running"]))
            elif path == "/api/settings":
                bridge.save_settings(value)
                self._send(200, {"ok": True})
            elif path == "/api/input":
                if (value.get("type") != "key" or type(value.get("lane")) is not int
                        or not 0 <= value["lane"] <= 7 or type(value.get("down")) is not bool):
                    raise ValueError("Input requires type key, lane 0..7, and a boolean down.")
                if "direction" in value and (type(value["direction"]) is not int or value["direction"] not in (-1, 1)):
                    raise ValueError("direction must be -1 or 1.")
                timestamp = value.get("time", time.time_ns() / 1_000_000)
                if type(timestamp) not in (int, float) or not 0 <= timestamp <= 1e16 or not math.isfinite(timestamp):
                    raise ValueError("time must be a nonnegative finite epoch timestamp in milliseconds.")
                event = {"type": "key", "lane": value["lane"], "down": value["down"], "time": timestamp}
                if "direction" in value:
                    event["direction"] = value["direction"]
                with bridge.lock:
                    if bridge.demo_running:
                        bridge.set_demo(False)
                    bridge.broadcast(event)
                self._send(200, {"ok": True})
            else:
                self._send(404, {"error": "Unknown API route."})
        except AutomationError as exc:
            self._send(400, {"error": str(exc), "code": exc.code, "status": bridge.automation.status()})
        except (ValueError, RecursionError) as exc:
            self._send(400, {"error": str(exc)})
        except OSError:
            self._send(500, {"error": "Could not save settings. Check the data directory permissions."})


def main() -> None:
    parser = argparse.ArgumentParser(description="Lift Input local prototype server")
    parser.add_argument("--port", type=int, default=8765, help="Loopback HTTP port (default: 8765)")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="Local settings directory")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    bridge = Bridge(args.data_dir)
    try:
        server = LocalServer(("127.0.0.1", args.port), ROOT / "web", bridge)
    except OSError as exc:
        parser.exit(1, f"Could not start local server on port {args.port}: {exc}\n")
    bridge.start()
    print(f"Lift Input: http://127.0.0.1:{args.port}/", flush=True)
    print("Controller input is off until you select a device. Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.close()
        server.server_close()


if __name__ == "__main__":
    main()
