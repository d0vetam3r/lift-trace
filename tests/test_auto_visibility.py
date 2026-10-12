"""Synthetic control-policy tests; no device, capture or live OBS connection."""
from __future__ import annotations

import unittest

from auto_visibility import Observation, ObsSceneItems, PlayState, SceneItem, VisibilitySession
from tools.replay_visibility import EXAMPLE, replay


class Detector:
    def __init__(self):
        self.sample = Observation(PlayState.UNKNOWN, 0)
        self.starts = self.stops = 0
        self.fail_start = self.fail_read = False

    def start(self):
        self.starts += 1
        if self.fail_start:
            raise RuntimeError("Cannot acquire detector")

    def stop(self):
        self.stops += 1

    def observe(self):
        if self.fail_read:
            raise RuntimeError("Capture failed")
        return self.sample


class VisibilityTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.detector = Detector()
        self.items = [{"sceneItemId": 1, "sourceUuid": "game"},
                      {"sceneItemId": 2, "sourceUuid": "game"},
                      {"sceneItemId": 3, "sourceUuid": "camera"}]
        self.writes = []
        self.fail_item = None

        def request(kind, data):
            if kind == "GetSceneItemList":
                return {"sceneItems": self.items}
            if data["sceneItemId"] == self.fail_item:
                raise ConnectionError("Disconnected after an earlier item was changed")
            self.writes.append((data["sceneItemId"], data["sceneItemEnabled"]))
            return {}

        self.output = ObsSceneItems((SceneItem("scene", 2, "game"),
                                     SceneItem("scene", 3, "camera")), request)
        self.session = VisibilitySession(self.detector, self.output, clock=lambda: self.now)
        self.session.start()

    def observe(self, at, state, stamp=None):
        self.now = at
        self.detector.sample = Observation(state, at if stamp is None else stamp)
        return self.session.tick()

    def play(self):
        self.observe(0, PlayState.PLAYING)
        self.observe(0.25, PlayState.PLAYING)
        self.assertTrue(self.session.status().applied)

    def test_only_continuous_gameplay_shows_selected_items_and_exit_is_debounced(self):
        self.play()
        self.assertEqual(self.writes, [(2, False), (3, False), (2, True), (3, True)])
        self.observe(0.3, PlayState.NOT_PLAYING)
        self.observe(0.4, PlayState.PLAYING)  # One-frame misclassification must not flicker.
        self.observe(0.5, PlayState.NOT_PLAYING)
        self.assertTrue(self.observe(0.7, PlayState.NOT_PLAYING).applied)
        self.assertFalse(self.observe(0.85, PlayState.NOT_PLAYING).applied)
        self.observe(0.9, PlayState.NOT_PLAYING)
        self.assertEqual(self.writes[-2:], [(2, False), (3, False)])
        self.assertEqual(len(self.writes), 6)  # No repeated writes or original game-item write.

    def test_cached_frame_does_not_complete_entry_and_stale_frame_hides(self):
        self.observe(0, PlayState.PLAYING)
        self.assertFalse(self.observe(0.3, PlayState.PLAYING, stamp=0).applied)
        self.observe(0.4, PlayState.PLAYING)
        self.assertTrue(self.session.status().applied)
        status = self.observe(1.0, PlayState.PLAYING, stamp=0.4)
        self.assertEqual(status.state, PlayState.UNKNOWN)
        self.assertFalse(status.applied)

    def test_sampling_gap_starts_a_new_confirmation_window(self):
        self.observe(0, PlayState.PLAYING)
        self.assertFalse(self.observe(1, PlayState.PLAYING).applied)
        self.assertTrue(self.observe(1.25, PlayState.PLAYING).applied)

    def test_unknown_and_capture_error_hide_without_claiming_not_playing(self):
        self.play()
        status = self.observe(0.3, PlayState.UNKNOWN)
        self.assertEqual(status.state, PlayState.UNKNOWN)
        self.assertFalse(status.applied)
        self.detector.fail_read = True
        self.assertEqual(self.session.tick().error, "detector-observation-invalid")
        self.detector.fail_read = False
        self.assertIsNone(self.observe(0.4, PlayState.PLAYING).error)
        self.assertFalse(self.session.status().applied)

    def test_future_reversed_and_nonfinite_timestamps_cannot_enable(self):
        for invalid in (10, -1, float("nan"), float("inf")):
            with self.subTest(stamp=invalid):
                self.observe(0.1, PlayState.PLAYING, stamp=invalid)
                self.assertFalse(self.session.status().applied)
        self.observe(0.2, PlayState.PLAYING)
        self.observe(0.3, PlayState.PLAYING, stamp=0.1)
        self.assertFalse(self.observe(0.4, PlayState.PLAYING, stamp=0.2).applied)
        self.assertFalse(self.observe(0.5, PlayState.PLAYING).applied)

    def test_stop_is_manual_and_restart_rejects_previous_session_observations(self):
        self.play()
        self.session.stop()
        count = len(self.writes)
        self.observe(0.3, PlayState.NOT_PLAYING)
        self.assertEqual(len(self.writes), count)
        self.now = 0.5
        self.session.start()
        self.session.start()  # Idempotent start does not allocate twice.
        self.assertEqual(self.detector.starts, 2)
        self.assertFalse(self.observe(0.55, PlayState.PLAYING, stamp=0.25).applied)
        self.observe(0.6, PlayState.PLAYING)
        self.assertTrue(self.observe(0.85, PlayState.PLAYING).applied)

    def test_changed_target_aborts_before_any_item_is_written(self):
        self.items[-1]["sourceUuid"] = "replacement-camera"
        status = self.session.tick()
        self.assertFalse(status.running)
        self.assertIsNone(status.applied)
        self.assertEqual(status.error, "obs-apply-failed")
        self.assertEqual(self.writes, [])

    def test_partial_failure_is_not_success_and_requires_explicit_restart(self):
        self.fail_item = 3
        status = self.session.tick()
        self.assertEqual(self.writes, [(2, False)])
        self.assertFalse(status.running)
        self.assertIsNone(status.applied)
        self.assertEqual(self.detector.stops, 1)
        self.session.tick()
        self.assertEqual(self.writes, [(2, False)])
        self.fail_item = None
        self.now = 0.5
        self.session.start()
        self.assertFalse(self.observe(0.5, PlayState.PLAYING).applied)

    def test_start_failure_cleans_detector_and_never_writes_obs(self):
        self.session.stop()
        self.detector.fail_start = True
        self.assertEqual(self.session.start().error, "detector-start-failed")
        self.assertFalse(self.session.status().running)
        self.assertEqual(self.detector.stops, 2)
        self.session.tick()
        self.assertEqual(self.writes, [])

    def test_replay_demonstrates_only_selected_targets_then_yields_to_manual_control(self):
        rows = replay(EXAMPLE)
        transitions = [(row["at"], row["applied"]) for row in rows if row["requests"]]
        self.assertEqual(transitions, [(0, False), (0.35, True), (1, False), (1.4, True), (2, False)])
        self.assertFalse(rows[-1]["running"])
        self.assertEqual(rows[-1]["requests"], [])
        for row in rows:
            self.assertEqual({request["requestData"]["sceneItemId"] for request in row["requests"]},
                             {2, 3} if row["requests"] else set())


if __name__ == "__main__":
    unittest.main()
