# SPDX-License-Identifier: MIT
"""Decode the isolated Lift Trace pacing fixture; never connect to live services.

Example (Python with NumPy and PyAV installed):
    python analyze_pacing.py capture.mkv --telemetry frames.jsonl --browser-fps 60

The fixture encodes five 24-bit, little-endian barcodes.  A repeated frameId
proves that the same painted diagnostic frame was presented twice.  A missing
frameId is not by itself a defect: at browser=120/output=60, subsampling is
expected.  Telemetry distinguishes JavaScript callback gaps from presentation
repeats, but does not measure the native CEF compositor directly.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any


MODULUS = 1 << 24
BARCODE_FIELDS = (
    ("frameId", 300),
    ("rafStamp10", 318),
    ("callbackPerf10", 336),
    ("wallElapsed10", 354),
    ("previousDrawUs", 372),
)


def numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        index = (len(ordered) - 1) * fraction
        lower = int(index)
        upper = min(lower + 1, len(ordered) - 1)
        return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower), 4)

    return {
        "count": len(values),
        "min": round(ordered[0], 4),
        "p50": percentile(0.5),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": round(ordered[-1], 4),
        "mean": round(statistics.fmean(values), 4),
    }


def wrapped_delta(current: int, previous: int) -> int:
    """Forward delta of the fixture's modulo-24-bit counter/timestamps."""
    return (current - previous) % MODULUS


