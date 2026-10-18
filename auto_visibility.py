"""Experimental, game-neutral visibility policy; not enabled in the app yet.

One owner calls start/tick/stop serially, outside the controller-input thread.
Detector lifecycle/observe calls must return within bounded time: a blocked call
also blocks stale checks and stop. Observations use the same monotonic clock
domain. An OBS request
adapter must return acknowledged responseData or raise on failure, use bounded
timeouts, and never replay queued writes after a disconnect. Stop this session
before changing connection/scene collection; reselect targets before restarting.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import time
import uuid
from typing import Callable, Protocol


CAPTURE_STALL_GRACE = 2.0
TIME_EPSILON = 1e-9  # Arithmetic rounding only; never relax timestamp validity.


class PlayState(Enum):
    UNKNOWN = "unknown"
    PLAYING = "playing"
    NOT_PLAYING = "not_playing"


@dataclass(frozen=True)
class Observation:
    state: PlayState
    observed_at: float


class Detector(Protocol):
    def start(self) -> None: ...
    def observe(self) -> Observation: ...
    def stop(self) -> None: ...


@dataclass(frozen=True)
class SceneItem:
    scene_uuid: str
    item_id: int
    source_uuid: str

    def __post_init__(self):
        if (not self.scene_uuid or not self.source_uuid
                or type(self.item_id) is not int or self.item_id < 0):
            raise ValueError("A target needs scene/source UUIDs and a nonnegative scene item ID")


class ObsSceneItems:
    """Control explicitly selected top-level scene items, never source names.

    All identities are checked before the first write. OBS requests are not an
    atomic transaction: a scene edit or disconnect can still interrupt a batch.
    A raised error therefore means the actual visibility may be partly changed.
    Groups and nested-scene traversal are deliberately outside this first scope.
    """
    def __init__(self, targets: tuple[SceneItem, ...], request: Callable[[str, dict], dict],
                 *, diagnostic: Callable[[dict], None] | None = None):
        self.targets = tuple(targets)
        identities = {(target.scene_uuid, target.item_id) for target in self.targets}
        if not self.targets or len(identities) != len(self.targets):
            raise ValueError("Select at least one target, with no duplicate scene items")
        self.request = request
        self.diagnostic = diagnostic
        self.last_request_id: str | None = None
        self._acknowledged: dict[SceneItem, bool] = {}

    def _report(self, target, visible, actual, outcome):
        if self.diagnostic is None:
            return
        expected = self._acknowledged.get(target)
        try:
            self.diagnostic({"requestId": self.last_request_id,
                             "sceneUuid": target.scene_uuid, "sourceUuid": target.source_uuid,
                             "sceneItemId": target.item_id, "desired": visible,
                             "beforeActual": actual, "previousAcknowledged": expected,
                             "origin": ("external-or-unattributed" if actual is not None
                                        and expected is not None and actual != expected
                                        else "lift-command"), "outcome": outcome})
        except Exception:
            pass  # Optional diagnostics must never change visibility behavior.

    def set_visible(self, visible: bool) -> None:
        scenes = {}
        actual = {}
        self.last_request_id = str(uuid.uuid4())
        for target in self.targets:
            if target.scene_uuid not in scenes:
                try:
                    scenes[target.scene_uuid] = self.request(
                        "GetSceneItemList", {"sceneUuid": target.scene_uuid})["sceneItems"]
                except Exception:
                    self._report(target, visible, None, "validation-failed")
                    raise
            matches = [item for item in scenes[target.scene_uuid]
                       if item.get("sceneItemId") == target.item_id]
            if len(matches) != 1 or matches[0].get("sourceUuid") != target.source_uuid:
                self._report(target, visible, None, "identity-rejected")
                raise ValueError("Selected scene item changed; select targets again")
            value = matches[0].get("sceneItemEnabled")
            actual[target] = value if type(value) is bool else None
        for target in self.targets:
            self._report(target, visible, actual[target], "requested")
            try:
                self.request("SetSceneItemEnabled", {
                    "sceneUuid": target.scene_uuid, "sceneItemId": target.item_id,
                    "sceneItemEnabled": visible,
                })
            except Exception:
                self._report(target, visible, actual[target], "failed")
                raise
            self._report(target, visible, actual[target], "acknowledged")
            self._acknowledged[target] = visible


@dataclass(frozen=True)
class VisibilityStatus:
    running: bool
    state: PlayState
    applied: bool | None
    error: str | None


class VisibilitySession:
    """Only fresh, confirmed gameplay enables targets.

    A classified but late frame is discarded. A fresh, known unavailable capture
    shares that recovery budget. Existing visibility can survive a short capture
    stall; a longer stall hides it and requires a fresh exit
    before another entry. This prevents a capture stall from looking like a
    new song to optional consumers of the overlay's visibility.

    stop() yields control without changing visibility. applied records the last
    fully acknowledged batch, not live OBS state. On a write failure it becomes
    unknown; automatic control stops and needs an explicit start(). No claim is
    made that sources can be hidden while OBS is disconnected.
    """
    def __init__(self, detector: Detector, output: ObsSceneItems, *,
                 clock: Callable[[], float] = time.monotonic,
                 enter_delay: float = 0.2, exit_delay: float = 0.3,
                 max_age: float = 0.5, stale_grace: float = CAPTURE_STALL_GRACE):
        if any(not math.isfinite(value) or value < 0
               for value in (enter_delay, exit_delay, max_age, stale_grace)) or max_age == 0:
            raise ValueError("Delays must be finite/nonnegative and max_age positive")
        self.detector, self.output, self.clock = detector, output, clock
        self.enter_delay, self.exit_delay, self.max_age = enter_delay, exit_delay, max_age
        self.stale_grace = stale_grace
        self.running = False
        self.state = PlayState.UNKNOWN
        self.applied: bool | None = None
        self.error: str | None = None
        self._reset_observation_diagnostic()
        self._reset()

    def _reset_observation_diagnostic(self) -> None:
        # Only a newly acquired, valid classified sample can refresh optional
        # playback proofs. Cached frames and the last applied value cannot.
        self.observation_fresh = False
        self.observation_state = PlayState.UNKNOWN
        self.observation_at: float | None = None
        self.observation_age: float | None = None
        self.observation_reason: str | None = None
        self.observation_exception_type: str | None = None
        self.observation_exception_code: int | None = None

    def _reset(self) -> None:
        self._unknown()
        self._last_observed: float | None = None
        self._last_seen_stamp: float | None = None
        self._last_fresh_at: float | None = None
        self._recovery_anchor: float | None = None
        self._resume_candidate_reset = False
        self._rearm_required = False
        # Transient diagnostics, not errors: automation keeps polling for a
        # fresh frame, without restarting its detector or OBS connection.
        self.recovery_state: str | None = None

    def _unknown(self) -> None:
        self.state = PlayState.UNKNOWN
        self._reset_candidate()

    def _reset_candidate(self) -> None:
        self._candidate = PlayState.UNKNOWN
        self._candidate_since = 0.0

    def _grace_expired(self, now: float) -> bool:
        anchor = self._recovery_anchor
        if anchor is None:
            anchor = self._last_fresh_at if self._last_fresh_at is not None else self._started_at
        return now - anchor > self.stale_grace + TIME_EPSILON

    def _begin_recovery(self) -> None:
        if self._recovery_anchor is None:
            self._recovery_anchor = (self._last_fresh_at if self._last_fresh_at is not None
                                     else self._started_at)

    def _finish_recovery(self) -> None:
        self.recovery_state = None
        self._recovery_anchor = None
        self._resume_candidate_reset = False

    def _wait_for_frame(self, now: float) -> None:
        # Do not advance either freshness timestamp with the discarded frame.
        # A synchronous capture may block beyond this budget; hide on the first
        # tick that can observe its expiry, not on an independent writer thread.
        self._begin_recovery()
        self._reset_candidate()
        self._resume_candidate_reset = True
        if self._rearm_required or self._grace_expired(now):
            self._rearm_required = True
            self._unknown()
            self.recovery_state = "waiting-for-not-playing"
        else:
            self.recovery_state = "waiting-for-frame"

    def _observe_fresh(self, state: PlayState, stamp: float, now: float) -> None:
        recovering = self.recovery_state == "waiting-for-frame"
        gap = self._last_observed is not None and stamp - self._last_observed > self.max_age
        interrupted = recovering or gap
        if gap:
            self.observation_reason = "sampling-gap"
            self._begin_recovery()
        if interrupted and self._grace_expired(now):
            self._rearm_required = True
            self._unknown()
        changed = stamp != self._last_observed
        if self._rearm_required:
            self.recovery_state = "waiting-for-not-playing"
            if state is PlayState.NOT_PLAYING:
                if gap or self._candidate is not state:
                    self._candidate, self._candidate_since = state, stamp
                if changed and stamp - self._candidate_since + TIME_EPSILON >= self.exit_delay:
                    self._rearm_required = False
                    self._finish_recovery()
                    self.state = PlayState.NOT_PLAYING
            else:
                self._unknown()
        else:
            if gap or self._resume_candidate_reset:
                # Keep the last confirmed visibility, but never count the
                # capture stall toward entry or exit confirmation.
                self._reset_candidate()
                self._resume_candidate_reset = False
            if interrupted:
                self.recovery_state = "waiting-for-frame"
            if changed:
                if state is not self._candidate:
                    self._candidate, self._candidate_since = state, stamp
                delay = self.enter_delay if state is PlayState.PLAYING else self.exit_delay
                if stamp - self._candidate_since + TIME_EPSILON >= delay:
                    self.state = state
                    # Only a continuous fresh confirmation ends recovery. Sparse
                    # fresh frames must not extend the original grace forever.
                    self._finish_recovery()
        self._last_observed = stamp
        self._last_fresh_at = stamp

    def status(self) -> VisibilityStatus:
        return VisibilityStatus(self.running, self.state, self.applied, self.error)

    def start(self) -> VisibilityStatus:
        if self.running:
            return self.status()
        self._reset()
        self._reset_observation_diagnostic()
        self.applied, self.error = None, None
        self._started_at = self.clock()
        try:
            self.detector.start()
            self.running = True
        except Exception:
            self.error = "detector-start-failed"
            self._stop_detector()
        return self.status()

    def _stop_detector(self) -> None:
        self.running = False
        try:
            self.detector.stop()
        except Exception:
            self.error = self.error or "detector-stop-failed"

    def stop(self) -> VisibilityStatus:
        if self.running:
            self._stop_detector()
        self._reset()
        return self.status()

    def tick(self) -> VisibilityStatus:
        if not self.running:
            return self.status()
        self._reset_observation_diagnostic()
        phase = "observe-exception"
        try:
            observation = self.detector.observe()
            phase = "invalid-observation"
            now = self.clock()  # Account for time spent acquiring the observation.
            stamp = observation.observed_at
            phase = "invalid-timestamp"
            valid = (isinstance(observation.state, PlayState) and math.isfinite(stamp)
                     and self._started_at <= stamp <= now
                     and now - stamp <= self.max_age
                     and (self._last_seen_stamp is None or stamp >= self._last_seen_stamp))
            if not isinstance(observation.state, PlayState):
                self.observation_reason = "invalid-state"
            else:
                phase = "invalid-timestamp"
                if not math.isfinite(stamp):
                    self.observation_reason = "nonfinite-timestamp"
                else:
                    age = now - stamp
                    self.observation_age = age if math.isfinite(age) else None
                    if stamp < self._started_at:
                        self.observation_reason = "timestamp-before-start"
                    elif stamp > now:
                        self.observation_reason = "future-timestamp"
                    elif not self._started_at <= stamp <= now:
                        self.observation_reason = "invalid-timestamp"
                    elif self._last_seen_stamp is not None and stamp < self._last_seen_stamp:
                        self.observation_reason = "regressed-timestamp"
                    elif age > self.max_age:
                        self.observation_reason = "stale-observation"
        except Exception as error:
            valid = False
            self.observation_reason = phase
            # Keep only bounded class/code metadata, never exception messages,
            # screenshot contents, request bodies or connection credentials.
            name = type(error).__name__
            self.observation_exception_type = (name if len(name) <= 80 and name.isascii()
                                               and name.isidentifier() else "Exception")
            code = vars(error).get("code")
            if type(code) is int and 0 <= code <= 2147483647:
                self.observation_exception_code = code
        recoverable_stale = False
        if self.observation_reason == "stale-observation":
            # Missing/malformed images and transport errors are not a slow but
            # otherwise valid classified frame, even when their response is late.
            try:
                recoverable_stale = (observation.state in (PlayState.PLAYING, PlayState.NOT_PLAYING)
                                     and math.isfinite(now) and self.observation_age is not None
                                     and getattr(self.detector, "last_error", None) is None)
            except Exception:
                pass
        self.error = None if valid or recoverable_stale else "detector-observation-invalid"
        if valid:
            self.observation_at = stamp
            self.observation_state = observation.state
            self.observation_fresh = (observation.state is not PlayState.UNKNOWN
                                      and stamp != self._last_observed)
        if valid or recoverable_stale:
            # Rejected late frames still establish timestamp ordering, but do
            # not advance the freshness budget or the confirmation window.
            self._last_seen_stamp = stamp
        recoverable_missing = (valid and observation.state is PlayState.UNKNOWN
                               and getattr(self.detector, "last_error", None) == "capture-unavailable")
        if recoverable_stale or recoverable_missing:
            self._wait_for_frame(now)
        elif valid and observation.state is PlayState.UNKNOWN and self._recovery_anchor is not None:
            # An unclassified frame still hides immediately, but cannot erase
            # the existing outage budget or bypass its required fresh exit.
            self._unknown()
            self._wait_for_frame(now)
        elif not valid or observation.state is PlayState.UNKNOWN:
            self._unknown()
            if valid:
                self._last_observed = stamp
            if self._rearm_required:
                self.recovery_state = "waiting-for-not-playing"
            else:
                self._finish_recovery()
        else:
            self._observe_fresh(observation.state, stamp, now)
        desired = self.state is PlayState.PLAYING
        if desired != self.applied:
            try:
                self.output.set_visible(desired)
                self.applied = desired
            except Exception:
                # Do not report success after partial writes or retry old ON work.
                self.applied, self.error = None, "obs-apply-failed"
                self._stop_detector()
        return self.status()
