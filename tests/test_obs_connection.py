"""Protocol and cancellation checks using in-memory WebSockets, never live OBS."""
from __future__ import annotations

import base64
import hashlib
import json
import queue
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import obs_connection
from obs_connection import ObsConnection, ObsConnectionError, ObsRequestError


class FakeSocket:
    def __init__(self, *, authentication=None):
        self.messages = queue.Queue()
        hello = {"rpcVersion": 1}
        if authentication is not None:
            hello["authentication"] = authentication
        self.put(0, hello)
        self.timeout = 0.5
        self.closed = threading.Event()
        self.sent = []
        self.on_request = self.acknowledge
        self.upgrade_status = 101

    def getstatus(self):
        return self.upgrade_status

    def settimeout(self, value):
        self.timeout = value

    def put(self, op, data):
        self.messages.put(json.dumps({"op": op, "d": data}))

    def acknowledge(self, request, *, result=True, code=100, data=None):
        self.put(7, {"requestType": request["requestType"], "requestId": request["requestId"],
                     "requestStatus": {"result": result, "code": code}, "responseData": data or {}})

    def send(self, raw):
        if self.closed.is_set():
            raise OSError("closed")
        message = json.loads(raw)
        self.sent.append(message)
        if message["op"] == 1:
            self.put(2, {"negotiatedRpcVersion": 1})
        elif message["op"] == 6:
            self.on_request(message["d"])

    def recv(self):
        if self.closed.is_set():
            return ""
        try:
            return self.messages.get(timeout=self.timeout)
        except queue.Empty:
            raise TimeoutError from None

    def abort(self):
        self.closed.set()
        self.messages.put("")

    def shutdown(self):
        self.abort()


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.socket = FakeSocket()
        self.factory_calls = []

        def factory(url, **options):
            self.factory_calls.append((url, options))
            return self.socket

        self.module = SimpleNamespace(create_connection=factory, WebSocketTimeoutException=TimeoutError)
        self.patch = patch.object(obs_connection, "_websocket_module", return_value=self.module)
        self.patch.start()
        self.connection = ObsConnection(4455, "test-password", timeout=0.3)
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.connection.close)

    def connect(self):
        self.connection.connect()
        self.assertTrue(self.connection.connected)

    def test_loopback_no_proxy_no_redirect_and_acknowledged_data(self):
        self.connect()
        self.socket.on_request = lambda request: self.socket.acknowledge(request, data={"ok": 1})
        self.assertEqual(self.connection.request("GetVersion"), {"ok": 1})
        url, options = self.factory_calls[0]
        self.assertEqual(url, "ws://127.0.0.1:4455")
        self.assertEqual(options["http_no_proxy"], ["127.0.0.1"])
        self.assertEqual(options["redirect_limit"], 0)
        self.assertTrue(options["enable_multithread"])
        self.assertEqual(self.socket.sent[0], {"op": 1, "d": {"rpcVersion": 1, "eventSubscriptions": 3}})

    def test_v5_authentication_uses_salt_then_challenge_without_sending_password(self):
        self.socket = FakeSocket(authentication={"salt": "test-salt", "challenge": "test-challenge"})
        self.connect()
        secret = base64.b64encode(hashlib.sha256(b"test-passwordtest-salt").digest())
        expected = base64.b64encode(hashlib.sha256(secret + b"test-challenge").digest()).decode()
        self.assertEqual(self.socket.sent[0]["d"]["authentication"], expected)
        self.assertNotIn("test-password", json.dumps(self.socket.sent))

    def test_redirect_response_is_rejected_without_identification(self):
        self.socket.upgrade_status = 302
        with self.assertRaises(ObsConnectionError):
            self.connection.connect()
        self.assertEqual(self.socket.sent, [])
        self.assertTrue(self.socket.closed.is_set())

    def test_idle_collection_change_invalidates_and_prevents_later_writes(self):
        self.connect()
        self.socket.put(5, {"eventType": "CurrentSceneCollectionChanging"})
        self.assertTrue(self.socket.closed.wait(0.5))
        self.assertFalse(self.connection.connected)
        with self.assertRaises(ObsConnectionError):
            self.connection.request("SetSceneItemEnabled", {"sceneItemId": 2, "sceneItemEnabled": True})
        self.assertEqual(len(self.socket.sent), 1)

    def test_collection_change_during_request_rejects_even_a_later_success_ack(self):
        self.connect()

        def changing(request):
            self.socket.put(5, {"eventType": "CurrentSceneCollectionChanged"})
            self.socket.acknowledge(request)

        self.socket.on_request = changing
        with self.assertRaises(ObsConnectionError):
            self.connection.request("GetSceneItemList")
        self.assertFalse(self.connection.connected)

    def test_events_and_unrelated_responses_do_not_count_as_acknowledgement(self):
        self.connect()

        def interleaved(request):
            self.socket.put(5, {"eventType": "VendorEvent"})
            self.socket.acknowledge({**request, "requestId": "another-request"}, data={"wrong": True})
            self.socket.acknowledge(request, data={"right": True})

        self.socket.on_request = interleaved
        self.assertEqual(self.connection.request("GetVersion"), {"right": True})

    def test_negative_ack_is_distinct_from_transport_failure(self):
        self.connect()
        self.socket.on_request = lambda request: self.socket.acknowledge(request, result=False, code=600)
        with self.assertRaises(ObsRequestError) as raised:
            self.connection.request("GetSourceScreenshot")
        self.assertEqual(raised.exception.code, 600)
        self.assertTrue(self.connection.connected)

    def test_events_cannot_extend_overall_request_deadline(self):
        self.connection.timeout = 0.08
        self.connect()

        def no_ack(_request):
            def emit():
                while not self.socket.closed.wait(0.002):
                    self.socket.put(5, {"eventType": "VendorEvent"})
            threading.Thread(target=emit, daemon=True).start()

        self.socket.on_request = no_ack
        started = time.monotonic()
        with self.assertRaises(ObsConnectionError):
            self.connection.request("GetVersion")
        self.assertLess(time.monotonic() - started, 0.8)
        self.assertFalse(self.connection.connected)

    def test_close_interrupts_request_without_waiting_for_its_lock(self):
        self.connection.timeout = 2.0
        self.connect()
        requested = threading.Event()
        self.socket.on_request = lambda _request: requested.set()
        errors = []

        def request():
            try:
                self.connection.request("GetVersion")
            except ObsConnectionError as error:
                errors.append(error)

        worker = threading.Thread(target=request)
        worker.start()
        self.assertTrue(requested.wait(0.5))
        self.connection.close()
        worker.join(0.5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertTrue(self.socket.closed.is_set())

    def test_queued_request_from_old_connection_cannot_write_after_reconnect(self):
        self.connect()
        # Hold the request lock until the worker has observed the old generation.
        started = threading.Event()
        original_acquire = self.connection._requests

        class Gate:
            def acquire(_self, **kwargs):
                started.set()
                return original_acquire.acquire(**kwargs)
            def release(_self):
                original_acquire.release()

        self.connection._requests = Gate()
        errors = []

        def queued():
            try:
                self.connection.request("SetSceneItemEnabled", {"sceneItemEnabled": True})
            except ObsConnectionError as error:
                errors.append(error)

        with original_acquire:
            worker = threading.Thread(target=queued)
            worker.start()
            self.assertTrue(started.wait(0.5))
            self.connection.close()
            self.socket = FakeSocket()
            self.connection.connect()
        worker.join(0.5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertEqual(len(self.socket.sent), 1)
        self.assertTrue(self.connection.connected)

    def test_malformed_or_oversized_response_invalidates_connection(self):
        for payload in ("not-json", '{"op":7,"d":NaN}', '[1]', 'x' * 101):
            with self.subTest(payload=payload[:20]):
                self.socket = FakeSocket()
                self.connect()
                self.socket.on_request = lambda _request: self.socket.messages.put(payload)
                with patch.object(obs_connection, "MAX_MESSAGE_BYTES", 100):
                    with self.assertRaises(ObsConnectionError):
                        self.connection.request("GetVersion")
                self.assertFalse(self.connection.connected)

    def test_invalid_configuration_and_local_request_are_rejected(self):
        for port in (True, 0, 65536, "4455"):
            with self.assertRaises(ValueError):
                ObsConnection(port, "")
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                ObsConnection(4455, "", timeout)
        self.connect()
        with self.assertRaises(ValueError):
            self.connection.request("GetVersion", {"bad": float("nan")})
        self.assertTrue(self.connection.connected)


if __name__ == "__main__":
    unittest.main()
