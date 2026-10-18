"""Compatibility entry point; implementation lives in native/obs."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import runpy
import sys

_target = Path(__file__).resolve().parents[2] / "native" / "obs" / "live_bridge.py"
sys.path.insert(0, str(_target.parent))
if __name__ == "__main__":
    runpy.run_path(str(_target), run_name="__main__")
else:
    _spec = spec_from_file_location(__name__, _target)
    _module = module_from_spec(_spec)
    sys.modules[__name__] = _module
    _spec.loader.exec_module(_module)
