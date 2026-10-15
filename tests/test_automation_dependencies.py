"""Synthetic wheel provenance checks; no downloaded code is executed."""
from io import BytesIO
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from tools import automation_dependencies as dependencies
from tools.runtime_provenance import digest


class WheelProvenanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.site = self.root / "site-packages"
        self.internal = self.root / "app" / "_internal"
        self.internal.mkdir(parents=True)
        self.files = {"PIL/__init__.py": b"# synthetic source, never imported",
                      "PIL/_imaging.fixture.pyd": b"non-executable binary fixture",
                      "pillow-12.3.0.dist-info/METADATA": b"Version: 12.3.0\n",
                      "pillow-12.3.0.dist-info/licenses/LICENSE": b"Pillow terms\nEntire third-party notice\n"}
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, contents in self.files.items():
                archive.writestr(name, contents)
                path = self.site / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)
            archive.writestr("pillow-12.3.0.dist-info/RECORD", b"rewritten on install")
        self.contents = buffer.getvalue()
        self.wheel = {"url": "https://files.pythonhosted.org/packages/fixture.whl",
                      "sha256": digest(self.contents)}
        self.pins = {"pillow": {"version": "12.3.0", "package": "PIL", "wheels": {"any": self.wheel}}}
        self.cache = self.root / "cache"
        self.cache.mkdir()
        (self.cache / "fixture.whl").write_bytes(self.contents)
        self.distribution = SimpleNamespace(version="12.3.0", locate_file=lambda name: self.site / name)
        for name, value in (("load_pins", lambda: self.pins),
                            ("importlib.metadata.distribution", lambda name: self.distribution)):
            context = patch("tools.automation_dependencies." + name, value)
            context.start()
            self.addCleanup(context.stop)
        self.binary = self.internal / "PIL" / "_imaging.fixture.pyd"
        self.binary.parent.mkdir()
        self.binary.write_bytes(self.files["PIL/_imaging.fixture.pyd"])

    def verify(self):
        return dependencies.verify_dependencies(self.cache, self.internal, self.root / "licenses")

    def test_valid_wheel_verifies_installed_bytes_and_retains_complete_notice(self):
        result = self.verify()
        self.assertTrue(result["verified"])
        binary = result["bundledFiles"]["PIL/_imaging.fixture.pyd"]
        self.assertEqual(binary["wheelSha256"], self.wheel["sha256"])
        self.assertEqual(binary["source"], "PIL/_imaging.fixture.pyd")
        self.assertEqual((self.root / "licenses/pillow/LICENSE").read_bytes(),
                         self.files["pillow-12.3.0.dist-info/licenses/LICENSE"])

    def test_changed_cached_wheel_and_installed_file_are_rejected(self):
        cached = self.cache / "fixture.whl"
        cached.write_bytes(b"not the pinned wheel")
        with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
            self.verify()
        cached.write_bytes(self.contents)
        (self.site / "PIL/__init__.py").write_bytes(b"modified")
        with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
            self.verify()

    def test_changed_packaged_binary_is_not_exempted_by_pil_directory(self):
        self.binary.write_bytes(b"not from the wheel")
        with self.assertRaisesRegex(RuntimeError, "imaging module does not match"):
            self.verify()

    def test_extra_installed_code_is_rejected_but_generated_cache_is_ignored(self):
        cache = self.site / "PIL/__pycache__/fixture.pyc"
        cache.parent.mkdir()
        cache.write_bytes(b"generated cache")
        self.assertTrue(self.verify()["verified"])
        (self.site / "PIL/extra.py").write_bytes(b"unknown source")
        with self.assertRaisesRegex(RuntimeError, "Unlisted installed dependency"):
            self.verify()

    def test_wrong_installed_version_is_rejected(self):
        self.distribution.version = "12.2.0"
        with self.assertRaisesRegex(RuntimeError, "version differs"):
            self.verify()

    def test_unpinned_download_is_not_cached(self):
        response = BytesIO(b"incorrect downloaded bytes")
        response.geturl = lambda: self.wheel["url"]
        with patch.object(dependencies, "urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                dependencies.wheel_bytes(self.wheel, self.root / "fresh-cache")
        self.assertFalse((self.root / "fresh-cache").exists())


if __name__ == "__main__":
    unittest.main()
