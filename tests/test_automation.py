"""Runtime lifecycle tests with no OBS connection, screen capture, or credentials."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from auto_visibility import Observation, PlayState
from automation import Automation, AutomationError


CONFIG = {"sceneUuid": "scene", "captureItemId": 1, "captureSourceUuid": "game",
          "targets": [{"sceneUuid": "scene", "sceneItemId": 2, "sourceUuid": "game"},
                      {"sceneUuid": "scene", "sceneItemId": 3, "sourceUuid": "camera"}]}


class FakeConnection:
    def __init__(self, port, password, timeout=2):
        self.port, self.password = port, password
        self.connected = False
        self.calls = []
        self.fail_kind = None
        self.fail_item = None
        self.scenes = [{"sceneUuid": "scene", "sceneName": "My scene"}]
        self.items = [{"sceneItemId": index, "sceneItemIndex": index - 1,
                       "sourceUuid": source, "sourceName": source,
                       "isGroup": False, "sourceType": "OBS_SOURCE_TYPE_INPUT", "sceneItemEnabled": True}
                      for index, source in ((1, "game"), (2, "game"), (3, "camera"))]

    def connect(self):
        self.connected = True

    def close(self):
        self.connected = False

    def request(self, kind, data):
        if (not self.connected or kind == self.fail_kind
                or (self.fail_item is not None and data.get("sceneItemId") == self.fail_item)):
            raise ConnectionError("Private password must never escape: " + self.password)
        self.calls.append((kind, dict(data)))
        if kind == "GetSceneList":
            return {"scenes": self.scenes}
        if kind == "GetSceneItemList":
            return {"sceneItems": self.items}
        return {}


class FakeDetector:
    def __init__(self, connection, source_uuid, template_path, *, clock):
        self.connection, self.clock = connection, clock
        self.state = PlayState.PLAYING
        self.last_score, self.last_error = .999, None
        self.fail = False
        self.stopped = False
        self.entered = None
        self.release = None

    def start(self):
        pass

    def observe(self):
        if self.entered is not None:
            self.entered.set()
            self.release.wait(timeout=1)
        if self.fail:
            raise ConnectionError("Detector private exception")
        return Observation(self.state, self.clock())

    def stop(self):
        self.stopped = True


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.connections, self.detectors = [], []

        def connection_factory(*args, **kwargs):
            value = FakeConnection(*args, **kwargs)
            self.connections.append(value)
            return value

        def detector_factory(*args, **kwargs):
            value = FakeDetector(*args, **kwargs)
            self.detectors.append(value)
            return value

        self.factories = {"connection_factory": connection_factory, "detector_factory": detector_factory,
                          "template_capture": lambda connection, source, path: path.write_bytes(b"fake template")}
        self.automation = Automation(self.root, **self.factories)

    def tearDown(self):
        self.automation.close()
        self.temporary.cleanup()

    def ready(self):
        self.automation.connect({"port": 4455, "password": "private-test-password"})
        self.automation.configure(CONFIG)
        self.automation.template()
        return self.connections[-1]

    def wait_for(self, predicate):
        deadline = time.monotonic() + 2
        while not predicate() and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertTrue(predicate())

    def writes(self, connection):
        return [data for kind, data in connection.calls if kind == "SetSceneItemEnabled"]

    def test_private_config_reloads_disarmed_without_any_connection_or_password_response(self):
        self.ready()
        status = self.automation.status()
        self.assertTrue(status["config"]["hasPassword"])
        self.assertNotIn("private-test-password", json.dumps(status))
        self.assertNotIn("password", status["config"])
        self.assertFalse((self.root / "settings.json").exists())
        saved = json.loads((self.root / "automation.json").read_text())
        self.assertEqual(saved["password"], "private-test-password")
        count = len(self.connections)
        reloaded = Automation(self.root, **self.factories)
        try:
            self.assertFalse(reloaded.status()["running"])
            self.assertFalse(reloaded.status()["connected"])
            self.assertTrue(reloaded.status()["templateReady"])
            self.assertEqual(len(self.connections), count)
        finally:
            reloaded.close()

    def test_missing_optional_dependencies_leave_core_manager_available_without_connecting(self):
        import builtins
        real_import = builtins.__import__

        def without_websocket(name, *args, **kwargs):
            if name == "websocket":
                raise ImportError("Optional package absent")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=without_websocket):
            unavailable = Automation(self.root)
        try:
            self.assertFalse(unavailable.status()["available"])
            self.assertFalse(unavailable.status()["running"])
            with self.assertRaises(AutomationError) as caught:
                unavailable.connect({})
            self.assertEqual(caught.exception.code, "automation-unavailable")
        finally:
            unavailable.close()

    def test_configuration_rejects_capture_target_duplicate_group_and_replaced_source(self):
        connection = self.ready()
        for targets in ([CONFIG["targets"][0]] * 2,
                        [{"sceneUuid": "scene", "sceneItemId": 1, "sourceUuid": "game"}],
                        [{"sceneUuid": "other", "sceneItemId": 3, "sourceUuid": "camera"}]):
            with self.subTest(targets=targets), self.assertRaises(AutomationError):
                self.automation.configure({**CONFIG, "targets": targets})
        connection.items[-1]["isGroup"] = True
        with self.assertRaises(AutomationError):
            self.automation.configure(CONFIG)
        connection.items[-1]["isGroup"] = False
        connection.items[-1]["sourceUuid"] = "replacement"
        with self.assertRaises(AutomationError):
            self.automation.start()
        self.assertEqual(self.writes(connection), [])

    def test_start_requires_template_and_remains_an_explicit_action(self):
        self.automation.connect({"port": 4455})
        self.automation.configure(CONFIG)
        with self.assertRaises(AutomationError) as caught:
            self.automation.start()
        self.assertEqual(caught.exception.code, "template-required")
        self.automation.template()
        self.assertFalse(self.automation.status()["running"])
        self.automation.start()
        self.assertTrue(self.automation.status()["running"])

    def test_catalog_restores_current_names_while_running_without_writes_or_persistence(self):
        connection = self.ready()
        self.automation.start()
        self.wait_for(lambda: self.automation.status()["applied"] is True)
        worker = self.automation._thread
        saved = (self.root / "automation.json").read_bytes()
        template = self.automation.template_path.read_bytes()
        writes = list(self.writes(connection))
        connection.scenes[0]["sceneName"] = "Renamed OBS scene"
        connection.items[1]["sourceName"] = "Game capture"
        count = len(connection.calls)
        catalog = self.automation.catalog()
        self.assertEqual(catalog["scenes"], [{"sceneUuid": "scene", "sceneName": "Renamed OBS scene"}])
        self.assertEqual(catalog["items"][1]["sourceName"], "Game capture")
        self.assertEqual(catalog["items"][1]["sceneItemIndex"], 1)
        self.assertEqual(connection.calls[count:], [("GetSceneList", {}),
                                                   ("GetSceneItemList", {"sceneUuid": "scene"})])
        self.assertTrue(catalog["status"]["running"])
        self.assertIs(self.automation._thread, worker)
        self.assertEqual(self.writes(connection), writes)
        self.assertEqual((self.root / "automation.json").read_bytes(), saved)
        self.assertEqual(self.automation.template_path.read_bytes(), template)
        self.assertNotIn("private-test-password", json.dumps(catalog))

    def test_catalog_disconnected_does_not_connect_and_read_failure_does_not_stop_worker(self):
        catalog = self.automation.catalog()
        self.assertEqual(catalog["scenes"], [])
        self.assertEqual(catalog["items"], [])
        self.assertEqual(self.connections, [])
        connection = self.ready()
        self.automation.start()
        self.wait_for(lambda: self.automation.status()["applied"] is True)
        connection.fail_kind = "GetSceneList"
        with self.assertRaises(AutomationError) as caught:
            self.automation.catalog("scene")
        self.assertEqual(caught.exception.code, "obs-catalog-failed")
        self.assertNotIn("private-test-password", str(caught.exception))
        self.assertTrue(connection.connected)
        self.assertTrue(self.automation.status()["running"])
        self.assertIsNone(self.automation.status()["error"])

    def test_catalog_slow_read_does_not_block_stop_or_return_a_replaced_connection(self):
        connection = self.ready()
        self.automation.start()
        self.wait_for(lambda: self.automation.status()["applied"] is True)
        entered, release = threading.Event(), threading.Event()
        original = connection.request
        errors = []

        def slow_request(kind, data):
            if kind == "GetSceneList":
                entered.set()
                release.wait(timeout=1)
            return original(kind, data)

        def lookup():
            try:
                self.automation.catalog()
            except AutomationError as error:
                errors.append(error.code)

        connection.request = slow_request
        reader = threading.Thread(target=lookup)
        reader.start()
        try:
            self.assertTrue(entered.wait(timeout=1))
            self.automation.stop()
            self.assertFalse(self.automation.status()["running"])
            self.assertTrue(reader.is_alive())
            self.automation.connect({})
        finally:
            release.set()
            reader.join(timeout=1)
        self.assertEqual(errors, ["obs-catalog-failed"])

    def test_invalid_saved_reference_requires_recapture_without_a_false_connection_error(self):
        connection = self.ready()
        with patch.object(FakeDetector, "start", side_effect=ValueError("Invalid local reference")):
            with self.assertRaises(AutomationError) as caught:
                self.automation.start()
        self.assertEqual(caught.exception.code, "template-invalid")
        self.assertTrue(connection.connected)
        self.assertFalse(self.automation.status()["templateReady"])
        self.assertFalse(self.automation.status()["running"])
        self.automation.template()
        self.assertTrue(self.automation.status()["templateReady"])
        self.assertIsNone(self.automation.status()["error"])

    def test_stop_yields_to_manual_and_only_selected_placements_are_written(self):
        connection = self.ready()
        self.automation.start()
        self.wait_for(lambda: self.automation.status()["applied"] is True)
        self.assertEqual({item["sceneItemId"] for item in self.writes(connection)}, {2, 3})
        self.assertEqual([item["sceneItemEnabled"] for item in self.writes(connection)], [False, False, True, True])
        self.automation.stop()
        count = len(connection.calls)
        self.assertFalse(self.automation.status()["running"])
        self.assertTrue(self.automation.status()["applied"])
        self.assertTrue(connection.connected)
        time.sleep(.12)
        self.assertEqual(len(connection.calls), count)
        self.automation.start()
        self.wait_for(lambda: self.automation.status()["applied"] is False)

    def test_stop_during_observation_cancels_future_writes_and_preserves_manual_state(self):
        connection = self.ready()
        self.automation.start()
        self.wait_for(lambda: self.automation.status()["applied"] is True)
        detector = self.detectors[-1]
        detector.entered, detector.release = threading.Event(), threading.Event()
        detector.state = PlayState.UNKNOWN
        self.assertTrue(detector.entered.wait(timeout=1))
        stopper = threading.Thread(target=self.automation.stop)
        stopper.start()
        self.assertTrue(self.automation._cancel.wait(timeout=1))
        writes = list(self.writes(connection))
        detector.release.set()
        stopper.join(timeout=1)
        self.assertFalse(stopper.is_alive())
        self.assertEqual(self.writes(connection), writes)
        self.assertFalse(self.automation.status()["running"])
        self.assertIsNone(self.automation.status()["error"])

    def test_runtime_capture_failure_stops_and_requires_reconnect_not_just_restart(self):
        connection = self.ready()
        self.automation.start()
        self.wait_for(lambda: self.automation.status()["applied"] is True)
        self.detectors[-1].fail = True
        self.wait_for(lambda: not self.automation.status()["running"])
        self.assertFalse(connection.connected)
        self.assertNotIn("private", json.dumps(self.automation.status()))
        with self.assertRaises(AutomationError):
            self.automation.start()
        self.automation.connect({"port": 4455})
        self.assertEqual(self.connections[-1].password, "private-test-password")
        self.automation.start()
        self.wait_for(lambda: self.automation.status()["applied"] is False)

    def test_known_temporarily_unavailable_capture_hides_and_can_recover_without_reconnect(self):
        connection = self.ready()
        self.automation.start()
        self.wait_for(lambda: self.automation.status()["applied"] is True)
        detector = self.detectors[-1]
        detector.state, detector.last_error = PlayState.UNKNOWN, "capture-unavailable"
        self.wait_for(lambda: self.automation.status()["applied"] is False)
        status = self.automation.status()
        self.assertTrue(status["running"])
        self.assertEqual(status["state"], "unknown")
        self.assertIsNone(status["error"])
        self.assertTrue(connection.connected)
        detector.state, detector.last_error = PlayState.PLAYING, None
        self.wait_for(lambda: self.automation.status()["applied"] is True)
        self.assertEqual(len(self.connections), 1)

    def test_partial_obs_failure_does_not_retry_or_claim_success(self):
        connection = self.ready()
        connection.fail_item = 3
        self.automation.start()
        self.wait_for(lambda: not self.automation.status()["running"])
        self.assertIsNone(self.automation.status()["applied"])
        self.assertFalse(connection.connected)
        self.assertEqual(self.writes(connection), [{"sceneUuid": "scene", "sceneItemId": 2, "sceneItemEnabled": False}])

    def test_connection_errors_are_redacted_and_password_may_be_explicitly_cleared(self):
        connection = self.ready()
        connection.fail_kind = "GetSceneItemList"
        with self.assertRaises(AutomationError) as caught:
            self.automation.discover("scene")
        self.assertNotIn("private-test-password", str(caught.exception))
        self.assertFalse(self.automation.status()["connected"])
        self.automation.connect({"password": ""})
        self.assertEqual(self.connections[-1].password, "")
        self.assertFalse(self.automation.status()["config"]["hasPassword"])

    def test_changed_capture_invalidates_template_but_changing_targets_does_not(self):
        self.ready()
        self.automation.configure({**CONFIG, "targets": CONFIG["targets"][:1]})
        self.assertTrue(self.automation.status()["templateReady"])
        self.automation.configure({**CONFIG, "captureItemId": 2,
                                   "targets": [CONFIG["targets"][1]]})
        self.assertFalse(self.automation.status()["templateReady"])

    def test_idle_disconnect_is_visible_and_failed_recapture_does_not_keep_old_reference(self):
        connection = self.ready()
        connection.connected = False  # Receiver thread can invalidate an idle socket.
        self.assertFalse(self.automation.status()["connected"])
        self.assertEqual(self.automation.status()["error"], "obs-disconnected")
        self.automation.connect({})

        def fail_capture(*args):
            raise ValueError("Invalid frame")

        self.automation.template_capture = fail_capture
        with self.assertRaises(AutomationError):
            self.automation.template()
        self.assertFalse(self.automation.status()["templateReady"])


if __name__ == "__main__":
    unittest.main()
