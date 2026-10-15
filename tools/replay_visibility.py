"""Replay synthetic observations without opening OBS, a camera, or a socket.

An optional JSON file contains rows {"at": seconds, "state": "playing"}, with
optional observed_at (defaults to at) or action (start/stop, no state required).
This checks control policy, not screenshot recognition or real OBS behavior.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from auto_visibility import Observation, ObsSceneItems, PlayState, SceneItem, VisibilitySession


EXAMPLE = [
    {"at": 0, "state": "unknown"},
    {"at": 0.1, "state": "playing"},
    {"at": 0.35, "state": "playing"},
    {"at": 0.4, "state": "not_playing"},
    {"at": 0.5, "state": "playing"},
    {"at": 0.6, "state": "not_playing"},
    {"at": 1.0, "state": "not_playing"},
    {"at": 1.1, "state": "playing"},
    {"at": 1.4, "state": "playing"},
    {"at": 2.0, "state": "playing", "observed_at": 1.4},
    {"at": 2.1, "action": "stop"},
    {"at": 2.4, "state": "playing"},
]


def replay(rows: list[dict]) -> list[dict]:
    class RecordedDetector:
        sample = Observation(PlayState.UNKNOWN, 0)
        def start(self): pass
        def stop(self): pass
        def observe(self): return self.sample

    # Two placements share the game source: only the cropped one is selected.
    # These are synthetic identifiers, not anyone's OBS configuration.
    items = [{"sceneItemId": 1, "sourceUuid": "game"},
             {"sceneItemId": 2, "sourceUuid": "game"},
             {"sceneItemId": 3, "sourceUuid": "overlay"}]
    writes = []

    def request(kind, data):
        if kind == "GetSceneItemList":
            return {"sceneItems": items}
        writes.append({"requestType": kind, "requestData": data})
        return {}

    now = 0.0
    detector = RecordedDetector()
    output = ObsSceneItems((SceneItem("scene", 2, "game"),
                            SceneItem("scene", 3, "overlay")), request)
    session = VisibilitySession(detector, output, clock=lambda: now)
    session.start()
    result = []
    try:
        for row in rows:
            previous = now
            now = float(row["at"])
            if not (previous <= now < float("inf")):
                raise ValueError("Replay times must be finite, nonnegative and ordered")
            writes.clear()
            action = row.get("action", "observe")
            if action == "start":
                status = session.start()
            elif action == "stop":
                status = session.stop()
            elif action == "observe":
                detector.sample = Observation(PlayState(row["state"]), float(row.get("observed_at", now)))
                status = session.tick()
            else:
                raise ValueError("Unknown replay action")
            result.append({"at": now, "running": status.running, "state": status.state.value,
                           "applied": status.applied, "error": status.error, "requests": list(writes)})
    finally:
        session.stop()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("timeline", nargs="?", type=Path, help="Optional JSON observation array")
    args = parser.parse_args()
    rows = json.loads(args.timeline.read_text("utf-8")) if args.timeline else EXAMPLE
    for row in replay(rows):
        print(json.dumps(row, separators=(",", ":")))


if __name__ == "__main__":
    main()
