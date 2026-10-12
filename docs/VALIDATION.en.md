# Validation status

[한국어](VALIDATION.md) · [日本語](VALIDATION.ja.md) · [English](VALIDATION.en.md)

[Home](../README.en.md) · [User guide](USER_GUIDE.en.md) · [Development](DEVELOPMENT.en.md) · [Contributing](../CONTRIBUTING.en.md)

This record separates evidence for the **public 0.1.0 prototype and unreleased development source**. It separates automated and AI-assisted checks from testing that requires a person or physical hardware. A passing check supports only the behavior and environment it exercised; it does not certify the product.

## Unreleased: INFINITAS automatic visibility connected to the app

On 2026-10-13, development source with local OBS connection, SCORE-region detection and target-selection UI was checked. The table separates the local `0.2.0-dev.1` package, `0.2.0-dev.2` UI source and subsequent `0.2.0-dev.3` bundled-reference source evidence. **Public v0.1.0 and its ZIPs are unchanged.**

| Evidence | Observed result | Limits |
| --- | --- | --- |
| `0.2.0-dev.3` bundled-reference source and mocked UI | Python 130 and JavaScript 77 checks passed. Mocked APIs confirmed fresh setup through connect→save selection→start without a registration request. Existing personal references stayed preferred; disconnected state blocked start, and a missing reference showed fresh-extraction guidance. All three locales had no overflow or JavaScript errors at 390px and 1440px. | Not a new package build or actual OBS-control check. Local evidence: `bundled-reference-ui/result.json`. |
| Offline recheck of the bundled SCORE reference | With the same 90 × 20 reference and current detector, 306 existing original screenshots yielded 7 play-UI detections (6 excluding the reference original) and no false positives among the other 299. The 24 extracted recording frames retained the previous 13 detected and 11 not detected classifications. | One 1P layout using material already involved in reference selection, not an independent accuracy estimate. Includes temporary entrance-animation misses; 2P, DP, HDR, other layouts and live gameplay remain unverified. The full continuous video was not rechecked. Local evidence: `bundled-reference-validation/result.json`. |
| `0.2.0-dev.2` UI-source changes | Python 124 and JavaScript 77 checks passed. A mock manager confirmed catalog reads without stopping execution or writing settings. A headless browser with mocked APIs restored running selections and actual names using GET only, showed duplicate positions instead of internal IDs, completed stop→uncheck→save→start without acknowledgement, and required explicit scene/original selection on first connection. All three locales had no horizontal overflow at 390px or JavaScript errors. | Source and mocked UI checks, not a new `dev.2` ZIP build/run or actual OBS control. Local UI evidence: `automation-ux-review/result.json`. |
| Local `0.2.0-dev.1` source and Windows ZIP | Python 120 and JavaScript 76 checks passed, and the build passed strict runtime-provenance verification. The extracted ZIP ran without external Python; `/api/automation` reported available and initially disconnected, and OBS-helper lifecycle checks passed. | Packaging and basic execution evidence for this build. Not a clean-PC, live-game, physical-device or actual OBS-rendering check. |
| 24 still frames extracted from a recording | Recorded classification scores for the fixed 1080p SCORE region. Sampled play UI and result frames were distinguished; two entrance-animation samples temporarily classified as non-play. | Selected samples from one recording. This does not establish flicker suppression on continuous video or performance during actual gameplay. Detection includes pre-song play UI. |
| Actual OBS 32.1.2 with recorded still frames | Confirmed play ON → result OFF → ON again, visibility retained on manual stop, fresh observation after restart, stopping without retry after connection failure, and result-screen OFF after explicit reconnect. Controlled two cameras, the overlay and the duplicated gauge while the original game and audio items stayed enabled. | Actual OBS requests and item states were checked. This was neither live gameplay nor continuous video playback, and did not assess audible output or physical camera image quality. |
| `0.2.0-dev.1` headless browser with a mocked automation API | Confirmed connection, duplicate gauge selection by item ID, reference capture, start/stop, the then-current connection/acknowledgement button guards, password-field clearing and absence from browser storage. Korean/Japanese switching and text wrapping were checked; no JavaScript errors occurred. | UI requests and presentation were checked. This test itself did not exercise actual OBS or first-time-user usability. |

