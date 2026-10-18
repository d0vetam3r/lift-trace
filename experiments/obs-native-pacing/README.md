# Native OBS pacing experiment

[한국어](README.ko.md) · [日本語](README.ja.md) · [English](README.md)

The live implementation now lives in [native/obs](../../native/obs/README.md). This directory retains the explicit synthetic benchmark build, disposable recording fixtures and analysis. Its empty-channel synthetic behavior is preserved; the live runtime build generates no synthetic notes. Legacy observer/Lua paths below are compatibility entry points. Do not install the benchmark DLL for live use.

This is an optional rendering experiment, **not a released replacement overlay**.
It tests whether drawing input-note geometry directly during OBS composition
avoids the repeated-frame/catch-up pattern observed in browser-source output.
Nothing in the normal Lift Trace executable, settings UI, input recorder,
automatic overlay control, Live Core, or Remote is changed by these files.
Lift Trace remains independently runnable. The first-at-most-four-minutes save
rule and next-round disposal of unsaved footage remain unchanged. This prototype
is not included in the normal application distribution.

See [Measured results](RESULTS.md) for the recorded comparison and its limits.

## Live input and the existing settings UI (Windows)

The optional launcher now observes the existing `Bridge.subscribe()` stream.
Its owned Node process imports the unchanged `web/client.js` `InputClient`,
`TrailEngine`, and `ScratchTracker`. It receives the same selected-controller
samples, key mapping, scratch axis/inversion/threshold/stop settings, resets,
and UI settings updates as the browser. It never writes back input records.

```text
python experiments/obs-native-pacing/live_launcher.py --node PATH_TO_NODE_EXE --channel lift-test
```

This experiment needs Python 3.10+, Node 22+ and a separately built native plugin.
Normal Lift Trace still runs without Node, the plugin, Live Core or Remote.
The launcher serves the **existing** UI at `http://127.0.0.1:8766/` and defaults to
isolated `artifacts/native-live-data` settings. Select the controller and use the
existing settings controls there. A copied settings JSON can be imported with
the existing UI; no second native rendering settings file is introduced.
Do not point simultaneous launchers at the same data directory.

Set the experimental OBS source's `Live channel` property to `lift-test`.
A separate connection worker retries unavailable publishers every 100ms,
so either side can start first. Diagnostics default off in live mode;
the existing synthetic comparison keeps them on. Restarting the producer with
the same channel resumes an already attached source with a new session.

The bridge publishes bounded snapshots through Windows session-local shared
memory. OBS tries the mutex with **zero wait**, then draws from unchanged event
timestamps using its own video-frame clock. A stalled, invalid or exited producer
clears input marks within one second; the existing UI and controller polling
continue. The observer ticks scratch-stop detection every 4ms, so its grace-period
release observation can precede a 60Hz browser callback by up to about one frame.
Raw controller timestamps and the existing grace policy are unchanged.

Keyboard head/body, short-input scaling, delay, 1P/2P, size, speed, guides and
background come from the existing UI. Scratch always retains its body and
direction colors/arrow, independent of keyboard shortening. Optional scene
placement and automatic visibility setup are described below. The launcher does
not migrate existing sources or recording targets. Test in a disposable profile
before any production migration.
Actual controller gameplay and end-to-end input latency remain separate checks;
see the live results in [RESULTS.md](RESULTS.md) before interpreting automated fixtures as hardware tests.

The source registers `lift_trace_native_pacing`. Build it as a separate OBS plugin
using the matching official OBS SDK (`obs-module.h`, `util/platform.h`, and
libobs). The C code uses C11 atomics and a small Windows connection worker;
it does not require C++. Connection handles are opened outside OBS's video thread.
Load it only in a disposable OBS installation with an isolated profile and scene.
Do not copy an experimental DLL into a normal OBS installation or release package.
The repository does not vendor OBS headers, libraries, or compiled binaries.
`CMakeLists.txt` is a reference build route for an official SDK and has not been
executed here. The recorded local test instead used Clang and a minimal local ABI
header; that header and local toolchain are not part of this experiment's source.

## Boundary

### Attach to an existing Lift Trace application

When the normal application already owns the input server, use
`live_observer.py --node PATH_TO_NODE_EXE --channel lift-test --port 8765`
instead of starting another `live_launcher.py`. This optional observer only
reads the existing loopback status and event stream. It starts no input poller,
UI, automation or recording service and never writes application settings.
On a lost or invalid stream it clears its snapshot, closes its owned Node child,
and reconnects with a fresh engine and the server's current state.

