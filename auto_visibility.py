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
from typing import Callable, Protocol


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
    def __init__(self, targets: tuple[SceneItem, ...], request: Callable[[str, dict], dict]):
        self.targets = tuple(targets)
        identities = {(target.scene_uuid, target.item_id) for target in self.targets}
        if not self.targets or len(identities) != len(self.targets):
            raise ValueError("Select at least one target, with no duplicate scene items")
        self.request = request

    def set_visible(self, visible: bool) -> None:
        scenes = {}
        for target in self.targets:
            if target.scene_uuid not in scenes:
                scenes[target.scene_uuid] = self.request(
                    "GetSceneItemList", {"sceneUuid": target.scene_uuid})["sceneItems"]
            matches = [item for item in scenes[target.scene_uuid]
                       if item.get("sceneItemId") == target.item_id]
            if len(matches) != 1 or matches[0].get("sourceUuid") != target.source_uuid:
                raise ValueError("Selected scene item changed; select targets again")
        for target in self.targets:
            self.request("SetSceneItemEnabled", {
                "sceneUuid": target.scene_uuid, "sceneItemId": target.item_id,
                "sceneItemEnabled": visible,
            })


@dataclass(frozen=True)
class VisibilityStatus:
    running: bool
    state: PlayState
    applied: bool | None
    error: str | None


class VisibilitySession:
    """Only confirmed gameplay enables targets; unknown/stale input hides them.

    stop() yields control without changing visibility. applied records the last
    fully acknowledged batch, not live OBS state. On a write failure it becomes
    unknown; automatic control stops and needs an explicit start(). No claim is
    made that sources can be hidden while OBS is disconnected.
    """
    def __init__(self, detector: Detector, output: ObsSceneItems, *,
                 clock: Callable[[], float] = time.monotonic,
                 enter_delay: float = 0.2, exit_delay: float = 0.3,
                 max_age: float = 0.5):
        if any(not math.isfinite(value) or value < 0
               for value in (enter_delay, exit_delay, max_age)) or max_age == 0:
            raise ValueError("Delays must be finite/nonnegative and max_age positive")
        self.detector, self.output, self.clock = detector, output, clock
        self.enter_delay, self.exit_delay, self.max_age = enter_delay, exit_delay, max_age
        self.running = False
        self.state = PlayState.UNKNOWN
        self.applied: bool | None = None
        self.error: str | None = None
        self._reset()

    def _reset(self) -> None:
        self._unknown()
        self._last_observed: float | None = None

    def _unknown(self) -> None:
        self.state = PlayState.UNKNOWN
        self._candidate = PlayState.UNKNOWN
        self._candidate_since = 0.0

    def status(self) -> VisibilityStatus:
        return VisibilityStatus(self.running, self.state, self.applied, self.error)

    def start(self) -> VisibilityStatus:
        if self.running:
            return self.status()
        self._reset()
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
        try:
            observation = self.detector.observe()
            now = self.clock()  # Account for time spent acquiring the observation.
            stamp = observation.observed_at
            valid = (isinstance(observation.state, PlayState) and math.isfinite(stamp)
                     and self._started_at <= stamp <= now
                     and now - stamp <= self.max_age
                     and (self._last_observed is None or stamp >= self._last_observed))
        except Exception:
            valid = False
        self.error = None if valid else "detector-observation-invalid"
        if not valid or observation.state is PlayState.UNKNOWN:
            self._unknown()
            if valid:
                self._last_observed = stamp
        elif stamp != self._last_observed:
            # A long sampling gap is not evidence of continuous gameplay.
            if self._last_observed is not None and stamp - self._last_observed > self.max_age:
                self._unknown()
            if observation.state is not self._candidate:
                self._candidate, self._candidate_since = observation.state, stamp
            self._last_observed = stamp
            delay = self.enter_delay if observation.state is PlayState.PLAYING else self.exit_delay
            if stamp - self._candidate_since >= delay:
                self.state = observation.state
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
