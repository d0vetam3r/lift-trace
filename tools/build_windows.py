"""Build a Windows x64 portable app from the exact allowlisted public source.

Run using a dedicated virtual environment populated by requirements-build.txt.
Build output stays in a fresh directory; no user settings are copied or deleted.
The first build needs HTTPS access to official upstream license files.
"""
from __future__ import annotations

import argparse
import ctypes
import decimal
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import ssl
import struct
import subprocess
import sys
import tempfile
from urllib.request import urlopen
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
import zipfile
import zlib

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.build_release import ROOT, collect_files, read_version, write_release_checksums
from tools.runtime_provenance import verify_runtime
from tools.automation_dependencies import verify_dependencies


def fetch_license(url: str) -> bytes:
    try:
        with urlopen(url, timeout=30) as response:
            data = response.read(512 * 1024 + 1)
    except OSError as error:
        raise RuntimeError(f"Could not fetch upstream license {url}: {error}") from error
    if not 100 <= len(data) <= 512 * 1024 or b"<html" in data[:200].lower():
        raise ValueError(f"Invalid upstream license response: {url}")
    return data


def release_version(value: str, component: str) -> str:
    """Never interpolate an unrecognized runtime version into a source URL."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise RuntimeError(f"Unsupported {component} version for license collection: {value!r}")
    return value


def windows_file_version(path: Path) -> str:
    """Read the actual Tk DLL version without creating a visible Tk window."""
    from ctypes import wintypes

    version = ctypes.WinDLL("version", use_last_error=True)
    version.GetFileVersionInfoSizeW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD))
    version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    version.GetFileVersionInfoW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p)
    version.GetFileVersionInfoW.restype = wintypes.BOOL
    version.VerQueryValueW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR,
                                     ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT))
    version.VerQueryValueW.restype = wintypes.BOOL
    size = version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        raise RuntimeError(f"Cannot read bundled DLL version: {path.name}")
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
        raise ctypes.WinError(ctypes.get_last_error())
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not version.VerQueryValueW(buffer, "\\VarFileInfo\\Translation", ctypes.byref(pointer), ctypes.byref(length)):
        raise RuntimeError(f"Missing DLL version translation: {path.name}")
    translations = ctypes.cast(pointer, ctypes.POINTER(wintypes.WORD))
    pairs = [(translations[index], translations[index + 1]) for index in range(0, length.value // 2 - 1, 2)]
    # Tk's numeric VS_FIXEDFILEINFO uses its release level and serial in the
    # last two fields (e.g. 8,6,2,12), so it is not the semantic patch version.
    for language, code_page in pairs:
        for field in ("ProductVersion", "FileVersion"):
            key = f"\\StringFileInfo\\{language:04x}{code_page:04x}\\{field}"
            if version.VerQueryValueW(buffer, key, ctypes.byref(pointer), ctypes.byref(length)):
                value = ctypes.wstring_at(pointer).strip()
                if re.fullmatch(r"\d+\.\d+\.\d+", value):
                    return value
    raise RuntimeError(f"Missing semantic DLL patch version: {path.name}")


def cpython_reference_versions(contents: bytes) -> dict[str, str]:
    """Parse declarations as references, never as evidence of the local binaries."""
    tree = ET.fromstring(contents)
    result = {}
    for component, property_name, prefix in (("libffi", "libffiDir", "libffi"),
                                              ("liblzma", "lzmaDir", "xz")):
        values = [item.text or "" for item in tree.iter() if item.tag.rsplit("}", 1)[-1] == property_name]
        matches = {match.group(1) for value in values
                   for match in re.finditer(rf"{prefix}-(\d+\.\d+\.\d+)(?:\\|$)", value)}
        if len(matches) != 1:
            raise RuntimeError(f"Cannot establish CPython's declared {component} source version")
        result[component] = matches.pop()
    return result


def require_release_provenance(details: dict, require_verified_runtime: bool) -> None:
    if require_verified_runtime and not details.get("runtimeProvenanceVerified"):
        raise RuntimeError(
            "Runtime provenance check failed: " + details.get("provenance", {}).get("error", "unverified runtime")
            + ". Run tools/prepare_runtime.py and build with its virtual environment. "
              "An ordinary local build may proceed with an unverified-runtime warning.")
    if require_verified_runtime and details.get("automationProvenanceVerified") is False:
        raise RuntimeError("Automation dependency provenance check failed")


def inspect_runtime(base: Path, internal: Path | None = None, dependency_binaries: dict | None = None) -> dict:
    try:
        if dependency_binaries is None:
            return verify_runtime(base, internal)
        return verify_runtime(base, internal, dependency_binaries=dependency_binaries)
    except RuntimeError as error:
        return {"verified": False, "error": str(error)}


def sbom_package(provenance: dict, name: str, version: str | None = None) -> dict:
    packages = [package for package in provenance["sbom"]["packages"]
                if package["name"] == name and (version is None or package.get("versionInfo") == version)]
    if len(packages) != 1:
        raise RuntimeError(f"Official runtime SBOM does not uniquely identify {name} {version or ''}".rstrip())
    return packages[0]


def license_header(contents: bytes, url: str) -> bytes:
    """Retain the complete leading upstream notice, not unrelated C source."""
    match = re.match(rb"\s*(/\*.*?\*/)", contents, re.DOTALL)
    if not match or not any(word in match[1].lower() for word in (b"copyright", b"license", b"public domain")):
        raise RuntimeError(f"Cannot locate upstream copyright/license header: {url}")
    return match[1] + b"\n"


def collect_licenses(target: Path, require_verified_runtime: bool = False) -> dict:
    """Retain dependency terms separately from this project's MIT license."""
    import tkinter

    target.mkdir(parents=True, exist_ok=True)
    base = Path(sys.base_prefix)
    pyinstaller = importlib.metadata.distribution("PyInstaller")
    python_license = base / "LICENSE.txt"
    if not python_license.is_file():
        raise FileNotFoundError("Use an official Windows Python installation with LICENSE.txt")
    pyinstaller_license = next(
        pyinstaller.locate_file(file) for file in pyinstaller.files or []
        if str(file).endswith("licenses/COPYING.txt"))
    tcl = tkinter.Tcl()
    python_version = release_version(platform.python_version(), "Python")
    tcl_version = release_version(tcl.eval("info patchlevel"), "Tcl")
    internal = target.parent / "_internal"
    tk_dlls = list(internal.glob("tk*t.dll"))
    if len(tk_dlls) != 1:
        raise RuntimeError("Expected one bundled Tk DLL to identify its full patch version")
    tk_version = release_version(windows_file_version(tk_dlls[0]), "Tk")
    openssl_version = release_version(ssl.OPENSSL_VERSION.split()[1], "OpenSSL")
    zlib_version = release_version(zlib.ZLIB_RUNTIME_VERSION, "zlib")
    mpdecimal_version = release_version(decimal.__libmpdec_version__, "mpdecimal")
    cpython = f"https://raw.githubusercontent.com/python/cpython/v{python_version}"
    automation = verify_dependencies(ROOT / "artifacts" / "dependency-wheels", internal, target)
    provenance = inspect_runtime(base, internal, automation["bundledFiles"])
    require_release_provenance({"runtimeProvenanceVerified": provenance["verified"], "provenance": provenance},
                               require_verified_runtime)
    reference = None
    if provenance["verified"]:
        if provenance["version"] != python_version:
            raise RuntimeError("Running interpreter version differs from the verified runtime")
        ffi = release_version(sbom_package(provenance, "libffi")["versionInfo"], "libffi")
        xz = release_version(sbom_package(provenance, "xz")["versionInfo"], "XZ")
        # The official SBOM also lists dependency sources for other platforms.
        # Select the observed Windows mpdecimal rather than the first entry.
        sbom_package(provenance, "mpdecimal", mpdecimal_version)
        for name, observed in (("openssl", openssl_version), ("zlib", zlib_version),
                               ("tcl-core", tcl_version + ".0"), ("tk", tk_version + ".0")):
            sbom_package(provenance, name, observed)
        evidence = target.parent / "provenance"
        evidence.mkdir(exist_ok=True)
        sbom_source = base.parent / "downloads" / urlsplit(provenance["sbom"]["url"]).path.rsplit("/", 1)[-1]
        sbom_contents = sbom_source.read_bytes()
        if hashlib.sha256(sbom_contents).hexdigest() != provenance["sbom"]["sha256"]:
            raise RuntimeError("Official runtime SBOM changed after verification")
        (evidence / "python-runtime.spdx.json").write_bytes(sbom_contents)
    else:
        # A custom supplier may rebuild Python with different dependencies.
        # These declarations are retained only as references in local builds.
        reference_url = f"{cpython}/PCbuild/python.props"
        reference_contents = fetch_license(reference_url)
        references = cpython_reference_versions(reference_contents)
        ffi, xz = references["libffi"], references["liblzma"]
        reference = {"url": reference_url, "sha256": hashlib.sha256(reference_contents).hexdigest(),
                     "declaredVersions": references,
                     "scope": "Upstream declarations only; not verified against these binaries"}
    sources = {
        "Python.txt": (python_license.read_bytes(), "https://www.python.org/psf/license/"),
        "PyInstaller.txt": (Path(pyinstaller_license).read_bytes(), "https://pyinstaller.org/en/stable/license.html"),
    }
    sources.update({name: ((target / name).read_bytes(), url)
                    for name, url in automation["licenses"].items()})
    upstream = {
        "Python-incorporated-software.txt": f"{cpython}/Doc/license.rst",
        "Tcl.txt": f"https://raw.githubusercontent.com/tcltk/tcl/core-{tcl_version.replace('.', '-')}/license.terms",
        "Tk.txt": f"https://raw.githubusercontent.com/tcltk/tk/core-{tk_version.replace('.', '-')}/license.terms",
        "Apache-2.0.txt": "https://www.apache.org/licenses/LICENSE-2.0.txt",
        "OpenSSL.txt": f"https://raw.githubusercontent.com/openssl/openssl/openssl-{openssl_version}/LICENSE.txt",
        "zlib.txt": f"https://raw.githubusercontent.com/madler/zlib/v{zlib_version}/LICENSE",
        "CC0-1.0.txt": "https://raw.githubusercontent.com/spdx/license-list-data/v3.29.0/text/CC0-1.0.txt",
    }
    suffix = "" if provenance["verified"] else "-reference"
    if provenance["verified"]:
        deps = "https://raw.githubusercontent.com/python/cpython-source-deps"
        upstream[f"libffi{suffix}.txt"] = f"{deps}/libffi-{ffi}/LICENSE"
        upstream[f"XZ{suffix}.txt"] = f"{deps}/xz-{xz}/COPYING"
        upstream["mpdecimal.txt"] = f"{deps}/mpdecimal-{mpdecimal_version}/COPYRIGHT.txt"
    else:
        upstream[f"libffi{suffix}.txt"] = f"https://raw.githubusercontent.com/libffi/libffi/v{ffi}/LICENSE"
        upstream[f"XZ{suffix}.txt"] = f"https://raw.githubusercontent.com/tukaani-project/xz/v{xz}/COPYING"
    # Expat is not used by the app today. Do not suggest it is bundled just
    # because the build interpreter happens to have pyexpat installed.
    expat_version = None
    if list(internal.glob("pyexpat*.pyd")):
        import pyexpat
        expat_version = release_version(".".join(map(str, pyexpat.version_info)), "Expat")
        if provenance["verified"]:
            sbom_package(provenance, "expat", expat_version)
        upstream["Expat.txt"] = f"https://raw.githubusercontent.com/libexpat/libexpat/R_{expat_version.replace('.', '_')}/expat/COPYING"
    if not provenance["verified"]:
        # Older custom builds use the vendored implementation covered by the
        # CPython appendix. Refuse to silently attach that notice to another one.
        mpdecimal_url = f"{cpython}/Modules/_decimal/libmpdec/mpdecimal.h"
        mpdecimal_header = fetch_license(mpdecimal_url)
        header_version = re.search(rb'#define\s+MPD_VERSION\s+"([0-9.]+)"', mpdecimal_header)
        if not header_version or header_version[1].decode() != mpdecimal_version:
            raise RuntimeError("Bundled mpdecimal version does not match the retained CPython notice provenance")
    # Incorporated hash implementations have notices in their source headers,
    # outside CPython's general license appendix. Preserve those headers intact.
    headers = {
        "HACL-MIT.txt": "Modules/_hacl/Hacl_Hash_MD5.c",
        "KaRaMeL-Apache.txt": "Modules/_hacl/include/krml/internal/target.h",
        "BLAKE2-wrapper.txt": "Modules/_blake2/blake2b_impl.c",
        "BLAKE2-reference.txt": "Modules/_blake2/impl/blake2b-ref.c",
    }
    for name, relative in headers.items():
        url = f"{cpython}/{relative}"
        sources[name] = (license_header(fetch_license(url), url), url)
    for name, url in upstream.items():
        sources[name] = (fetch_license(url), url)
    for name, (contents, _url) in sources.items():
        (target / name).write_bytes(contents)
    return {
        "python": python_version, "pyinstaller": pyinstaller.version,
        "tcl": tcl_version, "tk": tk_version, "openssl": ssl.OPENSSL_VERSION,
        "zlib": zlib_version, "mpdecimal": mpdecimal_version, "expat": expat_version,
        "runtimeProvenanceVerified": provenance["verified"],
        "automationProvenanceVerified": automation["verified"],
        "automationProvenance": automation,
        "unverifiedComponents": [] if provenance["verified"] else ["custom Python distribution"],
        "provenance": provenance,
        "libffi": ffi if provenance["verified"] else None,
        "liblzma": xz if provenance["verified"] else None,
        "referenceBuild": reference,
        "licenseHashes": {name: hashlib.sha256(contents).hexdigest() for name, (contents, _url) in sorted(sources.items())},
        "licenses": {name: url for name, (_contents, url) in sorted(sources.items())},
    }


