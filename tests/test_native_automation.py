"""Native inputs use the existing explicit selection and visibility policy.

No OBS process, network connection, controller, or recording dependency is used.
The native input kind is metadata: control remains bound to exact scene items.
"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from automation import Automation, AutomationError
from auto_visibility import Observation, ObsSceneItems, PlayState, SceneItem, VisibilitySession


NATIVE_KIND = "lift_trace_native_pacing"
CONFIG = {"sceneUuid": "scene-a", "captureItemId": 1, "captureSourceUuid": "game",
          "targets": [{"sceneUuid": "scene-a", "sceneItemId": 2, "sourceUuid": "native"}]}


class SceneFixture:
    def __init__(self, *_args, **_kwargs):
        self.connected = False
        self.scene_uuid = "scene-a"
        self.scene_name = "Play scene"
        self.writes = []
        self.items = []
        for item_id, uuid, name, kind, visible in (
                (1, "game", "Game", "game_capture", True),
                (2, "native", "Lift Native", NATIVE_KIND, False),
                (3, "native", "Lift Native", NATIVE_KIND, False),
                (4, "browser", "Browser overlay", "browser_source", True)):
            self.items.append({"sceneItemId": item_id, "sceneItemIndex": item_id - 1,
                               "sourceUuid": uuid, "sourceName": name, "inputKind": kind,
                               "sourceType": "OBS_SOURCE_TYPE_INPUT", "isGroup": False,
                               "sceneItemEnabled": visible})

    def connect(self):
        self.connected = True

    def close(self):
        self.connected = False

    def request(self, kind, data):
        if not self.connected:
            raise ConnectionError("Fixture disconnected")
        if kind == "GetSceneList":
            return {"scenes": [{"sceneUuid": self.scene_uuid, "sceneName": self.scene_name}]}
        if data.get("sceneUuid") != self.scene_uuid:
            raise ValueError("Fixture scene no longer exists")
        if kind == "GetSceneItemList":
            return {"sceneItems": deepcopy(self.items)}
        if kind == "SetSceneItemEnabled":
            item = next(item for item in self.items if item["sceneItemId"] == data["sceneItemId"])
            item["sceneItemEnabled"] = data["sceneItemEnabled"]
            self.writes.append(dict(data))
            return {}
        raise AssertionError(kind)


class NativeAutomationTests(unittest.TestCase):
    def setUp(self):
        self.scene = SceneFixture()
        self.scene.connect()
        self.output = ObsSceneItems((SceneItem("scene-a", 2, "native"),), self.scene.request)

    def test_catalog_and_configuration_accept_native_kind_with_exact_duplicate_placement(self):
        with tempfile.TemporaryDirectory() as directory:
            automation = Automation(Path(directory), connection_factory=lambda *_a, **_k: self.scene,
                                    detector_factory=lambda *_a, **_k: None,
                                    template_capture=lambda *_a, **_k: None)
            try:
                automation.connect({"port": 4455, "password": ""})
                automation.configure(CONFIG)
                catalog = automation.catalog("scene-a")
                self.assertEqual(catalog["items"][1]["inputKind"], NATIVE_KIND)
                self.assertEqual(automation.status()["config"]["targets"], CONFIG["targets"])
                self.assertFalse(automation.status()["running"])
                self.assertEqual(self.scene.writes, [])
                # A saved name is never used to recover a replaced item.
                self.scene.items[1]["sourceUuid"] = "replacement"
                with self.assertRaises(AutomationError):
                    automation.configure(CONFIG)
            finally:
                automation.close()
                if automation._log_thread is not None:
                    automation._log_thread.join(timeout=2)
                    self.assertFalse(automation._log_thread.is_alive())

    def test_native_rename_preserves_identity_and_only_selected_placement_changes(self):
        self.output.set_visible(False)
        self.scene.scene_name = "Renamed scene"
        self.scene.items[1]["sourceName"] = "Renamed native overlay"
        self.output.set_visible(True)
        self.assertEqual([row["sceneItemId"] for row in self.scene.writes], [2, 2])
        self.assertEqual([item["sceneItemEnabled"] for item in self.scene.items],
                         [True, True, False, True])

    def test_reused_native_item_id_with_new_uuid_aborts_before_any_batch_write(self):
        output = ObsSceneItems((SceneItem("scene-a", 4, "browser"),
                                SceneItem("scene-a", 2, "native")), self.scene.request)
        self.scene.items[1]["sourceUuid"] = "replacement-native"
        with self.assertRaises(ValueError):
            output.set_visible(False)
        self.assertEqual(self.scene.writes, [])
        self.assertTrue(self.scene.items[3]["sceneItemEnabled"])

    def test_recreated_item_with_original_source_uuid_is_not_automatically_followed(self):
        self.scene.items[1]["sceneItemId"] = 20
        with self.assertRaises(ValueError):
            self.output.set_visible(True)
        self.assertEqual(self.scene.writes, [])

    def test_replaced_scene_with_same_name_is_not_automatically_followed(self):
        self.scene.scene_uuid = "replacement-scene"
        with self.assertRaises(ValueError):
            self.output.set_visible(True)
        self.assertEqual(self.scene.writes, [])

    def test_ambiguous_duplicate_item_identity_is_rejected(self):
        self.scene.items.append(dict(self.scene.items[1]))
        with self.assertRaises(ValueError):
            self.output.set_visible(True)
        self.assertEqual(self.scene.writes, [])

    def test_native_visibility_requires_confirmed_play_and_recovers_without_false_entry(self):
        class Detector:
            sample = Observation(PlayState.UNKNOWN, 0)
            last_error = None
            def start(self): pass
            def stop(self): pass
            def observe(self): return self.sample

        detector = Detector()
        now = 0.0
        session = VisibilitySession(detector, self.output, clock=lambda: now)
        session.start()

        def observe(at, state, error=None):
            nonlocal now
            now = at
            detector.sample, detector.last_error = Observation(state, at), error
            return session.tick()

        observe(0, PlayState.NOT_PLAYING)
        observe(.4, PlayState.NOT_PLAYING)
        self.assertFalse(self.scene.items[1]["sceneItemEnabled"])
        observe(.6, PlayState.PLAYING)
        self.assertFalse(self.scene.items[1]["sceneItemEnabled"])
        observe(.8, PlayState.PLAYING)
        self.assertTrue(self.scene.items[1]["sceneItemEnabled"])
        observe(1, PlayState.UNKNOWN, "capture-unavailable")
        observe(1.2, PlayState.UNKNOWN, "capture-unavailable")
        observe(1.4, PlayState.PLAYING)
        observe(1.6, PlayState.PLAYING)
        self.assertEqual([row["sceneItemEnabled"] for row in self.scene.writes], [False, True])
        for stamp in (1.8, 2.2, 2.6, 3, 3.4, 3.8):
            observe(stamp, PlayState.UNKNOWN, "capture-unavailable")
        self.assertFalse(self.scene.items[1]["sceneItemEnabled"])
        observe(4, PlayState.PLAYING)
        observe(4.2, PlayState.PLAYING)
        self.assertFalse(self.scene.items[1]["sceneItemEnabled"])
        observe(4.4, PlayState.NOT_PLAYING)
        observe(4.8, PlayState.NOT_PLAYING)
        observe(5, PlayState.PLAYING)
        observe(5.2, PlayState.PLAYING)
        self.assertEqual([row["sceneItemEnabled"] for row in self.scene.writes],
                         [False, True, False, True])
        self.assertEqual([item["sceneItemEnabled"] for item in self.scene.items],
                         [True, True, False, True])
        session.stop()
        self.assertTrue(self.scene.items[1]["sceneItemEnabled"])


if __name__ == "__main__":
    unittest.main()
