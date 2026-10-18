"""Build the overlay-only public source archive with Python's standard library.

Only the explicit file lists below are distributed. Local settings, recordings,
optional integrations, installed dependencies, and unrelated files are never
discovered by globbing the working directory. No Python or OBS binary is bundled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile


ROOT = Path(__file__).resolve().parent.parent
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

# Private development trees may supply an overlay-only helper override.
# Normal public checkouts use the helper at the repository root.
PUBLIC_RUNTIME_OVERRIDES = {
    "start-obs-bridge.ps1": "distribution/start-obs-bridge.ps1",
}

RUNTIME_FILES = (
    "LICENSE",
    "server.py",
    "native_input.py",
    "auto_visibility.py",
    "automation.py",
    "obs_connection.py",
    "infinitas_detector.py",
    "assets/infinitas-score-1080p.png",
    "desktop.py",
    "start.bat",
    "start.sh",
    "obs-lift-trace.lua",
    "start-obs-bridge.ps1",
    "web/app.js",
    "web/automation.js",
    "web/client.js",
    "web/demo.json",
    "web/engine.js",
    "web/games/infinitas.js",
    "web/i18n.js",
    "web/index.html",
    "web/overlay.html",
    "web/overlay.js",
    "web/render.js",
    "web/style.css",
    "web/setup.js",
    "web/settings-writer.js",
    "web/short-input-controls.js",
    "web/short-input-preview.js",
    "web/translations.js",
)

DOCUMENTATION_FILES = (
    "README.md",
    "README.ko.md",
    "README.en.md",
    "README.ja.md",
    "CHANGELOG.md",
    "CHANGELOG.ja.md",
    "CHANGELOG.en.md",
    "CONTRIBUTING.md",
    "CONTRIBUTING.ja.md",
    "CONTRIBUTING.en.md",
    "SECURITY.md",
    "SECURITY.ja.md",
    "SECURITY.en.md",
    "docs/DEVELOPMENT.md",
    "docs/DEVELOPMENT.ja.md",
    "docs/DEVELOPMENT.en.md",
    "docs/USER_GUIDE.en.md",
    "docs/USER_GUIDE.ko.md",
    "docs/USER_GUIDE.ja.md",
    "docs/REFERENCE.md",
    "docs/REFERENCE.ja.md",
    "docs/REFERENCE.en.md",
    "docs/RELEASING.md",
    "docs/RELEASING.ja.md",
    "docs/RELEASING.en.md",
    "docs/VALIDATION.md",
    "docs/VALIDATION.ja.md",
    "docs/VALIDATION.en.md",
    "docs/releases/0.2.0.md",
    "docs/images/lane-layout.svg",
    "docs/images/lift-trace-demo.gif",
    "docs/images/README.md",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/feature_request.md",
)

SOURCE_FILES = (
    # Developer-only pacing prototype; never part of RUNTIME_FILES.
    "experiments/obs-native-pacing/CMakeLists.txt",
    "experiments/obs-native-pacing/README.md",
    "experiments/obs-native-pacing/README.ko.md",
    "experiments/obs-native-pacing/README.ja.md",
    "experiments/obs-native-pacing/RESULTS.md",
    "experiments/obs-native-pacing/lift-native-pacing.c",
    "experiments/obs-native-pacing/live-protocol.h",
    "experiments/obs-native-pacing/live-geometry-test.c",
    "experiments/obs-native-pacing/live-geometry-vectors.mjs",
    "experiments/obs-native-pacing/check-live-geometry.py",
    "experiments/obs-native-pacing/live-input.mjs",
    "experiments/obs-native-pacing/live-input.test.mjs",
    "experiments/obs-native-pacing/live_bridge.py",
    "experiments/obs-native-pacing/live_launcher.py",
    "experiments/obs-native-pacing/test_live_transport.py",
    "experiments/obs-native-pacing/test_live_layout.py",
    "experiments/obs-native-pacing/native-layout-mock.lua",
    "experiments/obs-native-pacing/obs-native-layout.lua",
    "experiments/obs-native-pacing/live-control.lua",
    "experiments/obs-native-pacing/pacing-geometry.h",
    "experiments/obs-native-pacing/pacing-control.lua",
    "experiments/obs-native-pacing/geometry-test.c",
    "experiments/obs-native-pacing/geometry-vectors.mjs",
    "experiments/obs-native-pacing/check-geometry.py",
    "experiments/obs-native-pacing/generate-browser.mjs",
    "experiments/obs-native-pacing/analysis/analyze_native_pacing.py",
    "experiments/obs-native-pacing/analysis/barcode_analysis.py",
    "experiments/obs-native-pacing/analysis/README.md",
    ".gitignore",
    "package.json",
    "tools/build_release.py",
    "tools/build_windows.py",
    "tools/prepare_runtime.py",
    "tools/runtime_provenance.py",
    "tools/automation_dependencies.py",
    "tools/automation-dependencies.json",
    "tools/python-runtime.json",
    "tools/smoke_windows.py",
    "tools/render_readme_demo.mjs",
    "tools/replay_visibility.py",
    "tools/verify_release.py",
    "requirements-build.txt",
    "requirements-automation.txt",
    ".github/workflows/verify.yml",
    ".github/workflows/release.yml",
    ".github/release-intent",
    "tests/client.test.mjs",
    "tests/automation.test.mjs",
    "tests/engine.test.mjs",
    "tests/i18n.test.mjs",
    "tests/setup.test.mjs",
    "tests/render.test.mjs",
    "tests/settings-writer.test.mjs",
    "tests/short-input-controls.test.mjs",
    "tests/short-input-preview.test.mjs",
    "tests/test_native_input.py",
    "tests/test_server.py",
    "tests/test_release.py",
    "tests/test_build_windows.py",
    "tests/test_runtime_provenance.py",
    "tests/test_automation_dependencies.py",
    "tests/test_desktop.py",
    "tests/test_auto_visibility.py",
    "tests/test_automation.py",
    "tests/test_native_automation.py",
    "tests/test_obs_connection.py",
    "tests/test_obs_bridge_autostart.py",
    "tests/test_infinitas_detector.py",
    "tests/test_verify_release.py",
)


def sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _read_file(root: Path, relative: str) -> bytes:
    """Do not let a symlink replace an allowlisted source with an external file."""
    target = root / relative
    for part in (target, *target.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ValueError(f"Release input must not be a symlink: {relative}")
    target.resolve().relative_to(root.resolve())
    if not target.is_file():
        raise FileNotFoundError(f"Required release input is missing: {target}")
    return target.read_bytes()


def read_version(root: Path) -> str:
    version = json.loads(_read_file(root, "package.json"))["version"]
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version):
        raise ValueError("package.json must contain a valid release version")
    return version


def collect_files(root: Path) -> dict[str, bytes]:
    """Map public archive paths to bytes, flattening explicit staging directories.

    Development checkout: documentation lives in docs/public/ so the user's
    existing local README can remain separate. Extracted source distribution:
    the same public documents already live at the release root. A local
    distribution/ directory supplies the overlay-only helper; extracted public
    sources already contain that helper at their root and need no override.
    """
    root = Path(root).resolve()
    names = RUNTIME_FILES + SOURCE_FILES
    overrides = PUBLIC_RUNTIME_OVERRIDES if (root / "distribution").is_dir() else {}
    files = {name: _read_file(root, overrides.get(name, name)) for name in names}
    staged_docs = root / "docs" / "public"
    docs_prefix = "docs/public/" if staged_docs.is_dir() else ""
    for name in DOCUMENTATION_FILES:
        if name in files:
            raise ValueError(f"Duplicate release path: {name}")
        files[name] = _read_file(root, docs_prefix + name)
    return files


def create_archive(path: Path, files: dict[str, bytes], version: str) -> None:
    """Write stable ZIP metadata and a manifest of every payload file.

    MANIFEST.json deliberately does not hash itself. ZIP checksums are written
    beside the archives, covering both payload and manifest.
    """
    manifest = {
        "project": "lift-trace",
        "version": version,
        "distribution": "source",
        "license": "MIT",
        "files": {
            name: {"sha256": sha256(contents), "size": len(contents)}
            for name, contents in sorted(files.items())
        },
    }
    archive_files = {**files, "MANIFEST.json": (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, contents in sorted(archive_files.items()):
                info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o100755 if name == "start.sh" else 0o100644) << 16
                archive.writestr(info, contents, compresslevel=9)
        with zipfile.ZipFile(temporary) as archive:
            damaged = archive.testzip()
            if damaged is not None:
                raise ValueError(f"ZIP integrity check failed: {damaged}")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def build_release(root: Path = ROOT, output_dir: Path | None = None) -> Path:
    root = Path(root).resolve()
    output_dir = Path(output_dir).resolve() if output_dir is not None else root / "artifacts"
    version = read_version(root)
    # Validate and read the complete payload before creating any output.
    files = collect_files(root)
    path = output_dir / f"lift-trace-source-{version}.zip"
    create_archive(path, files, version)
    checksum_line = f"{sha256(path.read_bytes())}  {path.name}\n"
    path.with_suffix(path.suffix + ".sha256").write_text(checksum_line, encoding="utf-8", newline="\n")
    write_release_checksums(output_dir, version)
    return path


def write_release_checksums(output_dir: Path, version: str) -> None:
    """List the matching source and Windows archives that have been built."""
    lines = []
    for name in (f"lift-trace-source-{version}.zip", f"lift-trace-windows-x64-{version}.zip"):
        path = output_dir / name
        if path.is_file():
            lines.append(f"{sha256(path.read_bytes())}  {name}\n")
    (output_dir / "SHA256SUMS").write_text("".join(lines), encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the overlay-only public source ZIP (standard library only).")
    parser.add_argument("--output-dir", type=Path, help="Archive directory (default: artifacts/ beside the project)")
    args = parser.parse_args()
    path = build_release(output_dir=args.output_dir)
    print(f"Created {path.name} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
