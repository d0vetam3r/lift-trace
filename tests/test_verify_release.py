"""Release integrity and publication boundaries without network or credentials."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
import zipfile

from tools import verify_release as release


SHA = "a" * 40


class Fixture:
    def __init__(self, root):
        self.root = root
        self.directory = root / "artifacts"
        self.directory.mkdir()
        (root / "docs/releases").mkdir(parents=True)
        (root / ".github").mkdir()
        (root / ".github/release-intent").write_text("0.2.0\n", encoding="utf-8")
        (root / "package.json").write_text('{"version":"0.2.0"}', encoding="utf-8")
        (root / "docs/releases/0.2.0.md").write_text("# Lift Trace 0.2.0\nTest notes.\n", encoding="utf-8")
        self.source = {"package.json": (root / "package.json").read_bytes(), "LICENSE": b"MIT fixture"}
        self.windows = {"LiftTrace.exe": b"executable fixture", "LICENSE": b"MIT fixture",
                        "THIRD_PARTY_NOTICES.md": b"notices", "licenses/runtime.txt": b"runtime license",
                        "provenance/python-runtime.spdx.json": b'{}'}
        self.runtime = {"runtimeProvenanceVerified": True, "automationProvenanceVerified": True,
                        "unverifiedComponents": [], "licenseHashes": {"runtime.txt": release.digest(b"runtime license")}}
        self.source_hashes = None
        self.build()

    def build(self):
        for kind, payload, prefix in [("source", self.source, ""), ("windows-x64", self.windows, "LiftTrace/")]:
            manifest = {"project": "lift-trace", "version": "0.2.0", "distribution": kind,
                        "files": {name: {"sha256": release.digest(raw), "size": len(raw)} for name, raw in payload.items()}}
            if prefix:
                manifest["bundledRuntime"] = self.runtime
                manifest["sourceFiles"] = self.source_hashes or {name: release.digest(raw) for name, raw in self.source.items()}
            path = self.directory / f"lift-trace-{kind}-0.2.0.zip"
            with zipfile.ZipFile(path, "w") as archive:
                for name, raw in payload.items():
                    archive.writestr(prefix + name, raw)
                archive.writestr(prefix + "MANIFEST.json", json.dumps(manifest))
        self.checksums()

    def checksums(self):
        rows = []
        for name in release.asset_names("0.2.0")[:2]:
            path = self.directory / name
            row = f"{release.digest(path.read_bytes())}  {name}\n"
            (self.directory / (name + ".sha256")).write_text(row, encoding="utf-8")
            rows.append(row)
        (self.directory / "SHA256SUMS").write_text("".join(rows), encoding="utf-8")

    def verify(self):
        return release.verify_assets(self.directory, self.root, self.source, exact_inventory=True)


class FakeGitHub:
    def __init__(self):
        self.calls = []
        self.fork = False
        self.main_sha = SHA
        self.tag_sha = None
        self.existing = None
        self.drafts = []
        self.current = None
        self.assets = []
        self.bad_digest = False
        self.fail_upload = False
        self.wrong_created_tag = False
        self.draft_creates_tag = False

    def request(self, method, endpoint, value=None, *, upload=None, missing_ok=False):
        self.calls.append((method, endpoint, value))
        if method == "GET":
            if endpoint == "": return {"fork": self.fork}
            if endpoint == "git/ref/heads/main": return {"object": {"sha": self.main_sha}}
            if endpoint.startswith("releases/tags/"): return self.existing
            if endpoint.startswith("releases?"): return self.drafts
            if endpoint.startswith("git/ref/tags/"):
                return {"object": {"sha": self.tag_sha, "type": "commit"}} if self.tag_sha else None
            if endpoint.startswith("releases/1/assets?"):
                return [{**item, "digest": "sha256:wrong"} for item in self.assets] if self.bad_digest else self.assets
            if endpoint == "releases/1": return self.current
        if method == "POST":
            if endpoint == "releases":
                self.current = {**value, "id": 1, "html_url": "https://github.com/owner/repo/releases/tag/v0.2.0"}
                if self.draft_creates_tag:
                    self.tag_sha = value["target_commitish"]
                return self.current
            if endpoint.startswith("releases/1/assets?"):
                if self.fail_upload: raise release.ReleaseError("Upload failed; draft preserved")
                name = parse_qs(urlsplit(endpoint).query)["name"][0]
                asset = {"name": name, "size": len(upload), "digest": "sha256:" + release.digest(upload), "state": "uploaded"}
                self.assets.append(asset)
                return asset
            if endpoint == "git/refs":
                self.tag_sha = "b" * 40 if self.wrong_created_tag else value["sha"]
                return {"object": {"sha": self.tag_sha, "type": "commit"}}
        if method == "PATCH" and endpoint == "releases/1":
            self.current = {**self.current, **value}
            return self.current
        raise AssertionError((method, endpoint))


class ReleaseVerificationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lift-trace-release-verify-")
        self.addCleanup(temporary.cleanup)
        self.fixture = Fixture(Path(temporary.name))

    def test_five_matching_assets_and_runtime_notices_pass(self):
        result = self.fixture.verify()
        self.assertEqual(result["tag"], "v0.2.0")
        self.assertEqual(len(result["assets"]), 5)

    def test_stable_version_notes_and_intent_are_required(self):
        package = self.fixture.root / "package.json"
        for version in ["0.2.0-dev.3", "v0.2.0", "01.2.0", "0.2", "1.0.0+build", "../../escape"]:
            package.write_text(json.dumps({"version": version}), encoding="utf-8")
            with self.subTest(version=version), self.assertRaises(release.ReleaseError):
                release.metadata(self.fixture.root)
        package.write_text('{"version":"0.2.0"}', encoding="utf-8")
        intent = self.fixture.root / ".github/release-intent"
        intent.unlink()
        with self.assertRaises(release.ReleaseError): release.metadata(self.fixture.root)
        intent.write_text("0.3.0", encoding="utf-8")
        with self.assertRaises(release.ReleaseError): release.metadata(self.fixture.root)
        intent.write_text("0.2.0", encoding="utf-8")
        (self.fixture.root / "docs/releases/0.2.0.md").write_text(" ", encoding="utf-8")
        with self.assertRaises(release.ReleaseError): release.metadata(self.fixture.root)

    def test_archive_and_checksum_tampering_is_rejected(self):
        path = self.fixture.directory / release.asset_names("0.2.0")[0]
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("extra.txt", b"unexpected")
        with self.assertRaises(release.ReleaseError): self.fixture.verify()
        self.fixture.checksums()
        with self.assertRaises(release.ReleaseError): self.fixture.verify()

    def test_different_windows_source_is_rejected(self):
        self.fixture.source_hashes = {"package.json": "b" * 64}
        self.fixture.build()
        with self.assertRaisesRegex(release.ReleaseError, "identical source"): self.fixture.verify()

    def test_archive_cannot_substitute_other_checked_out_source(self):
        with self.assertRaisesRegex(release.ReleaseError, "checked-out"):
            release.verify_assets(self.fixture.directory, self.fixture.root, {"other.py": b"other"})

    def test_both_provenance_flags_and_empty_unverified_list_are_required(self):
        for field, wrong in [("runtimeProvenanceVerified", False), ("automationProvenanceVerified", False),
                             ("unverifiedComponents", ["unknown"])]:
            original = self.fixture.runtime[field]
            self.fixture.runtime[field] = wrong
            self.fixture.build()
            with self.subTest(field=field), self.assertRaises(release.ReleaseError): self.fixture.verify()
            self.fixture.runtime[field] = original

    def test_missing_or_altered_license_and_extra_download_are_rejected(self):
        self.fixture.windows["licenses/runtime.txt"] = b"altered license"
        self.fixture.build()
        with self.assertRaisesRegex(release.ReleaseError, "License"): self.fixture.verify()
        self.fixture.windows["licenses/runtime.txt"] = b"runtime license"
        self.fixture.build()
        (self.fixture.directory / "extra.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(release.ReleaseError, "Unexpected"): self.fixture.verify()

    def test_unsafe_archive_names_are_rejected(self):
        self.fixture.windows["../outside.txt"] = b"escape"
        self.fixture.build()
        with self.assertRaisesRegex(release.ReleaseError, "Unsafe"): self.fixture.verify()

    def test_publication_rejects_untrusted_context(self):
        valid = {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "push", "GITHUB_SHA": SHA}
        self.assertEqual(release.trusted_context(valid), SHA)
        for key, value in [("GITHUB_REF", "refs/pull/2/merge"), ("GITHUB_EVENT_NAME", "pull_request"),
                           ("GITHUB_ACTIONS", "false"), ("GITHUB_SHA", "main")]:
            with self.subTest(key=key), self.assertRaises(release.ReleaseError):
                release.trusted_context({**valid, key: value})

    def publish(self, api):
        return release.publish(api, self.fixture.verify(), self.fixture.directory, SHA,
                               "https://github.com/owner/repo/actions/runs/1")

    def test_new_draft_upload_verify_exact_tag_then_publish(self):
        api = FakeGitHub()
        self.assertIn("/releases/tag/", self.publish(api))
        self.assertFalse(api.current["draft"])
        self.assertEqual(api.current["make_latest"], "true")
        self.assertEqual(api.tag_sha, SHA)
        self.assertEqual(len(api.assets), 5)
        actions = [method for method, _path, _value in api.calls]
        self.assertNotIn("DELETE", actions)
        publish_index = next(i for i, call in enumerate(api.calls) if call[0] == "PATCH")
        tag_index = next(i for i, call in enumerate(api.calls) if call[:2] == ("POST", "git/refs"))
        self.assertLess(tag_index, publish_index)

    def test_existing_release_draft_tag_or_fork_never_mutates_remote(self):
        for field, value in [("existing", {"draft": False}), ("drafts", [{"tag_name": "v0.2.0", "draft": True}]),
                             ("tag_sha", SHA), ("fork", True), ("main_sha", "b" * 40)]:
            api = FakeGitHub()
            setattr(api, field, value)
            with self.subTest(field=field), self.assertRaises(release.ReleaseError): self.publish(api)
            self.assertTrue(all(call[0] == "GET" for call in api.calls))

    def test_matching_tag_created_with_draft_is_verified_without_modification(self):
        api = FakeGitHub()
        api.draft_creates_tag = True
        self.publish(api)
        self.assertFalse(api.current["draft"])
        self.assertFalse(any(call[:2] == ("POST", "git/refs") for call in api.calls))

    def test_remote_digest_or_upload_failure_leaves_unpublished_draft(self):
        for field in ("bad_digest", "fail_upload", "wrong_created_tag"):
            api = FakeGitHub()
            setattr(api, field, True)
            with self.subTest(field=field), self.assertRaises(release.ReleaseError): self.publish(api)
            self.assertTrue(api.current["draft"])
            self.assertFalse(any(call[0] in ("PATCH", "DELETE") for call in api.calls))

    def test_main_or_tag_changes_during_upload_do_not_publish_or_retag(self):
        for field in ("main_sha", "tag_sha"):
            api = FakeGitHub()
            original = api.request

            def changed(method, endpoint, *args, **kwargs):
                result = original(method, endpoint, *args, **kwargs)
                if endpoint.startswith("releases/1/assets?per_page"):
                    setattr(api, field, "b" * 40)
                return result

            api.request = changed
            with self.subTest(field=field), self.assertRaises(release.ReleaseError): self.publish(api)
            self.assertTrue(api.current["draft"])
            self.assertFalse(any(call[:2] == ("POST", "git/refs") or call[0] in ("PATCH", "DELETE") for call in api.calls))

    def test_transport_failure_does_not_expose_credentials_or_response_body(self):
        class FailedTransport:
            def open(self, request, timeout):
                raise HTTPError("https://private.invalid/credential", 403, "private-response", {}, None)

        api = release.GitHub("owner/repo", "private-fixture-token")
        api.opener = FailedTransport()
        with self.assertRaises(release.ReleaseError) as error:
            api.request("POST", "releases", {"body": "private-notes"})
        self.assertEqual(str(error.exception), "GitHub POST request failed (HTTP 403); draft preserved")


if __name__ == "__main__":
    unittest.main()
