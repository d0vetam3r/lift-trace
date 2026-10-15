"""Small, local-only obs-websocket v5 client with acknowledged requests.

A receiver watches collection changes even between requests. Calls are serialized;
close() cancels waiting work without waiting for the request lock. No reconnect or
request replay is automatic. Passwords and received payloads are never logged.
Protocol: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import threading
import time
import uuid


MAX_MESSAGE_BYTES = 16 * 1024 * 1024
INVALIDATING_EVENTS = {
    "CurrentSceneCollectionChanging", "CurrentSceneCollectionChanged", "ExitStarted",
}


class ObsConnectionError(ConnectionError):
    """The connection must be explicitly established again before further work."""


class ObsRequestError(RuntimeError):
    """OBS acknowledged a request but rejected it."""
    def __init__(self, kind: str, code: int):
        self.kind, self.code = kind, code
        super().__init__(f"OBS rejected {kind} (code {code})")


def _websocket_module():
    # Core input functionality remains importable without the optional transport.
    try:
        import websocket
    except ImportError:
        raise ObsConnectionError("OBS runtime dependencies are not installed") from None
    return websocket


def _reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON number")


def _decode(raw) -> dict:
    if not isinstance(raw, str) or not raw or len(raw) > MAX_MESSAGE_BYTES:
        raise ObsConnectionError("Invalid OBS message")
    if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ObsConnectionError("OBS message is too large")
    try:
        value = json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise ObsConnectionError("Invalid OBS JSON") from None
    if (not isinstance(value, dict) or type(value.get("op")) is not int
            or not isinstance(value.get("d"), dict)):
        raise ObsConnectionError("Invalid OBS message structure")
    return value


def _abort(ws) -> None:
    # websocket-client documents abort() as safe for waking another recv thread.
    for method in ("abort", "shutdown"):
        try:
            getattr(ws, method)()
        except Exception:
            pass


class ObsConnection:
    def __init__(self, port: int, password: str, timeout: float = 2.0):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("OBS port must be between 1 and 65535")
        if not isinstance(password, str):
            raise ValueError("OBS password must be a string")
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("OBS timeout must be finite and positive")
        self.port, self.timeout = port, float(timeout)
        self._password = password
        self._requests = threading.RLock()
        self._condition = threading.Condition(threading.RLock())
        self._socket = None
        self._connected = False
        self._generation = 0
        self._pending = None
        self._response = None
        self._reader = None
        self._timeout_errors = (TimeoutError,)
        self._reason = "OBS is not connected"

    @property
    def connected(self) -> bool:
        with self._condition:
            return self._connected

    def _invalidate(self, reason: str, ws=None) -> None:
        with self._condition:
            if ws is not None and self._socket is not ws:
                return
            old = self._socket
            self._socket, self._connected = None, False
            self._generation += 1
            self._reason = reason
            self._response = None
            self._condition.notify_all()
        if old is not None:
            _abort(old)

    def close(self) -> None:
        self._invalidate("OBS connection was closed")

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ObsConnectionError("OBS request timed out")
        return remaining

    def connect(self) -> None:
        deadline = time.monotonic() + self.timeout
        if not self._requests.acquire(timeout=self.timeout):
            raise ObsConnectionError("OBS connection is busy")
        ws = None
        try:
            with self._condition:
                if self._connected:
                    return
                self._generation += 1
                generation = self._generation
            library = _websocket_module()
            self._timeout_errors = (TimeoutError, library.WebSocketTimeoutException)
            # recv() still strictly decodes text as UTF-8. Avoid the library's
            # duplicate Python scan of large screenshot payloads; bounded JSON
            # validation and connection invalidation on CLOSE remain unchanged.
            ws = library.create_connection(
                f"ws://127.0.0.1:{self.port}", timeout=self._remaining(deadline),
                http_no_proxy=["127.0.0.1"], redirect_limit=0, enable_multithread=True,
                skip_utf8_validation=True,
            )
            with self._condition:
                if generation != self._generation:
                    raise ObsConnectionError("OBS connection was cancelled")
                self._socket = ws
            if ws.getstatus() != 101:
                raise ObsConnectionError("OBS WebSocket upgrade failed")
            ws.settimeout(self._remaining(deadline))
            hello = _decode(ws.recv())
            rpc = hello["d"].get("rpcVersion")
            if hello["op"] != 0 or type(rpc) is not int or rpc < 1:
                raise ObsConnectionError("OBS WebSocket v5 is required")
            identify = {"rpcVersion": 1, "eventSubscriptions": 3}  # General | Config
            auth = hello["d"].get("authentication")
            if auth is not None:
                if (not isinstance(auth, dict) or not isinstance(auth.get("salt"), str)
                        or not isinstance(auth.get("challenge"), str)):
                    raise ObsConnectionError("Invalid OBS authentication challenge")
                secret = base64.b64encode(hashlib.sha256(
                    (self._password + auth["salt"]).encode("utf-8")).digest()).decode("ascii")
                identify["authentication"] = base64.b64encode(hashlib.sha256(
                    (secret + auth["challenge"]).encode("utf-8")).digest()).decode("ascii")
            ws.settimeout(self._remaining(deadline))
            ws.send(json.dumps({"op": 1, "d": identify}))
            ws.settimeout(self._remaining(deadline))
            identified = _decode(ws.recv())
            if identified["op"] != 2 or identified["d"].get("negotiatedRpcVersion") != 1:
                raise ObsConnectionError("OBS authentication or RPC negotiation failed")
            self._remaining(deadline)
            with self._condition:
                if self._socket is not ws or generation != self._generation:
                    raise ObsConnectionError("OBS connection was cancelled")
                self._connected = True
                self._pending, self._response = None, None
                ws.settimeout(self.timeout)
                self._reader = threading.Thread(target=self._receive, args=(ws,),
                                                name="obs-events", daemon=True)
                self._reader.start()
        except Exception as error:
            reason = str(error) if isinstance(error, ObsConnectionError) else "Could not connect to OBS"
            self._invalidate(reason, ws)
            if ws is not None:
                _abort(ws)
            raise ObsConnectionError(reason) from None
        finally:
            self._requests.release()

    def _receive(self, ws) -> None:
        try:
            while True:
                with self._condition:
                    if self._socket is not ws:
                        return
                try:
                    message = _decode(ws.recv())
                except self._timeout_errors:
                    continue  # Idle socket timeouts do not extend a request deadline.
                with self._condition:
                    if self._socket is not ws:
                        return
                    if message["op"] == 5:
                        if message["d"].get("eventType") in INVALIDATING_EVENTS:
                            raise ObsConnectionError("OBS session changed; reconnect and select targets again")
                    elif message["op"] == 7:
                        if (self._pending is not None
                                and message["d"].get("requestId") == self._pending[0]):
                            self._response = message["d"]
                            self._condition.notify_all()
                    else:
                        raise ObsConnectionError("Unexpected OBS protocol message")
        except Exception as error:
            reason = str(error) if isinstance(error, ObsConnectionError) else "OBS connection was lost"
            self._invalidate(reason, ws)

    def request(self, kind: str, data: dict | None = None) -> dict:
        if not isinstance(kind, str) or not kind or (data is not None and not isinstance(data, dict)):
            raise ValueError("OBS requests need a name and an object")
        request_id = uuid.uuid4().hex
        payload = json.dumps({"op": 6, "d": {
            "requestType": kind, "requestId": request_id, "requestData": data or {},
        }}, allow_nan=False)
        deadline = time.monotonic() + self.timeout
        with self._condition:
            if not self._connected:
                raise ObsConnectionError(self._reason)
            generation = self._generation
        if not self._requests.acquire(timeout=self._remaining(deadline)):
            raise ObsConnectionError("OBS request timed out waiting for another request")
        ws = None
        try:
            with self._condition:
                if not self._connected or generation != self._generation:
                    raise ObsConnectionError(self._reason)
                ws = self._socket
                self._pending, self._response = (request_id, kind), None
            ws.settimeout(self._remaining(deadline))
            ws.send(payload)
            ws.settimeout(self.timeout)
            with self._condition:
                while self._response is None:
                    if not self._connected or self._socket is not ws:
                        raise ObsConnectionError(self._reason)
                    self._condition.wait(self._remaining(deadline))
                if not self._connected or self._socket is not ws:
                    raise ObsConnectionError(self._reason)
                response = self._response
            self._remaining(deadline)
            status = response.get("requestStatus")
            if (response.get("requestType") != kind or not isinstance(status, dict)
                    or type(status.get("result")) is not bool or type(status.get("code")) is not int):
                raise ObsConnectionError("Invalid OBS request acknowledgement")
            if not status["result"]:
                raise ObsRequestError(kind, status["code"])
            result = response.get("responseData", {})
            if not isinstance(result, dict):
                raise ObsConnectionError("Invalid OBS response data")
            return result
        except ObsRequestError:
            raise
        except Exception as error:
            reason = str(error) if isinstance(error, ObsConnectionError) else "OBS request failed"
            if ws is not None:
                self._invalidate(reason, ws)
            raise ObsConnectionError(reason) from None
        finally:
            with self._condition:
                self._pending, self._response = None, None
            self._requests.release()