Earlier local evidence is retained in `live-obs-results.json`, `recorded-frame-results.json`, `artifacts/ui-smoke/result.json` and UI screenshots. Personal recordings, personal references and OBS settings are excluded from public distribution. The bundled SCORE-label reference is a separate distribution asset. Synthetic-observation/mock-OBS policy tests and actual connection checks are separate evidence.

These results do not establish sustained performance with the game, OBS and controller together, normal song completion and transitions, other layouts/2P, or final-package execution on a clean PC. BMS and an external plugin API/loader are not implemented. See the [user guide](USER_GUIDE.en.md#optional-infinitas-automatic-visibility-unreleased) and [Development](DEVELOPMENT.en.md) for setup, recovery and implementation scope.

## Runtime provenance checked

On 2026-10-12, a complete Windows build passed `--require-verified-runtime` using the pinned official Python 3.13.16 x64 distribution. The check matched the official archive, Windows manifest and SPDX SBOM, verified 3,159 extracted original files, and compared every packaged DLL/PYD with the corresponding official runtime files. The resulting manifest records `bundledRuntime.runtimeProvenanceVerified: true` with an empty `unverifiedComponents` list.

This closes the earlier gap in identifying the supplied libffi and XZ binaries. The official SBOM identifies libffi 3.4.4 and XZ/liblzma 5.2.5; the Windows runtime's mpdecimal 4.0.0 entry is also matched. The package includes 16 license/notice files, the official SBOM at `provenance/python-runtime.spdx.json`, and source URLs, hashes and binary mappings in `MANIFEST.json`.

The result establishes traceability to the official distributor and file integrity. It is not an independently reproduced build, security audit, legal certification or confirmation of application quality. A build using another Python distribution can still report unverified provenance. The source ZIP bundles no runtime. Follow [Releasing](RELEASING.en.md) to repeat the check on the package being published.

## Recorded evidence

The Python, JavaScript, runtime-provenance and packaged-app results below were refreshed on 2026-10-12. The OBS Lua row retains earlier development evidence with its scope stated. Maintainers must check the exact package they intend to publish.

| Check | Recorded result | Scope and limits |
| --- | --- | --- |
| Python tests | 57 tests passed from extracted public source | Server behavior, settings, native-input handling with test doubles, desktop ownership, provenance verification and release packaging. Not a physical-controller or novice-installation test. Private launcher tests are excluded from this count and distribution. |
| JavaScript tests | 72 passed | Input history, rendering logic, settings-file validation, placement, setup state machine and translation coverage. Translation coverage checks do not judge natural wording. |
| OBS Lua checks | 27 passed in a local development harness | Installed OBS Lua bindings were exercised with scene operations mocked. This did not place an overlay in an actual OBS scene. The harness was a local development check, not part of the distributed test suite. |
| Runtime provenance | Strict Windows build passed | Official archive/metadata and 3,159 extracted originals checked; every packaged DLL/PYD matched. Distributor traceability, not independent source-to-binary reproduction. |
| Windows package smoke checks | 3 passed on the verified 2026-10-12 build | Executable startup without external Python on PATH, shutdown with a synthetic OBS parent, and preservation of a preexisting standalone server. No physical controller, live OBS rendering or clean-PC installation was involved. Rerun on each newly built package. |
| Desktop manager construction | English, Korean and Japanese completed with official Tcl/Tk | Automated check with a hidden window and a fake server. Does not verify visual legibility, real server interaction or the packaged GUI with a human user. |
| Settings-page inspection | Checked with browser automation and synthetic input | Size/position changes, saved settings and copy controls. Does not establish usability for a first-time user. |
| Basic controller input | One PHOENIXWAN: seven buttons and bidirectional X-axis movement observed | An earlier basic input check. The complete current direction-setup flow still needs a physical test. Firmware and connection-mode coverage is not established. |
| Position reference | 1P reference compared with a fullscreen 1920 × 1080 game capture | 2P uses a mirrored estimate. Pixel alignment across other layouts or captures is unverified. |
| Documentation | AI-assisted editorial pass | No completed independent human language-review report is recorded. |

On 2026-10-12, [GitHub Actions push run 38171755965](https://github.com/d0vetam3r/lift-trace/actions/runs/38171755965) passed all four test jobs: Ubuntu and Windows, each with Python 3.10 and 3.13. The tested commit was [2da03af0287db3a12a2b54e305b344dc311c3ad2](https://github.com/d0vetam3r/lift-trace/commit/2da03af0287db3a12a2b54e305b344dc311c3ad2). The `windows-app` job was skipped because this was a push run; no Windows executable was built by that run. The packaged-app evidence above is from local builds, not a GitHub Windows build. No independent security audit is recorded.

## Still to check

- Installation from the Windows ZIP on another PC without development tools, using only the user guide.
- The complete current setup wizard with a physical controller, followed by simultaneous INFINITAS play and OBS display.
- Short presses, holds, chords, repeated taps, both scratch directions and reversals in the actual capture. The game and overlay may have different capture/input delays.
- Actual 2P placement, and startup/shutdown through real OBS rather than a synthetic parent process.
- Readability with Korean, Japanese and English readers, including a fluent Japanese reader who has not worked on the project.

Windows 10/11 x64 is the intended platform. The local checks above do not establish compatibility with every Windows version, controller, firmware or controller mode.

## A short human test

Use a newly extracted Windows ZIP and record its filename. Do not replace a working installation. A temporary OBS scene can be used for the overlay checks; streaming or recording is not required.

### Install from the guide

1. Ask someone who has not set up the project to follow the guide in their preferred language. Do not explain the steps in advance.
2. Have them download, extract and open the app, then enter their own game values. Note the first place where they pause, ask for help or cannot find a control.
3. Let them finish the guide and add the overlay to OBS. Record whether help was needed and the exact step. If Windows blocks the app, record the message; do not disable its protection to finish the test.

### Check the controller and OBS

1. Complete keys 1–7, clockwise and counterclockwise setup. Press each key and turn the table in both directions. Check clockwise ↻ / light coral and counterclockwise ↺ / deep coral, then alternate directions.
2. Check short presses, a held key, two keys together and repeated taps. Unplug the controller while an input is active; it should not stay lit indefinitely. Reconnect and select the device again if needed.
3. With INFINITAS focused, confirm the overlay still receives input. Check lane alignment and falling motion in OBS. Record 1P or 2P, game values and any adjustments needed; do not label timing as exact from an informal visual check.
4. Close the settings tab and confirm input continues. Close the standalone Lift Trace window that started the display and confirm it stops.
5. For optional OBS startup, close the standalone app first. Start the display from OBS, then close OBS and check that the display stops. Repeat with the standalone app already running: closing OBS should leave that app's display running.

### Read the documentation

1. Read the README and complete user guide in the language being reviewed. Compare each control name with the app and OBS.
2. Mark wording that feels translated, an undefined term, or a step that needs outside knowledge. Quote the sentence and suggest a replacement if possible.
3. Confirm the distinction between controller inputs and chart notes is clear, along with automatic height, manual height and the two windows' shutdown behavior.

## Report template

Copy this into an issue or review note. Leave unknown details blank. A skipped or blocked check is useful information; do not mark it as passed.

```text
Date:
ZIP filename / version:
Windows and OBS versions (if known):
Language used:
Controller and INFINITAS connection mode (if tested):
1P / 2P; green number / LIFT / SUDDEN+ (if tested):

Checks attempted:
Result for each: passed / failed / blocked / not tested
First unclear guide step or awkward sentence:
Help or extra steps needed:
Expected result:
Actual result / exact error:
Suggested wording or other notes:

Review performed by: person / automated tool / AI-assisted review
```

Remove personal paths, usernames and device identifiers from logs before sharing. Summarize accepted reports here with their build and scope; do not turn a report about one setup into a general compatibility claim.
