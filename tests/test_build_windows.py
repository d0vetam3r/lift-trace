"""License provenance boundaries; no network, native UI, or executable build."""
from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from tools import build_windows as builder


PROPERTIES = b'''<?xml version="1.0"?>
<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
 <PropertyGroup>
  <libffiDir>$(ExternalsDir)libffi-3.4.4\\</libffiDir>
  <lzmaDir>$(ExternalsDir)xz-5.2.5\\</lzmaDir>
 </PropertyGroup>
</Project>'''


class RuntimeNoticeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lift-trace-notices-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.python = self.root / "python"
        self.python.mkdir()
        (self.python / "LICENSE.txt").write_text("Python license fixture", encoding="utf-8")
        (self.python / "COPYING.txt").write_text("PyInstaller license fixture", encoding="utf-8")
        self.app = self.root / "LiftTrace"
        self.internal = self.app / "_internal"
        self.internal.mkdir(parents=True)
        (self.internal / "tk86t.dll").write_bytes(b"fixture")
        packages = [{"name": name, "versionInfo": version} for name, version in (
            ("libffi", "3.4.4"), ("xz", "5.2.5"), ("mpdecimal", "2.5.1"),
            ("mpdecimal", "4.0.0"), ("openssl", "3.5.9"), ("zlib", "1.3.1"),
            ("tcl-core", "8.6.15.0"), ("tk", "8.6.15.0"), ("expat", "2.8.5"))]
        sbom = json.dumps({"packages": packages}).encode()
        downloads = self.root / "downloads"
        downloads.mkdir()
        (downloads / "runtime.spdx.json").write_bytes(sbom)
        self.provenance = {
            "verified": True, "version": "3.13.16",
            "archive": {"url": "https://www.python.org/runtime.zip", "sha256": "a" * 64},
            "sbom": {"url": "https://www.python.org/runtime.spdx.json",
                     "sha256": hashlib.sha256(sbom).hexdigest(), "packages": packages},
            "runtimeFiles": {}, "bundledFiles": {},
        }
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        fake_tk = SimpleNamespace(Tcl=lambda: SimpleNamespace(eval=lambda command: "8.6.15"))
        fake_installer = SimpleNamespace(version="6.22.3", files=["licenses/COPYING.txt"],
                                         locate_file=lambda path: self.python / "COPYING.txt")
        for name, value in (
            ("sys.base_prefix", str(self.python)),
            ("platform.python_version", lambda: "3.13.16"),
            ("importlib.metadata.distribution", lambda name: fake_installer),
            ("windows_file_version", lambda path: "8.6.15"),
            ("ssl.OPENSSL_VERSION", "OpenSSL 3.5.9 6 Oct 2026"),
            ("zlib.ZLIB_RUNTIME_VERSION", "1.3.1"),
            ("decimal.__libmpdec_version__", "4.0.0"),
        ):
            self.stack.enter_context(patch("tools.build_windows." + name, value))
        self.stack.enter_context(patch.dict("sys.modules", {"tkinter": fake_tk}))
        self.verifier = self.stack.enter_context(patch.object(builder, "verify_runtime", return_value=self.provenance))
        self.automation = {"verified": True, "packages": {
            "pillow": {"version": "12.3.0"}, "websocket-client": {"version": "1.9.2"}},
            "bundledFiles": {}, "licenses": {}}
        self.stack.enter_context(patch.object(builder, "verify_dependencies", return_value=self.automation))
        self.requested = []

        def upstream(url):
            self.requested.append(url)
            if url.endswith("/PCbuild/python.props"):
                return PROPERTIES
            if url.endswith("/mpdecimal.h"):
                return b'#define MPD_VERSION "2.5.1"\n'
            if url.endswith((".c", "/target.h")):
                return b"/* Copyright fixture; licensed for redistribution. */\nint ignored_source;"
            return ("Upstream license fixture for " + url).encode()

        self.stack.enter_context(patch.object(builder, "fetch_license", upstream))

    def collect(self):
        return builder.collect_licenses(self.app / "licenses")

    def test_verified_runtime_uses_matching_notices_and_retains_evidence(self):
        details = self.collect()
        self.verifier.assert_called_once_with(self.python, self.internal, dependency_binaries={})
        self.assertTrue(details["runtimeProvenanceVerified"])
        self.assertTrue(details["automationProvenanceVerified"])
        self.assertEqual(details["unverifiedComponents"], [])
        self.assertIsNone(details["referenceBuild"])
        self.assertEqual((details["libffi"], details["liblzma"]), ("3.4.4", "5.2.5"))
        self.assertIn("/libffi-3.4.4/LICENSE", details["licenses"]["libffi.txt"])
        self.assertIn("/xz-5.2.5/COPYING", details["licenses"]["XZ.txt"])
        self.assertIn("/mpdecimal-4.0.0/COPYRIGHT.txt", details["licenses"]["mpdecimal.txt"])
        self.assertIn("/v1.3.1/LICENSE", details["licenses"]["zlib.txt"])
        self.assertIn("/core-8-6-15/", details["licenses"]["Tk.txt"])
        self.assertEqual((self.app / "provenance/python-runtime.spdx.json").read_bytes(),
                         (self.root / "downloads/runtime.spdx.json").read_bytes())
        for name, digest in details["licenseHashes"].items():
            self.assertEqual(digest, hashlib.sha256((self.app / "licenses" / name).read_bytes()).hexdigest())

    def test_verified_notices_and_publication_check_are_scoped(self):
        details = self.collect()
        builder.require_release_provenance(details, True)
        builder.write_notices(self.app, details)
        notice = (self.app / "THIRD_PARTY_NOTICES.md").read_text("utf-8")
        self.assertIn("runtimeProvenanceVerified: true", notice)
        self.assertIn("not a reproducible-build proof", notice)
        self.assertIn("mpdecimal 4.0.0", notice)
        self.assertNotIn("publicReleaseReady", notice)
        self.assertNotIn("local prototype", notice)
        self.assertIn("verified separately", notice)
        self.assertNotIn("every packaged DLL/PYD match", notice)

    def test_verified_python_does_not_override_failed_automation_proof(self):
        with self.assertRaisesRegex(RuntimeError, "Automation dependency provenance"):
            builder.require_release_provenance({"runtimeProvenanceVerified": True,
                                                "automationProvenanceVerified": False}, True)

    def test_custom_runtime_remains_buildable_without_false_verification(self):
        self.verifier.side_effect = RuntimeError("Missing regular runtime evidence file: runtime.zip")
        with patch.object(builder.platform, "python_version", return_value="3.12.14"), \
                patch.object(builder.decimal, "__libmpdec_version__", "2.5.1"):
            details = self.collect()
        self.assertFalse(details["runtimeProvenanceVerified"])
        self.assertIsNone(details["libffi"])
        self.assertIn("libffi-reference.txt", details["licenses"])
        builder.require_release_provenance(details, False)
        with self.assertRaisesRegex(RuntimeError, "Run tools/prepare_runtime.py"):
            builder.require_release_provenance(details, True)
        builder.write_notices(self.app, details)
        notice = (self.app / "THIRD_PARTY_NOTICES.md").read_text("utf-8")
        self.assertIn("runtimeProvenanceVerified: false", notice)
        self.assertIn("does not by itself establish a license violation", notice)

    def test_observed_version_must_exist_in_official_sbom(self):
        with patch.object(builder.decimal, "__libmpdec_version__", "9.9.9"):
            with self.assertRaisesRegex(RuntimeError, "SBOM.*mpdecimal 9.9.9"):
                self.collect()
        with patch.object(builder.zlib, "ZLIB_RUNTIME_VERSION", "9.9.9"):
            with self.assertRaisesRegex(RuntimeError, "SBOM.*zlib 9.9.9"):
                self.collect()

    def test_strict_packaged_verification_fails_before_license_fallback(self):
        self.verifier.side_effect = RuntimeError("Packaged binary differs from the official runtime: foreign.dll")
        with self.assertRaisesRegex(RuntimeError, "Packaged binary differs.*foreign.dll"):
            builder.collect_licenses(self.app / "licenses", require_verified_runtime=True)
        self.assertEqual(self.requested, [])

    def test_freeze_environment_excludes_foreign_dependency_paths(self):
        executable = self.root / "venv" / "Scripts" / "python.exe"
        windows = self.root / "Windows"
        inherited = {"PATH": "foreign-sdk", "SystemRoot": str(windows), "TEMP": "keep-this",
                     "PYTHONHOME": "foreign-python", "PYTHONPATH": "foreign-modules",
                     "TCL_LIBRARY": "foreign-tcl", "TK_LIBRARY": "foreign-tk", "TCLLIBPATH": "foreign-packages"}
        with patch.dict(os.environ, inherited, clear=True), patch.object(builder.sys, "executable", str(executable)):
            environment = builder.freeze_environment()
            self.assertEqual(os.environ["PATH"], "foreign-sdk")
        self.assertEqual(next(value for name, value in environment.items() if name.upper() == "SYSTEMROOT"), str(windows))
        self.assertEqual(environment["TEMP"], "keep-this")
        self.assertEqual(environment["PATH"].split(os.pathsep), list(map(str, (
            executable.parent, self.python, self.python / "DLLs", windows / "System32", windows))))
        self.assertFalse(any(name in environment for name in
                             ("PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY", "TCLLIBPATH")))
    def test_changed_retained_sbom_is_rejected(self):
        (self.root / "downloads/runtime.spdx.json").write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "SBOM changed after verification"):
            self.collect()

    def test_only_bundled_expat_receives_a_notice(self):
        details = self.collect()
        self.assertIsNone(details["expat"])
        self.assertNotIn("Expat.txt", details["licenses"])
        (self.internal / "pyexpat.pyd").write_bytes(b"fixture")
        with patch.dict("sys.modules", {"pyexpat": SimpleNamespace(version_info=(2, 8, 5))}):
            details = self.collect()
        self.assertEqual(details["expat"], "2.8.5")
        self.assertTrue(details["licenses"]["Expat.txt"].endswith("/R_2_8_5/expat/COPYING"))

    def test_incorporated_code_notices_keep_license_header_only(self):
        details = self.collect()
        self.assertIn("CC0-1.0.txt", details["licenses"])
        for name in ("HACL-MIT.txt", "KaRaMeL-Apache.txt", "BLAKE2-wrapper.txt", "BLAKE2-reference.txt"):
            contents = (self.app / "licenses" / name).read_bytes()
            self.assertIn(b"Copyright fixture", contents)
            self.assertNotIn(b"ignored_source", contents)
        with self.assertRaisesRegex(RuntimeError, "Cannot locate upstream"):
            builder.license_header(b"/* unrelated comment */\n", "test")

    def test_empty_unverified_list_does_not_bypass_publication_check(self):
        with self.assertRaisesRegex(RuntimeError, "Runtime provenance check failed"):
            builder.require_release_provenance({"unverifiedComponents": []}, True)

    def test_ambiguous_sbom_or_reference_declarations_are_rejected(self):
        ambiguous = deepcopy(self.provenance)
        ambiguous["sbom"]["packages"].append({"name": "libffi", "versionInfo": "9.9.9"})
        with self.assertRaisesRegex(RuntimeError, "uniquely identify libffi"):
            builder.sbom_package(ambiguous, "libffi")
        with self.assertRaisesRegex(RuntimeError, "declared libffi"):
            builder.cpython_reference_versions(b"<Project />")

    def test_unsupported_version_is_not_used_in_a_source_url(self):
        with self.assertRaisesRegex(RuntimeError, "Unsupported zlib"):
            builder.release_version("1.3.2/vendor-patch", "zlib")


class LicenseDownloadTests(unittest.TestCase):
    def test_download_failure_identifies_the_url_and_preserves_cause(self):
        url = "https://example.test/license.txt"
        error = HTTPError(url, 403, "Forbidden", None, None)
        with patch.object(builder, "urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as raised:
                builder.fetch_license(url)
        self.assertIn(url, str(raised.exception))
        self.assertIn("403", str(raised.exception))
        self.assertIs(raised.exception.__cause__, error)


if __name__ == "__main__":
    unittest.main()
