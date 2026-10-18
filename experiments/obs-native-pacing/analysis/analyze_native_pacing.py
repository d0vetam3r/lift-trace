# SPDX-License-Identifier: MIT
"""Offline comparison of browser/native OBS synthetic note presentation.

Reads recorded pixels only. It never launches OBS or contacts a running service.
Motion is measured from note pixels independently from the diagnostic counter.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import statistics
import sys
from typing import Any

import barcode_analysis as barcode

SPEED = 723 * 529 / 1000 * 600 / 270
WIDTH = 432
NOTE_REGION_HEIGHT = 290
HEAD_HEIGHT = 12
BARCODE_CONTRACT = {
    "canvas": [432, 390], "bits": 24, "bitOrder": "LSB first",
    "cell": {"x": 8, "pitch": 12, "width": 10, "height": 14},
    "rows": [
        {"y": 300, "field": "frameId", "meaning": "source update sequence"},
        {"y": 318, "field": "rafStamp10", "meaning": "source animation frame clock, 0.1 ms"},
        {"y": 336, "field": "callbackPerf10", "meaning": "actual callback clock, 0.1 ms"},
        {"y": 354, "field": "wallElapsed10", "meaning": "animation elapsed time, 0.1 ms"},
        {"y": 372, "field": "previousDrawUs", "meaning": "preceding draw duration, us"},
    ],
    "note": {"height": 12, "speedPixelsPerSecond": SPEED,
             "intervalMs": 120, "releaseMs": 40, "keyboardLanes": 7},
}


def lane_geometry() -> list[tuple[float, float]]:
    weights = [5 / 3, 1, 7 / 9, 1, 7 / 9, 1, 7 / 9, 1]
    unit = WIDTH / sum(weights)
    current = 0.0
    result = []
    for weight in weights:
        width = weight * unit
        result.append((current, width))
        current += width
    return result


def extract_heads(rgb: Any) -> dict[int, dict[str, float]]:
    """Measure full, isolated head bands away from lane guides and ROI edges.

    Each lane has a note every 840 ms but a head crosses this ROI in 341 ms,
    so two same-lane heads cannot be visible at once in the intended fixture.
    Multiple bright bands or incorrect thickness reject the lane for that frame.
    """
    import numpy as np

    heads = {}
    for lane, (left, width) in enumerate(lane_geometry()):
        if lane == 0:
            continue
        center = round(left + width / 2)
        profile = rgb[:NOTE_REGION_HEIGHT, center - 8:center + 8, :3].max(axis=2).mean(axis=1)
        bright = np.flatnonzero(profile > 90)
        if len(bright) == 0:
            continue
        splits = np.split(bright, np.flatnonzero(np.diff(bright) > 1) + 1)
        bands = [band for band in splits if 9 <= len(band) <= 15]
        if len(bands) != 1:
            continue
        band = bands[0]
        first, last = int(band[0]), int(band[-1])
        if first < 2 or last >= NOTE_REGION_HEIGHT - 2:
            continue
        # A 2 px margin captures fractional edge coverage without including
        # dark compression noise. Pixel centers, rather than integer edges,
        # yield a centroid appropriate for subpixel Canvas rectangles.
        ys = np.arange(first - 2, last + 3)
        weights = np.maximum(profile[ys] - 12, 0)
        y = float(np.dot(ys + .5, weights) / weights.sum())
        peak = float(profile[band].max())
        area_height = float(weights.sum() / max(1, peak - 12))
        if not 10.5 <= area_height <= 13.5:
            continue
        heads[lane] = {"y": y, "height": area_height}
    return heads


def motion_pair(previous: dict[int, dict[str, float]], current: dict[int, dict[str, float]],
                elapsed_seconds: float, output_fps: float = 60) -> dict[str, Any]:
    movement = [current[lane]["y"] - old["y"] for lane, old in previous.items()
                if lane in current and -1 <= current[lane]["y"] - old["y"] <= 48]
    expected = SPEED * elapsed_seconds
    if not movement:
        return {"matchedHeads": 0, "qualified": False}
    spread = max(movement) - min(movement)
    shift = statistics.median(movement)
    qualified = len(movement) >= 2 and spread <= 1.25 and 0 < elapsed_seconds < .025
    return {
        "matchedHeads": len(movement), "qualified": qualified,
        "headMotionPx": round(shift, 5), "laneMotionSpreadPx": round(spread, 5),
        "expectedMotionPx": round(expected, 5), "motionErrorPx": round(shift - expected, 5),
        "nominalExpectedMotionPx": round(SPEED / output_fps, 5),
        "nominalMotionErrorPx": round(shift - SPEED / output_fps, 5),
        "stopped": qualified and abs(shift) < 1,
        "largeStep": qualified and shift > 1.5 * expected,
    }


def summarize_motion(rows: list[dict[str, Any]]) -> dict[str, Any]:
    transitions = [row for row in rows if "matchedHeads" in row]
    qualified = [row for row in transitions if row["qualified"]]
    moves = [row["headMotionPx"] for row in qualified]
    errors = [row["motionErrorPx"] for row in qualified]
    nominal_errors = [row["nominalMotionErrorPx"] for row in qualified]
    events = []
    for row in qualified:
        if row["stopped"] or row["largeStep"]:
            events.append({key: row[key] for key in (
                "index", "ptsSeconds", "frameId", "frameIdDelta", "matchedHeads",
                "headMotionPx", "expectedMotionPx", "laneMotionSpreadPx", "stopped", "largeStep")})
    return {
        "measurement": "Independent pixel tracking of 12 px head centroids, not inferred from barcodes",
        "totalAdjacentPairs": len(transitions), "qualifiedPairs": len(qualified),
        "qualification": "At least two corresponding full heads; lane displacement spread <=1.25 px; 0<PTS delta<25 ms",
        "qualificationPercent": round(len(qualified) / len(transitions) * 100, 3) if transitions else None,
        "stoppedPairs": sum(row["stopped"] for row in qualified),
        "largeStepPairs": sum(row["largeStep"] for row in qualified),
        "stoppedWithAdvancingCounter": sum(row["stopped"] and row["frameIdDelta"] > 0 for row in qualified),
        "motionPx": barcode.numeric_summary(moves),
        "errorFromPtsExpectedPx": barcode.numeric_summary(errors),
        "errorRmsPx": round((statistics.fmean(v*v for v in errors)) ** .5, 5) if errors else None,
        "errorFromNominalCadencePx": barcode.numeric_summary(nominal_errors),
        "nominalErrorRmsPx": round((statistics.fmean(v*v for v in nominal_errors)) ** .5, 5) if nominal_errors else None,
        "roiMeanAbsPixelDiff": barcode.numeric_summary([row["roiMeanAbsPixelDiff"] for row in transitions]),
        "events": events,
        "limits": [
            "Only full head pairs satisfying the stated criteria contribute to stop/large-step counts.",
            "Rasterization and codec quantization cause small centroid variation; <1 px is classified as a stop.",
            "Matroska millisecond PTS quantization itself alternates 16/17 ms. Nominal-cadence error avoids treating that container rounding as rendered jitter.",
            "A successful synthetic run does not prove absence of stutter under every real gaming/GPU load.",
        ],
    }


def analyze(video: Path, warmup: float, duration: float | None, av_libs: Path | None,
            source_fps: float = 60, output_fps: float = 60) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    import numpy as np
    if av_libs is not None:
        sys.path.insert(0, str(av_libs))
    import av

    rows = []
    previous_rgb = None
    previous_heads = None
    previous_row = None
    first_pts = None
    with av.open(str(video)) as container:
        videos = list(container.streams.video)
        if len(videos) != 1:
            raise ValueError(f"Expected one video stream, got {len(videos)}")
        stream = videos[0]
        stream.codec_context.thread_count = 1
        stream.codec_context.thread_type = "NONE"
        metadata = {"width": stream.width, "height": stream.height,
                    "codec": stream.codec_context.name, "averageRate": str(stream.average_rate),
                    "timeBase": str(stream.time_base), "decoderThreads": 1}
        for index, frame in enumerate(container.decode(stream)):
            if frame.pts is None:
                raise ValueError("Frame has no PTS")
            pts = float(frame.pts * frame.time_base)
            if first_pts is None:
                first_pts = pts
            elapsed = pts - first_pts
            if elapsed < warmup:
                continue
            if duration is not None and elapsed >= warmup + duration:
                break
            rgb = frame.to_ndarray(format="rgb24")
            row = {"index": index, "ptsSeconds": round(pts, 8),
                   "elapsedSeconds": round(elapsed, 8), **barcode.decode_barcode(rgb)}
            heads = extract_heads(rgb)
            row["detectedHeads"] = len(heads)
            row["medianHeadHeightPx"] = round(statistics.median(h["height"] for h in heads.values()), 5) if heads else None
            if previous_row is not None:
                diff = np.abs(rgb[:290].astype(np.int16) - previous_rgb[:290].astype(np.int16))
                row.update(motion_pair(previous_heads, heads, pts - previous_row["ptsSeconds"], output_fps))
                row["roiMeanAbsPixelDiff"] = round(float(diff.mean()), 5)
                row["roiPixelsChangedOver20"] = int(np.count_nonzero(np.max(diff, axis=2) > 20))
                row["frameIdDelta"] = barcode.wrapped_delta(row["frameId"], previous_row["frameId"])
            rows.append(row)
            previous_rgb, previous_heads, previous_row = rgb, heads, row
    result = {
        "video": str(video), "videoMetadata": metadata,
        "warmupSeconds": warmup, "durationSeconds": duration,
        "sourceFpsConfigured": source_fps, "outputFpsConfigured": output_fps,
        "barcodes": barcode.summarize(rows, {}, source_fps, output_fps),
        "noteMotion": summarize_motion(rows),
    }
    return result, rows


def synthetic_image(elapsed_ms: float) -> Any:
    """Analytical rectangle coverage provides a codec-free motion oracle."""
    import numpy as np
    rgb = np.zeros((390, 432, 3), dtype=np.uint8)
    for index in range(int(elapsed_ms // 120) - 4, int(elapsed_ms // 120) + 1):
        lane = index % 7 + 1
        head = (elapsed_ms - index * 120) * SPEED / 1000
        left, width = lane_geometry()[lane]
        ys = np.arange(290)
        coverage = np.maximum(0, np.minimum(ys + 1, head + 6) - np.maximum(ys, head - 6))
        rgb[:290, int(left + 3):int(left + width - 3), :] = (coverage[:, None, None] * 240).astype(np.uint8)
    return rgb


def self_test() -> dict[str, Any]:
    results = barcode.self_test()
    normal_rows = []
    injected_rows = []
    base_ms = 5000
    previous_normal = previous_injected = None
    # At output index 30, note pixels repeat despite an advancing barcode.
    # Index31 then catches up. This verifies that pixel tracking is independent.
    for index in range(90):
        normal = extract_heads(synthetic_image(base_ms + index * 1000 / 60))
        injected = extract_heads(synthetic_image(base_ms + (index - 1 if index == 30 else index) * 1000 / 60))
        if index:
            shared = {"index": index, "ptsSeconds": index / 60,
                      "frameId": index + 1, "frameIdDelta": 1, "roiMeanAbsPixelDiff": 0}
            normal_rows.append({**shared, **motion_pair(previous_normal, normal, 1 / 60)})
            injected_rows.append({**shared, **motion_pair(previous_injected, injected, 1 / 60)})
        previous_normal, previous_injected = normal, injected
    normal_summary = summarize_motion(normal_rows)
    injected_summary = summarize_motion(injected_rows)
    assert normal_summary["qualifiedPairs"] >= 70, normal_summary
    assert normal_summary["stoppedPairs"] == 0, normal_summary
    assert normal_summary["largeStepPairs"] == 0, normal_summary
    assert normal_summary["errorRmsPx"] < .05, normal_summary
    assert injected_summary["stoppedPairs"] == 1, injected_summary
    assert injected_summary["largeStepPairs"] == 1, injected_summary
    assert injected_summary["stoppedWithAdvancingCounter"] == 1, injected_summary
    results.update({"pixelMotionOracle": "passed", "smoothQualifiedPairs": normal_summary["qualifiedPairs"],
                    "independentFrozenPixelsDetected": True, "doubleStepDetected": True,
                    "smoothErrorRmsPx": normal_summary["errorRmsPx"]})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, nargs="?")
    parser.add_argument("--warmup", type=float, default=2)
    parser.add_argument("--duration", type=float, default=14)
    parser.add_argument("--source-fps", type=float, default=60)
    parser.add_argument("--output-fps", type=float, default=60)
    parser.add_argument("--av-libs", type=Path, help="Explicit alternate directory containing PyAV, if not installed in this Python")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--csv-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--contract", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return
    if args.contract:
        print(json.dumps(BARCODE_CONTRACT, indent=2))
        return
    if args.video is None:
        parser.error("video required except --self-test/--contract")
    if args.warmup < 0 or args.duration <= 0 or args.source_fps <= 0 or args.output_fps <= 0:
        parser.error("duration/fps must be positive and warmup nonnegative")
    result, rows = analyze(args.video, args.warmup, args.duration, args.av_libs,
                           args.source_fps, args.output_fps)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(encoded + "\n", encoding="utf-8")
    if args.csv_out:
        fields = list(dict.fromkeys(key for row in rows for key in row))
        with args.csv_out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    print(encoded)


if __name__ == "__main__":
    main()
