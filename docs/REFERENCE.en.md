# Technical reference

[한국어](REFERENCE.md) · [日本語](REFERENCE.ja.md) · [English](REFERENCE.en.md)

[Home](../README.en.md) · [User guide](USER_GUIDE.en.md) · [Development](DEVELOPMENT.en.md) · [Validation](VALIDATION.en.md)

This document explains the prototype's model and constraints. It is not required to install the Windows app.

## Distributions and boundaries

The Windows ZIP contains a desktop launcher, the Python runtime and required application files, bundled runtime notices, public documentation, and optional OBS Lua/PowerShell integration. The source ZIP contains the same project's source, tests and build tools. It contains no installed Python runtime.

Neither distribution includes the iPad remote server, a combined streaming launcher, personal controller settings, machine-specific paths, OBS profiles, game binaries, music or game images. The schematic in the user guides is original project artwork.

The public OBS helper starts only the Lift Trace overlay. It does not search for or launch extra-service scripts beside the app.

The app is a loopback HTTP server and a Browser Source, not a native OBS DLL plugin. Settings are served at `http://127.0.0.1:8765/`; overlay output is at `http://127.0.0.1:8765/overlay.html`. Browser rendering and native acquisition are separate, so a native device continues supplying input after the settings tab closes.

## Speed model

The calculation assumes a fullscreen game on a **1920 × 1080 OBS canvas**, with the Browser Source at **100% transform scale**:

```text
reference lane height at 1080p = 723 px
visible lane height ≈ 723 × (1000 − LIFT − SUDDEN) / 1000
visible time ≈ green number / 600 seconds
speed (px/s) = visible lane height × 600 / green number × speed correction
```

LIFT + SUDDEN must be less than 1000. Example: LIFT 200, SUDDEN 300, green number 300 and correction 1 produce 723 px/s. Changing overlay height from 120 px to 360 px keeps this velocity and reveals a longer part of the input history.

This is a calibration approximation, not an official game API or an exact reproduction of every game pixel-rounding rule. The reference height was compared with a 1920 × 1080 capture. Input delay and speed correction solve different problems: delay shifts when an input note appears, while correction changes its velocity.

Overlay dimensions or cropping control the visible area. OBS's vertical transform scaling also scales the apparent velocity. Horizontal lane widths and 1P/2P layout affect horizontal alignment only.

Green number, LIFT, SUDDEN and BPM are not read from the game. The overlay does not automatically follow changes in actual game speed. Default settings are green number 300, LIFT 0 and SUDDEN 0, not a recommendation for any player's game.

