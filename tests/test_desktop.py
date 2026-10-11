import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from desktop import ServerSession, StartupError, healthy_server, prepare_data_dir


class DesktopTests(unittest.TestCase):
    def setUp(self):
        # Lifecycle tests must not scan the developer's real controllers.
        native_patch = patch("server.NativeInput")
        native = native_patch.start().return_value
        self.addCleanup(native_patch.stop)
        native.supported = False
        native.scan.return_value = []
        native.poll.return_value = None
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data = Path(self.temporary.name) / "data"

    def session(self, port=0):
        session = ServerSession(port, self.data)
        self.addCleanup(session.close)
        return session

    def test_owned_server_serves_resources_and_stops(self):
        session = self.session()
        session.start(allow_reuse=False)
        self.assertTrue(healthy_server(session.port))
        connection = http.client.HTTPConnection("127.0.0.1", session.port, timeout=2)
        connection.request("GET", "/")
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertIn(b"Lift", response.read())
        connection.close()
        session.close()
        self.assertFalse(healthy_server(session.port))

    def test_reuse_never_stops_existing_server(self):
        original = self.session()
        original.start(allow_reuse=False)
        reused = self.session(original.port)
        reused.start()
        self.assertTrue(reused.reused)
        self.assertIsNone(reused.server)
        reused.close()
        self.assertTrue(healthy_server(original.port))

    def test_headless_refuses_existing_server(self):
        original = self.session()
        original.start(allow_reuse=False)
        other = self.session(original.port)
        with self.assertRaises(StartupError):
            other.start(allow_reuse=False)
        self.assertTrue(healthy_server(original.port))

    def test_unrelated_server_is_not_reused_or_stopped(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                payload = json.dumps({"nativeSupported": True, "devices": [], "selectedDevice": None}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        other = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=other.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        self.addCleanup(other.server_close)
        self.addCleanup(other.shutdown)
        self.assertFalse(healthy_server(other.server_port))
        session = self.session(other.server_port)
        with self.assertRaises(StartupError) as error:
            session.start()
        self.assertEqual(error.exception.key, "port")
        self.assertTrue(thread.is_alive())

    def test_unwritable_data_has_actionable_error(self):
        with patch("desktop.tempfile.TemporaryFile", side_effect=PermissionError("denied")):
            with self.assertRaises(StartupError) as error:
                prepare_data_dir(self.data)
        self.assertEqual(error.exception.key, "data")
        self.assertEqual(error.exception.values["path"], str(self.data))

    def test_reuse_does_not_require_writing_other_server_data(self):
        original = self.session()
        original.start(allow_reuse=False)
        reused = self.session(original.port)
        with patch("desktop.prepare_data_dir", side_effect=StartupError("data", path="unwritable")):
            reused.start()
        self.assertTrue(reused.reused)


if __name__ == "__main__":
    unittest.main()
