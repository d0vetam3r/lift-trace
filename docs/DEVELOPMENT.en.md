# Development

[한국어](DEVELOPMENT.md) · [日本語](DEVELOPMENT.ja.md) · [English](DEVELOPMENT.en.md)

[Home](../README.en.md) · [Contributing](../CONTRIBUTING.en.md) · [Validation](VALIDATION.en.md) · [Releasing](RELEASING.en.md)

This document is for contributors. **Windows app users can follow the [user guide](USER_GUIDE.en.md) without installing development tools.**

The repository and `lift-trace-source-<version>.zip` are the source of the Windows app. The executable package is the same app with a bundled runtime, so users can run it without a development environment.

## Run from source

Requirements:

- **Python 3.10+**. The desktop manager uses Tkinter, normally included in the Windows Python installer.
- **Node.js 18+** for JavaScript tests only.
- Windows for native controller input and OBS automatic startup; OBS Studio for manual integration checks.

Existing controller input and the manual OBS overlay need no third-party Python or npm packages. For optional automatic visibility from source, first run `python -m pip install -r requirements-automation.txt` to install `websocket-client==1.9.2` and `Pillow==12.3.0`. Ordinary input and the manual overlay still work without these dependencies. Windows app builds bundle them; app users do not need an installation command. From the source root:

```sh
python desktop.py
```

This opens the same desktop manager used in the Windows app and a browser settings page. Alternatively, run only the server:

```sh
python server.py
```

Then open `http://127.0.0.1:8765/`. Ctrl+C stops this foreground server. `start.bat` remains a convenience for source users; it is not the installation route in user documentation. `bash start.sh` supports the demo/focused-page keyboard path on macOS/Linux, without native controller input or OBS startup support.

The packaged executable supports a headless mode used by the OBS helper; its source equivalent is:

```sh
python desktop.py --serve --port 8765 --data-dir data
```

Use a writable `--data-dir` for isolated checks. The manager supports `--language en`, `--language ko` and `--language ja`; the settings page accepts `?lang=en`, `?lang=ko` and `?lang=ja`.

## Test

```sh
python -m unittest discover -s tests -p "test_*.py" -v
npm test
```

Some Python tests open temporary loopback listeners. A restricted environment must permit them. Tests use synthetic input, so they require no controller and cannot verify physical compatibility or game-capture synchronization.

`.github/workflows/verify.yml` runs these checks on Windows and Ubuntu with Python 3.10/3.13 and Node 22. A manual run of this verification workflow also builds Windows artifacts but does not publish a release. The separate `.github/workflows/release.yml` publishes a GitHub Release from main only after tests, a provenance-verified build, smoke checks and asset verification pass. See [Releasing](RELEASING.en.md) for triggers and failure recovery. [Validation](VALIDATION.en.md) separates historical runs from current evidence. Cross-platform test success does not add native controller support to non-Windows systems.

## Structure

| Path | Responsibility |
| --- | --- |
| `desktop.py` | Desktop manager, localized startup/errors, server ownership, frozen-app paths and headless entry. |
| `server.py` | Loopback HTTP, SSE, settings and shared demo timing. |
| `native_input.py` | Windows WinMM enumeration and controller polling. |
| `web/engine.js` | Input history, scratch tracking and elapsed-time falling positions. |
| `web/games/infinitas.js` | INFINITAS geometry, speed and OBS placement calculations for normalized settings. |
| `auto_visibility.py` | Gameplay policy and adapter for selected OBS scene items. |
| `automation.py`, `web/automation.js` | Explicit connection, target selection and start/stop UI; automation work separate from input polling. |
| `obs_connection.py`, `infinitas_detector.py` | Local OBS WebSocket v5 connection and fixed INFINITAS SCORE-region detection. |
| `assets/infinitas-score-1080p.png` | 90 × 20 SCORE reference, included in the source-distribution allowlist and Windows PyInstaller data. |
| `tools/replay_visibility.py` | Replay synthetic observations through the visibility policy and print JSONL request records. |
| `web/render.js` | Canvas renderer shared by preview and overlay. |
| `web/client.js` | Server events, settings and input-mode coordination. |
| `web/index.html`, `web/app.js` | Settings page, preview and guided setup UI. |
| `web/setup.js` | Controller setup state machine, button releases, separate clockwise/counterclockwise checks, axis/polarity detection and draft validation. |
| `web/i18n.js`, `web/translations.js` | English, Korean and Japanese UI, language selection. |
| `web/overlay.html`, `web/overlay.js` | Browser Source output. |
| `web/demo.json` | Synthetic demonstration; no game chart or game asset. |
| `obs-lift-trace.lua` | Optional OBS settings, startup and source placement. |
| `start-obs-bridge.ps1` | Hidden startup, adjacent-EXE selection, server reuse and OBS ownership. |
| `tests/` | Python protocol/lifecycle/input and JavaScript behavior tests. |
| `tools/build_release.py` | Explicit source-distribution allowlist, manifest and archive checksums. |
| `tools/build_windows.py`, `requirements-build.txt` | Windows packaging and pinned build-only dependencies. |
| `tools/prepare_runtime.py`, `tools/python-runtime.json` | Download and extract the pinned official Windows Python and its published provenance files into the workspace. |
| `tools/runtime_provenance.py` | Verify official archive metadata, extracted files and packaged runtime binaries. |
| `tools/smoke_windows.py` | Extracted Windows ZIP startup and synthetic OBS-parent lifecycle checks. |

