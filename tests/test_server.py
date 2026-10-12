import http.client
import json
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest

from server import Bridge, CLIENT_QUEUE_SIZE, LocalServer, MAX_BODY
from automation import Automation
from tests.test_automation import CONFIG, FakeConnection, FakeDetector, write_template


class FakeNative:
    supported = True

    def __init__(self):
        self.connected = True
        self.down = True

    def scan(self):
        return [{"id": 0, "name": "Fake device", "buttons": 7, "axes": 2}] if self.connected else []

    def poll(self, device_id):
        if not self.connected:
            return None
        return {"type": "input", "device": 0, "buttons": [self.down] + [False] * 6,
                "axes": [0, 0], "time": time.time() * 1000}


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "web").mkdir()
        (self.root / "web" / "index.html").write_text("<h1>Lift Input</h1>", encoding="utf-8")
        (self.root / "secret.txt").write_text("secret", encoding="utf-8")
        self.native = FakeNative()
        self.bridge = Bridge(self.root / "data", self.native)
        self.server = LocalServer(("127.0.0.1", 0), self.root / "web", self.bridge)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.bridge.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, method, path, value=None, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        body = json.dumps(value).encode() if value is not None else raw
        request_headers = {"Content-Type": "application/json"} if body is not None else {}
        request_headers.update(headers or {})
        connection.request(method, path, body, request_headers)
        response = connection.getresponse()
        data = response.read()
        status = response.status
        connection.close()
        try:
            return status, json.loads(data)
        except ValueError:
            return status, data

    def drain(self, channel):
        events = []
        while not channel.empty():
            events.append(channel.get_nowait())
        return events

    def subscribe_clean(self):
        channel = self.bridge.subscribe()
        self.drain(channel)
        return channel

    def test_static_and_status(self):
        self.assertEqual(self.request("GET", "/")[0], 200)
        status, payload = self.request("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(payload["app"], "lift-trace")
        self.assertEqual(payload["apiVersion"], 1)
        self.assertIsNone(payload["selectedDevice"])
        self.assertTrue(payload["nativeSupported"])
        self.assertEqual(payload["devices"][0]["id"], 0)

    def test_static_traversal_and_source_are_inaccessible(self):
        for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/%2e%2e%5csecret.txt", "/server.py", "/C:/secret.txt", "/%00"):
            with self.subTest(path=path):
                status, payload = self.request("GET", path)
                self.assertEqual(status, 404)
                self.assertNotIn("secret", str(payload))

    def test_bad_host_and_cross_origin_are_rejected(self):
        status, _ = self.request("GET", "/api/status", headers={"Host": f"evil.example:{self.server.server_port}"})
        self.assertEqual(status, 403)
        for origin in ("https://evil.example", "null", f"http://localhost:{self.server.server_port}"):
            self.assertEqual(self.request("POST", "/api/settings", {"x": 1}, {"Origin": origin})[0], 403)
        origin = f"http://127.0.0.1:{self.server.server_port}"
        self.assertEqual(self.request("POST", "/api/settings", {"x": 1}, {"Origin": origin})[0], 200)

    def test_settings_are_persisted_and_broadcast(self):
        channel = self.subscribe_clean()
        settings = {"green": 300, "mapping": [0, 1], "label": "키 입력"}
        self.assertEqual(self.request("POST", "/api/settings", settings)[0], 200)
        self.assertEqual(self.request("GET", "/api/settings"), (200, settings))
        reloaded = Bridge(self.root / "data", self.native)
        self.assertEqual(reloaded.settings, settings)
        self.assertEqual(channel.get_nowait(), {"type": "settings", "settings": settings})
        reloaded.close()

    def automation_fixture(self):
        connections = []

        def factory(*args, **kwargs):
            connection = FakeConnection(*args, **kwargs)
            connections.append(connection)
            return connection

        self.bridge.automation.close()
        self.bridge.automation = Automation(
            self.root / "data", connection_factory=factory, detector_factory=FakeDetector,
            template_capture=lambda connection, source, path: write_template(path),
            default_template_path=self.root / "bundled-reference.png")
        return connections

    def test_automation_routes_keep_credentials_out_of_settings_events_and_static_files(self):
        self.automation_fixture()
        channel = self.subscribe_clean()
        self.assertFalse(self.request("GET", "/api/automation")[1]["running"])
        code, payload = self.request("POST", "/api/automation/connect", {"port": 4455, "password": "private-only"})
        self.assertEqual(code, 200)
        self.assertEqual(payload["scenes"], [{"sceneUuid": "scene", "sceneName": "My scene"}])
        self.assertTrue(payload["status"]["config"]["hasPassword"])
        self.assertNotIn("private-only", json.dumps(payload))
        code, payload = self.request("POST", "/api/automation/discover", {"sceneUuid": "scene"})
        self.assertEqual(code, 200)
        self.assertEqual([item["sceneItemId"] for item in payload["items"]], [1, 2, 3])
        self.assertEqual(self.request("POST", "/api/automation/config", CONFIG)[0], 200)
        self.assertTrue(self.request("POST", "/api/automation/template", {})[1]["status"]["templateReady"])
        self.assertEqual(self.request("POST", "/api/automation/start", {})[0], 200)
        self.assertFalse(self.request("POST", "/api/automation/stop", {})[1]["status"]["running"])
        self.assertEqual(self.request("GET", "/api/settings"), (200, {}))
        self.assertTrue(channel.empty())
        for path in ("/automation.json", "/data/automation.json", "/automation-template.png"):
            self.assertEqual(self.request("GET", path)[0], 404)

    def test_automation_errors_are_redacted_and_do_not_take_the_controller_lock(self):
        connections = self.automation_fixture()
        with self.bridge.lock:
            self.assertEqual(self.request("POST", "/api/automation/connect", {"password": "private-only"})[0], 200)
            self.assertEqual(self.request("GET", "/api/automation")[0], 200)
        connections[-1].fail_kind = "GetSceneItemList"
        code, payload = self.request("POST", "/api/automation/discover", {"sceneUuid": "scene"})
        self.assertEqual(code, 400)
        self.assertEqual(payload["code"], "obs-request-failed")
        self.assertNotIn("private-only", json.dumps(payload))
        self.assertFalse(payload["status"]["connected"])
        self.assertEqual(self.request("POST", "/api/automation/unknown", {})[0], 404)

    def test_builtin_reference_starts_without_a_template_registration_route(self):
        self.automation_fixture()
        write_template(self.bridge.automation.default_template_path)
        status = self.request("GET", "/api/automation")[1]
        self.assertTrue(status["templateReady"])
        self.assertEqual(status["referenceSource"], "builtin")
        self.assertFalse(status["running"])
        self.request("POST", "/api/automation/connect", {})
        self.request("POST", "/api/automation/config", CONFIG)
        code, result = self.request("POST", "/api/automation/start", {})
        self.assertEqual(code, 200)
        self.assertTrue(result["status"]["running"])
        self.assertEqual(result["status"]["referenceSource"], "builtin")
        self.assertFalse(self.bridge.automation.template_path.exists())
        self.request("POST", "/api/automation/stop", {})

    def test_catalog_endpoint_is_read_only_and_restores_names_during_automation(self):
        connections = self.automation_fixture()
        code, catalog = self.request("GET", "/api/automation/catalog")
        self.assertEqual(code, 200)
        self.assertEqual(catalog["scenes"], [])
        self.assertEqual(catalog["items"], [])
        self.assertEqual(connections, [])
        self.request("POST", "/api/automation/connect", {"password": "private-only"})
        self.request("POST", "/api/automation/config", CONFIG)
        self.request("POST", "/api/automation/template", {})
        # The old optional field no longer gates a user's explicit Start action.
        self.assertEqual(self.request("POST", "/api/automation/start", {"exclusiveControl": False})[0], 200)
        with self.bridge.lock:
            code, catalog = self.request("GET", "/api/automation/catalog?sceneUuid=scene")
        self.assertEqual(code, 200)
        self.assertTrue(catalog["status"]["running"])
        self.assertEqual(catalog["scenes"][0]["sceneName"], "My scene")
        self.assertEqual([item["sourceName"] for item in catalog["items"]], ["game", "game", "camera"])
        self.assertEqual([item["sceneItemIndex"] for item in catalog["items"]], [0, 1, 2])
        self.assertNotIn("private-only", json.dumps(catalog))
        connection = connections[-1]
        connection.fail_kind = "GetSceneList"
        code, failure = self.request("GET", "/api/automation/catalog")
        self.assertEqual(code, 400)
        self.assertEqual(failure["code"], "obs-catalog-failed")
        self.assertTrue(failure["status"]["connected"])
        self.assertTrue(failure["status"]["running"])
        self.assertNotIn("private-only", json.dumps(failure))
        self.assertEqual(self.request("GET", "/api/automation/catalog?sceneUuid=scene&sceneUuid=other")[0], 400)

    def test_body_limit_and_json_validation(self):
        self.assertEqual(self.request("POST", "/api/settings", raw=b"x" * (MAX_BODY + 1))[0], 413)
        for raw in (b"[]", b"{broken", b'{"x":NaN}', b'{"x":1e999}', b"[" * 1500):
            with self.subTest(raw=raw[:30]):
                self.assertEqual(self.request("POST", "/api/settings", raw=raw)[0], 400)
        self.assertEqual(self.request("POST", "/api/settings", raw=b"{}", headers={"Content-Type": "text/plain"})[0], 400)

    def test_settings_reseed_latest_native_state_after_mapping_changes(self):
        self.bridge.latest = {"type": "input", "buttons": [True], "axes": [0], "device": 0, "time": 1}
        channel = self.bridge.subscribe()
        while not channel.empty():
            channel.get_nowait()
        settings = {"inputMode": "native", "buttonMap": [0, 1, 2, 3, 4, 5, 6]}
        self.assertEqual(self.request("POST", "/api/settings", settings)[0], 200)
        self.assertEqual(channel.get_nowait(), {"type": "settings", "settings": settings})
        self.assertEqual(channel.get_nowait(), self.bridge.latest)

    def test_device_selection_validates_and_releases(self):
        channel = self.subscribe_clean()
        self.assertEqual(self.request("POST", "/api/device", {"id": 0})[0], 200)
        self.assertEqual(channel.get_nowait(), {"type": "reset"})
        self.assertFalse(channel.get_nowait()["running"])
        self.assertEqual(channel.get_nowait()["selectedDevice"], 0)
        for value in ({"id": 999}, {"id": True}, {}, {"id": "0"}):
            self.assertEqual(self.request("POST", "/api/device", value)[0], 400)
        self.assertEqual(self.request("POST", "/api/device", {"id": None})[0], 200)

    def test_input_validates_and_relays_timestamp(self):
        channel = self.subscribe_clean()
        event = {"type": "key", "lane": 7, "down": True, "direction": -1, "time": 1234}
        self.assertEqual(self.request("POST", "/api/input", event)[0], 200)
        self.assertEqual(channel.get_nowait(), event)
        for patch in ({"lane": -1}, {"lane": 8}, {"lane": True}, {"down": 1}, {"direction": 0}, {"time": -1}, {"time": "today"}, {"time": 10**400}):
            self.assertEqual(self.request("POST", "/api/input", {**event, **patch})[0], 400)

    def test_reset_clears_connected_clients(self):
        channel = self.subscribe_clean()
        self.assertEqual(self.request("POST", "/api/reset", {})[0], 200)
        self.assertEqual(channel.get_nowait(), {"type": "reset"})

    def test_overflow_resets_then_emits_latest_state(self):
        channel = self.bridge.subscribe()
        event = {"type": "input", "buttons": [True], "axes": [], "device": 0, "time": 1}
        self.bridge.latest = event
        for i in range(CLIENT_QUEUE_SIZE - 2):
            self.bridge.broadcast({"type": "key", "lane": 0, "down": bool(i % 2), "time": i})
        events = []
        while not channel.empty():
            events.append(channel.get_nowait())
        self.assertEqual(events[0], {"type": "reset"})
        self.assertEqual(events[1], {"type": "status", **self.bridge.status()})
        self.assertEqual(events[2], {"type": "settings", "settings": self.bridge.settings})
        self.assertEqual(events[3], self.bridge.demo_status())
        self.assertEqual(events[4], event)
        self.assertEqual(events[-1]["time"], CLIENT_QUEUE_SIZE - 3)

    def test_overflow_recovers_settings_for_a_slow_observer(self):
        channel = self.subscribe_clean()
        settings = {"inputMode": "native", "buttonMap": [6, 5, 4, 3, 2, 1, 0], "width": 432}
        self.bridge.save_settings(settings)
        for timestamp in range(CLIENT_QUEUE_SIZE):
            sample = {"type": "input", "device": 0, "buttons": [bool(timestamp % 2)] * 7,
                      "axes": [0, 0], "time": timestamp}
            self.bridge.latest = sample
            self.bridge.broadcast(sample)
        events = self.drain(channel)
        self.assertEqual(events[0], {"type": "reset"})
        restored = [event["settings"] for event in events if event["type"] == "settings"]
        self.assertEqual(restored, [settings])
        self.assertEqual(events[-1], self.bridge.latest)

    def test_sse_starts_with_status_and_latest_input(self):
        event = {"type": "input", "buttons": [True], "axes": [], "device": 0, "time": 1}
        self.bridge.latest = event
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        connection.request("GET", "/api/events")
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        messages = []
        while len(messages) < 4:
            line = response.readline()
            if line.startswith(b"data: "):
                messages.append(json.loads(line[6:]))
        self.assertEqual(messages[0]["type"], "status")
        self.assertEqual(messages[1], {"type": "settings", "settings": {}})
        self.assertEqual(messages[2]["type"], "demo")
        self.assertFalse(messages[2]["running"])
        self.assertEqual(messages[3], event)
        response.close()
        connection.close()

    def test_poll_disconnect_releases_held_state(self):
        self.bridge.select(0)
        self.bridge.start()
        deadline = time.monotonic() + 1
        while self.bridge.latest is None and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertIsNotNone(self.bridge.latest)
        channel = self.subscribe_clean()
        self.native.connected = False
        self.assertEqual(channel.get(timeout=1), {"type": "reset"})
        self.assertIsNone(self.bridge.latest)
        self.native.connected = True
        self.bridge.rescan()
        deadline = time.monotonic() + 1
        while self.bridge.latest is None and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertIsNotNone(self.bridge.latest)

    def test_demo_endpoint_start_stop_and_validation(self):
        status, state = self.request("POST", "/api/demo", {"running": True})
        self.assertEqual(status, 200)
        self.assertTrue(state["running"])
        self.assertEqual(state["period"], 7200)
        self.assertEqual(len(state["notes"]), 20)
        self.assertGreater(state["startTime"], time.time() * 1000)
        self.assertEqual(self.request("POST", "/api/demo", {"running": 1})[0], 400)
        self.assertFalse(self.request("POST", "/api/demo", {"running": False})[1]["running"])

    def test_demo_uses_scheduled_timestamps_without_browser(self):
        self.bridge.set_demo(True, now_ms=1000)
        channel = self.subscribe_clean()
        self.bridge.advance_demo(1899)
        self.assertTrue(channel.empty())
        self.bridge.advance_demo(1900)
        self.assertEqual(channel.get_nowait(), {"type": "key", "lane": 1, "down": True, "time": 1900})
        self.bridge.advance_demo(1965)
        self.assertEqual(channel.get_nowait(), {"type": "key", "lane": 1, "down": False, "time": 1965})
        new_client = self.bridge.subscribe()
        seeded = self.drain(new_client)
        self.assertTrue(seeded[2]["running"])
        self.assertEqual([item["down"] for item in seeded if item["type"] == "key"], [True, False])

    def test_demo_releases_before_reverse_press_and_loops(self):
        self.bridge.set_demo(True, now_ms=1000)
        channel = self.subscribe_clean()
        for timestamp in range(1500, 5501, 500):
            self.bridge.advance_demo(timestamp)
        self.drain(channel)
        self.bridge.advance_demo(5700)
        events = self.drain(channel)
        turn = [event for event in events if event.get("lane") == 0 and event["time"] == 5700]
        self.assertEqual([(event["down"], event["direction"]) for event in turn], [(False, 1), (True, -1)])
        for timestamp in range(6200, 9201, 500):
            self.bridge.advance_demo(timestamp)
        self.assertIn({"type": "key", "lane": 1, "down": True, "time": 9100}, self.drain(channel))

    def test_demo_large_stall_discards_missed_cycles(self):
        self.bridge.set_demo(True, now_ms=1000)
        channel = self.subscribe_clean()
        self.bridge.advance_demo(1200 + 7200 * 500 + 800)
        events = self.drain(channel)
        self.assertEqual(events[0], {"type": "reset"})
        keys = [event for event in events if event["type"] == "key"]
        self.assertEqual(len(keys), 2)
        self.assertTrue(all(event["time"] >= 1200 + 7200 * 500 for event in keys))

    def test_manual_input_and_reset_stop_demo(self):
        self.bridge.set_demo(True, now_ms=1000)
        channel = self.subscribe_clean()
        event = {"type": "key", "lane": 1, "down": True, "time": 2000}
        self.assertEqual(self.request("POST", "/api/input", event)[0], 200)
        events = self.drain(channel)
        self.assertEqual(events[0], {"type": "reset"})
        self.assertFalse(events[1]["running"])
        self.assertEqual(events[2], event)
        self.bridge.set_demo(True, now_ms=1000)
        self.assertEqual(self.request("POST", "/api/reset", {})[0], 200)
        self.assertFalse(self.bridge.demo_running)

    def test_device_and_native_mode_stop_demo(self):
        self.bridge.set_demo(True, now_ms=1000)
        self.bridge.select(0)
        self.assertFalse(self.bridge.demo_running)
        self.bridge.set_demo(True, now_ms=1000)
        self.bridge.save_settings({"inputMode": "native"})
        self.assertFalse(self.bridge.demo_running)
        self.assertEqual(self.request("POST", "/api/demo", {"running": True})[0], 400)


if __name__ == "__main__":
    unittest.main()
