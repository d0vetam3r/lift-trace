"""Validate matching release assets and publish once from a trusted main run.

No credential is stored or printed. Publication only creates new objects; a
failure leaves its draft/tag for inspection and never replaces existing assets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile


ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")


class ReleaseError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def metadata(root=ROOT):
    root = Path(root)
    version = json.loads((root / "package.json").read_text("utf-8"))["version"]
    require(isinstance(version, str) and VERSION.fullmatch(version), "A stable X.Y.Z version is required")
    notes = root / "docs" / "releases" / f"{version}.md"
    require(notes.is_file() and not notes.is_symlink(), "Versioned release notes are required")
    text = notes.read_text("utf-8")
    require(0 < len(text.encode("utf-8")) <= 120000 and text.strip(), "Release notes must be nonempty and bounded")
    intent = root / ".github" / "release-intent"
    require(intent.is_file() and not intent.is_symlink() and intent.read_text("utf-8").strip() == version,
            "Release intent does not match package.json")
    return {"version": version, "tag": f"v{version}", "notes": text}


def asset_names(version):
    require(VERSION.fullmatch(version), "Invalid release version")
    zips = [f"lift-trace-source-{version}.zip", f"lift-trace-windows-x64-{version}.zip"]
    return zips + [name + ".sha256" for name in zips] + ["SHA256SUMS"]


def checked_archive(path, version, distribution, prefix=""):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Duplicate ZIP entries")
        require(sum(item.file_size for item in archive.infolist()) <= 1024 ** 3, "Oversized archive")
        for name in names:
            part = PurePosixPath(name)
            require(not part.is_absolute() and ".." not in part.parts and "\\" not in name
                    and ":" not in name and name.startswith(prefix) and not name.endswith("/"),
                    "Unsafe ZIP entry")
        manifest_name = prefix + "MANIFEST.json"
        require(manifest_name in names, "Archive manifest missing")
        manifest = json.loads(archive.read(manifest_name))
        require(manifest.get("project") == "lift-trace" and manifest.get("version") == version
                and manifest.get("distribution") == distribution, "Archive identity mismatch")
        files = manifest.get("files")
        require(isinstance(files, dict) and set(names) == {prefix + name for name in files} | {manifest_name},
                "Archive inventory does not match manifest")
        for name, entry in files.items():
            raw = archive.read(prefix + name)
            require(entry == {"sha256": digest(raw), "size": len(raw)}, "Archive file hash/size mismatch")
        return manifest, {name: archive.read(prefix + name) for name in files}


def verify_assets(directory, root=ROOT, expected_source=None, *, exact_inventory=False):
    directory, root = Path(directory), Path(root)
    info = metadata(root)
    names = asset_names(info["version"])
    require(all((directory / name).is_file() and not (directory / name).is_symlink() for name in names),
            "All five release assets are required")
    if exact_inventory:
        require(set(item.name for item in directory.iterdir()) == set(names), "Unexpected downloaded artifact files")
    hashes = {name: digest((directory / name).read_bytes()) for name in names}
    sums = "".join(f"{hashes[name]}  {name}\n" for name in names[:2])
    require((directory / "SHA256SUMS").read_text("utf-8") == sums, "SHA256SUMS mismatch")
    for name in names[:2]:
        require((directory / (name + ".sha256")).read_text("utf-8") == f"{hashes[name]}  {name}\n",
                "Individual checksum mismatch")
    source, source_files = checked_archive(directory / names[0], info["version"], "source")
    windows, windows_files = checked_archive(directory / names[1], info["version"], "windows-x64", "LiftTrace/")
    require(json.loads(source_files["package.json"])["version"] == info["version"], "Source package version mismatch")
    if expected_source is None:
        from tools.build_release import collect_files
        expected_source = collect_files(root)
    require(source_files == expected_source, "Source archive differs from the checked-out release source")
    require(windows.get("sourceFiles") == {name: digest(raw) for name, raw in source_files.items()},
            "Windows and source ZIPs were not built from identical source")
    runtime = windows.get("bundledRuntime", {})
    require(runtime.get("runtimeProvenanceVerified") is True
            and runtime.get("automationProvenanceVerified") is True
            and runtime.get("unverifiedComponents") == [], "Verified runtime and automation provenance required")
    required = {"LICENSE", "THIRD_PARTY_NOTICES.md", "provenance/python-runtime.spdx.json", "LiftTrace.exe"}
    require(required <= windows_files.keys(), "Executable or required notices/SBOM missing")
    license_hashes = runtime.get("licenseHashes", {})
    require(isinstance(license_hashes, dict) and license_hashes, "License hashes missing")
    for name, sha in license_hashes.items():
        require("licenses/" + name in windows_files and digest(windows_files["licenses/" + name]) == sha,
                "License notice hash mismatch")
    require(all("data" not in PurePosixPath(name).parts for name in source_files)
            and all("data" not in PurePosixPath(name).parts for name in windows_files), "Personal data directory included")
    return {**info, "assets": [{"name": name, "size": (directory / name).stat().st_size,
                               "digest": "sha256:" + hashes[name]} for name in names]}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, url):
        return None


class GitHub:
    def __init__(self, repository, token):
        require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository), "Invalid repository")
        require(bool(token), "GITHUB_TOKEN is required")
        self.repository, self.token = repository, token
        self.opener = build_opener(NoRedirect())

    def request(self, method, endpoint, value=None, *, upload=None, missing_ok=False):
        host = "uploads.github.com" if upload is not None else "api.github.com"
        url = f"https://{host}/repos/{self.repository}" + ("/" + endpoint if endpoint else "")
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "lift-trace-release"}
        data = upload if upload is not None else (json.dumps(value).encode() if value is not None else None)
        headers["Content-Type"] = "application/octet-stream" if upload is not None else "application/json"
        try:
            with self.opener.open(Request(url, data=data, headers=headers, method=method), timeout=120) as response:
                return json.load(response)
        except HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            raise ReleaseError(f"GitHub {method} request failed (HTTP {error.code}); draft preserved") from None
        except (URLError, OSError, ValueError):
            raise ReleaseError("GitHub response unavailable or invalid; draft preserved") from None


def trusted_context(environment):
    require(environment.get("GITHUB_ACTIONS") == "true" and environment.get("GITHUB_REF") == "refs/heads/main"
            and environment.get("GITHUB_EVENT_NAME") in ("push", "workflow_dispatch"), "Publish only from trusted main")
    sha = environment.get("GITHUB_SHA", "")
    require(re.fullmatch(r"[0-9a-f]{40}", sha), "Exact commit SHA is required")
    return sha


def publish(api, release, directory, sha, run_url):
    """Create new draft/assets/tag; verify remote bytes and ref before publication."""
    tag = release["tag"]
    ref_path = "git/ref/tags/" + quote(tag, safe="")
    require(api.request("GET", "").get("fork") is False, "Fork repositories cannot publish")
    require(api.request("GET", "git/ref/heads/main")["object"]["sha"] == sha, "main advanced; build its current commit")
    require(api.request("GET", "releases/tags/" + quote(tag, safe=""), missing_ok=True) is None,
            "A release already exists; never replace or republish it")
    # Drafts are not guaranteed to be returned by the tag endpoint.
    page = 1
    while True:
        entries = api.request("GET", f"releases?per_page=100&page={page}")
        require(not any(item.get("tag_name") == tag for item in entries), "A draft/release already exists; inspect it first")
        if len(entries) < 100:
            break
        page += 1
        require(page <= 100, "Release inventory exceeds safety bound")
    require(api.request("GET", ref_path, missing_ok=True) is None, "Tag already exists; never retag")
    body = release["notes"] + f"\n\nBuild commit: `{sha}`\n\n[Verified build run]({run_url})\n"
    draft = api.request("POST", "releases", {"tag_name": tag, "target_commitish": sha,
                        "name": "Lift Trace " + release["version"], "body": body,
                        "draft": True, "prerelease": False, "make_latest": "false"})
    require(draft.get("draft") is True and type(draft.get("id")) is int, "Draft creation unconfirmed")
    release_id = draft["id"]
    for asset in release["assets"]:
        raw = (Path(directory) / asset["name"]).read_bytes()
        require(len(raw) == asset["size"] and "sha256:" + digest(raw) == asset["digest"], "Asset changed before upload")
        api.request("POST", f"releases/{release_id}/assets?name=" + quote(asset["name"], safe=""), upload=raw)
    remote = api.request("GET", f"releases/{release_id}/assets?per_page=100")
    require(len(remote) == 5 and {item["name"] for item in remote} == {item["name"] for item in release["assets"]},
            "Remote asset inventory mismatch; draft preserved")
    for expected in release["assets"]:
        actual = next(item for item in remote if item["name"] == expected["name"])
        require(actual.get("state") == "uploaded" and actual.get("size") == expected["size"]
                and actual.get("digest") == expected["digest"], "Remote asset digest/size mismatch; draft preserved")
    require(api.request("GET", "git/ref/heads/main")["object"]["sha"] == sha, "main advanced; draft preserved")
    # Some release configurations may create the ref with the draft. Accept a
    # newly appeared direct match, never update or move any ref.
    ref = api.request("GET", ref_path, missing_ok=True)
    if ref is None:
        api.request("POST", "git/refs", {"ref": "refs/tags/" + tag, "sha": sha})
    else:
        require(ref["object"].get("type") == "commit" and ref["object"].get("sha") == sha,
                "A different tag appeared during build; draft preserved")
    ref = api.request("GET", ref_path)
    require(ref["object"].get("type") == "commit" and ref["object"].get("sha") == sha,
            "Tag does not point directly to the built commit; draft preserved")
    current = api.request("GET", f"releases/{release_id}")
    require(current.get("draft") is True and current.get("tag_name") == tag,
            "Draft changed during upload; publication refused")
    result = api.request("PATCH", f"releases/{release_id}", {"draft": False, "make_latest": "true"})
    require(result.get("draft") is False and result.get("tag_name") == tag, "Publication not confirmed")
    require(api.request("GET", ref_path)["object"]["sha"] == sha, "Published tag verification failed")
    return result.get("html_url", "")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("metadata", "verify", "publish"))
    parser.add_argument("--directory", type=Path, default=ROOT / "artifacts")
    arguments = parser.parse_args()
    try:
        if arguments.command == "metadata":
            print(metadata()["version"])
            return
        release = verify_assets(arguments.directory, exact_inventory=arguments.command == "publish")
        if arguments.command == "publish":
            sha = trusted_context(os.environ)
            repo = os.environ.get("GITHUB_REPOSITORY", "")
            run_id = os.environ.get("GITHUB_RUN_ID", "")
            require(run_id.isdigit(), "Workflow run ID required")
            api = GitHub(repo, os.environ.get("GITHUB_TOKEN", ""))
            print(publish(api, release, arguments.directory, sha, f"https://github.com/{repo}/actions/runs/{run_id}"))
        else:
            print("Verified five matching release assets and provenance")
    except ReleaseError as error:
        print(str(error), file=sys.stderr)  # Only our bounded, credential-free messages.
        raise SystemExit(1)
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        # Do not print request objects, response bodies or credential-bearing errors.
        print("Release validation/publication failed. Existing releases are unchanged; inspect any new draft.", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    # Direct script execution must also resolve the sibling tools package.
    sys.path.insert(0, str(ROOT))
    main()