def signed_wrapped_delta(current: int, previous: int) -> int:
    return (current - previous + MODULUS // 2) % MODULUS - MODULUS // 2


def decode_barcode(rgb: Any) -> dict[str, Any]:
    """Sample well inside each cell to avoid H.264 edge/color artifacts."""
    import numpy as np

    if rgb.ndim != 3 or rgb.shape[0] != 390 or rgb.shape[1] != 432:
        raise ValueError(f"Expected unscaled fixture 432x390, got {rgb.shape}")
    decoded: dict[str, Any] = {}
    ambiguous_cells = 0
    minimum_contrast = 127.5
    for name, y in BARCODE_FIELDS:
        value = 0
        for bit in range(24):
            x = 8 + 12 * bit
            level = float(np.mean(rgb[y + 4:y + 10, x + 3:x + 8, :3]))
            # Both colors must be safely away from threshold.  Keep the decoded
            # value for diagnosis but mark that whole frame as uncertain.
            if 60 < level < 195:
                ambiguous_cells += 1
            minimum_contrast = min(minimum_contrast, abs(level - 127.5))
            if level >= 127.5:
                value |= 1 << bit
        decoded[name] = value
    decoded["ambiguousCells"] = ambiguous_cells
    decoded["minimumContrast"] = round(minimum_contrast, 3)
    decoded["valid"] = (
        ambiguous_cells == 0 and decoded["frameId"] > 0
        and decoded["callbackPerf10"] > 0
    )
    return decoded


def telemetry_frames(path: Path | None, run: str | None) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Accept fixture batches, one frame per line, and server-wrapped bodies."""
    if path is None:
        return {}, {"provided": False}
    frames: dict[int, dict[str, Any]] = {}
    runs: set[str] = set()
    dropped_by_run: dict[str, int] = {}
    malformed = 0
    batches = 0
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
            if isinstance(item, dict) and isinstance(item.get("body"), dict):
                item = item["body"]
            if not isinstance(item, dict):
                raise ValueError("Not an object")
            batch_run = str(item.get("run", ""))
            if run is not None and batch_run != run:
                continue
            if batch_run:
                runs.add(batch_run)
            if len(runs) > 1 and run is None:
                raise RuntimeError("Telemetry contains multiple runs; choose --run to avoid mixing counters")
            entries = item.get("frames", [item] if "frameId" in item else [])
            if not isinstance(entries, list):
                raise ValueError("frames must be a list")
            batches += 1
            dropped_by_run[batch_run] = max(dropped_by_run.get(batch_run, 0), int(item.get("dropped", 0)))
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("Frame must be an object")
                frame_id = int(entry["frameId"])
                for field in ("rafMs", "callbackPerfMs", "wallElapsedMs", "drawCostMs"):
                    if not math.isfinite(float(entry[field])):
                        raise ValueError("Non-finite telemetry")
                frames[frame_id % MODULUS] = entry
        except (ValueError, TypeError, KeyError, OverflowError):
            malformed += 1
    return frames, {
        "provided": True, "runs": sorted(runs), "batches": batches,
        "uniqueFrames": len(frames), "malformedLines": malformed,
        "reportedDroppedByRun": dropped_by_run,
    }


def summarize(rows: list[dict[str, Any]], telemetry: dict[int, dict[str, Any]],
              browser_fps: float, output_fps: float) -> dict[str, Any]:
    period_ms = 1000 / output_fps
    valid = [row for row in rows if row["valid"]]
    pairs = [(a, b) for a, b in zip(valid, valid[1:]) if b["index"] == a["index"] + 1]
    pts_steps = [(b["ptsSeconds"] - a["ptsSeconds"]) * 1000 for a, b in zip(rows, rows[1:])]
    ids = [wrapped_delta(b["frameId"], a["frameId"]) for a, b in pairs]
    # Timestamp reset/reload would yield near-modulus jumps; report separately.
    continuous = [(a, b) for (a, b), delta in zip(pairs, ids) if delta < MODULUS // 2]
    step_fields = ("rafStamp10", "callbackPerf10", "wallElapsed10")
    source_steps = {
        field: [wrapped_delta(b[field], a[field]) / 10 for a, b in continuous]
        for field in step_fields
    }
    histogram: dict[str, int] = {}
    for delta in ids:
        histogram[str(delta)] = histogram.get(str(delta), 0) + 1
    duplicates = sum(delta == 0 for delta in ids)
    unique_presented = {row["frameId"]: row for row in valid}.values()
    consecutive_source_gaps = [
        wrapped_delta(row["callbackPerf10"], previous["callbackPerf10"]) / 10
        for (previous, row), delta in zip(pairs, ids) if delta == 1
    ]
    longest_repeat = current_repeat = 0
    for delta in ids:
        current_repeat = current_repeat + 1 if delta == 0 else 0
        longest_repeat = max(longest_repeat, current_repeat)
    events = []
    for (previous, row), delta in zip(pairs, ids):
        wall_step = wrapped_delta(row["wallElapsed10"], previous["wallElapsed10"]) / 10
        if delta == 0 or (delta < MODULUS // 2 and wall_step > 1.5 * period_ms):
            matched = telemetry.get(row["frameId"])
            prior = telemetry.get(previous["frameId"])
            event = {
                "ptsSeconds": row["ptsSeconds"], "frameId": row["frameId"],
                "previousFrameId": previous["frameId"], "idDelta": delta,
                "wallStepMs": wall_step,
                "rafStepMs": wrapped_delta(row["rafStamp10"], previous["rafStamp10"]) / 10,
                "callbackStepMs": wrapped_delta(row["callbackPerf10"], previous["callbackPerf10"]) / 10,
            }
            if matched and prior:
                event["presentedCallbackGapMs"] = round(float(matched["callbackPerfMs"]) - float(prior["callbackPerfMs"]), 4)
                event["currentDrawCostMs"] = matched["drawCostMs"]
            events.append(event)
    telemetry_summary: dict[str, Any] = {"matchedPresentedFrames": sum(row["frameId"] in telemetry for row in valid)}
    if valid and telemetry:
        first_id, last_id = valid[0]["frameId"], valid[-1]["frameId"]
        # This diagnostic run is short; a source counter reset is reported above.
        bounded = [telemetry[key] for key in sorted(telemetry) if first_id <= key <= last_id]
        consecutive = [(a, b) for a, b in zip(bounded, bounded[1:]) if int(b["frameId"]) == int(a["frameId"]) + 1]
        callback_gaps = [float(b["callbackPerfMs"]) - float(a["callbackPerfMs"]) for a, b in consecutive]
        raf_gaps = [float(b["rafMs"]) - float(a["rafMs"]) for a, b in consecutive]
        telemetry_summary.update({
            "framesInPresentedSpan": len(bounded),
            "consecutivePairs": len(consecutive),
            "callbackGapMs": numeric_summary(callback_gaps),
            "rafTimestampGapMs": numeric_summary(raf_gaps),
            "callbackGapOver1_5SourcePeriods": sum(gap > 1500 / browser_fps for gap in callback_gaps),
            "callbackGapOver1_5OutputPeriods": sum(gap > 1.5 * period_ms for gap in callback_gaps),
            "callbackLatenessFromRafStampMs": numeric_summary([
                float(frame["callbackPerfMs"]) - float(frame["rafMs"]) for frame in bounded]),
            "drawCostMs": numeric_summary([float(frame["drawCostMs"]) for frame in bounded]),
        })
    return {
        "analyzedFrames": len(rows), "validBarcodeFrames": len(valid),
        "invalidBarcodeFrames": len(rows) - len(valid), "adjacentValidPairs": len(pairs),
        "outputPtsStepMs": numeric_summary(pts_steps),
        "outputPtsGapsOver1_5Periods": sum(step > 1.5 * period_ms for step in pts_steps),
        "repeatedPresentedFrames": duplicates,
        "repeatedPresentedPercent": round(100 * duplicates / len(pairs), 4) if pairs else None,
        "longestRepeatExtraFrames": longest_repeat,
        "frameIdDeltaHistogram": histogram,
        "counterResetOrBackwardPairs": sum(delta >= MODULUS // 2 for delta in ids),
        "expectedSourceFramesPerOutputFrame": browser_fps / output_fps,
        "presentedSourceStepMs": {key: numeric_summary(values) for key, values in source_steps.items()},
        "presentedWallStepsOver1_5OutputPeriods": sum(step > 1.5 * period_ms for step in source_steps["wallElapsed10"]),
        "barcodeTiming": {
            "scope": "Unique presented frames only; unpresented callbacks are not sampled",
            "callbackLatenessFromRafStampMs": numeric_summary([
                signed_wrapped_delta(row["callbackPerf10"], row["rafStamp10"]) / 10
                for row in unique_presented]),
            "precedingCallbackDrawCostMs": numeric_summary([
                row["previousDrawUs"] / 1000 for row in unique_presented]),
            "knownConsecutiveSourceCallbackGapMs": numeric_summary(consecutive_source_gaps),
            "knownConsecutiveSourceGapsOver1_5SourcePeriods": sum(
                gap > 1500 / browser_fps for gap in consecutive_source_gaps),
        },
        "telemetry": telemetry_summary,
        "events": events,
        "interpretationLimits": [
            "Repeated frameId measures repeated painted frames in the encoded OBS output.",
            "At 120 browser fps and 60 output fps, missing every other source frame is expected.",
            "Callback and draw telemetry do not observe native CEF composition or OBS texture handoff.",
            "Telemetry may be flushed later; missing telemetry is not proof that a callback did not occur.",
            "Without telemetry, barcode timing covers only presented frames and cannot rule out hidden callback gaps.",
        ],
    }


def decode_video(video: Path, warmup: float, duration: float | None, av_libs: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if av_libs is not None:
        sys.path.insert(0, str(av_libs))
    import av

    rows = []
    with av.open(str(video)) as container:
        streams = list(container.streams.video)
        if len(streams) != 1:
            raise ValueError(f"Expected one video stream; got {len(streams)}")
        stream = streams[0]
        stream.codec_context.thread_count = 1
        stream.codec_context.thread_type = "NONE"
        metadata = {
            "codec": stream.codec_context.name,
            "width": stream.codec_context.width, "height": stream.codec_context.height,
            "averageRate": str(stream.average_rate), "timeBase": str(stream.time_base),
            "decoderThreads": 1,
        }
        first_pts = None
        for index, frame in enumerate(container.decode(stream)):
            if frame.pts is None:
                raise ValueError("Frame without PTS cannot be used for pacing analysis")
            pts = float(frame.pts * frame.time_base)
            if first_pts is None:
                first_pts = pts
            elapsed = pts - first_pts
            if elapsed < warmup:
                continue
            if duration is not None and elapsed >= warmup + duration:
                break
            decoded = decode_barcode(frame.to_ndarray(format="rgb24"))
            rows.append({"index": index, "ptsSeconds": round(pts, 8), "elapsedSeconds": round(elapsed, 8), **decoded})
        metadata["firstPtsSeconds"] = first_pts
    return rows, metadata


def self_test() -> dict[str, Any]:
    """Tiny in-memory barcode exercise; no codec, OBS, GPU, or file input."""
    import numpy as np

    cases = [
        [1, 167, 175, 10, 350],
        [123456, MODULUS - 1, 0xA5A5A5, 0x555555, 0xAAAAAA],
        [MODULUS - 1, 100, 200, 300, 400],
    ]
    for values in cases:
        rgb = np.zeros((390, 432, 3), dtype=np.uint8)
        for (_, y), value in zip(BARCODE_FIELDS, values):
            for bit in range(24):
                rgb[y:y + 14, 8 + 12 * bit:18 + 12 * bit] = 235 if value & (1 << bit) else 16
        result = decode_barcode(rgb)
        assert result["valid"]
        assert [result[name] for name, _ in BARCODE_FIELDS] == values
    rgb[304:310, 11:16] = 127
    assert not decode_barcode(rgb)["valid"]
    assert wrapped_delta(3, MODULUS - 2) == 5
    sample_rows = []
    for index, frame_id in enumerate([10, 11, 11, 13, 14]):
        sample_rows.append({"index": index, "ptsSeconds": index / 60, "valid": True,
                           "frameId": frame_id, "rafStamp10": round(frame_id * 1000 / 6),
                           "callbackPerf10": round(frame_id * 1000 / 6) + 2,
                           "wallElapsed10": round(frame_id * 1000 / 6), "previousDrawUs": 200})
    summary = summarize(sample_rows, {}, 60, 60)
    assert summary["repeatedPresentedFrames"] == 1
    assert summary["presentedWallStepsOver1_5OutputPeriods"] == 1
    assert summary["outputPtsGapsOver1_5Periods"] == 0
    return {"selfTest": "passed", "barcodeCases": len(cases), "ambiguousCellRejected": True,
            "wraparoundChecked": True, "repeatAndCatchupChecked": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, nargs="?")
    parser.add_argument("--telemetry", type=Path)
    parser.add_argument("--run")
    parser.add_argument("--browser-fps", type=float, default=60)
    parser.add_argument("--output-fps", type=float, default=60)
    parser.add_argument("--warmup", type=float, default=2)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--av-libs", type=Path, help="Explicit alternate directory containing PyAV, if not installed in this Python")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--csv-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return
    if args.video is None:
        parser.error("video is required unless --self-test is used")
    if args.browser_fps <= 0 or args.output_fps <= 0 or args.warmup < 0 or (args.duration is not None and args.duration <= 0):
        parser.error("FPS and duration must be positive; warmup must be nonnegative")
    telemetry, telemetry_meta = telemetry_frames(args.telemetry, args.run)
    rows, video_meta = decode_video(args.video, args.warmup, args.duration, args.av_libs)
    result = {
        "video": str(args.video), "videoMetadata": video_meta,
        "browserFpsConfigured": args.browser_fps, "outputFpsConfigured": args.output_fps,
        "warmupSeconds": args.warmup, "telemetryInput": telemetry_meta,
        **summarize(rows, telemetry, args.browser_fps, args.output_fps),
    }
    encoded = json.dumps(result, indent=2, ensure_ascii=False)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(encoded + "\n", encoding="utf-8")
    if args.csv_out:
        args.csv_out.parent.mkdir(parents=True, exist_ok=True)
        with args.csv_out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["index", "ptsSeconds"])
            writer.writeheader()
            writer.writerows(rows)
    print(encoded)


if __name__ == "__main__":
    main()
