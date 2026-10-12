"""Explicitly armed, local OBS visibility automation, separate from input polling.

OBS credentials live only in automation.json. No connection or worker starts on
app launch. Avoid having another controller change the same scene items.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import threading
import time

from auto_visibility import ObsSceneItems, SceneItem, VisibilitySession


class AutomationError(ValueError):
    """A safe, user-facing error; never include transport/password details."""

    def __init__(self, message, code="invalid-automation-config"):
        super().__init__(message)
        self.code = code


def _selection(value: dict) -> dict:
    if not isinstance(value, dict):
        raise AutomationError("Select a capture item and visibility targets.")
    scene = value.get("sceneUuid")
    capture = value.get("captureItemId")
    source = value.get("captureSourceUuid")
    targets = value.get("targets")
    if (not isinstance(scene, str) or not scene or len(scene) > 128
            or type(capture) is not int or capture < 0
            or not isinstance(source, str) or not source or len(source) > 128
            or not isinstance(targets, list) or not 1 <= len(targets) <= 8):
        raise AutomationError("Select one capture item and 1 to 8 targets in one scene.")
    clean, seen = [], set()
    for target in targets:
        if not isinstance(target, dict):
            raise AutomationError("Invalid visibility target.")
        item_id, source_uuid = target.get("sceneItemId"), target.get("sourceUuid")
        if (target.get("sceneUuid") != scene or type(item_id) is not int or item_id < 0
                or item_id == capture or item_id in seen
                or not isinstance(source_uuid, str) or not source_uuid or len(source_uuid) > 128):
            raise AutomationError("Targets must be distinct items in the capture scene, excluding the capture item.")
        seen.add(item_id)
        clean.append({"sceneUuid": scene, "sceneItemId": item_id, "sourceUuid": source_uuid})
    return {"sceneUuid": scene, "captureItemId": capture,
            "captureSourceUuid": source, "targets": clean}


class Automation:
    def __init__(self, data_dir: Path, *, connection_factory=None,
                 detector_factory=None, template_capture=None, clock=time.monotonic,
                 default_template_path: Path | None = None):
        self.data_dir = Path(data_dir)
        self.template_path = self.data_dir / "automation-template.png"
        self.default_template_path = (Path(default_template_path) if default_template_path is not None
                                      else Path(__file__).resolve().parent / "assets" / "infinitas-score-1080p.png")
        self.clock = clock
        if connection_factory is None:
            try:
                from obs_connection import ObsConnection
                from infinitas_detector import InfinitasDetector, capture_template
                import websocket  # Optional runtime dependencies, never needed by input polling.
                from PIL import Image
                connection_factory, detector_factory = ObsConnection, InfinitasDetector
                template_capture = capture_template
            except ImportError:
                pass
        self.connection_factory = connection_factory
        self.detector_factory = detector_factory
        self.template_capture = template_capture
        self.available = all(callable(item) for item in
                             (connection_factory, detector_factory, template_capture))
        self._operations = threading.RLock()
        self._state_lock = threading.Lock()
        self._connection = None
        self._thread = None
        self._cancel = threading.Event()
        self._closed = False
        self._invalid_template = False
        self._password = ""
        self._config = {"port": 4455, "sceneUuid": None, "captureItemId": None,
                        "captureSourceUuid": None, "targets": []}
        self._state = {"running": False, "state": "unknown", "applied": None,
                       "error": None, "score": None, "connected": False}
        self._load()

    def _load(self):
        try:
            path = self.data_dir / "automation.json"
            if path.stat().st_size > 32768:
                return
            saved = json.loads(path.read_text("utf-8"))
            port, password = saved["port"], saved.get("password", "")
            self._validate_connection(port, password)
            config = {"port": port, **_selection(saved)} if saved.get("sceneUuid") else {**self._config, "port": port}
            self._config, self._password = config, password
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            pass

    @staticmethod
    def _validate_connection(port, password):
        if type(port) is not int or not 1 <= port <= 65535:
            raise AutomationError("OBS port must be between 1 and 65535.")
        if not isinstance(password, str) or len(password) > 4096:
            raise AutomationError("Invalid OBS password.")

    def _save(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / "automation.json.tmp"
        # Private local settings: not served, broadcast, exported, or included in diagnostics.
        with path.open("w", encoding="utf-8") as stream:
            if os.name != "nt":
                os.chmod(path, 0o600)
            json.dump({**self._config, "password": self._password}, stream)
        os.replace(path, self.data_dir / "automation.json")

    def status(self):
        reference, reference_source = self._reference()
        with self._state_lock:
            connected = self._connection is not None and self._connection.connected
            state = {**self._state, "connected": connected}
            if self._state["connected"] and not connected and not state["error"]:
                state["error"] = "obs-disconnected"
            config = {**self._config, "hasPassword": bool(self._password),
                      "targets": [dict(item) for item in self._config["targets"]]}
            return {"available": self.available, **state, "config": config,
                    "templateReady": reference is not None, "referenceSource": reference_source}

    def _reference(self):
        """Prefer a valid local override; never write the bundled reference to data."""
        if not self.available or self._invalid_template:
            return None, None
        from infinitas_detector import validate_template

        for path, source in ((self.template_path, "custom"), (self.default_template_path, "builtin")):
            try:
                validate_template(path)
            except (OSError, ValueError, ImportError):
                continue
            return path, source
        return None, None

    def _idle_connection(self):
        if self._closed:
            raise AutomationError("Automation has been closed.", "automation-unavailable")
        if self._thread is not None and self._thread.is_alive():
            raise AutomationError("Stop automatic visibility before changing its setup.", "automation-busy")
        if self._connection is None or not self._connection.connected:
            raise AutomationError("Connect to OBS before continuing.", "obs-not-connected")
        return self._connection

    def _disconnect(self):
        connection, self._connection = self._connection, None
        if connection is not None:
            connection.close()
        with self._state_lock:
            self._state["connected"] = False

    def connect(self, value):
        with self._operations:
            if self._closed or not self.available:
                raise AutomationError("OBS automation dependencies are unavailable.", "automation-unavailable")
            port, password = value.get("port", self._config["port"]), value.get("password", self._password)
            self._validate_connection(port, password)
            self._stop()
            self._disconnect()
            connection = None
            try:
                connection = self.connection_factory(port, password, timeout=2)
                connection.connect()
                scenes = connection.request("GetSceneList", {})["scenes"]
                catalog = [{"sceneUuid": item["sceneUuid"], "sceneName": item["sceneName"]}
                           for item in scenes]
                self._config["port"], self._password = port, password
                self._save()
            except Exception:
                if connection is not None:
                    connection.close()
                with self._state_lock:
                    self._state["error"] = "obs-connect-failed"
                raise AutomationError("Could not connect to OBS or save its local connection settings.", "obs-connect-failed") from None
            self._connection = connection
            with self._state_lock:
                self._state.update(connected=True, error=None, score=None)
            return {"status": self.status(), "scenes": catalog}

    def _items(self, connection, scene_uuid):
        if not isinstance(scene_uuid, str) or not scene_uuid or len(scene_uuid) > 128:
            raise AutomationError("Select an OBS scene.")
        return connection.request("GetSceneItemList", {"sceneUuid": scene_uuid})["sceneItems"]

    def _connection_failed(self):
        self._disconnect()
        with self._state_lock:
            self._state["error"] = "obs-request-failed"
        raise AutomationError("OBS request failed. Reconnect before trying again.", "obs-request-failed") from None

    @staticmethod
    def _catalog_items(items):
        return [{key: item.get(key) for key in
                 ("sceneItemId", "sceneItemIndex", "sourceUuid", "sourceName", "isGroup",
                  "sourceType", "inputKind", "sceneItemEnabled")} for item in items]

    def catalog(self, scene_uuid=None):
        """Read names on demand, including while automation is running.

        Do not hold the lifecycle lock: a slow name lookup must not prevent
        stop/close. Transport requests are serialized by the existing connection.
        A lookup failure never invokes reconnect, stop, configuration or writes.
        """
        connection = self._connection
        if connection is None or not connection.connected:
            return {"status": self.status(), "scenes": [], "items": []}
        selected = self._config["sceneUuid"] if scene_uuid is None else scene_uuid
        if selected is not None and (not isinstance(selected, str) or not selected or len(selected) > 128):
            raise AutomationError("Select an OBS scene.")
        try:
            scenes = [{"sceneUuid": item["sceneUuid"], "sceneName": item["sceneName"]}
                      for item in connection.request("GetSceneList", {})["scenes"]]
            items = self._catalog_items(self._items(connection, selected)) if selected in {
                scene["sceneUuid"] for scene in scenes} else []
            if connection is not self._connection or not connection.connected:
                raise ConnectionError("Connection changed during lookup")
        except Exception:
            raise AutomationError("Could not refresh OBS names. Try refreshing again.", "obs-catalog-failed") from None
        return {"status": self.status(), "scenes": scenes, "items": items}

    def discover(self, scene_uuid):
        with self._operations:
            connection = self._idle_connection()
            try:
                items = self._catalog_items(self._items(connection, scene_uuid))
            except AutomationError:
                raise
            except Exception:
                self._connection_failed()
            return {"status": self.status(), "items": items}

    def _validate_items(self, connection, config):
        items = self._items(connection, config["sceneUuid"])
        selected = [(config["captureItemId"], config["captureSourceUuid"])]
        selected += [(item["sceneItemId"], item["sourceUuid"]) for item in config["targets"]]
        for item_id, source_uuid in selected:
            matches = [item for item in items if item.get("sceneItemId") == item_id]
            if (len(matches) != 1 or matches[0].get("sourceUuid") != source_uuid
                    or matches[0].get("isGroup") or matches[0].get("sourceType") == "OBS_SOURCE_TYPE_SCENE"):
                raise AutomationError("Selected items changed or include a group/nested scene. Select them again.")
        capture = next(item for item in items if item["sceneItemId"] == config["captureItemId"])
        if capture.get("sceneItemEnabled") is not True:
            raise AutomationError("Keep the original capture item visible before starting automation.")

    def configure(self, value):
        with self._operations:
            connection = self._idle_connection()
            config = {"port": self._config["port"], **_selection(value)}
            try:
                self._validate_items(connection, config)
            except AutomationError:
                raise
            except Exception:
                self._connection_failed()
            changed_capture = any(config[key] != self._config[key]
                                  for key in ("sceneUuid", "captureItemId", "captureSourceUuid"))
            previous = self._config
            self._config = config
            try:
                if changed_capture:
                    self.template_path.unlink(missing_ok=True)
                    self._invalid_template = False
                self._save()
            except OSError:
                self._config = previous
                raise AutomationError("Could not save local automation settings.") from None
            with self._state_lock:
                self._state["error"] = None
            return {"status": self.status()}

    def template(self):
        with self._operations:
            connection = self._idle_connection()
            config = _selection(self._config)
            temporary = self.data_dir / "automation-template.tmp.png"
            try:
                self._validate_items(connection, config)
                self.data_dir.mkdir(parents=True, exist_ok=True)
                # A failed explicit recapture must not leave a stale "ready" flag.
                self.template_path.unlink(missing_ok=True)
                self.template_capture(connection, config["captureSourceUuid"], temporary)
                os.replace(temporary, self.template_path)
                self._invalid_template = False
            except AutomationError:
                raise
            except Exception:
                self._connection_failed()
            finally:
                temporary.unlink(missing_ok=True)
            with self._state_lock:
                self._state["error"] = None
            return {"status": self.status()}

    def start(self):
        with self._operations:
            connection = self._idle_connection()
            config = _selection(self._config)
            reference, _source = self._reference()
            if reference is None:
                if (self._invalid_template or self.template_path.exists()
                        or self.default_template_path.exists()):
                    raise AutomationError("The gameplay reference could not be loaded.", "template-invalid")
                raise AutomationError("The gameplay reference is missing.", "template-required")
            try:
                self._validate_items(connection, config)
            except AutomationError:
                raise
            except Exception:
                self._connection_failed()
            cancel = self._cancel = threading.Event()

            class ActiveConnection:
                @property
                def connected(self):
                    return not cancel.is_set() and connection.connected

                def request(self, kind, data):
                    if not self.connected:
                        raise ConnectionError("Automation stopped")
                    result = connection.request(kind, data)
                    if not self.connected:
                        raise ConnectionError("Automation stopped")
                    return result

            active = ActiveConnection()
            try:
                detector = self.detector_factory(active, config["captureSourceUuid"],
                                                 reference, clock=self.clock)
                targets = tuple(SceneItem(item["sceneUuid"], item["sceneItemId"], item["sourceUuid"])
                                for item in config["targets"])
                session = VisibilitySession(detector, ObsSceneItems(targets, active.request), clock=self.clock)
                state = session.start()
            except Exception:
                self._connection_failed()
            if not state.running:
                self._invalid_template = True
                self._publish(session, detector)
                raise AutomationError("The gameplay reference could not be loaded. Capture it again.", "template-invalid")
            self._publish(session, detector)
            self._thread = threading.Thread(target=self._run, args=(session, detector, connection, cancel),
                                            name="obs-visibility", daemon=True)
            self._thread.start()
            return {"status": self.status()}

    def _publish(self, session, detector, error=None):
        state = session.status()
        score = getattr(detector, "last_score", None)
        if type(score) not in (int, float) or not math.isfinite(score):
            score = None
        with self._state_lock:
            self._state.update(running=state.running, state=state.state.value,
                               applied=state.applied, error=error or state.error, score=score)

    def _run(self, session, detector, connection, cancel):
        failure = None
        try:
            while not cancel.is_set():
                started = self.clock()
                state = session.tick()
                if cancel.is_set():
                    break
                detector_error = getattr(detector, "last_error", None)
                # Only OBS's known screenshot-render/unavailable case is a
                # recoverable missing frame. Unsupported/malformed frames and
                # all other request errors still require an explicit restart.
                failure = state.error or ("detector-failed" if detector_error not in
                                          (None, "capture-unavailable") else None)
                if not connection.connected:
                    failure = "obs-disconnected"
                self._publish(session, detector, failure)
                if failure or not state.running:
                    break
                cancel.wait(max(0, 0.1 - (self.clock() - started)))
        except Exception:
            failure = "automation-failed"
        finally:
            session.stop()
            if cancel.is_set() and failure is None:
                session.error = None  # Cancellation is intentional, not a reconnect fault.
            if failure:
                connection.close()
                with self._state_lock:
                    self._state["connected"] = False
            self._publish(session, detector, failure)

    def _stop(self):
        self._cancel.set()
        if self._thread is not None:
            self._thread.join(timeout=2.5)
            if self._thread.is_alive():
                self._disconnect()  # Interrupt a blocked request; never queue replacement work.
                self._thread.join(timeout=0.5)
            if self._thread.is_alive():
                raise AutomationError("Automation is still stopping. Reconnect after it stops.")
            self._thread = None

    def stop(self):
        with self._operations:
            self._stop()
            return {"status": self.status()}

    def close(self):
        with self._operations:
            self._closed = True
            self._cancel.set()
            self._disconnect()
            try:
                self._stop()
            except AutomationError:
                # A cancelled daemon cannot issue another guarded request. Keep
                # application shutdown bounded even if a detector fails to return.
                with self._state_lock:
                    self._state.update(running=False, error="automation-stop-timeout")
