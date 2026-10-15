"""Run the real Windows helper against isolated HTTP fixtures, never OBS."""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = r'''
import argparse,json,os,socket,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,HTTPServer
p=argparse.ArgumentParser();p.add_argument('--port',type=int);p.add_argument('--data-dir');a=p.parse_args()
data=Path(a.data_dir);mode=json.loads((data/'fixture-mode.json').read_text())['mode'];calls=[]
state={'available':True,'templateReady':True,'running':mode=='already-running','connected':mode=='already-running',
       'error':'detector-observation-invalid' if mode=='existing-error' else None,
       'config':{'sceneUuid':'scene','captureSourceUuid':'game','targets':[{'sceneItemId':1}]}}
def wait_for_test_release():
 deadline=time.monotonic()+5
 while not (data/'release-response').exists() and time.monotonic()<deadline:time.sleep(.01)
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def reply(self,value,code=200):
  raw=json.dumps(value).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def record(self):
  calls.append(self.command+' '+self.path);tmp=data/'calls.tmp';tmp.write_text(json.dumps(calls));tmp.replace(data/'calls.json')
 def do_GET(self):
  self.record()
  if self.path=='/api/status':self.reply({'app':'lift-trace','apiVersion':1,'nativeSupported':True,'selectedDevice':0,'devices':[]})
  elif self.path=='/api/automation':
   if mode=='owner-exit-before-start' and state['connected']:wait_for_test_release()
   self.reply(state)
  elif self.path=='/api/settings':self.reply({})
  else:self.reply({},404)
 def do_POST(self):
  self.rfile.read(int(self.headers.get('Content-Length','0')));self.record()
  if self.path=='/api/automation/connect':
   if mode=='delayed-success':time.sleep(3.25)
   if mode in ('owner-exit-connect','owner-exit-connect-failure'):wait_for_test_release()
   if mode in ('connect-failure','owner-exit-connect-failure'):
    state['error']='obs-connect-failed';self.reply({'code':'obs-connect-failed','status':state},400)
   else:
    state['connected']=True;state['error']=None;self.reply({'status':state})
  elif self.path=='/api/automation/start':
   if mode=='delayed-success':time.sleep(3.25)
   if mode=='start-failure':self.reply({'code':'template-invalid','status':state},400)
   else:
    state['running']=True
    if mode=='lost-start-response':
     self.connection.shutdown(socket.SHUT_RDWR);self.connection.close()
    else:self.reply({'status':state})
  elif self.path=='/api/automation/stop':state['running']=False;self.reply({'status':state})
  else:self.reply({'ok':True})
server=HTTPServer(('127.0.0.1',a.port),Handler);(data/'fixture.pid').write_text(str(os.getpid()));server.serve_forever()
'''


