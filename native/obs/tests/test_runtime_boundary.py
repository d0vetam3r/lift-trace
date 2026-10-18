"""Exercise canonical and retained entry points from an extracted source archive."""
from __future__ import annotations

import json
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.build_release import RUNTIME_FILES, build_release


class RendererModeTests(unittest.TestCase):
    def test_runtime_and_explicit_benchmark_draw_modes(self):
        paths = [os.environ.get(name) for name in
                 ("LIFT_NATIVE_TEST_RUNTIME_MODE_DLL", "LIFT_NATIVE_TEST_BENCHMARK_MODE_DLL")]
        if not all(paths):
            self.skipTest("Set both native renderer mode test libraries to run the C mock-drawing check.")
        for name, path in zip(("runtime", "benchmark"), paths):
            with self.subTest(build=name):
                library = ctypes.CDLL(path)
                library.lift_renderer_mode_tests.restype = ctypes.c_int
                self.assertEqual(library.lift_renderer_mode_tests(), 0,
                                 "Nonzero result identifies the failed C fixture line.")


class RuntimeBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="native-paths-")
        cls.directory = Path(cls.temporary.name)
        archive = build_release(ROOT, cls.directory / "archive")
        cls.extracted = cls.directory / "source"
        with zipfile.ZipFile(archive) as source:
            source.extractall(cls.extracted)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_python(self, *arguments):
        result = subprocess.run(
            [sys.executable, *arguments], cwd=self.extracted,
            text=True, capture_output=True, encoding="utf-8", timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_legacy_imports_resolve_only_the_canonical_read_only_modules(self):
        output = self.run_python("-c", """
import json, pathlib, sys
sys.path.insert(0, 'experiments/obs-native-pacing')
import live_bridge, live_observer
print(json.dumps({
 'files': [pathlib.Path(module.__file__).relative_to(pathlib.Path.cwd()).as_posix()
           for module in (live_bridge, live_observer)],
 'samePipeline': live_observer.NativePipeline is live_bridge.NativePipeline,
 'inputServerImported': 'server' in sys.modules,
 'coreImported': any('live_core' in name for name in sys.modules)}))
""")
        result = json.loads(output)
        self.assertEqual(result["files"], ["native/obs/live_bridge.py", "native/obs/live_observer.py"])
        self.assertTrue(result["samePipeline"])
        self.assertFalse(result["inputServerImported"])
        self.assertFalse(result["coreImported"])

    def test_canonical_and_legacy_observer_and_lab_help_are_runnable(self):
        for name in ("native/obs/live_observer.py",
                     "experiments/obs-native-pacing/live_observer.py",
                     "experiments/obs-native-pacing/live_launcher.py"):
            with self.subTest(entry=name):
                help_text = self.run_python(name, "--help")
                self.assertIn("--channel", help_text)
                self.assertIn("--node", help_text)

    def test_legacy_javascript_exports_the_same_observer_and_preserves_raw_input(self):
        node = os.environ.get("LIFT_NATIVE_TEST_NODE") or shutil.which("node")
        if not node:
            self.skipTest("Node is required for the optional native sidecar.")
        result = subprocess.run([node, "--input-type=module", "-e", """
import assert from 'node:assert/strict';
import { LiveInputObserver as legacy } from './experiments/obs-native-pacing/live-input.mjs';
import { LiveInputObserver as canonical } from './native/obs/live-input.mjs';
assert.equal(legacy, canonical);
const observer = new legacy();
observer.accept({type:'settings', settings:{inputMode:'demo', heightMode:'manual', manualOverlayHeight:240}});
observer.accept({type:'key', lane:1, down:true, time:1000.125});
observer.accept({type:'key', lane:1, down:false, time:1040.375});
assert.equal(observer.snapshot(1050).events[0].start, 1000.125);
assert.equal(observer.snapshot(1050).events[0].end, 1040.375);
console.log('same observer, unchanged input timestamps');
"""], cwd=self.extracted, text=True, capture_output=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_normal_app_has_no_new_native_or_experiment_dependency(self):
        self.assertFalse(any(name.startswith(("native/", "experiments/")) for name in RUNTIME_FILES))
        self.run_python("-c", """
import server, sys
assert not any(name in sys.modules for name in ('live_bridge', 'live_observer'))
""")


if __name__ == "__main__":
    unittest.main()
