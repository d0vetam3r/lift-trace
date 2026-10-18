"""Compare the experimental C geometry to the real JavaScript renderer.

The supplied library must be built from geometry-test.c, not the OBS plugin.
This check never starts OBS or accesses controller/settings data.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
from pathlib import Path
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", type=Path)
    parser.add_argument("--node", default="node")
    args = parser.parse_args()

    native = ctypes.CDLL(str(args.library.resolve()))
    native.pacing_geometry_tests.argtypes = []
    native.pacing_geometry_tests.restype = ctypes.c_int
    failure_line = native.pacing_geometry_tests()
    if failure_line:
        raise AssertionError(f"C regression failed at geometry-test.c:{failure_line}")

    native.pacing_geometry_sample.argtypes = [
        ctypes.c_double, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_double)
    ]
    native.pacing_geometry_sample.restype = ctypes.c_int
    produced = subprocess.run(
        [args.node, str(Path(__file__).with_name("geometry-vectors.mjs"))],
        check=True, capture_output=True, text=True, timeout=15,
    )
    vectors = json.loads(produced.stdout)["vectors"]
    for vector in vectors:
        output = (ctypes.c_double * 9)()
        present = bool(native.pacing_geometry_sample(
            vector["elapsed"], vector["variant"], vector["index"], output
        ))
        if present != vector["present"]:
            raise AssertionError(f"Event presence differs: {vector}")
        if present:
            for field, (actual, expected) in enumerate(zip(output, vector["values"])):
                if not math.isclose(actual, expected, abs_tol=1e-6):
                    raise AssertionError(
                        f"Geometry field {field}: C={actual}, JS={expected}; {vector}"
                    )
    print(json.dumps({"c_regression": "passed", "javascript_vectors_passed": len(vectors)}))


if __name__ == "__main__":
    main()
