"""Prove the two automation dependencies against pinned PyPI Windows wheels.

This checks installed source/binary files before packaging, then packaged binary
bytes separately from CPython. Frozen bytecode is not a reproducible-build proof.
Pillow's complete wheel LICENSE includes its bundled third-party notices.
"""
from __future__ import annotations

import importlib.metadata
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import urlsplit
from urllib.request import urlopen
import zipfile

from tools.runtime_provenance import archive_members, check_file, digest


PIN_PATH = Path(__file__).with_name("automation-dependencies.json")
MAX_WHEEL_BYTES = 32 * 1024 * 1024


def load_pins() -> dict:
    pins = json.loads(PIN_PATH.read_text("utf-8"))
    if set(pins) != {"pillow", "websocket-client"}:
        raise RuntimeError("Unexpected automation dependencies")
    for name, pin in pins.items():
        if not re.fullmatch(r"\d+\.\d+\.\d+", pin["version"]):
            raise RuntimeError("Invalid dependency version")
        if pin["package"] != {"pillow": "PIL", "websocket-client": "websocket"}[name]:
            raise RuntimeError("Invalid dependency package")
        for tag, wheel in pin["wheels"].items():
            url = urlsplit(wheel["url"])
            suffix = "py3-none-any" if tag == "any" else f"{tag}-{tag}-win_amd64"
            filename = f"{name.replace('-', '_')}-{pin['version']}-{suffix}.whl"
            if (tag not in ("any", "cp312", "cp313") or url.scheme != "https"
                    or url.netloc != "files.pythonhosted.org" or url.query or url.fragment
                    or PurePosixPath(url.path).name != filename
                    or not re.fullmatch(r"[0-9a-f]{64}", wheel["sha256"])):
                raise RuntimeError("Invalid official PyPI wheel pin")
    return pins


def wheel_bytes(wheel: dict, cache: Path) -> bytes:
    path = cache / PurePosixPath(urlsplit(wheel["url"]).path).name
    if path.exists():
        return check_file(path, wheel["sha256"])
    with urlopen(wheel["url"], timeout=30) as response:
        if urlsplit(response.geturl()).netloc != "files.pythonhosted.org":
            raise RuntimeError("Wheel download left the official PyPI host")
        contents = response.read(MAX_WHEEL_BYTES + 1)
    if len(contents) > MAX_WHEEL_BYTES or digest(contents) != wheel["sha256"]:
        raise RuntimeError("PyPI wheel checksum mismatch")
    cache.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)
    return contents


def verify_dependencies(cache: Path, internal: Path | None = None,
                        licenses: Path | None = None) -> dict:
    """Fail closed for modified wheels/installations; never install packages.

    Only exact binary paths returned here may be excluded from the independent
    PSF runtime check. Unrecognized DLL/PYD files still fail that check.
    """
    packages, binaries, sources = {}, {}, {}
    tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    for name, pin in load_pins().items():
        wheel = pin["wheels"].get(tag, pin["wheels"].get("any"))
        if wheel is None:
            raise RuntimeError(f"No pinned {name} wheel for {tag}")
        distribution = importlib.metadata.distribution(name)
        if distribution.version != pin["version"]:
            raise RuntimeError(f"Installed {name} version differs from its wheel pin")
        base = Path(distribution.locate_file("")).resolve()
        installed, notices = {}, {}
        with zipfile.ZipFile(BytesIO(wheel_bytes(wheel, cache))) as archive:
            for entry in archive_members(archive):
                if entry.is_dir() or entry.filename.endswith(".dist-info/RECORD"):
                    continue  # pip rewrites RECORD for its generated caches.
                contents = archive.read(entry)
                checksum = digest(contents)
                path = Path(distribution.locate_file(entry.filename))
                if path.is_symlink() or base not in path.resolve().parents:
                    raise RuntimeError(f"Installed dependency escapes its directory: {entry.filename}")
                check_file(path, checksum)
                installed[entry.filename] = checksum
                if path.suffix.lower() in (".dll", ".pyd"):
                    binaries.setdefault((path.name.casefold(), checksum), []).append({
                        "package": name, "source": entry.filename, "sha256": checksum,
                        "wheelSha256": wheel["sha256"],
                    })
                if ".dist-info/licenses/" in entry.filename:
                    # Retain the entire license directory, including all bundled
                    # third-party terms, not just the project's short license.
                    relative = entry.filename.split(".dist-info/licenses/", 1)[1]
                    output = f"{name}/{relative}"
                    notices[output] = checksum
                    sources[output] = wheel["url"] + "#" + entry.filename
                    if licenses is not None:
                        destination = licenses / output
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(contents)
        if not notices:
            raise RuntimeError(f"The pinned {name} wheel has no retained license notices")
        for path in (base / pin["package"]).rglob("*"):
            if path.is_dir():
                continue
            relative = path.relative_to(base)
            if relative.as_posix() not in installed:
                if not path.is_symlink() and "__pycache__" in relative.parts and path.suffix == ".pyc":
                    continue
                raise RuntimeError(f"Unlisted installed dependency file: {relative.as_posix()}")
        packages[name] = {"version": pin["version"], "wheel": wheel,
                          "installedFiles": installed, "licenseHashes": notices}
    bundled = {}
    if internal is not None:
        internal = internal.resolve()
        for path in internal.rglob("*"):
            if path.suffix.lower() not in (".dll", ".pyd"):
                continue
            if path.is_symlink() or internal not in path.resolve().parents:
                raise RuntimeError("Packaged binary escapes its directory")
            candidates = binaries.get((path.name.casefold(), digest(path.read_bytes())), [])
            if candidates:
                bundled[path.relative_to(internal).as_posix()] = candidates[0]
        if not any(item["package"] == "pillow" and "_imaging." in item["source"] for item in bundled.values()):
            raise RuntimeError("Packaged Pillow imaging module does not match the pinned wheel")
    return {"verified": True, "packages": packages, "bundledFiles": bundled, "licenses": sources,
            "scope": "Pinned PyPI wheel bytes, installed source/binary files and packaged dependency DLL/PYD bytes; excludes frozen bytecode reproducibility"}