The model's references are [KONAMI's speed-option explanation](https://p.eagate.573.jp/game/2dx/26/howto/play/option_speed.html) and [masaoblue's INFINITAS simulator analysis](https://note.com/masaoblue/n/n02ecb7426a76).

## Automatic and manual display height

The effective output height is separate from the saved manual height:

```text
heightMode = "auto" (default) or "manual"
auto height = max(1, round(723 × LIFT / 1000)) px
manualOverlayHeight = saved custom height, 40–2160 px
overlayHeight = effective height derived from the selected mode
```

For LIFT 401, automatic height is 290 px. This uses the same approximate 1080p lane reference as the speed model. It does not measure the captured game's geometry. Width remains configurable and defaults to 400 px for compatibility. The explicit 1080p lane-size preset sets it to the 432 px reference; it is not silently applied to existing settings.

LIFT 0 in automatic mode has no visible input area. The internal 1 px canvas is a transparent technical placeholder, not a recommended display height. The UI asks users to enter their game's LIFT or choose a manual height before checking falling input notes.

New settings and pre-release settings without `heightMode` use automatic mode. A previous `overlayHeight` (or legacy `liftHeight`) is retained as `manualOverlayHeight`; if no previous custom value exists, its fallback is 240 px. That fallback is not an instruction for the ordinary automatic setup. Switching modes preserves the saved manual choice. `overlayHeight` is derived, so code changing manual height must update `manualOverlayHeight` rather than overwriting the effective value.

Changing only the display-height mode or manual height does not change speed. Changing LIFT itself changes both its automatic display height and the speed formula, because it changes the game's visible lane length.

The settings page and overlay recalculate height, but **an existing OBS Browser Source is not resized automatically**. Copy its new height into OBS's Browser Source properties, or explicitly apply the optional OBS script's placement action. Vertical transform scaling is not a substitute.

## OBS position and the 1080p preset

`getObsPlacement()` returns the source's top-left corner in a 1920 × 1080 canvas. Use top-left alignment, 100% scale, no bounds scaling and zero cropping:

```text
reference lane width = 432 px
1P X = 75 + obsOffsetX
2P X = (1920 - 75 - 432) + obsOffsetX = 1413 + obsOffsetX
Y = 723 - round(723 × LIFT / 1000) + obsOffsetY
```

Example: LIFT 401 with no adjustments gives Y 433 and automatic height 290. X is 75 for 1P or 1413 for 2P. The 1P reference was checked against a fullscreen 1080p capture. The 2P reference is a mirrored estimate, not a verified measurement of a 2P capture. Different game geometry or a scaled/cropped capture requires calibration.

`obsOffsetX` and `obsOffsetY` are saved integer pixel adjustments, defaulting to 0. Positive X moves right and positive Y moves down. Their accepted ranges are −3840…3840 and −2160…2160 respectively. Position is anchored to the game lane reference, independent of custom output width, manual display height, green number and SUDDEN+. LIFT changes Y; 1P/2P changes X. A custom width does not recenter the source.

The **Match 1080p lane size** action sets `width = 432`, `scratchWidth = 5/3`, `blackKeyRatio = 7/9`, and both position adjustments to 0. It preserves game values, the selected side, input mapping, height mode and saved manual height. The width ratios yield a 90 px scratch lane, 54 px white-key lanes and 42 px black-key lanes. It is a deliberate setup action, not a migration applied to existing users.

The settings page supplies separate X/Y copy buttons. Changing settings only recalculates the values: **it does not move an existing OBS scene item**. Paste X/Y into Edit Transform, or explicitly invoke the optional OBS script's placement action. After changing LIFT, update both Browser Source height (when automatic) and Y position. A manual-height change updates height only.

## Meaning of each input note

The table describes the default display. The development version can change the appearance of key input using the settings below.

| Input | Display |
| --- | --- |
| Short key press | Falling input note whose length reflects the press duration. |
| Held key | Ribbon grows while held; after release, its tail falls away from the judgment line. |
| Clockwise turntable movement | ↻ and light coral (`#ffb4aa`); length reflects detected movement duration. |
| Counterclockwise turntable movement | ↺ and deep coral (`#e45470`); a direction change begins a separate segment. |
| Device loss | Active input states clear to avoid stuck held notes. |

A held key can look like a long note, but the tool cannot know whether the chart contains one. It cannot identify individual chart notes inside continuous scratch motion, distinguish long scratches using chart information, or report game judgments. Stopping a scratch is inferred after a short timeout. Input notes describe controller input history, not chart data.

Native input targets a polling interval near 4 ms. Drawing follows browser animation frames; the optional OBS script sets the Browser Source to 60 FPS. OBS output rate, scheduling, drivers and capture latency can limit the result. Synthetic demo smoothness does not establish actual capture synchronization.

### Key note bodies and brief input display (unreleased)

| Setting | Default · range | Behavior |
| --- | --- | --- |
| `inputBodyEnabled` | `true` · boolean | `false` shows only the heads for keys 1–7, with no bodies or tail caps. |
| `shortInputEnabled` | `false` · boolean | Shortens brief inputs visually when bodies are enabled. |
| `shortInputThresholdMs` | `200` · integer 1–2000 ms | Only released inputs with an actual duration below this value are shortened. |
| `shortInputPercent` | `30` · integer 1–100% | Percentage of the original visual length to keep. 100% keeps the original length. |

Heads-only mode applies to held and released keys of any duration. The single head created at press onset follows its original position, speed and display delay; holding a key does not generate repeated heads. Turning bodies off preserves the shortening settings. Scratch length and arrows, and the example game chart above the preview, stay unchanged.

With bodies enabled, shortening applies only once release is visible after the configured display delay. Inputs at or above the threshold and keys still shown as held keep their original length. These are rendering changes only: input start/end times, input history and the engine's original segments remain unchanged. They do not detect chart long notes.

The settings comparison shows an unsaved draft. **Apply and save** updates the live overlay and local settings; **Revert edits** restores the applied values. Older files missing the new settings use bodies on and shortening off, preserving the previous display.

## Controller support and guided setup

Windows native input uses WinMM joystick enumeration and polling. Button indices are zero-based. Scratch tracking expects a **wrapping absolute-position axis**; supported axis names and indices can differ by device. Keyboard-only modes and other scratch encodings may need a different adapter.

The guided setup collects one unique button for each key and requires releases between keys. It then asks for clockwise movement followed by counterclockwise movement, each viewed from above and checked separately. Both steps must identify the same wrapping axis with opposite movement signs. The clockwise sample determines the saved `scratchInvert` boolean: after applying it, direction `+1` means clockwise and `-1` means counterclockwise. Device axis signs do not define physical direction by themselves. The setup relies on the user following the two physical-direction prompts; it cannot detect a consistently reversed interpretation of both prompts.

Applying a reviewed result updates the ordinary configurable mapping. Canceling does not save a partial mapping; device changes or disconnects invalidate a draft. Retrying rotation setup keeps the seven key assignments and repeats both directions. Manual controls, including direction reversal, remain available for troubleshooting and unsupported detection cases.

One PHOENIXWAN was checked for seven buttons and bidirectional X-axis scratch during development. That basic input check does not validate the complete current setup wizard or establish compatibility with every firmware, controller mode or device. Simultaneous input with INFINITAS and exact game-capture synchronization remain to be validated for each setup. See [Validation](VALIDATION.en.md) for the recorded scope. The adapter reads input; it does not install drivers, change controller firmware or send game input.

Selected devices are not restored automatically during manual startup. OBS's helper can select a configured device number, default 0; -1 skips automatic selection. Device numbers may change after reconnection.

macOS/Linux can run the source demo and focused-page keyboard input, but Windows native input and OBS automatic startup are not supported there. The packaged desktop app is Windows x64 only.

## Optional OBS startup settings

The user guides cover a minimal automatic-start setup with defaults. These details are for custom configurations and troubleshooting.

1. Stop the standalone app, then open **OBS → Tools → Scripts → +** and choose `obs-lift-trace.lua` from the app folder.
2. Keep the Lua file, `start-obs-bridge.ps1` and `LiftTrace.exe` together. The helper prefers the adjacent executable. Source users without that executable can leave the Python path blank for detection or select their interpreter; OBS's Python scripting configuration is not used.
3. The local port defaults to 8765. If changed, it must also match the application and Browser Source URL. Do not change it merely to copy the address; the ordinary UI provides copy buttons.
4. Controller ID defaults to 0; -1 disables automatic selection. Choose the number shown by the settings page for another controller. Device numbers can change after reconnecting hardware.
5. **Start / connect input server** starts or reuses the local server for this OBS session. **Open input settings** opens its browser controls.
6. **Use the size set in Lift Trace (recommended)** is enabled by default. **Add overlay / apply placement** reads the saved app width and effective automatic/manual height, then creates or updates the named Browser Source at 60 FPS. If that checkbox is off, the script's separate width and height fields are used instead.
7. **Use the position calculated in Lift Trace (recommended)** uses the saved side, LIFT and position adjustments to calculate X/Y when **Add overlay / apply placement** is clicked. If disabled, the script's manual X/Y fields are used. It defaults to enabled for a new script configuration. Pre-release script settings with existing manual coordinates keep manual positioning until this option is deliberately enabled.

The placement action changes the named source in the current scene, places it above the other sources, resets transform scale to 100%, top-left alignment and no bounds scaling, clears cropping, and locks it. It applies X/Y from the selected app/manual positioning mode. It does not start streaming or recording. Later app edits do not automatically invoke this action, resize the Browser Source or move the scene item; update the Browser Source/transform fields or apply placement explicitly.

Scripts belong to scene collections. Register it in each collection where it is needed, and replace its registered path if the app folder moves. Removing the script or disabling automatic startup affects future launches; the ownership rules below still apply to an already started server.

For failures, check `data/obs-bridge-*.status`, `data/obs-bridge-*.stdout.log`, `data/obs-bridge-*.stderr.log` and, for device selection, `data/obs-controller-*.log`. Desktop diagnostics use `data/lift-trace.log`, with a possible `%TEMP%/LiftTrace/` fallback when the app folder is unwritable. Remove private paths and device information before sharing excerpts.

<a id="saved-automation-startup"></a>

## Optional saved automatic-visibility startup

First connect to OBS, save the targets and verify manual start in the settings page. Close OBS, create `obs-automation-autostart.json` in the helper data directory (normally `data/`), and save `{"enabled":true}` to opt in for the next OBS launch. A missing file or `false` leaves it disabled. Set `false` or remove only this preference file to disable future automatic starts; use Stop in settings to stop a running controller.

The helper requests connection and start only for a server it just created with a ready saved selection and reference. It leaves reused standalone servers, already connected/running automation and existing errors alone. Only acknowledged connection failures during OBS startup receive up to three attempts; start is requested once. A timeout or lost response never authorizes a duplicate request. Failure leaves the input server running and writes guidance to `data/obs-automation-<port>.log`. Later manual stops and runtime failures do not trigger a restart.

This is optional Lift Trace behavior without a Core, iPad remote or combined-launcher dependency. Standalone execution and server ownership stay unchanged. See [Development](DEVELOPMENT.en.md) for visibility recovery and `automation-events.jsonl` retention.

## Server ownership

| Startup situation | Who stops the server? |
| --- | --- |
| LiftTrace.exe creates a new server | Closing its manager window or choosing Quit stops that server. |
| LiftTrace.exe connects to an existing Lift Trace server | The manager leaves the existing server running. |
| OBS helper creates a new server | That OBS process exiting stops the server. |
| OBS helper finds an existing healthy Lift Trace server | It reuses it without taking ownership; exiting OBS leaves it running. |

Changing automatic-start settings or removing the OBS script affects later launches. A currently OBS-owned server remains tied to its owning OBS process. No path should terminate an unrelated process merely because it uses the same port.

## Settings and privacy

The default `data/` folder is beside the extracted app or source. `settings.json` stores overlay configuration; `desktop.json` stores the desktop window's language. Runtime diagnostics may contain local paths or device details.

The app binds to `127.0.0.1` only and does not require an account or contact an external service for normal operation. It is intended for OBS and a browser on the same PC. Do not expose it as a public network service. See [Security](../SECURITY.en.md) before sharing diagnostics.

