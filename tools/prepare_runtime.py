"""Prepare the pinned official Windows Python in a local folder, without installing it.

Does not change PATH, file associations, registry entries, or the system Python.
Run this with an existing Python, then use the resulting python/python.exe to
create the release build virtual environment.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from urllib.parse import urlsplit
from urllib.request import urlopen
import zipfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.runtime_provenance import archive_members, check_file, checked_metadata, evidence_paths, load_pin, verify_runtime


def prepare(output: Path) -> Path:
    pin = load_pin()
    output = output.resolve()
    base = output / "python"
    downloads = output / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    paths = evidence_paths(base, pin)
    for key, path in paths.items():
        if not path.exists():
            temporary = path.with_suffix(path.suffix + ".partial")
            try:
                with urlopen(pin[key]["url"], timeout=60) as response, temporary.open("wb") as target:
                    final = urlsplit(response.geturl())
                    if final.scheme != "https" or final.netloc != "www.python.org":
                        raise RuntimeError("Runtime download redirected outside python.org")
                    while chunk := response.read(1024 * 1024):
                        target.write(chunk)
                check_file(temporary, pin[key]["sha256"])
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        check_file(path, pin[key]["sha256"])
    checked_metadata(base, pin)
    if base.exists():
        verify_runtime(base)
        print(f"Verified existing official runtime: {base / 'python.exe'}")
        return base
    with zipfile.ZipFile(paths["archive"]) as archive:
        entries = archive_members(archive)
        base.mkdir()
        for entry in entries:
            archive.extract(entry, base)
    result = verify_runtime(base)
    print(f"Prepared official Python {result['version']}: {base / 'python.exe'}")
    print(f"Verified {len(result['runtimeFiles'])} original files against the pinned official ZIP and SBOM.")
    return base


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/python-runtime"))
    args = parser.parse_args()
    prepare(args.output_dir)


if __name__ == "__main__":
    main()