def write_notices(target: Path, details: dict) -> None:
    licenses = "\n".join(f"- [{name}](licenses/{name}) — {url}" for name, url in details["licenses"].items())
    expat = f" Expat {details['expat']} is also bundled." if details["expat"] else " Expat is not bundled as a separate module."
    if details["runtimeProvenanceVerified"]:
        provenance = details["provenance"]
        status = f"""The extracted Python runtime and packaged Python DLL/PYD files match the pinned
[Python Software Foundation Windows archive]({provenance['archive']['url']})
(SHA-256 `{provenance['archive']['sha256']}`). The matching
[official SBOM](provenance/python-runtime.spdx.json) identifies libffi {details['libffi']}
and XZ/liblzma {details['liblzma']}. Its mpdecimal entry was selected using the
observed runtime version; the SBOM also describes dependencies for other platforms
and tools that are not bundled with this app.

`bundledRuntime.runtimeProvenanceVerified: true` records this distributor and
file-integrity check. It is not a reproducible-build proof, security audit,
application-quality certification, or legal opinion. The manifest retains the
archive/SBOM checksums and the original-to-packaged binary mapping."""
    else:
        declared = details["referenceBuild"]["declaredVersions"]
        status = f"""This local build uses an unverified Python distribution.
`bundledRuntime.runtimeProvenanceVerified: false` records the missing or mismatched
evidence: {details['provenance']['error']}.

CPython's source declares libffi {declared['libffi']} and XZ/liblzma {declared['liblzma']}
in [its Windows build properties]({details['referenceBuild']['url']}). Those are
references, not verified identifications of the supplied binaries.
`libffi-reference.txt` and `XZ-reference.txt` retain the corresponding upstream
texts without claiming a match. Run `tools/prepare_runtime.py` and build using its
virtual environment with `--require-verified-runtime` to verify the pinned official
distribution. This evidence gap does not by itself establish a license violation."""
    contents = f"""# Third-party notices

Lift Trace application source is licensed under MIT; see LICENSE. The bundled
runtime components retain their own licenses. The MIT license does not replace
those terms. No OBS, controller firmware, or iPad remote is bundled.
The app includes one 90 × 20 SCORE reference crop for the tested INFINITAS
1920 × 1080 layout. It contains no full game screenshot or personal settings.

## Runtime provenance

{status}

## Observed components

This build contains Python {details['python']}, Tcl {details['tcl']}, Tk {details['tk']},
{details['openssl']}, zlib {details['zlib']}, mpdecimal {details['mpdecimal']}, and the
PyInstaller {details['pyinstaller']} bootloader/runtime hooks.{expat}
These version values come from the running build interpreter, the bundled Tk DLL,
and installed build-tool metadata. Python.txt includes the PSF license, historical
Python licenses, bzip2/Tcl/Tk notices, and Microsoft runtime redistribution conditions.
Python-incorporated-software.txt retains CPython's broader acknowledgement and
license appendix, including mimalloc, Unicode data, and incorporated-code notices.
Some entries in that upstream appendix describe modules not in this app. The
verified build also includes the matching mpdecimal copyright notice separately.
HACL-MIT.txt and KaRaMeL-Apache.txt retain the hash implementations' notices;
BLAKE2 notices and CC0-1.0.txt retain their public-domain dedication.
PyInstaller.txt
includes its bootloader exception, which permits application distribution under
the application's own license. Apache-2.0.txt also covers PyInstaller runtime hooks
and OpenSSL 3.

Pillow {details['automationProvenance']['packages']['pillow']['version']} and
websocket-client {details['automationProvenance']['packages']['websocket-client']['version']}
are verified separately against SHA-256-pinned official PyPI wheels. Their
installed source files and packaged dependency DLL/PYD bytes are recorded under
`bundledRuntime.automationProvenance`; this does not prove frozen bytecode is a
reproducible build. `licenses/pillow/LICENSE` retains Pillow's complete bundled
third-party notices, and `licenses/websocket-client/LICENSE` retains its terms.
These dependency binaries are excluded from the PSF comparison only by their
individually wheel-verified paths and hashes, never by a directory exemption.

The bundled Windows runtime is supplied only for use on supported Microsoft
Windows systems under the included Microsoft redistribution conditions. No runtime
component has been modified by this project. Keep notices and the manifest with the app.

## Included license texts

{licenses}
"""
    (target / "THIRD_PARTY_NOTICES.md").write_text(contents, encoding="utf-8", newline="\n")


