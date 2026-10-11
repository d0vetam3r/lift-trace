"""Verify the real Windows release in isolation, without Python on its PATH.

Uses temporary ports/data and a synthetic OBS owner; never opens the real OBS,
selects a controller, or starts a broadcast. Requires Windows for the helper.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import zipfile


ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        return reservation.getsockname()[1]


def request(port: int, route: str) -> bytes:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        connection.request("GET", route)
        response = connection.getresponse()
        if response.status != 200:
            raise AssertionError(f"{route}: HTTP {response.status}")
        return response.read()
    finally:
        connection.close()


def ready(port: int) -> bool:
    try:
        status = json.loads(request(port, "/api/status"))
        return status.get("app") == "lift-trace" and status.get("apiVersion") == 1
    except (OSError, ValueError, AssertionError):
        return False


def listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def wait_until(predicate, timeout=25) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for the packaged application lifecycle")


def stop(process) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        process.wait(timeout=8)


def verify(archive_path: Path) -> None:
    if os.name != "nt":
        raise RuntimeError("Windows is required for the executable and OBS helper test")
    windows = Path(os.environ["SystemRoot"])
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")}
    env["PATH"] = str(windows / "System32") + os.pathsep + str(windows)
    powershell = windows / "System32/WindowsPowerShell/v1.0/powershell.exe"
    with tempfile.TemporaryDirectory(prefix="lift-trace-windows-smoke-") as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(archive_path) as archive:
            for name in archive.namelist():
                (root / name).resolve().relative_to(root.resolve())
            archive.extractall(root)
        app = root / "LiftTrace"
        exe = app / "LiftTrace.exe"
        helper_path = app / "start-obs-bridge.ps1"
        assert exe.is_file() and helper_path.is_file()
        assert not (app / "data").exists(), "User data must not be bundled"
        assert not (app / "stream_launcher.py").exists()
        assert not (app / "start-obs-extra-services.ps1").exists()

        def spawn(command):
            return subprocess.Popen(command, cwd=app, env=env,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)

        def server(port, data):
            process = spawn([str(exe), "--serve", "--port", str(port), "--data-dir", str(data)])
            try:
                wait_until(lambda: ready(port))
            except BaseException:
                stop(process)
                raise
            return process

        standalone_port = free_port()
        standalone = server(standalone_port, root / "standalone-data")
        try:
            assert json.loads(request(standalone_port, "/api/settings")) == {}
            assert json.loads(request(standalone_port, "/api/status"))["selectedDevice"] is None
            for route in ("/", "/overlay.html", "/app.js", "/i18n.js", "/translations.js", "/setup.js"):
                assert request(standalone_port, route), route
        finally:
            stop(standalone)
        wait_until(lambda: not listening(standalone_port))
        print("PASS: bundled server/assets run with no external Python on PATH")

        for reuse in (False, True):
            port, owner_port = free_port(), free_port()
            while port == owner_port:
                owner_port = free_port()
            data = root / ("reused-data" if reuse else "owned-data")
            existing = owner = helper = None
            try:
                if reuse:
                    existing = server(port, data)
                owner = server(owner_port, root / ("fake-owner-reused" if reuse else "fake-owner-owned"))
                helper = spawn([str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                "-File", str(helper_path), "-Port", str(port), "-DeviceId", "-1",
                                "-ObsProcessId", str(owner.pid), "-DataDir", str(data),
                                "-PythonPath", str(root / "no-python-installed.exe")])
                status_file = data / f"obs-bridge-{owner.pid}-{port}.status"
                wait_until(lambda: status_file.is_file() and status_file.read_text("utf-8") == "ready")
                assert ready(port)
                if reuse:
                    assert helper.wait(timeout=8) == 0
                stop(owner)
                if reuse:
                    assert existing.poll() is None and ready(port)
                    print("PASS: OBS helper preserves a preexisting standalone server")
                else:
                    assert helper.wait(timeout=10) == 0
                    wait_until(lambda: not listening(port))
                    print("PASS: OBS helper uses bundled EXE and stops its server with the owner")
            finally:
                stop(owner)
                if helper is not None and helper.poll() is None:
                    try:
                        helper.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        stop(helper)
                stop(existing)


def main() -> None:
    version = json.loads((ROOT / "package.json").read_text("utf-8"))["version"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", type=Path,
                        default=ROOT / "artifacts" / f"lift-trace-windows-x64-{version}.zip")
    args = parser.parse_args()
    verify(args.archive.resolve())


if __name__ == "__main__":
    main()
