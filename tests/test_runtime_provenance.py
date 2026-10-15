"""Offline provenance regressions using a tiny, non-executable runtime fixture."""
from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools.prepare_runtime import prepare
from tools.runtime_provenance import archive_members, digest, evidence_paths, verify_runtime


class Download(io.BytesIO):
    def __init__(self, contents: bytes, url: str):
        super().__init__(contents)
        self.url = url

    def geturl(self):
        return self.url


class RuntimeProvenanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lift-trace-provenance-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.base = self.root / "python"
        self.internal = self.root / "app" / "_internal"
        self.base.mkdir()
        self.internal.mkdir(parents=True)
        self.original = {
            "python.exe": b"fixture interpreter, never executed",
            "LICENSE.txt": b"fixture license text",
            "DLLs/libffi-8.dll": b"fixture libffi",
            "DLLs/_lzma.pyd": b"fixture liblzma",
        }
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            for name, contents in self.original.items():
                archive.writestr(name, contents)
                path = self.base / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)
                if path.suffix in (".dll", ".pyd"):
                    (self.internal / path.name).write_bytes(contents)
        prefix = "https://www.python.org/ftp/python/3.13.16/"
        self.pin = {"version": "3.13.16", "architecture": "amd64",
                    "archive": {"url": prefix + "fixture-amd64.zip", "sha256": digest(archive_bytes.getvalue())},
                    "sbom": {"url": prefix + "fixture.spdx.json"},
                    "manifest": {"url": prefix + "fixture-manifest.json"}}
        self.sbom = {"packages": [{"name": "CPython", "versionInfo": "3.13.16",
                                   "downloadLocation": self.pin["archive"]["url"],
                                   "checksums": [{"algorithm": "SHA256", "checksumValue": self.pin["archive"]["sha256"]}]}]}
        self.manifest = {"versions": [{"url": self.pin["archive"]["url"], "sort-version": "3.13.16",
                                       "hash": {"sha256": self.pin["archive"]["sha256"]}}]}
        self.paths = evidence_paths(self.base, self.pin)
        self.paths["archive"].parent.mkdir()
        self.paths["archive"].write_bytes(archive_bytes.getvalue())
        self.write_metadata("sbom", self.sbom)
        self.write_metadata("manifest", self.manifest)

    def write_metadata(self, key, value):
        contents = json.dumps(value).encode("utf-8")
        self.paths[key].write_bytes(contents)
        self.pin[key]["sha256"] = digest(contents)

    def test_matching_runtime_and_payload_report_exact_originals(self):
        result = verify_runtime(self.base, self.internal, pin=self.pin)
        self.assertTrue(result["verified"])
        self.assertEqual(result["runtimeFiles"], {name: digest(value) for name, value in self.original.items()})
        self.assertEqual(result["bundledFiles"]["_lzma.pyd"]["source"], "DLLs/_lzma.pyd")
        self.assertEqual(result["bundledFiles"]["libffi-8.dll"]["sha256"], digest(b"fixture libffi"))

    def test_corrupt_download_is_not_cached_or_extracted(self):
        output = self.root / "fresh-download"
        with patch("tools.prepare_runtime.load_pin", return_value=self.pin), \
                patch("tools.prepare_runtime.urlopen", return_value=Download(b"corrupted download", self.pin["archive"]["url"])):
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                prepare(output)
        self.assertFalse((output / "python").exists())
        self.assertEqual(list((output / "downloads").iterdir()), [])

    def test_metadata_must_identify_the_same_archive_even_with_valid_hashes(self):
        for field, wrong in (("versionInfo", "3.13.15"), ("downloadLocation", "https://example.invalid/other.zip"),
                             ("checksums", [{"algorithm": "SHA256", "checksumValue": "0" * 64}])):
            with self.subTest(source="sbom", field=field):
                changed = copy.deepcopy(self.sbom)
                changed["packages"][0][field] = wrong
                self.write_metadata("sbom", changed)
                with self.assertRaisesRegex(RuntimeError, "SBOM does not identify"):
                    verify_runtime(self.base, pin=self.pin)
        self.write_metadata("sbom", self.sbom)
        for field, wrong in (("sort-version", "3.13.15"), ("url", "https://example.invalid/other.zip"),
                             ("hash", {"sha256": "0" * 64})):
            with self.subTest(source="manifest", field=field):
                changed = copy.deepcopy(self.manifest)
                changed["versions"][0][field] = wrong
                self.write_metadata("manifest", changed)
                with self.assertRaisesRegex(RuntimeError, "manifest does not identify"):
                    verify_runtime(self.base, pin=self.pin)

    def test_modified_extracted_original_is_rejected(self):
        target = self.base / "DLLs" / "_lzma.pyd"
        target.write_bytes(b"altered runtime binary")
        with self.assertRaisesRegex(RuntimeError, "checksum mismatch: _lzma.pyd"):
            verify_runtime(self.base, self.internal, pin=self.pin)

    def test_added_startup_code_is_rejected_but_generated_bytecode_cache_is_allowed(self):
        for name in ("Lib/sitecustomize.py", "Lib/site-packages/startup.pth"):
            with self.subTest(name=name):
                added = self.base / name
                added.parent.mkdir(parents=True, exist_ok=True)
                added.write_bytes(b"fixture startup modification, never executed")
                try:
                    with self.assertRaisesRegex(RuntimeError, "Unlisted file in official runtime"):
                        verify_runtime(self.base, self.internal, pin=self.pin)
                finally:
                    added.unlink()
        cache = self.base / "Lib" / "__pycache__" / "fixture.cpython-313.pyc"
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b"fixture generated cache, never executed")
        result = verify_runtime(self.base, self.internal, pin=self.pin)
        self.assertTrue(result["verified"])
        self.assertNotIn(cache.relative_to(self.base).as_posix(), result["runtimeFiles"])

    def test_modified_or_missing_packaged_component_is_rejected(self):
        target = self.internal / "libffi-8.dll"
        target.write_bytes(b"altered packaged binary")
        with self.assertRaisesRegex(RuntimeError, "differs from the official runtime: libffi-8.dll"):
            verify_runtime(self.base, self.internal, pin=self.pin)
        target.unlink()
        with self.assertRaisesRegex(RuntimeError, "libffi and liblzma runtime binaries are missing"):
            verify_runtime(self.base, self.internal, pin=self.pin)

    def test_dependency_exception_requires_the_individually_verified_path_and_hash(self):
        target = self.internal / "PIL" / "_imaging.pyd"
        target.parent.mkdir()
        target.write_bytes(b"wheel fixture")
        with self.assertRaisesRegex(RuntimeError, "differs from the official runtime"):
            verify_runtime(self.base, self.internal, pin=self.pin)
        verified = {"PIL/_imaging.pyd": {"sha256": digest(b"wheel fixture"), "source": "PIL/_imaging.pyd"}}
        result = verify_runtime(self.base, self.internal, pin=self.pin, dependency_binaries=verified)
        self.assertNotIn("PIL/_imaging.pyd", result["bundledFiles"])
        self.assertEqual(result["separatelyVerifiedDependencyFiles"], verified)
        target.write_bytes(b"changed after verification")
        with self.assertRaisesRegex(RuntimeError, "dependency changed"):
            verify_runtime(self.base, self.internal, pin=self.pin, dependency_binaries=verified)
        target.unlink()
        with self.assertRaisesRegex(RuntimeError, "dependency binary disappeared"):
            verify_runtime(self.base, self.internal, pin=self.pin, dependency_binaries=verified)

    def test_escaping_and_ambiguous_archive_paths_are_rejected_before_extraction(self):
        names = ("../outside.dll", "dir/../../outside.dll", "/outside.dll", "C:/outside.dll", "..\\outside.dll",
                 "dir./outside.dll", "outside.dll ", "dir/./outside.dll", "dir//outside.dll")
        for name in names:
            with self.subTest(name=name):
                contents = io.BytesIO()
                with zipfile.ZipFile(contents, "w") as archive:
                    archive.writestr(name, b"not extracted")
                contents.seek(0)
                with zipfile.ZipFile(contents) as archive:
                    with self.assertRaisesRegex(RuntimeError, "Unsafe runtime ZIP member"):
                        archive_members(archive)
        contents = io.BytesIO()
        with zipfile.ZipFile(contents, "w") as archive:
            archive.writestr("DLLs/test.dll", b"first")
            archive.writestr("dlls/TEST.DLL", b"second")
        contents.seek(0)
        with zipfile.ZipFile(contents) as archive:
            with self.assertRaisesRegex(RuntimeError, "Duplicate runtime ZIP member"):
                archive_members(archive)


if __name__ == "__main__":
    unittest.main()
