# Isolated renderer pacing analysis

This directory analyzes synthetic OBS recordings offline. It does not launch OBS, contact services, send input, or modify recordings.

Use Python 3.10 or later with NumPy and PyAV installed. If PyAV is in a separate directory, explicitly pass `--av-libs PATH_TO_PYAV_DIRECTORY`. There is no machine-specific default path or dependency on another project. The in-memory self-test needs NumPy but not PyAV.

```powershell
python -B analyze_native_pacing.py --self-test
python -B analyze_native_pacing.py --contract
python -B analyze_native_pacing.py recording.mkv --warmup 2 --duration 20 --json-out result.json --csv-out frames.csv
```

Compare the same central time window of each completed A/B/A/B recording, excluding startup and stop/flush frames. The expected fixture is 432 × 390 at 60 output fps. Notes occupy the first 290 rows, with 12 px heads moving down at 849.9266667 px/s (723 × 529 / 1000 × 600 / 270), one event every 120 ms through keyboard lanes 1–7. Each lane has no overlapping heads in this ROI.

The five barcode rows retain the original decoder field names for compatibility. For the native source, `rafStamp10` denotes the OBS frame timestamp and `wallElapsed10` denotes animation elapsed time. Clock epochs must be documented by the producer; subtracting callback and source clocks is meaningful only when they share an epoch. Compare motion and sequence deltas rather than cross-renderer absolute times.

The analyzer independently tracks the centroid of actual bright note head pixels. A transition qualifies when at least two same-lane heads match, their displacement spread is at most 1.25 px, and the adjacent output timestamp difference is under 25 ms. It reports qualification coverage and all observed stops/large steps. A counter that continues advancing while the actual notes freeze is still detected by the image analysis.

`errorRmsPx` compares against encoded PTS spacing; `nominalErrorRmsPx` compares against the expected 60 fps step. The latter avoids treating Matroska's millisecond rounding (16/17 ms) as rendered motion jitter. Both include rasterization/codec measurement error. Barcodes alone are insufficient evidence that note motion is smooth.

The self-test includes an analytically antialiased smooth sequence and an injected pixel freeze/catch-up while the counter advances normally. A prior recorded browser trial was also independently checked: all 839 transitions qualified, and both repeated frames plus both catch-up steps matched the barcode anomalies.

Generated result JSON includes the input filename, which may be a private absolute path. Keep results, CSVs, recordings and logs outside the public source tree. Publish only deliberately reviewed aggregate measurements.

These short synthetic recordings can establish a difference under their test conditions. They cannot establish perfect behavior under every real game/GPU load or complete integration with live controller events.
