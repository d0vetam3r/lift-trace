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

    def test_cached_frame_does_not_complete_entry_and_stale_frame_does_not_extend_grace(self):
        self.observe(0, PlayState.PLAYING)
        self.assertFalse(self.observe(0.3, PlayState.PLAYING, stamp=0).applied)
        self.observe(0.4, PlayState.PLAYING)
        self.assertTrue(self.session.status().applied)
        status = self.observe(1.0, PlayState.PLAYING, stamp=0.4)
        self.assertTrue(status.applied)
        self.assertIsNone(status.error)
        self.assertEqual(self.session.recovery_state, "waiting-for-frame")
        status = self.observe(2.41, PlayState.PLAYING, stamp=0.4)
        self.assertEqual(status.state, PlayState.UNKNOWN)
        self.assertFalse(status.applied)
        self.assertEqual(self.session.recovery_state, "waiting-for-not-playing")

    def test_one_slow_capture_keeps_overlay_on_without_a_false_song_boundary(self):
        self.play()
        original_writes = list(self.writes)
        status = self.observe(1.8, PlayState.NOT_PLAYING, stamp=.4)
        self.assertTrue(status.running)
        self.assertTrue(status.applied)
        self.assertIsNone(status.error)
        self.assertEqual(self.session.observation_reason, "stale-observation")
        self.assertEqual(self.session.recovery_state, "waiting-for-frame")
        self.assertTrue(self.observe(2.0, PlayState.PLAYING).applied)
        self.assertEqual(self.session.recovery_state, "waiting-for-frame")
        self.assertTrue(self.observe(2.2, PlayState.PLAYING).applied)
        self.assertIsNone(self.session.recovery_state)
        self.assertEqual(self.writes, original_writes)

    def test_stall_time_does_not_complete_exit_confirmation(self):
        self.play()
        self.assertTrue(self.observe(.3, PlayState.NOT_PLAYING).applied)
        self.assertTrue(self.observe(1.75, PlayState.NOT_PLAYING, stamp=.35).applied)
        self.assertTrue(self.observe(1.8, PlayState.NOT_PLAYING).applied)
        self.assertTrue(self.observe(2.05, PlayState.NOT_PLAYING).applied)
        self.assertFalse(self.observe(2.15, PlayState.NOT_PLAYING).applied)
        self.assertIsNone(self.session.recovery_state)

    def test_stall_time_cannot_complete_entry_or_turn_on_a_cold_session(self):
        for initial_score in (False, True):
            with self.subTest(initial_score=initial_score):
                self.session.stop()
                self.now = 0
                self.session.start()
                if initial_score:
                    self.assertFalse(self.observe(.1, PlayState.PLAYING).applied)
                self.assertFalse(self.observe(.8, PlayState.PLAYING, stamp=.1).applied)
                self.assertFalse(self.observe(.9, PlayState.PLAYING).applied)
                self.assertTrue(self.observe(1.15, PlayState.PLAYING).applied)

    def test_long_stall_hides_once_and_requires_a_fresh_exit_before_the_next_entry(self):
        self.play()
        self.assertTrue(self.observe(2.25, PlayState.PLAYING, stamp=.4).applied)
        status = self.observe(2.3, PlayState.PLAYING, stamp=.5)
        self.assertTrue(status.running)
        self.assertFalse(status.applied)
        self.assertIsNone(status.error)
        self.assertEqual(self.session.recovery_state, "waiting-for-not-playing")
        hidden_writes = list(self.writes)
        self.assertFalse(self.observe(3.0, PlayState.PLAYING, stamp=.6).applied)
        self.assertFalse(self.observe(3.1, PlayState.PLAYING).applied)
        self.assertFalse(self.observe(3.4, PlayState.PLAYING).applied)
        self.assertFalse(self.observe(3.5, PlayState.NOT_PLAYING).applied)
        self.assertFalse(self.observe(3.7, PlayState.NOT_PLAYING).applied)
        self.assertFalse(self.observe(3.75, PlayState.PLAYING).applied)
        self.assertEqual(self.session.recovery_state, "waiting-for-not-playing")
        self.assertEqual(self.writes, hidden_writes)
        self.assertFalse(self.observe(3.8, PlayState.NOT_PLAYING).applied)
        self.assertFalse(self.observe(4.15, PlayState.NOT_PLAYING).applied)
        self.assertIsNone(self.session.recovery_state)
        self.assertFalse(self.observe(4.2, PlayState.PLAYING).applied)
        self.assertTrue(self.observe(4.45, PlayState.PLAYING).applied)
        self.assertEqual(self.writes, hidden_writes + [(2, True), (3, True)])

    def test_fresh_frame_arriving_after_grace_cannot_skip_required_exit(self):
        self.play()
        self.assertTrue(self.observe(1.7, PlayState.PLAYING, stamp=.3).applied)
        self.assertFalse(self.observe(2.4, PlayState.PLAYING).applied)
        self.assertEqual(self.session.recovery_state, "waiting-for-not-playing")
        self.assertFalse(self.observe(2.7, PlayState.PLAYING).applied)

    def test_stale_or_unknown_frames_cannot_rearm_after_a_long_stall(self):
        self.play()
        self.assertFalse(self.observe(2.3, PlayState.PLAYING, stamp=.4).applied)
        self.assertFalse(self.observe(2.4, PlayState.NOT_PLAYING).applied)
        self.assertFalse(self.observe(2.7, PlayState.NOT_PLAYING, stamp=2.4).applied)
        self.assertEqual(self.session.recovery_state, "waiting-for-not-playing")
        self.assertFalse(self.observe(3.0, PlayState.NOT_PLAYING, stamp=2.4).applied)
        self.assertFalse(self.observe(3.1, PlayState.UNKNOWN).applied)
        self.assertFalse(self.observe(3.2, PlayState.PLAYING).applied)
        self.assertEqual(self.session.recovery_state, "waiting-for-not-playing")
        self.observe(3.3, PlayState.NOT_PLAYING)
        self.observe(3.65, PlayState.NOT_PLAYING)
        self.assertIsNone(self.session.recovery_state)

    def test_late_unknown_malformed_and_regressed_samples_still_fail_closed(self):
        for state, stamp, detector_error in (
                (PlayState.UNKNOWN, .4, "capture-unavailable"),
                (PlayState.UNKNOWN, .4, "invalid-screenshot"),
                (PlayState.PLAYING, .4, "invalid-screenshot"),
                (PlayState.PLAYING, .1, None)):
            with self.subTest(state=state, detector_error=detector_error):
                self.session.stop()
                self.now = 0
                self.session.start()
                self.detector.last_error = None
                self.play()
                self.detector.last_error = detector_error
                status = self.observe(1.8, state, stamp)
                self.assertEqual(status.error, "detector-observation-invalid")
                self.assertFalse(status.applied)
                self.assertIsNone(self.session.recovery_state)

    def test_exception_during_grace_is_not_recoverable_and_stop_never_restarts(self):
        self.play()
        self.observe(1.7, PlayState.PLAYING, stamp=.4)
        self.detector.fail_read = True
        status = self.session.tick()
        self.assertEqual(status.error, "detector-observation-invalid")
        self.assertFalse(status.applied)
        self.assertIsNone(self.session.recovery_state)
        self.session.stop()
        writes = list(self.writes)
        self.detector.fail_read = False
        self.assertFalse(self.observe(2.0, PlayState.PLAYING).running)
        self.assertEqual(self.writes, writes)

    def test_sampling_gap_starts_a_new_confirmation_window(self):
        self.observe(0, PlayState.PLAYING)
        self.assertFalse(self.observe(1, PlayState.PLAYING).applied)
        self.assertTrue(self.observe(1.25, PlayState.PLAYING).applied)

    def test_short_sampling_gap_keeps_confirmed_visibility_and_restarts_exit_confirmation(self):
        self.play()
        original_writes = list(self.writes)
        self.assertTrue(self.observe(1.65, PlayState.PLAYING).applied)
        self.assertEqual(self.session.observation_reason, "sampling-gap")
        self.assertEqual(self.writes, original_writes)
        self.assertTrue(self.observe(1.9, PlayState.NOT_PLAYING).applied)
        self.assertTrue(self.observe(2.1, PlayState.NOT_PLAYING).applied)
        self.assertFalse(self.observe(2.25, PlayState.NOT_PLAYING).applied)

    def test_long_sampling_gap_requires_exit_even_when_first_returned_frame_is_fresh(self):
        self.play()
        self.assertFalse(self.observe(2.4, PlayState.PLAYING).applied)
        self.assertEqual(self.session.observation_reason, "sampling-gap")
        self.assertEqual(self.session.recovery_state, "waiting-for-not-playing")
        self.assertFalse(self.observe(2.7, PlayState.PLAYING).applied)
        self.observe(2.8, PlayState.NOT_PLAYING)
        self.observe(3.15, PlayState.NOT_PLAYING)
        self.assertIsNone(self.session.recovery_state)
        self.assertFalse(self.observe(3.2, PlayState.PLAYING).applied)
        self.assertTrue(self.observe(3.45, PlayState.PLAYING).applied)

    def test_discarded_stale_frames_still_enforce_timestamp_order(self):
        self.play()
        self.assertTrue(self.observe(1.7, PlayState.PLAYING, stamp=.4).applied)
        status = self.observe(1.8, PlayState.PLAYING, stamp=.3)
        self.assertEqual(status.error, "detector-observation-invalid")
        self.assertEqual(self.session.observation_reason, "regressed-timestamp")
        self.assertFalse(status.applied)

    def test_repeated_sparse_fresh_samples_cannot_extend_the_recovery_budget(self):
        for state in (PlayState.PLAYING, PlayState.NOT_PLAYING):
            with self.subTest(state=state):
                self.session.stop()
                self.now = 0
                self.session.start()
                self.play()
                original_writes = list(self.writes)
                for at in (.9, 1.5, 2.1):
                    self.assertTrue(self.observe(at, state).applied)
                    self.assertEqual(self.session.recovery_state, "waiting-for-frame")
                self.assertFalse(self.observe(2.7, state).applied)
                self.assertEqual(self.session.recovery_state, "waiting-for-not-playing")
                self.assertFalse(self.observe(3.3, state).applied)
                self.assertEqual(self.writes, original_writes + [(2, False), (3, False)])

    def test_fresh_samples_without_completed_confirmation_do_not_renew_stall_grace(self):
        self.play()
        self.assertTrue(self.observe(1.0, PlayState.PLAYING, stamp=.3).applied)
        self.assertTrue(self.observe(1.2, PlayState.PLAYING).applied)
        self.assertEqual(self.session.recovery_state, "waiting-for-frame")
        self.assertTrue(self.observe(1.9, PlayState.PLAYING, stamp=1.3).applied)
        self.assertTrue(self.observe(2.0, PlayState.PLAYING).applied)
        self.assertFalse(self.observe(2.3, PlayState.PLAYING).applied)
        self.assertEqual(self.session.recovery_state, "waiting-for-not-playing")

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

    def test_observation_diagnostics_distinguish_invalid_samples_without_policy_changes(self):
        samples = ((PlayState.PLAYING, 2, "future-timestamp", -1),
                   (PlayState.PLAYING, -1, "timestamp-before-start", 2),
                   (PlayState.PLAYING, float("nan"), "nonfinite-timestamp", None),
                   (PlayState.PLAYING, "private-invalid-stamp", "invalid-timestamp", None),
                   ("private-invalid-state", 1, "invalid-state", None),
                   (PlayState.PLAYING, .25, "stale-observation", .75))
        for state, stamp, reason, age in samples:
            with self.subTest(reason=reason):
                status = self.observe(1, state, stamp)
                self.assertEqual(status.error, None if reason == "stale-observation"
                                 else "detector-observation-invalid")
                self.assertFalse(status.applied)
                self.assertEqual(self.session.observation_reason, reason)
                self.assertEqual(self.session.observation_age, age)
        self.observe(1, PlayState.PLAYING)
        self.observe(1.1, PlayState.PLAYING, .9)
        self.assertEqual(self.session.observation_reason, "regressed-timestamp")

    def test_last_observation_diagnostic_survives_stop_and_resets_on_start(self):
        self.observe(1, PlayState.PLAYING, .25)
        self.session.stop()
        self.assertEqual(self.session.observation_reason, "stale-observation")
        self.assertEqual(self.session.observation_age, .75)
        self.session.start()
        self.assertIsNone(self.session.observation_reason)
        self.assertIsNone(self.session.observation_age)
        self.detector.fail_read = True
        self.session.tick()
        self.assertEqual(self.session.observation_reason, "observe-exception")
        self.assertEqual(self.session.observation_exception_type, "RuntimeError")
        self.assertIsNone(self.session.observation_exception_code)
        self.detector.fail_read = False
        self.observe(1.25, PlayState.PLAYING)
        self.assertIsNone(self.session.observation_reason)
        self.assertIsNone(self.session.observation_exception_type)
        self.assertEqual(self.session.observation_age, 0)

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
        self.assertEqual(transitions, [(0, False), (0.35, True), (1, False), (1.4, True)])
        self.assertFalse(rows[-1]["running"])
        self.assertEqual(rows[-1]["requests"], [])
        for row in rows:
            self.assertEqual({request["requestData"]["sceneItemId"] for request in row["requests"]},
                             {2, 3} if row["requests"] else set())


if __name__ == "__main__":
    unittest.main()
