"""Packaging boundaries and smoke tests against the public source ZIP."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import posixpath
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.parse import unquote, urlsplit
import zipfile

from tools.build_release import (
    DOCUMENTATION_FILES, ROOT, RUNTIME_FILES, SOURCE_FILES,
    ZIP_TIMESTAMP, build_release, collect_files, sha256,
)


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="lift-trace-release-")
        cls.workspace = Path(cls.temporary.name)
        # Exercise a clean source checkout without copying any local settings.
        cls.checkout = cls.workspace / "checkout"
        for name, contents in collect_files(ROOT).items():
            path = cls.checkout / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
        cls.archive = build_release(cls.checkout, cls.workspace / "release")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_exact_payloads_manifest_and_archive_checksums(self):
        expected = set(RUNTIME_FILES) | set(DOCUMENTATION_FILES) | set(SOURCE_FILES)
        with zipfile.ZipFile(self.archive) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(set(archive.namelist()), expected | {"MANIFEST.json"})
            self.assertEqual(archive.namelist(), sorted(archive.namelist()))
            manifest = json.loads(archive.read("MANIFEST.json"))
            self.assertEqual(set(manifest["files"]), expected)
            for name, expected_file in manifest["files"].items():
                contents = archive.read(name)
                self.assertEqual(expected_file, {"sha256": sha256(contents), "size": len(contents)})
                self.assertEqual(archive.getinfo(name).date_time, ZIP_TIMESTAMP)
            sidecar = self.archive.with_suffix(self.archive.suffix + ".sha256").read_text("utf-8")
            self.assertEqual(sidecar, f"{sha256(self.archive.read_bytes())}  {self.archive.name}\n")
        sums = (self.archive.parent / "SHA256SUMS").read_text("utf-8")
        self.assertEqual(sums, sidecar)

    def test_unlisted_files_and_private_integrations_cannot_leak(self):
        extras = (
            "data/settings.json", "data/launcher.json", "artifacts/capture.png",
            "stream_launcher.py", "start-stream.ps1", "start-stream.bat",
            "start-obs-extra-services.ps1", "launcher.example.json",
            "ipad_remote.py", "remote_server.py", "data/remote.json",
            "web/private.json", "web/debug.js", "tests/test_stream_launcher.py",
            "__pycache__/cache.pyc", "unrelated.txt",
        )
        marker = ("LOCAL_ONLY_" + str(time.time_ns())).encode("ascii")
        for name in extras:
            path = self.checkout / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(marker)
        rebuilt = build_release(self.checkout, self.workspace / "with-extras")
        self.assertEqual(self.archive.read_bytes(), rebuilt.read_bytes())
        with zipfile.ZipFile(rebuilt) as archive:
            self.assertTrue(set(extras).isdisjoint(archive.namelist()))
            self.assertFalse(any(marker in archive.read(name) for name in archive.namelist()))

    def test_public_obs_helper_has_no_private_service_startup_hook(self):
        relative = "start-obs-bridge.ps1"
        staging = ROOT / "distribution"
        expected = ((staging / relative) if staging.is_dir() else (ROOT / relative)).read_bytes()
        self.assertEqual(collect_files(ROOT)[relative], expected)
        self.assertFalse((self.checkout / "distribution").exists())
        self.assertEqual(collect_files(self.checkout)[relative], expected)
        with zipfile.ZipFile(self.archive) as archive:
            public = archive.read(relative)
            self.assertEqual(public, expected)
            self.assertNotIn(b"Start-ExtraServices", public)
            self.assertNotIn(b"start-obs-extra-services", public)
            self.assertNotIn(b"obs-extra-services.log", public)

    def test_documentation_relative_links_exist_in_public_payload(self):
        # The public docs use inline Markdown links. External URLs and section
        # anchors are intentionally not fetched or treated as local files.
        link_pattern = re.compile(r"!?\[[^\]\n]*\]\((<[^>]+>|[^\s)]+)(?:\s+\"[^\"]*\")?\)")
        with zipfile.ZipFile(self.archive) as archive:
            names = set(archive.namelist())
            for document in DOCUMENTATION_FILES:
                if not document.endswith(".md"):
                    continue
                markdown = archive.read(document).decode("utf-8")
                for target in link_pattern.findall(markdown):
                    target = target.strip("<>")
                    parts = urlsplit(target)
                    if parts.scheme or parts.netloc or not parts.path:
                        continue
                    path = unquote(parts.path)
                    relative = posixpath.normpath(posixpath.join(posixpath.dirname(document), path))
                    with self.subTest(document=document, target=target):
                        self.assertFalse(relative.startswith(("../", "/")), "Link leaves the release root")
                        self.assertIn(relative, names, "Broken relative documentation link")

    def test_extracted_source_rebuilds_identically(self):
        extracted = self.workspace / "source-extracted"
        with zipfile.ZipFile(self.archive) as archive:
            archive.extractall(extracted)
        output = self.workspace / "rebuilt-from-source"
        result = subprocess.run(
            [sys.executable, "tools/build_release.py", "--output-dir", str(output)],
            cwd=extracted, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.archive.read_bytes(), (output / self.archive.name).read_bytes())

    def test_extracted_source_can_replay_visibility_without_obs(self):
        extracted = self.workspace / "visibility-extracted"
        with zipfile.ZipFile(self.archive) as archive:
            archive.extractall(extracted)
        result = subprocess.run(
            [sys.executable, "tools/replay_visibility.py"], cwd=extracted,
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([(row["at"], row["applied"]) for row in rows if row["requests"]],
                         [(0, False), (0.35, True), (1, False), (1.4, True), (2, False)])
        self.assertFalse(rows[-1]["running"])
        self.assertEqual(rows[-1]["requests"], [])

    def test_missing_required_input_fails_before_output(self):
        source = self.checkout / "LICENSE"
        contents = source.read_bytes()
        output = self.workspace / "missing-input"
        try:
            source.unlink()
            with self.assertRaisesRegex(FileNotFoundError, "LICENSE"):
                build_release(self.checkout, output)
            self.assertFalse(output.exists())
        finally:
            source.write_bytes(contents)

    def test_extracted_overlay_serves_settings_and_all_web_assets(self):
        extracted = self.workspace / "overlay-extracted"
        with zipfile.ZipFile(self.archive) as archive:
            archive.extractall(extracted)
        data_dir = self.workspace / "smoke-local-data"
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        # Never contact a configured/live overlay or change the user's settings.
        self.assertNotIn(port, (8765, 8766))
        process = subprocess.Popen(
            [sys.executable, "-u", "server.py", "--port", str(port), "--data-dir", str(data_dir)],
            cwd=extracted, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        def request(method, route, value=None):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                body = json.dumps(value) if value is not None else None
                headers = {"Content-Type": "application/json"} if body is not None else {}
                connection.request(method, route, body=body, headers=headers)
                response = connection.getresponse()
                return response.status, response.read(), response.getheader("Content-Type", "")
            finally:
                connection.close()

        try:
            deadline = time.monotonic() + 12
            while True:
                if process.poll() is not None:
                    stdout, stderr = process.communicate()
                    self.fail(f"Packaged server exited during startup: {stdout}\n{stderr}")
                try:
                    status, body, _ = request("GET", "/api/status")
                    if status == 200:
                        break
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    self.fail("Packaged server did not become ready on its temporary port")
                time.sleep(0.05)
            initial = json.loads(body)
            self.assertIsNone(initial["selectedDevice"])
            self.assertIn("nativeSupported", initial)
            self.assertEqual(json.loads(request("GET", "/api/settings")[1]), {})
            status, body, content_type = request("GET", "/")
            self.assertEqual(status, 200)
            self.assertIn("text/html", content_type)
            self.assertIn(b"<html", body)
            for name in RUNTIME_FILES:
                if name.startswith("web/"):
                    status, body, _ = request("GET", "/" + name.removeprefix("web/"))
                    self.assertEqual(status, 200, name)
                    self.assertEqual(body, (extracted / name).read_bytes())
            settings = {"inputMode": "demo", "greenNumber": 300}
            self.assertEqual(request("POST", "/api/settings", settings)[0], 200)
            self.assertEqual(json.loads(request("GET", "/api/settings")[1]), settings)
            self.assertEqual(json.loads((data_dir / "settings.json").read_text("utf-8")), settings)
            self.assertFalse((extracted / "data").exists())
            self.assertFalse((extracted / "stream_launcher.py").exists())
        finally:
            if process.poll() is None:
                if sys.platform == "win32":
                    process.terminate()
                else:
                    process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            process.communicate(timeout=5)
        self.assertIsNotNone(process.returncode)
        with socket.socket() as probe:
            probe.settimeout(1)
            self.assertNotEqual(probe.connect_ex(("127.0.0.1", port)), 0)


if __name__ == "__main__":
    unittest.main()