def freeze_environment() -> dict[str, str]:
    """Keep foreign SDK DLLs and Python/Tcl overrides out of dependency discovery."""
    environment = {name: value for name, value in os.environ.items()
                   if name.upper() not in {"PATH", "PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY", "TCLLIBPATH"}}
    windows = next((value for name, value in environment.items() if name.upper() == "SYSTEMROOT"), None)
    if not windows:
        raise RuntimeError("SystemRoot is required for the Windows build environment")
    base = Path(sys.base_prefix)
    environment["PATH"] = os.pathsep.join(map(str, (
        Path(sys.executable).parent, base, base / "DLLs", Path(windows) / "System32", Path(windows))))
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def build_windows(root: Path = ROOT, output_dir: Path | None = None,
                  require_verified_runtime: bool = False) -> Path:
    if os.name != "nt" or struct.calcsize("P") != 8 or platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("Build the Windows x64 app with 64-bit Python on Windows")
    if sys.version_info[:2] not in ((3, 12), (3, 13)):
        raise RuntimeError("Build with 64-bit Python 3.12/3.13; use tools/prepare_runtime.py for verified releases")
    if sys.prefix == sys.base_prefix:
        raise RuntimeError("Use an isolated virtual environment with requirements-build.txt installed")
    preflight = inspect_runtime(Path(sys.base_prefix))
    require_release_provenance({"runtimeProvenanceVerified": preflight["verified"], "provenance": preflight},
                               require_verified_runtime)
    root = root.resolve()
    output = (output_dir or root / "artifacts").resolve()
    output.mkdir(parents=True, exist_ok=True)
    version = read_version(root)
    files = collect_files(root)
    work = Path(tempfile.mkdtemp(prefix="windows-build-", dir=output))
    stage = work / "source"
    for relative, contents in files.items():
        path = stage / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    dist = work / "dist"
    command = [sys.executable, "-I", "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
               "--name", "LiftTrace", "--distpath", str(dist), "--workpath", str(work / "freeze"),
               "--specpath", str(work), "--add-data", f"{stage / 'web'};web",
               "--add-data", f"{stage / 'assets'};assets", "--noupx", "desktop.py"]
    subprocess.run(command, cwd=stage, env=freeze_environment(), check=True)
    app = dist / "LiftTrace"
    # Public documentation only. Runtime sources and build tools remain in the
    # corresponding source ZIP; the binary requires no interpreter installation.
    for relative, contents in files.items():
        if (relative.endswith(".md") or relative.startswith("docs/images/")
                or relative in ("LICENSE", "obs-lift-trace.lua", "start-obs-bridge.ps1")):
            if relative.startswith(".github/"):
                continue
            path = app / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
    details = collect_licenses(app / "licenses", require_verified_runtime=require_verified_runtime)
    write_notices(app, details)
    require_release_provenance(details, require_verified_runtime)
    if details["unverifiedComponents"]:
        print("WARNING: local build uses an unverified runtime; run tools/prepare_runtime.py for release builds.")
    payload = {path.relative_to(app).as_posix(): path.read_bytes() for path in app.rglob("*") if path.is_file()}
    manifest = {"project": "lift-trace", "version": version, "distribution": "windows-x64",
                "applicationLicense": "MIT", "bundledRuntime": details,
                "sourceFiles": {name: hashlib.sha256(contents).hexdigest() for name, contents in sorted(files.items())},
                "files": {name: {"sha256": hashlib.sha256(contents).hexdigest(), "size": len(contents)}
                          for name, contents in sorted(payload.items())}}
    (app / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", "utf-8")
    archive = output / f"lift-trace-windows-x64-{version}.zip"
    temporary = archive.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(app.rglob("*")):
            if path.is_file():
                bundle.write(path, "LiftTrace/" + path.relative_to(app).as_posix())
    with zipfile.ZipFile(temporary) as bundle:
        if bundle.testzip() is not None:
            raise RuntimeError("Windows ZIP verification failed")
    temporary.replace(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", "utf-8")
    write_release_checksums(output, version)
    print(f"Portable app: {app}")
    print(f"Created {archive.name} ({archive.stat().st_size:,} bytes)")
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--require-verified-runtime", action="store_true",
                        help="Require original and packaged runtime files to match the pinned official Python ZIP")
    args = parser.parse_args()
    build_windows(output_dir=args.output_dir, require_verified_runtime=args.require_verified_runtime)


if __name__ == "__main__":
    main()