The settings page is a client of the server, not the owner of native input polling. Closing a browser tab must not stop native input. The desktop manager and OBS helper own only the server processes they created; reuse never transfers shutdown ownership.

## Optional INFINITAS automatic visibility

0.2.0 includes optional experimental visibility control using a local OBS WebSocket client, target-selection UI and SCORE-region detector. Lift Trace runs independently without Core or a remote control. See the [user guide](USER_GUIDE.en.md#optional-automatic-visibility) for setup. INFINITAS geometry, speed and placement calculations live in `web/games/infinitas.js`; existing settings, function names and results are preserved.

The first profile confirms entry using the SCORE region `(170, 953, 90, 20)` of an unscaled 1920 × 1080 original source. It uses bundled `assets/infinitas-score-1080p.png`, with a valid existing local reference preferred and never overwritten. After 0.2 seconds of fresh SCORE matches, it retains the fixed BPM-label region `(1414, 998, 55, 15)` in memory. That label can maintain already confirmed gameplay when FULL COMBO replaces SCORE; it cannot initiate a new play session. It does not read numeric BPM, song names or charts. Stop, mismatch, invalid images/timestamps, connection errors or an observation gap beyond 2 seconds clear the retained marker. Scope remains one tested 1P layout, including pre-song play UI, without guarantees for 2P, DP, arbitrary skins, resolutions or HDR. Screenshots and the BPM reference are not written to disk.

`auto_visibility.py` is an internal experimental contract, not a stable third-party plugin API. The detector has `start()` / `observe()` / `stop()`; the session has `start()` / `tick()` / `stop()`. Observations carry a monotonic timestamp and `UNKNOWN` / `PLAYING` / `NOT_PLAYING`. By default, 0.2 seconds of gameplay enables selected items and 0.3 seconds of non-gameplay hides them. Observation requests run at most 5 Hz, one at a time, without queuing catch-up work. Native input polling is unchanged.

An otherwise valid classified frame arriving more than 0.5 seconds late is discarded while polling continues. Confirmed visibility can survive up to 2 seconds from the last fresh observation, but the stall never counts toward entry or exit confirmation. Gaps between fresh frames and fresh OBS capture-unavailable responses (`GetSourceScreenshot` code 702, `capture-unavailable`) use the same policy. These responses or intermittent unconfirmed frames do not extend an ongoing recovery grace. On the first processing step beyond that grace, items are hidden; fresh non-gameplay must then be confirmed for 0.3 seconds before another gameplay entry. Synchronous capture can delay that check, so this is not a timer guaranteed to hide exactly at 2 seconds. Other unknown states hide immediately without clearing an ongoing recovery grace. Malformed images/timestamps and connection/target failures retain their error handling. Manual `stop()` leaves current visibility unchanged.

The OBS adapter controls 1–8 selected top-level items after checking scene UUID, scene item ID and source UUID. The original capture item stays visible and is excluded from targets. The UI displays actual OBS scene/source names, with upper/lower list-position labels for duplicate placements of one source. Internal identifiers remain in use for control but are not displayed. Checking or unchecking changes the automation target list without deleting OBS sources. Groups and nested scenes are outside the current scope. OBS requests are not an atomic batch: some items may change before a failure. Failure marks the applied state unknown and stops automation. Hiding cannot be guaranteed while OBS is disconnected.

Reopening the page or refreshing the list uses `GET /api/automation/catalog` to restore actual names and the saved selection. This read neither stops automation nor reconnects. First-time setup is connect to OBS → select and save the scene, original and targets → start automatic visibility. Supported scope and competing-controller guidance belong in collapsed help.

Capture and detection run on a worker separate from input polling. The OBS password and selection are stored in `automation.json` in the data directory; an existing personal reference is `automation-template.png`. The password and personal reference are excluded from general settings responses, events, settings export and public distribution. The bundled reference containing only the SCORE label is a separate distribution asset. The default `data/` directory is ignored by Git; do not commit a custom data directory either. This local file is not an encrypted password vault.

Manual app launches and fresh installations require an explicit automatic-visibility start. The optional OBS-helper preference in the [reference](REFERENCE.en.md#saved-automation-startup) applies only to a server newly created by that helper. Core or a separate combined launcher is not required. There is no mandatory Advanced Scene Switcher acknowledgement or `exclusiveControl` start condition. Help explains conflicts with rules controlling the same items; the app does not stop other programs. A runtime disconnect or scene-collection change stops automation without automatic reconnect or replay. Reconnect, review and save the selection, then start again. The startup helper also respects a later manual stop.

Visibility start/stop, connection, error/recovery and play/visibility transitions are recorded in `data/automation-events.jsonl` with UTC timestamps and bounded diagnostic metadata. Normal frames are not logged individually. Keep only the current file and one previous `.1`, at most 256 KiB each. A dedicated writer and 64-record queue separate disk work; full queues or write failures drop diagnostics without interrupting control. Shutdown waits at most 0.2 seconds for this writer. Logs exclude screenshot pixels, request/response bodies, passwords, exception messages and scene/song names. Other startup logs may contain personal paths, so inspect them before sharing.

To inspect the policy from source without OBS, run:

```sh
python tools/replay_visibility.py
```

Synthetic observations and fake OBS responses produce results and requests as JSONL (one JSON object per line). This does not test image recognition or real OBS behavior. An optional argument accepts a JSON file containing an observation array.

Automated tests, synthetic images, real OBS operation, simultaneous gameplay and packaged execution are separate evidence. Refer to [Validation](VALIDATION.en.md) for completed checks and remaining performance, recovery and distribution checks. Wiring up the code does not establish verification on real equipment.

BMS and an external plugin loader are not implemented. Scope implementation after a real user's player, skin, input method and verification fixtures are available. Adding a detector alone does not establish compatible input, lane layout or scrolling.

## Design constraints

- Keep native input acquisition independent of browser focus.
- Express motion in elapsed time, not frames. Overlay height must not change velocity.
- Keep `manualOverlayHeight` separate from the effective `overlayHeight`. Automatic mode derives height from LIFT; missing legacy modes migrate to automatic without losing the previous manual value. LIFT 0 must render no visible input-note area.
- Keep `getObsPlacement()` and OBS Lua placement calculations consistent: fixed 75/1413 X origins, Y from LIFT and 723 px reference, then saved integer offsets. Custom width/manual height must not shift the origin. The 2P origin is a mirrored reference, not confirmed capture geometry.
- Apply the 1080p width/ratio preset only on explicit user action. Preserve game values, side, input mapping and manual height; reset only position offsets along with lane sizes.
- Scene placement changes only on explicit OBS apply or user transform edits. Preserve existing script manual X/Y when introducing the app-position option.
- Preserve actual input semantics: a long hold does not identify a chart long note.
- Apply `inputBodyEnabled` and brief-input shortening only during rendering. Preserve input history, start/end times, engine segments, scratches and the example game chart. Keep shortening values when bodies are disabled, and keep settings drafts separate from the live overlay until Apply and save.
- Handle button release, axis wraparound and device loss without stuck input states.
- Keep manual mapping configurable; guided setup must not assume one controller's button IDs or scratch-axis sign. Normalize scratch direction to `+1` clockwise and `-1` counterclockwise with `scratchInvert`.
- Check clockwise and counterclockwise movement separately on the same wrapping axis. Retrying direction setup keeps the seven keys but clears both direction samples. Prompts describe directions as viewed from above. The physical meaning depends on following those prompts.
- Keep the clockwise ↻ / counterclockwise ↺ arrows and distinct light/deep coral colors consistent in both overlay and preview. Direction changes must remain visible in adjacent scratch segments.
- Apply guided mapping only after review. Cancel, disconnect and device changes must not save an incomplete draft.
- Bind to loopback only and keep settings private and local.
- Keep unrelated integrations, personal paths and private OBS configuration outside both public artifacts.
- The public OBS helper starts only the overlay. It must not discover or launch unrelated service scripts placed beside it.
- Give ordinary users one executable entry point. Do not add a Python, pip or terminal step to the user installation path.

See [Technical reference](REFERENCE.en.md) for the speed model, compatibility evidence and input-display limitations.

## Build the Windows app

Build on **Windows x64**. The public Windows build uses the official **Python 3.13.16 x64** distribution pinned in `tools/python-runtime.json`. An existing Python 3.10+ can run the preparation command. Source execution still supports Python 3.10+; ordinary app users receive the runtime in the ZIP.

Start in a clean checkout without an existing `.venv-build`. The preparation command downloads Python and its matching metadata from python.org, checks the pinned hashes and extracts it under `artifacts/python-runtime/`. It does not install Python system-wide or change PATH, registry entries or file associations.

```powershell
python tools/prepare_runtime.py
artifacts\python-runtime\python\python.exe -m venv .venv-build
.venv-build\Scripts\python -m pip install -r requirements-build.txt
.venv-build\Scripts\python tools\build_windows.py --require-verified-runtime
python tools/smoke_windows.py
```

The Windows ZIP contains a `LiftTrace/` folder with `LiftTrace.exe`, its `_internal/` dependencies, OBS scripts, documentation and third-party license notices. Keep that directory structure intact. A source-only archive can be built without PyInstaller:

```sh
python tools/build_release.py
```

The default output directory is `artifacts/`; the source builder also accepts `--output-dir PATH`. The smoke script accepts an optional ZIP path. Build final source and binary from the same revision, then check the [release checklist](RELEASING.en.md).

Keep `artifacts/python-runtime/downloads/` beside the extracted `python/` folder while building. It contains the pinned archive, official Windows manifest and SPDX software bill of materials (SBOM), which identifies the distribution's components. The builder compares the extracted originals with the official ZIP and checks the packaged DLL/PYD files against those originals. Do not reuse a virtual environment created from another Python installation; create a fresh build environment instead.

`--require-verified-runtime` stops the build if runtime provenance remains unresolved. An ordinary prototype build can report unresolved components, but that is not a successful publication check. See [Validation](VALIDATION.en.md) for completed runs. The source ZIP does not bundle a Python runtime.

## Manual verification

Use [Validation](VALIDATION.en.md) for the current evidence, a first-time-user check and a short report template. Keep observed results separate from planned checks. AI review or synthetic input cannot confirm physical direction, game timing or natural language quality for actual readers.

For a UI change, walk through the user guide from a newly extracted Windows ZIP, including the language selector, guided setup cancel/apply, input preview, OBS URL copy and settings export/import. Check the small desktop window separately from the browser. Do not require a terminal to recover from a typical startup failure.

For timing changes, test short/held keys, chords, repeated taps, both scratch directions, a reversal, disconnection and two manual overlay heights with the same speed. Check black/transparent backgrounds and 1P/2P layouts. Also verify LIFT 401 gives automatic height 290, mode changes preserve the saved manual height, LIFT 0 shows no automatic input-note area, and legacy settings migrate without losing the custom value. Set a positive LIFT or a manual height before visually checking the synthetic demo.

For position changes, check 1P/2P, LIFT 0/401/999, positive/negative offsets, and invariance under custom width/manual height/green/SUDDEN edits. Verify the 1080p preset preserves input mapping and game values while resetting offsets. Check width/height copies in Browser Source properties separately from X/Y copies in Edit Transform. Test new app-position defaults, old manual-position migration and all app/manual size/position combinations in OBS Lua. Applying placement must use top-left alignment, 100% scale, no bounds scaling and zero crop. UI settings changes alone must not move an OBS scene.

For lifecycle changes, test a new standalone server and a preexisting server that must survive manager closure. Test idle OBS starting its own server and stopping it on exit, then repeat with a standalone server that must remain. Verify both packaged-EXE selection and source-Python fallback. Do not start streaming or recording to perform this check.

For controller changes, test both device axis polarities through the complete clockwise-then-counterclockwise setup. Check same-direction rejection, ambiguous axes, wraparound, retry, cancel, reload and direction changes in displayed notes. Record the model, mode, Windows axis/button details and exactly what was tested. Distinguish ordinary device input checks from simultaneous use with INFINITAS and captured timing. The automated packaged smoke check uses a synthetic parent and does not replace actual OBS or hardware checks.

## Licenses and release hygiene

Project code is MIT licensed. Python, Tcl/Tk, PyInstaller's redistributed components and any other bundled runtime files keep their own applicable terms. The Windows builder collects notices; review them rather than describing the entire executable as solely MIT.

The runtime pin connects the downloaded distribution to its official manifest and SBOM; the binary comparisons connect the packaged runtime to that distribution. Notice collection uses the matching component information. The package retains the SBOM as `provenance/python-runtime.spdx.json` and records source URLs, hashes and binary mappings in `MANIFEST.json`. The upstream SBOM also describes tools and dependencies for other platforms; its full package list is not a list of everything bundled in Lift Trace.

`bundledRuntime.runtimeProvenanceVerified` records traceability to the official distributor, not an independently reproduced build, security audit or legal certification. Keep unresolved components visible in the manifest until evidence supports the match. A successful ordinary build or CI artifact does not substitute for the publication check.

To change the release runtime, review the new official archive, manifest and SBOM together before updating `tools/python-runtime.json`. Use a new runtime directory and build environment, rerun provenance and package checks, then update the recorded validation. Do not replace a failed hash check with a newly calculated hash merely to make the download pass.

The release builders use explicit source lists. Do not replace them with a recursive copy of the checkout. Exclude `data/`, logs, caches, virtual environments, user settings, private paths, OBS profiles, credentials, game files and captures. New public documents or tests must be added to the appropriate allowlist.
