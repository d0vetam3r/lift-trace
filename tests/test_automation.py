"""Runtime lifecycle tests with no OBS connection, screen capture, or credentials."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from auto_visibility import Observation, PlayState
from automation import Automation, AutomationError
from obs_connection import ObsRequestError


CONFIG = {"sceneUuid": "scene", "captureItemId": 1, "captureSourceUuid": "game",
          "targets": [{"sceneUuid": "scene", "sceneItemId": 2, "sourceUuid": "game"},
                      {"sceneUuid": "scene", "sceneItemId": 3, "sourceUuid": "camera"}]}


def write_template(path, color="white"):
    """A synthetic nonconstant PNG, unrelated to any game screenshot."""
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    with Image.new("RGB", (90, 20), "black") as image:
        image.paste(color, (0, 0, 45, 20))
        image.save(path, format="PNG")


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
        self.template_path = template_path
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
                          "template_capture": lambda connection, source, path: write_template(path),
                          "default_template_path": self.root / "bundled-reference.png"}
        self.automation = Automation(self.root, **self.factories)

    def tearDown(self):
        self.close_automation(self.automation)
        self.temporary.cleanup()

    def close_automation(self, automation):
        automation.close()
        # Runtime close deliberately bounds disk waiting to 0.2s. This fixture
        # owns the directory, so no writer may remain when cleanup removes it.
        writer = automation._log_thread
        if writer is not None:
            writer.join(timeout=5)
            self.assertFalse(writer.is_alive(), "Fixture event writer did not stop after close")
        self.assertEqual(automation._log_queue.unfinished_tasks, 0)

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

    def wait_for_event_log(self):
        self.wait_for(lambda: self.automation._log_queue.unfinished_tasks == 0)

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
            self.assertEqual(reloaded.status()["referenceSource"], "custom")
            self.assertEqual(len(self.connections), count)
        finally:
            self.close_automation(reloaded)

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
            self.close_automation(unavailable)

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

    def scripted_capture(self):
        now = [100.0]
        profile = [(PlayState.PLAYING, 100.0, .01, .005)]
        self.automation.clock = lambda: now[0]

        def observe(detector):
            state, stamp, age, latency = profile[0]
            now[0] = stamp + age
            detector.capture_latency = latency
            detector.last_error = None
            return Observation(state, stamp)

        return profile, observe

    def advance_capture(self, profile, state, stamp, age, latency=.005):
        profile[0] = (state, stamp, age, latency)
        self.wait_for(lambda: abs((self.automation.status()["diagnostic"]["observationAge"] or 0) - age) < .000001)

    def test_temporary_stale_frame_keeps_connection_visibility_and_preserves_recovery_log(self):
        connection = self.ready()
        profile, observe = self.scripted_capture()
        with patch.object(FakeDetector, "observe", observe):
            self.automation.start()
            self.wait_for(lambda: self.automation.status()["applied"] is False)
            self.advance_capture(profile, PlayState.PLAYING, 100.25, .02)
            self.assertTrue(self.automation.status()["applied"])
            worker = self.automation._thread
            writes = list(self.writes(connection))
            self.advance_capture(profile, PlayState.PLAYING, 100.35, 1.25, 1.2)
            status = self.automation.status()
            self.assertTrue(status["running"])
            self.assertTrue(status["connected"])
            self.assertTrue(status["applied"])
            self.assertIsNone(status["error"])
            self.assertEqual(status["diagnostic"], {
                "observationReason": "stale-observation", "observationAge": 1.25,
                "exceptionType": None, "exceptionCode": None, "captureLatency": 1.2,
                "detectorError": None, "recoveryState": "waiting-for-frame"})
            status["diagnostic"]["observationReason"] = "caller-mutation"
            self.assertEqual(self.automation.status()["diagnostic"]["observationReason"], "stale-observation")
            self.advance_capture(profile, PlayState.PLAYING, 101.65, .03)
            self.advance_capture(profile, PlayState.PLAYING, 101.9, .04)
            self.assertIsNone(self.automation.status()["diagnostic"]["recoveryState"])
            self.assertIs(self.automation._thread, worker)
            self.assertTrue(connection.connected)
            self.assertEqual(len(self.connections), 1)
            self.assertEqual(self.writes(connection), writes)
            self.automation.stop()
        self.wait_for_event_log()
        records = [json.loads(line) for line in (self.root / "automation-events.jsonl").read_text().splitlines()]
        delayed = next(record for record in records if "capture-delayed" in record["events"])
        self.assertEqual(delayed["diagnostic"]["observationAge"], 1.25)
        self.assertEqual(delayed["diagnostic"]["captureLatency"], 1.2)
        self.assertTrue(delayed["applied"])
        self.assertTrue(any("capture-resumed" in record["events"] for record in records))

    def test_long_capture_stall_hides_once_and_requires_nonplaying_before_new_play(self):
        connection = self.ready()
        profile, observe = self.scripted_capture()
        with patch.object(FakeDetector, "observe", observe):
            self.automation.start()
            self.wait_for(lambda: self.automation.status()["applied"] is False)
            self.advance_capture(profile, PlayState.PLAYING, 100.25, .02)
            self.assertTrue(self.automation.status()["applied"])
            self.advance_capture(profile, PlayState.PLAYING, 100.35, 1.25, 1.2)
            self.advance_capture(profile, PlayState.PLAYING, 103.2, 1.3, 1.25)
            status = self.automation.status()
            self.assertTrue(status["running"])
            self.assertTrue(status["connected"])
            self.assertFalse(status["applied"])
            self.assertIsNone(status["error"])
            self.assertEqual(status["diagnostic"]["recoveryState"], "waiting-for-not-playing")
            after_hide = list(self.writes(connection))
            self.assertEqual([item["sceneItemEnabled"] for item in after_hide], [False, False, True, True, False, False])
            for stamp, age in ((104.6, .01), (104.85, .02), (105.1, .03)):
                self.advance_capture(profile, PlayState.PLAYING, stamp, age)
                self.assertFalse(self.automation.status()["applied"])
                self.assertEqual(self.writes(connection), after_hide)
            self.advance_capture(profile, PlayState.NOT_PLAYING, 105.2, .01)
            self.assertEqual(self.automation.status()["diagnostic"]["recoveryState"], "waiting-for-not-playing")
            self.advance_capture(profile, PlayState.NOT_PLAYING, 105.55, .02)
            self.assertIsNone(self.automation.status()["diagnostic"]["recoveryState"])
            self.assertEqual(self.writes(connection), after_hide)
            self.advance_capture(profile, PlayState.PLAYING, 105.65, .03)
            self.assertFalse(self.automation.status()["applied"])
            self.advance_capture(profile, PlayState.PLAYING, 105.9, .04)
            self.assertTrue(self.automation.status()["applied"])
            self.assertEqual([item["sceneItemEnabled"] for item in self.writes(connection)],
                             [False, False, True, True, False, False, True, True])
            self.assertEqual(len(self.connections), 1)
            self.assertEqual(len(self.detectors), 1)
            self.automation.stop()

    def test_automation_uses_one_worker_with_a_five_hertz_capture_interval(self):
        self.ready()
        self.automation.clock = lambda: 100.0
        self.automation.start()
        worker = self.automation._thread
        with patch.object(self.automation._cancel, "wait", wraps=self.automation._cancel.wait) as waiting:
            self.wait_for(lambda: waiting.call_count >= 2)
            with self.assertRaises(AutomationError):
                self.automation.start()
            self.assertIs(self.automation._thread, worker)
            self.assertEqual(len(self.detectors), 1)
            self.assertEqual(len(self.connections), 1)
            self.assertTrue(all(abs(call.args[0] - .2) < .000001 for call in waiting.call_args_list))
            self.automation.stop()

    def test_request_failure_diagnostic_exposes_only_type_code_and_safe_detector_error(self):
        self.ready()

        def rejected_capture(detector):
            detector.capture_latency = .125
            detector.last_error = "private-image-response-password"
            raise ObsRequestError("private-test-password-imageData", 601)

        def clear_detector_counters(detector):
            detector.stopped = True
            detector.capture_latency = detector.last_error = None

        with patch.object(FakeDetector, "observe", rejected_capture), \
                patch.object(FakeDetector, "stop", clear_detector_counters):
            self.automation.start()
            self.wait_for(lambda: not self.automation.status()["running"])
        status = self.automation.status()
        self.assertEqual(status["diagnostic"], {
            "observationReason": "observe-exception", "observationAge": None,
            "exceptionType": "ObsRequestError", "exceptionCode": 601,
            "captureLatency": .125, "detectorError": "detector-error", "recoveryState": None})
        self.assertNotIn("private", json.dumps(status, allow_nan=False))

    def test_local_event_log_records_lifecycle_error_and_recovery_without_per_tick_writes(self):
        self.ready()
        self.wait_for_event_log()  # The writer creates the file asynchronously.
        log = self.root / "automation-events.jsonl"
        self.automation.start()
        self.wait_for(lambda: self.automation.status()["applied"] is True)
        self.wait_for(lambda: b'"state":"playing"' in log.read_bytes())
        stable = log.read_bytes()
        time.sleep(.22)
        self.assertEqual(log.read_bytes(), stable)
        self.detectors[-1].fail = True
        self.wait_for(lambda: not self.automation.status()["running"])
        self.automation.connect({})
        self.automation.start()
        self.wait_for(lambda: self.automation.status()["applied"] is True)
        self.automation.stop()
        self.wait_for_event_log()
        records = [json.loads(line) for line in log.read_text().splitlines()]
        events = [event for record in records for event in record["events"]]
        for required in ("connected", "started", "error", "stopped", "recovered"):
            self.assertIn(required, events)
        failure = next(record for record in records if record["error"] == "detector-observation-invalid")
        self.assertEqual(failure["diagnostic"]["exceptionType"], "ConnectionError")
        self.assertEqual(failure["diagnostic"]["observationReason"], "observe-exception")
        self.assertNotIn("private", log.read_text())
        for record in records:
            self.assertEqual(datetime.fromisoformat(record["at"]).utcoffset(), timedelta(0))
            self.assertNotIn("config", record)

    def test_event_log_records_normal_play_transitions_without_logging_stable_frames(self):
        self.ready()
        self.wait_for_event_log()
        log = self.root / "automation-events.jsonl"
        self.automation.start()
        self.wait_for(lambda: b'"state":"playing"' in log.read_bytes())
        self.detectors[-1].state = PlayState.NOT_PLAYING
        self.wait_for(lambda: b'"state":"not_playing"' in log.read_bytes())
        self.detectors[-1].state = PlayState.PLAYING
        self.wait_for(lambda: log.read_bytes().count(b'"state":"playing"') == 2)
        records = [json.loads(line) for line in log.read_text().splitlines()]
        transitions = [(record["state"], record["applied"]) for record in records
                       if record["state"] != "unknown" and "state-changed" in record["events"]]
        self.assertEqual(transitions, [("playing", True), ("not_playing", False), ("playing", True)])
        self.assertTrue(all(record["score"] == .999 for record in records if record["state"] != "unknown"))
        stable = log.read_bytes()
        time.sleep(.22)
        self.assertEqual(log.read_bytes(), stable)

    def test_local_event_log_rotates_one_bounded_backup(self):
        with patch("automation.DIAGNOSTIC_LOG_BYTES", 1024):
            for index in range(30):
                with self.automation._state_lock:
                    self.automation._state["error"] = "detector-observation-invalid" if index % 2 == 0 else None
                self.automation._record_transition()
            self.wait_for_event_log()
        paths = list(self.root.glob("automation-events.jsonl*"))
        self.assertEqual({path.name for path in paths}, {"automation-events.jsonl", "automation-events.jsonl.1"})
        for path in paths:
            self.assertLessEqual(path.stat().st_size, 1024)
            self.assertTrue(all(isinstance(json.loads(line), dict) for line in path.read_text().splitlines()))

    def test_event_log_write_failure_never_stops_automation_or_retries_every_tick(self):
        self.ready()
        self.wait_for_event_log()
        original_open = Path.open
        writes = []

        def blocked_log(path, *args, **kwargs):
            if path.name == "automation-events.jsonl":
                writes.append(path.name)
                raise PermissionError("private-path")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", blocked_log):
            self.automation.start()
            self.wait_for(lambda: self.automation.status()["applied"] is True)
            self.wait_for(lambda: len(writes) >= 3)  # Start, initial OFF, confirmed gameplay.
            count = len(writes)
            time.sleep(.22)
            self.assertEqual(len(writes), count)
            self.assertTrue(self.automation.status()["running"])
            self.assertIsNone(self.automation.status()["error"])
            self.automation.stop()
            self.wait_for_event_log()
            self.assertFalse(self.automation.status()["running"])
            self.assertTrue(self.automation.status()["connected"])

    def test_event_log_allowlist_drops_private_extra_fields_and_nonfinite_numbers(self):
        with self.automation._state_lock:
            self.automation._state.update(error="private-error-payload", diagnostic={
                "observationReason": "private-imageData", "exceptionType": "private password",
                "exceptionCode": 2 ** 64, "captureLatency": float("inf"),
                "observationAge": float("nan"), "detectorError": "private-source-name",
                "imageData": "private-pixels", "password": "private-password"})
        self.automation._record_transition()
        self.wait_for_event_log()
        log = (self.root / "automation-events.jsonl").read_text()
        self.assertNotIn("private", log)
        record = json.loads(log)
        self.assertEqual(record["error"], "other-error")
        self.assertEqual(record["diagnostic"], {"observationReason": None, "exceptionType": None,
                                               "exceptionCode": None, "captureLatency": None,
                                               "observationAge": None, "detectorError": "detector-error",
                                               "recoveryState": None})

    def test_slow_event_writer_does_not_block_observation_stop_or_bounded_close(self):
        entered, release = threading.Event(), threading.Event()
        original = self.automation._append_event

        def slow_append(raw):
            entered.set()
            release.wait(timeout=3)
            original(raw)

        with patch.object(self.automation, "_append_event", side_effect=slow_append):
            try:
                self.ready()
                self.assertTrue(entered.wait(timeout=1))
                self.automation.start()
                self.wait_for(lambda: self.automation.status()["applied"] is True)
                self.detectors[-1].state = PlayState.NOT_PLAYING
                self.wait_for(lambda: self.automation.status()["applied"] is False)
                started = time.monotonic()
                self.automation.stop()
                self.assertLess(time.monotonic() - started, .5)
                self.assertIsNone(self.automation.status()["error"])
                started = time.monotonic()
                self.automation.close()
                self.assertLess(time.monotonic() - started, .7)
                self.assertTrue(self.automation._log_thread.is_alive())
            finally:
                release.set()
                if self.automation._log_thread is not None:
                    self.automation._log_thread.join(timeout=2)

    def test_full_event_queue_drops_records_without_blocking_or_spawning_more_writers(self):
        entered, release = threading.Event(), threading.Event()

        def slow_append(raw):
            entered.set()
            release.wait(timeout=3)

        with patch.object(self.automation, "_append_event", side_effect=slow_append):
            try:
                with self.automation._state_lock:
                    self.automation._state["error"] = "detector-observation-invalid"
                self.automation._record_transition()
                self.assertTrue(entered.wait(timeout=1))
                writer = self.automation._log_thread
                started = time.monotonic()
                for index in range(200):
                    with self.automation._state_lock:
                        self.automation._state["error"] = None if index % 2 == 0 else "detector-observation-invalid"
                    self.automation._record_transition()
                self.assertLess(time.monotonic() - started, .5)
                self.assertEqual(self.automation._log_queue.qsize(), 64)
                self.assertIs(self.automation._log_thread, writer)
                self.assertTrue(writer.daemon)
            finally:
                release.set()
                self.automation.close()
                if self.automation._log_thread is not None:
                    self.automation._log_thread.join(timeout=2)

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

    def test_fresh_install_uses_builtin_without_registration_or_automatic_start(self):
        write_template(self.automation.default_template_path, "red")
        self.assertEqual(self.automation.status()["referenceSource"], "builtin")
        self.assertTrue(self.automation.status()["templateReady"])
        self.assertEqual(self.connections, [])
        self.assertFalse(self.automation.status()["running"])
        self.automation.connect({"port": 4455})
        self.automation.configure(CONFIG)
        with patch.object(self.automation, "template_capture", side_effect=AssertionError("No registration")):
            self.automation.start()
        self.assertEqual(self.detectors[-1].template_path, self.automation.default_template_path)
        self.assertFalse(self.automation.template_path.exists())
        self.automation.stop()

    def test_valid_saved_custom_reference_takes_priority_over_builtin(self):
        write_template(self.automation.default_template_path, "red")
        self.ready()
        self.assertEqual(self.automation.status()["referenceSource"], "custom")
        self.automation.start()
        self.assertEqual(self.detectors[-1].template_path, self.automation.template_path)
        self.automation.stop()
        reloaded = Automation(self.root, **self.factories)
        try:
            self.assertEqual(reloaded.status()["referenceSource"], "custom")
            self.assertFalse(reloaded.status()["connected"])
        finally:
            self.close_automation(reloaded)

    def test_capture_change_removes_custom_and_falls_back_to_builtin(self):
        write_template(self.automation.default_template_path)
        self.ready()
        self.automation.configure({**CONFIG, "captureItemId": 2,
                                   "targets": [CONFIG["targets"][1]]})
        self.assertFalse(self.automation.template_path.exists())
        self.assertTrue(self.automation.status()["templateReady"])
        self.assertEqual(self.automation.status()["referenceSource"], "builtin")

    def test_invalid_custom_falls_back_to_valid_builtin_without_overwriting_it(self):
        write_template(self.automation.default_template_path)
        self.root.mkdir(exist_ok=True)
        self.automation.template_path.write_bytes(b"invalid custom")
        self.assertEqual(self.automation.status()["referenceSource"], "builtin")
        self.assertEqual(self.automation.template_path.read_bytes(), b"invalid custom")

    def test_missing_or_invalid_builtin_never_claims_readiness_or_bypasses_detector(self):
        self.automation.connect({"port": 4455})
        self.automation.configure(CONFIG)
        for contents, expected in ((None, "template-required"), (b"invalid", "template-invalid")):
            with self.subTest(contents=contents):
                if contents is not None:
                    self.automation.default_template_path.write_bytes(contents)
                status = self.automation.status()
                self.assertFalse(status["templateReady"])
                self.assertIsNone(status["referenceSource"])
                with self.assertRaises(AutomationError) as caught:
                    self.automation.start()
                self.assertEqual(caught.exception.code, expected)
        self.assertEqual(self.detectors, [])
        self.assertEqual(self.writes(self.connections[-1]), [])

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
