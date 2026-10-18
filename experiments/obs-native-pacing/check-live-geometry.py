"""Compare actual-event C geometry with the unchanged JavaScript renderer.

Loads the separate live-geometry-test DLL only. Never starts OBS, accesses a
physical controller, writes settings, or connects to a service.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
from pathlib import Path
import subprocess

from live_bridge import pack_snapshot

FIELDS = ("x", "width", "head", "tail", "noteHeight", "body", "active", "start", "end", "direction")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", type=Path)
    parser.add_argument("--node", default="node")
    args = parser.parse_args()
    library = ctypes.CDLL(str(args.library.resolve()))
    library.lift_test_note.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                      ctypes.c_double, ctypes.POINTER(ctypes.c_double)]
    library.lift_test_note.restype = ctypes.c_int
    library.lift_test_packet_valid.argtypes = [ctypes.c_void_p]
    library.lift_test_packet_valid.restype = ctypes.c_int
    produced = subprocess.run(
        [args.node, str(Path(__file__).with_name("live-geometry-vectors.mjs"))],
        check=True, capture_output=True, text=True, timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    fixture = json.loads(produced.stdout)
    checked = present_count = 0
    coverage = {"clockwise": 0, "counterclockwise": 0, "keyboard": 0,
                "active": 0, "released": 0, "secondPlayer": 0, "displayChanges": 0}
    maximum_error = 0.0
    for sequence, case in enumerate(fixture["vectors"], 1):
        snapshot = {"type": "snapshot", "epochMs": case["now"],
                    "settings": case["settings"], "events": case["events"]}
        encoded = pack_snapshot(snapshot, session=1, sequence=sequence,
                                qpc_ns=10_000_000_000, epoch_ms=case["now"])
        buffer = ctypes.create_string_buffer(encoded, len(encoded))
        if not library.lift_test_packet_valid(buffer):
            raise AssertionError(f"C rejected a normalized JS snapshot: {case}")
        for expected in case["reference"]:
            checked += 1
            output = (ctypes.c_double * len(FIELDS))()
            present = bool(library.lift_test_note(buffer, expected["index"], case["now"], output))
            if present != expected["present"]:
                raise AssertionError(f"Event presence differs: {case}; reference={expected}")
            if not present:
                continue
            present_count += 1
            event = case["events"][expected["index"]]
            if event["lane"]:
                coverage["keyboard"] += 1
            else:
                coverage["clockwise" if event["direction"] > 0 else "counterclockwise"] += 1
            coverage["active" if output[6] else "released"] += 1
            coverage["secondPlayer"] += case["settings"]["side"] == "2P"
            coverage["displayChanges"] += case["variant"] == "ui-display-change"
            for field, actual, reference in zip(FIELDS, output, expected["values"]):
                maximum_error = max(maximum_error, abs(actual - reference))
                if not math.isclose(actual, reference, rel_tol=0, abs_tol=1e-7):
                    raise AssertionError(
                        f"{field}: C={actual}, JS={reference}; variant={case['variant']}, "
                        f"scenario={case['scenario']}, elapsed={case['elapsed']}, event={event}"
                    )
    if checked < 100 or not all(coverage.values()):
        raise AssertionError(f"Insufficient live geometry coverage: {checked}, {coverage}")
    print(json.dumps({"snapshot_cases": len(fixture["vectors"]),
                      "event_vectors_passed": checked, "present_events": present_count,
                      "absolute_tolerance": 1e-7, "maximum_absolute_error": maximum_error,
                      "coverage": coverage}, sort_keys=True))


if __name__ == "__main__":
    main()
