"""Opt-in INFINITAS SCORE detector for an unscaled 1920 x 1080 OBS source.

Screenshots stay in memory. Only capture_template(), called by an explicit user
action, writes the 90 x 20 reference crop. Pillow is imported when used, so the
ordinary controller/overlay path does not require it. This is one fixed screen
profile, not game-state recognition for arbitrary layouts.
"""
from __future__ import annotations

import base64
import binascii
from io import BytesIO
import math
import os
from pathlib import Path
import struct
import tempfile
import time
from typing import Callable, Protocol

from auto_visibility import Observation, PlayState
from obs_connection import ObsRequestError


SOURCE_SIZE = (1920, 1080)
TEMPLATE_SIZE = (90, 20)
SCORE_ROI = (170, 953, 260, 973)  # Pillow crop: left, top, right, bottom.
MATCH_THRESHOLD = 0.99
MAX_SCREENSHOT_BYTES = 16 * 1024 * 1024
MAX_TEMPLATE_BYTES = 256 * 1024
PNG_PREFIX = "data:image/png;base64,"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class Connection(Protocol):
    def request(self, kind: str, data: dict) -> dict: ...


class InvalidImage(ValueError):
    """A screenshot or reference does not fit the fixed detector profile."""


def _decode_png(data: bytes, size: tuple[int, int], limit: int):
    # Inspect the PNG header before giving compressed pixels to a decoder.
    if (len(data) > limit or len(data) < 33 or data[:8] != PNG_SIGNATURE
            or data[8:16] != b"\x00\x00\x00\rIHDR"
            or struct.unpack(">II", data[16:24]) != size):
        raise InvalidImage("Expected a PNG of the supported size")
    from PIL import Image  # Optional runtime dependency, deliberately lazy.

    try:
        with Image.open(BytesIO(data), formats=("PNG",)) as image:
            if image.size != size or getattr(image, "n_frames", 1) != 1:
                raise InvalidImage("Animated or differently sized PNG is unsupported")
            image.verify()
        with Image.open(BytesIO(data), formats=("PNG",)) as image:
            return image.convert("RGBA")
    except (OSError, ValueError, SyntaxError) as error:
        raise InvalidImage("Invalid PNG data") from error


def _screenshot_image(response: dict):
    encoded = response.get("imageData") if isinstance(response, dict) else None
    max_encoded = 4 * ((MAX_SCREENSHOT_BYTES + 2) // 3)
    if (not isinstance(encoded, str) or not encoded.startswith(PNG_PREFIX)
            or len(encoded) > len(PNG_PREFIX) + max_encoded):
        raise InvalidImage("Expected a bounded PNG screenshot response")
    try:
        data = base64.b64decode(encoded[len(PNG_PREFIX):], validate=True)
    except (ValueError, binascii.Error) as error:
        raise InvalidImage("Invalid screenshot encoding") from error
    return _decode_png(data, SOURCE_SIZE, MAX_SCREENSHOT_BYTES)


def _request_screenshot(connection: Connection, source_uuid: str) -> dict:
    # Omitting imageWidth/imageHeight is essential: scaling would conceal an
    # unsupported source size while moving the fixed SCORE crop.
    return connection.request("GetSourceScreenshot", {
        "sourceUuid": source_uuid, "imageFormat": "png",
    })


def _template_vector(image) -> bytes:
    vector = image.tobytes()
    first_pixel = vector[:4]
    if all(vector[index:index + 4] == first_pixel
           for index in range(0, len(vector), 4)):
        raise InvalidImage("The reference crop must contain a visible pattern")
    return vector


def _load_template(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_TEMPLATE_BYTES + 1)
    with _decode_png(data, TEMPLATE_SIZE, MAX_TEMPLATE_BYTES) as image:
        return _template_vector(image)


def _score(vector: bytes, reference: bytes, reference_norm: float) -> float:
    # TM_CCORR_NORMED at one fixed position, without mean subtraction or an
    # alpha mask. RGBA includes alpha=255 for opaque pixels, just as ASS does.
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm or not reference_norm:
        return 0.0
    score = sum(a * b for a, b in zip(vector, reference)) / (norm * reference_norm)
    return min(1.0, max(0.0, score)) if math.isfinite(score) else 0.0


class InfinitasDetector:
    def __init__(self, connection: Connection, source_uuid: str,
                 template_path: str | Path, *,
                 clock: Callable[[], float] = time.monotonic):
        if not isinstance(source_uuid, str) or not source_uuid:
            raise ValueError("Select an OBS source UUID")
        self.connection, self.source_uuid = connection, source_uuid
        self.template_path, self.clock = Path(template_path), clock
        self.last_score: float | None = None
        self.capture_latency: float | None = None
        self.last_error: str | None = None
        self._reference: bytes | None = None
        self._reference_norm = 0.0
        self._generation = 0

    def start(self) -> None:
        self.stop()
        reference = _load_template(self.template_path)
        self._reference_norm = math.sqrt(sum(value * value for value in reference))
        self._reference = reference

    def observe(self) -> Observation:
        self.last_score, self.capture_latency, self.last_error = None, None, None
        observed_at = self.clock()
        reference = self._reference
        generation = self._generation
        if reference is None:
            return Observation(PlayState.UNKNOWN, observed_at)
        # Transport/request failures must reach the connection supervisor. Do
        # not turn a disconnected OBS into an ordinary unrecognized screenshot.
        try:
            response = _request_screenshot(self.connection, self.source_uuid)
        except ObsRequestError as error:
            # obs-websocket uses 702 for screenshot render/encode failure,
            # including sources with no frame yet. Missing sources and all
            # other rejected requests still require supervisor intervention.
            if error.kind != "GetSourceScreenshot" or error.code != 702:
                raise
            self.last_error = "capture-unavailable"
            return Observation(PlayState.UNKNOWN, observed_at)
        finally:
            self.capture_latency = max(0.0, self.clock() - observed_at)
        if generation != self._generation:
            return Observation(PlayState.UNKNOWN, observed_at)
        try:
            with _screenshot_image(response) as image:
                with image.crop(SCORE_ROI) as crop:
                    score = _score(crop.tobytes(), reference, self._reference_norm)
        except InvalidImage:
            self.last_error = "invalid-screenshot"
            return Observation(PlayState.UNKNOWN, observed_at)
        if generation != self._generation:
            return Observation(PlayState.UNKNOWN, observed_at)
        self.last_score = score
        state = PlayState.PLAYING if score > MATCH_THRESHOLD else PlayState.NOT_PLAYING
        return Observation(state, observed_at)

    def stop(self) -> None:
        # Invalidate an outstanding capture without closing a shared connection.
        self._generation += 1
        self._reference = None
        self._reference_norm = 0.0
        self.last_score, self.capture_latency, self.last_error = None, None, None


def capture_template(connection: Connection, source_uuid: str, path: str | Path) -> Path:
    """Explicitly capture and atomically save only the fixed reference crop.

    The caller owns the user confirmation and destination. This function never
    runs as part of detector start/observe, and never saves the full screenshot.
    """
    if not isinstance(source_uuid, str) or not source_uuid:
        raise ValueError("Select an OBS source UUID")
    response = _request_screenshot(connection, source_uuid)
    with _screenshot_image(response) as image:
        with image.crop(SCORE_ROI) as crop:
            _template_vector(crop)
            destination = Path(path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=destination.parent,
                                                 prefix=".score-", suffix=".png",
                                                 delete=False) as stream:
                    temporary = Path(stream.name)
                    crop.save(stream, format="PNG")
                os.replace(temporary, destination)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    return destination