For OBS-owned startup, add `obs-native-observer.lua`, specify Python/Node paths,
the existing Lift Trace port and native channel, then enable its opt-in autostart.
It launches hidden without requesting elevation and verifies OBS's exact process
creation time; the observer and its child exit when that OBS process exits.
The existing application/helper still manages its own server and automation.
Do not start a second server on a port used by Lift Trace or Remote. An optional
status JSON contains connection/lifecycle metadata, never raw input or settings.
Removing or reloading the script does not terminate another process by guessed
PID; the original OBS lifetime remains the owner.

### Optional OBS placement and automatic visibility

In the disposable OBS installation, load `obs-native-layout.lua` as a script.
Set the same live channel as the launcher and a distinct native source name,
then use its add/bind button in the intended scene. A new native item starts
hidden; an existing item's visibility is preserved. The button resets scale,
crop, rotation, alignment and bounds for standard placement. Following settings
thereafter changes only its X/Y position; it preserves visibility, item order,
locking and other transforms. Disable following to keep manual positioning.

The existing settings UI supplies 1P/2P, LIFT and `obsOffsetX/Y`. The helper uses
the same 1920×1080 reference as `getObsPlacement`; output width/height continue
to follow the existing renderer settings. It reads a bounded shared-memory
header with zero-wait locking. No periodic file reads, socket requests or handle
opens run in the placement timer. Unavailable, stale or invalid data leaves the
last position unchanged. Either the helper or producer can start first, and a
producer restart on the same channel does not change item visibility.

The binding saves the scene UUID, scene-item ID, source UUID and live channel.
Renaming preserves the binding. Switching scenes never retargets it; replacing
a source/item or changing its channel requires explicit rebinding. An ambiguous
duplicate placement is rejected unless the exact item was already pinned.
A same-name browser source is never replaced. Rebuild the experimental plugin
along with the launcher: wire protocol v2 carries placement offsets and rejects
v1 packets instead of interpreting the former reserved bytes as offsets.

For automatic visibility, use the launcher's **existing** automatic control UI:
connect to the isolated OBS, select the game capture and the native overlay item,
save the selection, then start. The same detection, debounce and capture-recovery
policy applies to browser and native sources. Placement itself never starts
automatic visibility or turns an existing item on/off. Optional source-mode
automation dependencies are listed in [the development guide](../../docs/DEVELOPMENT.en.md).

Live Core remains optional and unchanged. A future recording migration must
explicitly select the new native item's identity in Core as well; creating or
renaming an overlay does not retarget an existing recording configuration.
The first-at-most-240-second cap and next-round unsaved disposal stay in Core.
This change does not install into or modify a running broadcast environment.

- With an empty live channel, synthetic keyboard events are rendered: a press every 120 ms, starting at
  index -3, lane `positiveMod(index, 7) + 1`, with a 40 ms hold. There is no
  controller access in this baseline mode. Live input uses the optional observer above.
- Existing normalized settings can be supplied as an OBS data object named
  `lift_settings`. This is a snapshot supplied by the test harness, not a second
  user settings file. Live mode takes normalized settings from the existing UI stream.
- `video_tick` takes the OBS video-frame clock and a settings snapshot. Rendering
  uses that snapshot rather than a separately scheduled browser animation clock.
  Settings updates use a short lock; file/pipe I/O and graphics stay outside it.
  Live shared-memory acquisition never waits. Zero/backwards synthetic clocks are handled without negative age.
- The native geometry uses the existing lane proportions, speed calculation,
  delayed display, head/body switch, and finished-short-input display rule.
  Event timestamps remain independent of those visual options. Work is bounded
  to the browser engine's 4,096-event limit even at very low configured speeds.
- This is geometry/temporal parity, not a promise of identical Canvas edge
  antialiasing, color handling, scratch marks, or transparency in every OBS mode.

Defaults are 432 × 290 notes plus 100 diagnostic pixels, 12 px heads, and
849.9266666666666 px/s. In the synthetic baseline the seven keyboard lanes are used; scratch has only its
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
| 4 | Synthetic: same as row 2; live: UTC animation milliseconds × 10, wrapped to 24 bits |
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
