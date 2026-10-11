"""Check a pinned PSF Windows distribution and the binaries copied from it.

This records distributor provenance. It is not a reproducible-build proof,
malware scan, legal opinion, or certification of the application's quality.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
from urllib.parse import urlsplit
import zipfile


PIN_PATH = Path(__file__).with_name("python-runtime.json")


def load_pin() -> dict:
    pin = json.loads(PIN_PATH.read_text("utf-8"))
    if not re.fullmatch(r"\d+\.\d+\.\d+", pin["version"]) or pin["architecture"] != "amd64":
        raise RuntimeError("Invalid Windows runtime pin")
    for key in ("archive", "sbom", "manifest"):
        url = urlsplit(pin[key]["url"])
        if (url.scheme != "https" or url.netloc != "www.python.org"
                or not url.path.startswith(f"/ftp/python/{pin['version']}/")
                or not re.fullmatch(r"[0-9a-f]{64}", pin[key]["sha256"])):
            raise RuntimeError(f"Invalid official runtime {key} pin")
    return pin


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_file(path: Path, expected: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"Missing regular runtime evidence file: {path.name}")
    contents = path.read_bytes()
    if digest(contents) != expected:
        raise RuntimeError(f"Runtime checksum mismatch: {path.name}")
    return contents


def evidence_paths(base: Path, pin: dict) -> dict[str, Path]:
    return {key: base.parent / "downloads" / urlsplit(pin[key]["url"]).path.rsplit("/", 1)[-1]
            for key in ("archive", "sbom", "manifest")}


def archive_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Reject ambiguous or escaping Windows ZIP names before extracting anything."""
    entries, seen = [], set()
    for entry in archive.infolist():
        name = entry.filename
        parts = name.rstrip("/").split("/")
        if (not parts or name.startswith("/") or "\\" in name or ":" in name
                or any(part in ("", ".", "..") or part.endswith((" ", ".")) for part in parts)
                or stat.S_ISLNK(entry.external_attr >> 16)):
            raise RuntimeError(f"Unsafe runtime ZIP member: {name}")
        canonical = name.rstrip("/").casefold()
        if canonical in seen:
            raise RuntimeError(f"Duplicate runtime ZIP member: {name}")
        seen.add(canonical)
        entries.append(entry)
    return entries


def checked_metadata(base: Path, pin: dict) -> tuple[dict, dict[str, Path]]:
    paths = evidence_paths(base, pin)
    for key, path in paths.items():
        check_file(path, pin[key]["sha256"])
    sbom = json.loads(paths["sbom"].read_text("utf-8"))
    manifest = json.loads(paths["manifest"].read_text("utf-8"))
    packages = [p for p in sbom.get("packages", []) if p.get("name") == "CPython"]
    if len(packages) != 1:
        raise RuntimeError("Official SBOM must identify one CPython package")
    package = packages[0]
    if (package.get("versionInfo") != pin["version"]
            or package.get("downloadLocation") != pin["archive"]["url"]
            or {"algorithm": "SHA256", "checksumValue": pin["archive"]["sha256"]} not in package.get("checksums", [])):
        raise RuntimeError("Official SBOM does not identify the pinned runtime archive")
    entries = [item for item in manifest.get("versions", [])
               if item.get("url") == pin["archive"]["url"]]
    if (len(entries) != 1 or entries[0].get("sort-version") != pin["version"]
            or entries[0].get("hash", {}).get("sha256") != pin["archive"]["sha256"]):
        raise RuntimeError("Official Windows manifest does not identify the pinned archive")
    return sbom, paths


def verify_runtime(base: Path, internal: Path | None = None, *, pin: dict | None = None) -> dict:
    """Verify the extracted originals and every packaged DLL/PYD against that ZIP.

    Added Python bytecode caches are ignored. Generated application
    bytecode and the PyInstaller bootloader are outside this runtime check.
    """
    pin = load_pin() if pin is None else pin
    base = Path(base).resolve()
    sbom, paths = checked_metadata(base, pin)
    original = {}
    with zipfile.ZipFile(paths["archive"]) as archive:
        for entry in archive_members(archive):
            if entry.is_dir():
                continue
            expected = digest(archive.read(entry))
            target = base / entry.filename
            if target.is_symlink() or base not in target.resolve().parents:
                raise RuntimeError(f"Runtime file escapes its directory: {entry.filename}")
            check_file(target, expected)
            original[entry.filename] = expected
    for path in base.rglob("*"):
        if path.is_dir():
            continue
        relative = path.relative_to(base)
        if relative.as_posix() not in original:
            if not path.is_symlink() and "__pycache__" in relative.parts and path.suffix == ".pyc":
                continue
            raise RuntimeError(f"Unlisted file in official runtime: {relative.as_posix()}")
    bundled = {}
    if internal is not None:
        internal = Path(internal).resolve()
        by_hash = {}
        for name, sha256 in original.items():
            by_hash.setdefault(sha256, []).append(name)
        binaries = [path for path in internal.rglob("*") if path.suffix.lower() in (".dll", ".pyd")]
        if not binaries:
            raise RuntimeError("No packaged runtime binaries to verify")
        for path in binaries:
            if path.is_symlink() or internal not in path.resolve().parents:
                raise RuntimeError(f"Packaged binary escapes its directory: {path.name}")
            checksum = digest(path.read_bytes())
            candidates = [name for name in by_hash.get(checksum, [])
                          if PurePosixPath(name).name.casefold() == path.name.casefold()]
            if not candidates:
                raise RuntimeError(f"Packaged binary differs from the official runtime: {path.name}")
            bundled[path.relative_to(internal).as_posix()] = {"source": sorted(candidates)[0], "sha256": checksum}
        names = {Path(name).name.casefold() for name in bundled}
        if "libffi-8.dll" not in names or "_lzma.pyd" not in names:
            raise RuntimeError("Expected libffi and liblzma runtime binaries are missing")
    return {"verified": True, "version": pin["version"], "supplier": "Python Software Foundation",
            "archive": pin["archive"], "manifest": pin["manifest"],
            "sbom": {**pin["sbom"], "packages": sbom["packages"]},
            "runtimeFiles": original, "bundledFiles": bundled,
            "scope": "Pinned official distribution, extracted original files, and packaged DLL/PYD bytes; not an application quality or security certification"}