@unittest.skipUnless(os.name == "nt", "The OBS bridge helper runs on Windows")
class BridgeAutostartTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lifttrace-autostart-")
        self.root = Path(self.temporary.name).resolve()
        self.data = self.root / "data"
        self.data.mkdir()
        shutil.copy2(ROOT / "start-obs-bridge.ps1", self.root / "start-obs-bridge.ps1")
        (self.root / "server.py").write_text(FIXTURE, encoding="utf-8")
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            self.port = reservation.getsockname()[1]
        self.processes = []
        self.owner = self.spawn([sys.executable, "-c", "import time; time.sleep(300)"])
        self.helper = None

    def spawn(self, command):
        process = subprocess.Popen(command, cwd=self.root, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        self.processes.append(process)
        return process

    def request(self, path="/api/status", *, post=False):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=1)
        try:
            connection.request("POST" if post else "GET", path, body="{}" if post else None,
                               headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            return json.loads(response.read())
        finally:
            connection.close()

    def calls(self):
        try:
            return json.loads((self.data / "calls.json").read_text())
        except (OSError, ValueError):
            return []

    def wait_for(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if predicate():
                    return
            except (OSError, ValueError, http.client.HTTPException):
                pass
            time.sleep(0.05)
        self.fail("Fixture did not reach the expected state")

    def begin(self, mode="normal", *, enabled=True, existing=False):
        (self.data / "fixture-mode.json").write_text(json.dumps({"mode": mode}))
        (self.data / "obs-automation-autostart.json").write_text(json.dumps({"enabled": enabled}))
        standalone = None
        if existing:
            standalone = self.spawn([sys.executable, str(self.root / "server.py"), "--port", str(self.port),
                                     "--data-dir", str(self.data)])
            self.wait_for(lambda: self.request()["app"] == "lift-trace")
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        self.helper = self.spawn([str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                 "-File", str(self.root / "start-obs-bridge.ps1"), "-PythonPath", sys.executable,
                                 "-Port", str(self.port), "-DeviceId", "-1", "-ObsProcessId", str(self.owner.pid),
                                 "-DataDir", str(self.data)])
        status = self.data / f"obs-bridge-{self.owner.pid}-{self.port}.status"
        self.wait_for(lambda: status.exists() and status.read_text() == "ready")
        return standalone

    def assert_owned_shutdown(self):
        self.assertEqual(self.request()["app"], "lift-trace")
        self.owner.terminate()
        self.owner.wait(timeout=3)
        self.assertEqual(self.helper.wait(timeout=6), 0)
        with self.assertRaises((OSError, http.client.HTTPException)):
            self.request()

    def test_new_owned_backend_connects_and_starts_once_and_respects_manual_stop(self):
        self.begin()
        self.wait_for(lambda: self.request("/api/automation")["running"])
        self.assertEqual(self.calls().count("POST /api/automation/connect"), 1)
        self.assertEqual(self.calls().count("POST /api/automation/start"), 1)
        self.request("/api/automation/stop", post=True)
        time.sleep(1.1)
        self.assertFalse(self.request("/api/automation")["running"])
        self.assertEqual(self.calls().count("POST /api/automation/start"), 1)
        self.assert_owned_shutdown()

    def test_disabled_preference_keeps_fresh_install_manual(self):
        self.begin(enabled=False)
        time.sleep(0.25)
        self.assertFalse(any("/api/automation" in call for call in self.calls()))
        self.assert_owned_shutdown()

    def test_delayed_connection_and_start_responses_complete_once(self):
        self.begin("delayed-success")
        self.wait_for(lambda: "POST /api/automation/start" in self.calls())
        time.sleep(3.5)
        self.assertTrue(self.request("/api/automation")["running"])
        self.assertEqual(self.calls().count("POST /api/automation/connect"), 1)
        self.assertEqual(self.calls().count("POST /api/automation/start"), 1)
        self.assertFalse((self.data / f"obs-automation-{self.port}.log").exists())
        self.assert_owned_shutdown()

    def test_existing_standalone_is_neither_armed_nor_stopped(self):
        standalone = self.begin(existing=True)
        self.assertEqual(self.helper.wait(timeout=5), 0)
        self.owner.terminate(); self.owner.wait(timeout=3)
        self.assertIsNone(standalone.poll())
        self.assertFalse(any("/api/automation" in call for call in self.calls()))
        self.assertEqual(self.request()["app"], "lift-trace")

    def test_already_running_backend_is_not_reconnected_or_started(self):
        self.begin("already-running")
        self.wait_for(lambda: "GET /api/automation" in self.calls())
        time.sleep(0.2)
        self.assertFalse(any(call.startswith("POST /api/automation/") for call in self.calls()))
        self.assert_owned_shutdown()

    def test_existing_automation_error_is_not_cleared(self):
        self.begin("existing-error")
        self.wait_for(lambda: "GET /api/automation" in self.calls())
        time.sleep(0.2)
        self.assertFalse(any(call.startswith("POST /api/automation/") for call in self.calls()))
        self.assertEqual(self.request("/api/automation")["error"], "detector-observation-invalid")
        self.assert_owned_shutdown()

    def test_connection_failure_is_bounded_and_preserves_input_and_ownership(self):
        self.begin("connect-failure")
        self.wait_for(lambda: (self.data / f"obs-automation-{self.port}.log").exists())
        self.assertEqual(self.calls().count("POST /api/automation/connect"), 3)
        self.assertNotIn("POST /api/automation/start", self.calls())
        self.assert_owned_shutdown()

    def test_lost_start_response_is_not_retried_and_input_remains_available(self):
        self.begin("lost-start-response")
        self.wait_for(lambda: (self.data / f"obs-automation-{self.port}.log").exists())
        time.sleep(1.1)
        self.assertEqual(self.calls().count("POST /api/automation/start"), 1)
        self.assert_owned_shutdown()

    def check_owner_exit_during_autostart(self, mode, waiting_for):
        self.begin(mode)
        self.wait_for(lambda: self.calls().count(waiting_for) >=
                      (2 if mode == "owner-exit-before-start" else 1))
        self.owner.terminate()
        self.owner.wait(timeout=3)
        # Release the exact outstanding response after the owner is gone, so
        # this regression does not depend on racing a fixed-duration sleep.
        (self.data / "release-response").touch()
        self.assertEqual(self.helper.wait(timeout=6), 0)
        self.assertEqual(self.calls().count("POST /api/automation/connect"), 1)
        self.assertNotIn("POST /api/automation/start", self.calls())
        with self.assertRaises((OSError, http.client.HTTPException)):
            self.request()

    def test_owner_exit_during_connect_prevents_start_and_keeps_owned_cleanup(self):
        self.check_owner_exit_during_autostart("owner-exit-connect", "POST /api/automation/connect")

    def test_owner_exit_during_failed_connect_prevents_retry(self):
        self.check_owner_exit_during_autostart("owner-exit-connect-failure", "POST /api/automation/connect")

    def test_owner_exit_during_final_status_read_prevents_start(self):
        self.check_owner_exit_during_autostart("owner-exit-before-start", "GET /api/automation")

    def tearDown(self):
        if self.owner.poll() is None:
            self.owner.terminate()
            self.owner.wait(timeout=3)
        if self.helper is not None and self.helper.poll() is None:
            try:
                self.helper.wait(timeout=7)
            except subprocess.TimeoutExpired:
                self.helper.terminate()
        for process in reversed(self.processes):
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=3)
        # The temporary fixture directory is the sole cleanup target.
        self.assertEqual(self.root, Path(self.temporary.name).absolute())
        self.temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
