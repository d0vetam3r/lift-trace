# Native OBS pacing experiment

[한국어](README.ko.md) · [日本語](README.ja.md) · [English](README.md)

This is a synthetic rendering experiment, **not a replacement gameplay overlay**.
It tests whether drawing input-note geometry directly during OBS composition
avoids the repeated-frame/catch-up pattern observed in browser-source output.
Nothing in the normal Lift Trace executable, settings UI, input recorder,
automatic overlay control, Live Core, or Remote is changed by these files.
Lift Trace remains independently runnable. The first-at-most-four-minutes save
rule and next-round disposal of unsaved footage remain unchanged. This prototype
is not included in the normal application distribution.

See [Measured results](RESULTS.md) for the recorded comparison and its limits.

The source registers `lift_trace_native_pacing`. Build it as a separate OBS plugin
using the matching official OBS SDK (`obs-module.h`, `util/platform.h`, and
libobs). The C code uses C11 atomics; it does not require C++ or a worker thread.
Load it only in a disposable OBS installation with an isolated profile and scene.
Do not copy an experimental DLL into a normal OBS installation or release package.
The repository does not vendor OBS headers, libraries, or compiled binaries.
`CMakeLists.txt` is a reference build route for an official SDK and has not been
executed here. The recorded local test instead used Clang and a minimal local ABI
header; that header and local toolchain are not part of this experiment's source.

## Boundary

- Only synthetic keyboard events are rendered: a press every 120 ms, starting at
  index -3, lane `positiveMod(index, 7) + 1`, with a 40 ms hold. There is no
  controller access, scratch implementation, input subscription, or real UI bridge.
- Existing normalized settings can be supplied as an OBS data object named
  `lift_settings`. This is a snapshot supplied by the test harness, not a second
  user settings file. A future integration would send these same settings from
  the existing UI; this experiment does not implement that integration.
- `video_tick` takes the OBS video-frame clock and a settings snapshot. Rendering
  uses that snapshot rather than a separately scheduled browser animation clock.
  Settings updates are protected by a short lock; no I/O or graphics call occurs
  while the lock is held. Zero/backwards clocks are handled without negative age.
- The native geometry uses the existing lane proportions, speed calculation,
  delayed display, head/body switch, and finished-short-input display rule.
  Event timestamps remain independent of those visual options. Work is bounded
  to the browser engine's 4,096-event limit even at very low configured speeds.
- This is geometry/temporal parity, not a promise of identical Canvas edge
  antialiasing, color handling, scratch marks, or transparency in every OBS mode.

Defaults are 432 × 290 notes plus 100 diagnostic pixels, 12 px heads, and
849.9266666666666 px/s. The seven keyboard lanes are used; scratch has only its
reserved lane width. For comparable footage, use 432 × 390 at 60 fps, with no
rescaling, and an opaque background. The diagnostic barcode needs at least 336
pixels of width; other normalized widths are not part of this pacing comparison.

## Diagnostics and interpretation

Five 24-bit rows use 10 × 14 px cells at `x = 8 + bit * 12`, least-significant bit
first. At the default height their row tops are 300, 318, 336, 354, and 372.
Each row has white/black calibration rectangles at x=308 and x=324.

| Row | Native value |
| --- | --- |
| 1 | OBS video-tick sequence |
| 2 | OBS animation elapsed time in tenths of a millisecond |
| 3 | Tick callback OS elapsed time in tenths of a millisecond |
| 4 | Animation elapsed time in tenths of a millisecond, same as row 2 |
| 5 | Previous render callback CPU cost in microseconds |

Row 2 begins at zero on the first initialized OBS video tick; row 3 begins at
zero on the first callback. They share an origin when the first tick supplies a
valid OBS clock, as expected in this test. An initial zero OBS clock would delay
row 2's origin; their difference is not a measurement of absolute clock phase.
The render cost excludes
GPU completion and video encoding. Multiple render calls may legitimately reuse
one tick; independent pixel motion and output PTS must be checked as well as the
counter. A passing small synthetic comparison is not proof of gameplay behavior
or immunity to OBS/GPU overload.

## Geometry regression

Build `geometry-test.c` as a separate shared library. It has no OBS dependency and
exports `pacing_geometry_tests` and `pacing_geometry_sample`. Then run:

```text
python check-geometry.py path/to/geometry-test.dll --node path/to/node
```

The check covers clock startup/reversal, bounded work, and 420 vectors generated
by calling the actual `web/engine.js` and `web/render.js` code. Those vectors cover
head-only/body display, short-input scaling and its strict threshold, display
delay, 1P/2P placement, before-press/active/released/pruned states, and unchanged
source timestamps. It launches no OBS process and accesses no personal settings.

## License and API references

Newly authored experiment source uses the repository's MIT license
(`SPDX-License-Identifier: MIT`). OBS components retain their separate
GPL-2.0-or-later license. Consult the accompanying component licenses when
building, linking, or distributing a plugin; the source license here does not
replace those licenses. No compiled plugin is distributed by this experiment.

- [OBS source callbacks](https://docs.obsproject.com/reference-sources)
- [OBS 32.1.2 API declarations](https://github.com/obsproject/obs-studio/tree/32.1.2/libobs)
- [OBS 32.1.2 graphics interface](https://github.com/obsproject/obs-studio/blob/32.1.2/libobs/graphics/graphics.h)
