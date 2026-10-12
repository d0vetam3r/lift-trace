"""Synthetic PNG and fake-request checks; no game images or live OBS access."""
from __future__ import annotations

import base64
from io import BytesIO
import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from auto_visibility import PlayState
from obs_connection import ObsRequestError
from infinitas_detector import (
    InfinitasDetector, InvalidImage, MAX_SCREENSHOT_BYTES, MAX_TEMPLATE_BYTES,
    PNG_PREFIX, SCORE_ROI, SOURCE_SIZE, TEMPLATE_SIZE, capture_template,
)


def png(image, image_format="PNG"):
    stream = BytesIO()
    image.save(stream, format=image_format)
    return stream.getvalue()


def response(data):
    return {"imageData": PNG_PREFIX + base64.b64encode(data).decode("ascii")}


def pattern(inverted=False):
    image = Image.new("RGB", TEMPLATE_SIZE, "white" if inverted else "black")
    image.paste("black" if inverted else "white", (0, 0, 45, 20))
    return image


def screenshot(inverted=False):
    image = Image.new("RGB", SOURCE_SIZE, "black")
    with pattern(inverted) as crop:
        image.paste(crop, SCORE_ROI[:2])
    return png(image)


class FakeConnection:
    def __init__(self, result):
        self.result = result
        self.calls = []
        self.on_request = None

    def request(self, kind, data):
        self.calls.append((kind, data))
        if self.on_request:
            self.on_request()
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class InfinitasDetectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.positive = screenshot()
        cls.negative = screenshot(True)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.template = self.directory / "score.png"
        with pattern() as image:
            image.save(self.template)
        self.now = 10.0
        self.connection = FakeConnection(response(self.positive))
        self.detector = InfinitasDetector(self.connection, "selected-source-uuid", self.template,
                                          clock=lambda: self.now)

    def test_matching_png_uses_raw_source_uuid_without_scaling_and_never_persists_frames(self):
        before = self.template.read_bytes()
        self.detector.start()
        self.assertEqual(self.detector.observe().state, PlayState.PLAYING)
        self.assertAlmostEqual(self.detector.last_score, 1.0)
        self.assertEqual(self.connection.calls, [("GetSourceScreenshot", {
            "sourceUuid": "selected-source-uuid", "imageFormat": "png",
        })])
        self.assertEqual(list(self.directory.iterdir()), [self.template])
        self.assertEqual(self.template.read_bytes(), before)

    def test_opposite_pixels_score_point_four_because_opaque_alpha_is_included(self):
        self.detector.start()
        self.connection.result = response(self.negative)
        self.assertEqual(self.detector.observe().state, PlayState.NOT_PLAYING)
        # White/black halves reversed: RGB products are zero; alpha still
        # contributes. Centered correlation would be -1, RGB-only would be 0.
        self.assertAlmostEqual(self.detector.last_score, 0.4)

    def test_threshold_is_strictly_greater_than_point_99(self):
        self.detector.start()
        with patch("infinitas_detector._score", return_value=0.99):
            self.assertEqual(self.detector.observe().state, PlayState.NOT_PLAYING)
        with patch("infinitas_detector._score", return_value=math.nextafter(0.99, 1.0)):
            self.assertEqual(self.detector.observe().state, PlayState.PLAYING)

    def test_timestamp_precedes_request_so_slow_capture_can_be_rejected_as_stale(self):
        self.detector.start()
        self.connection.on_request = lambda: setattr(self, "now", 10.75)
        observation = self.detector.observe()
        self.assertEqual(observation.observed_at, 10.0)
        self.assertEqual(self.detector.capture_latency, 0.75)

    def test_stop_invalidates_in_flight_result_and_does_not_close_shared_connection(self):
        self.detector.start()
        self.connection.on_request = self.detector.stop
        self.assertEqual(self.detector.observe().state, PlayState.UNKNOWN)
        self.assertIsNone(self.detector.last_score)
        self.assertEqual(self.detector.observe().state, PlayState.UNKNOWN)
        self.assertEqual(len(self.connection.calls), 1)

    def test_observe_before_start_or_after_stop_never_captures(self):
        self.assertEqual(self.detector.observe().state, PlayState.UNKNOWN)
        self.detector.start()
        self.detector.stop()
        self.assertEqual(self.detector.observe().state, PlayState.UNKNOWN)
        self.assertEqual(self.connection.calls, [])

    def test_restart_loads_the_reference_again_and_failed_start_leaves_it_stopped(self):
        self.detector.start()
        with pattern(True) as image:
            image.save(self.template)
        self.detector.start()
        self.assertEqual(self.detector.observe().state, PlayState.NOT_PLAYING)
        self.template.write_bytes(b"invalid")
        with self.assertRaises(InvalidImage):
            self.detector.start()
        calls = len(self.connection.calls)
        self.assertEqual(self.detector.observe().state, PlayState.UNKNOWN)
        self.assertEqual(len(self.connection.calls), calls)

    def test_request_errors_propagate_instead_of_becoming_unknown_images(self):
        self.detector.start()
        for error in (ConnectionError("Disconnected"), RuntimeError("OBS request rejected")):
            with self.subTest(error=type(error).__name__):
                self.connection.result = error
                with self.assertRaises(type(error)) as raised:
                    self.detector.observe()
                self.assertIs(raised.exception, error)
                self.assertIsNone(self.detector.last_score)

    def test_invalid_screenshot_clears_old_score_and_returns_unknown(self):
        self.detector.start()
        self.detector.observe()
        malformed = [None, {}, {"imageData": 123}, {"imageData": "data:image/jpeg;base64,AA=="},
                     {"imageData": PNG_PREFIX + "!"}, {"imageData": PNG_PREFIX + "é"},
                     response(b"not a png"), response(self.positive[:-20])]
        for value in malformed:
            with self.subTest(value=str(value)[:45]):
                self.connection.result = value
                self.assertEqual(self.detector.observe().state, PlayState.UNKNOWN)
                self.assertIsNone(self.detector.last_score)
                self.assertEqual(self.detector.last_error, "invalid-screenshot")

    def test_only_screenshot_processing_failure_is_temporary_unavailable(self):
        self.detector.start()
        self.detector.observe()
        self.connection.result = ObsRequestError("GetSourceScreenshot", 702)
        self.assertEqual(self.detector.observe().state, PlayState.UNKNOWN)
        self.assertEqual(self.detector.last_error, "capture-unavailable")
        self.assertIsNone(self.detector.last_score)
        self.connection.result = response(self.positive)
        self.assertEqual(self.detector.observe().state, PlayState.PLAYING)
        self.assertIsNone(self.detector.last_error)
        for kind, code in (("GetSourceScreenshot", 600), ("OtherRequest", 702)):
            self.connection.result = ObsRequestError(kind, code)
            with self.assertRaises(ObsRequestError):
                self.detector.observe()

    def test_wrong_size_is_unknown_instead_of_rescaling(self):
        self.detector.start()
        for size in ((960, 540), (1920, 1081), TEMPLATE_SIZE):
            with self.subTest(size=size), Image.new("RGB", size) as image:
                self.connection.result = response(png(image))
                self.assertEqual(self.detector.observe().state, PlayState.UNKNOWN)

    def test_dimensions_and_payload_limits_are_checked_before_pillow(self):
        self.detector.start()
        enormous = bytearray(self.positive)
        enormous[16:24] = struct.pack(">II", 100000, 100000)
        with patch("PIL.Image.open", side_effect=AssertionError("Must not decode")):
            for data in (bytes(enormous), b"x" * (MAX_SCREENSHOT_BYTES + 1)):
                self.connection.result = response(data)
                self.assertEqual(self.detector.observe().state, PlayState.UNKNOWN)

    def test_start_rejects_constant_wrong_format_wrong_size_and_oversized_templates(self):
        examples = []
        with Image.new("RGB", TEMPLATE_SIZE, "red") as image:
            examples.append(png(image))
        with pattern() as image:
            examples.append(png(image, "BMP"))
        with Image.new("RGB", (91, 20)) as image:
            examples.append(png(image))
        examples += [b"x" * (MAX_TEMPLATE_BYTES + 1), b"bad png"]
        for data in examples:
            with self.subTest(length=len(data)):
                self.template.write_bytes(data)
                with self.assertRaises(InvalidImage):
                    self.detector.start()
        self.assertEqual(self.connection.calls, [])

    def test_explicit_capture_writes_only_verified_crop_and_it_can_be_loaded(self):
        destination = self.directory / "references" / "captured.png"
        self.assertEqual(capture_template(self.connection, "chosen-source", destination), destination)
        with Image.open(destination) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, TEMPLATE_SIZE)
        self.assertEqual(list(destination.parent.iterdir()), [destination])
        detector = InfinitasDetector(self.connection, "chosen-source", destination)
        detector.start()
        self.assertEqual(detector.observe().state, PlayState.PLAYING)

    def test_failed_template_capture_preserves_old_file_and_no_temporary_files(self):
        original = self.template.read_bytes()
        with Image.new("RGB", SOURCE_SIZE, "black") as image:
            self.connection.result = response(png(image))
        with self.assertRaises(InvalidImage):
            capture_template(self.connection, "chosen-source", self.template)
        self.assertEqual(self.template.read_bytes(), original)
        self.assertEqual(list(self.directory.iterdir()), [self.template])

    def test_failed_template_write_preserves_old_file_and_cleans_temporary_crop(self):
        original = self.template.read_bytes()
        with patch("infinitas_detector.os.replace", side_effect=OSError("write failed")):
            with self.assertRaises(OSError):
                capture_template(self.connection, "chosen-source", self.template)
        self.assertEqual(self.template.read_bytes(), original)
        self.assertEqual(list(self.directory.iterdir()), [self.template])

    def test_source_uuid_must_be_explicit(self):
        for value in ("", None, 123):
            with self.subTest(value=value), self.assertRaises(ValueError):
                InfinitasDetector(self.connection, value, self.template)
            with self.subTest(value=value), self.assertRaises(ValueError):
                capture_template(self.connection, value, self.template)
        self.assertEqual(self.connection.calls, [])


if __name__ == "__main__":
    unittest.main()
