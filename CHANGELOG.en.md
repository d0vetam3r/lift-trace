# Changelog

[한국어](CHANGELOG.md) · [日本語](CHANGELOG.ja.md) · [English](CHANGELOG.en.md)

Changes to the public overlay distribution are recorded here. Internal development iterations are included in the first public version below.

## Unreleased

- Add optional read-only playback proofs with unique IDs only after confirmed non-play→play transitions. Visibility changes, capture faults and startup during play do not create new song events; lightweight polling reads no images or files. Correlate visibility commands with observed values and outcomes in bounded logs while preserving independent operation and input processing.
- Keep settings file writes and HTTP responses from blocking controller input. Preserve consecutive save ordering, previous settings on save failure, and current-input delivery after settings changes.
- Apply the same two-second recovery grace to OBS temporary capture-unavailable responses. Brief outages preserve visibility; longer outages require confirmed non-gameplay before showing items again, preventing the same song from being treated as a new one.
- Document the three projects' responsibilities, independent operation, optional integration, current availability and long-term direction toward a modular open-source ecosystem in the README.

## 0.2.0 — 2026-10-15

- Retain a BPM-label reference in memory only after fresh SCORE confirmation, maintaining gameplay visibility during FULL COMBO. The secondary label cannot initiate a new play session and does not read numeric BPM or song names.
- Discard late classified frames and keep polling. Brief stalls preserve visibility; stalls beyond 2 seconds hide items and require fresh non-gameplay confirmation before re-entry. Observe at most 5 Hz without changing input polling.
- Record state transitions and bounded metadata with an asynchronous diagnostic writer. Bound queue, retention and shutdown wait; exclude passwords, pixels and exception messages.
- Add an opt-in preference to start saved automatic visibility only on servers created by the OBS helper. Keep it off by default, preserve standalone servers/manual stops/existing errors, and require no Core installation.

- Extract INFINITAS calculations while preserving existing settings and results. Connect optional experimental automatic visibility to the app, with local OBS WebSocket connection, target selection by actual scene/source names and manual start/stop. Bundle a 1080p SCORE detection reference so startup needs no screen registration; prefer a valid existing personal reference. Detection includes pre-song play UI in the tested 1P layout.
- Add or exclude automation targets with checkboxes and distinguish duplicate source placements by upper/lower OBS list position. Reopening settings restores names and selections without stopping active automation. Reduce first-time setup to connect, save selection and start; collapse additional help and remove the separate start acknowledgement.
- Leave automation off by default after app restart and stop it on OBS disconnect or scene-collection change. Keep the OBS password and personal local reference image outside ordinary settings export and distribution files. BMS and an external plugin loader are not implemented.

- Add a key note body toggle under Input note appearance, allowing keys 1–7 to show only their falling heads. Bodies remain enabled by default. Actual input records, scratches and the example game chart stay unchanged.
- Add visual shortening for released brief key inputs, with a time threshold and percentage to keep. Comparison samples, a slider and presets support tuning before Apply and save or Revert edits. Turning bodies off preserves these values.

- Reorganize the English, Korean and Japanese READMEs around an animated demonstration, Windows setup, features and task-based guide links.
- Add an original synthetic demo rendered with the application's drawing code, with optional developer instructions for regenerating it.
- Make Korean the default documentation language.
- Provide development, contribution, reference, validation, release, security and changelog documents in all three languages, with links that retain the reader's chosen language.

## 0.1.0 — 2026-10-12

Initial public prototype.

- Ready-to-run Windows x64 app: extract and open LiftTrace.exe without installing Python or using a terminal.
- Seven-key input notes, held-input ribbons, and scratch notes with clockwise ↻ / counterclockwise ↺ arrows and distinct light/deep coral colors.
- Windows WinMM input with configurable buttons and scratch axis; guided setup checks keys 1–7, clockwise movement and counterclockwise movement before applying the mapping.
- Saved scratch-axis direction calibration, with manual reversal available.
- Green-number, LIFT and SUDDEN+ speed calibration for fullscreen 1080p capture. Automatic height follows LIFT; a separate manual height is preserved. Changing display height alone does not change calculated speed.
- Clear guidance for LIFT 0, which has no automatic input-display area.
- Separate address, width, height and X/Y position copy buttons for OBS. Position follows 1P/2P and LIFT with saved left/right and up/down adjustments; 2P uses a mirrored reference.
- Explicit 1080p lane-size preset and step-by-step placement instructions. Optional OBS placement can read the saved app size and position; existing manual coordinates are preserved during migration. App settings alone do not resize or move an OBS source.
- Black or transparent output, configurable lane widths, 1P/2P layout and display delay.
- Local settings storage, import/export, synthetic demo and focused-page keyboard testing.
- Invalid settings imports are rejected before saving; slow event connections receive a fresh settings/state snapshot instead of silently losing configuration updates.
- Optional OBS startup and shutdown of the server it started, preserving servers started separately.
- Public OBS integration starts only the overlay, with no discovery or startup of unrelated local services.
- English, Korean and Japanese interface and step-by-step user guides; separate development, technical reference and release guides.
- Public AI-use disclosure, contribution review guidance, and a validation record that separates automated checks from pending physical and human review. User guides explain selection/paste shortcuts, position adjustments and shutdown behavior.
- MIT-licensed source, Windows packaging, bundled runtime notices, matching source/app archive checksums, automated tests and optional manual Windows builds.
- Windows release builds use a hash-pinned official Python 3.13.16 x64 distribution with its matching manifest and SBOM. Preparation stays inside the workspace and does not change the system Python.
- Runtime provenance checks compare extracted originals and packaged DLL/PYD files with the official archive. The Windows package retains matching component notices, the SBOM and manifest evidence. Custom-runtime prototype builds remain possible but report unresolved provenance.

The Windows app and source ZIP are built from the same project. The public distribution contains only the overlay and optional OBS integration; no iPad remote, combined streaming launcher or personal settings are included.

## Known limitations

Native controller input and OBS automatic startup are Windows-only. The overlay does not read game charts, judgments, speed settings or BPM. A held input note does not identify a chart long note. Continuous same-direction scratch movement cannot be divided into individual chart notes. Compatibility, simultaneous input with INFINITAS and exact capture synchronization require validation in the user's environment. The Windows app is an unsigned prototype. First-time installation on another PC and human language review are still pending; see [Validation](docs/VALIDATION.en.md) and the [technical reference](docs/REFERENCE.en.md).

The official-runtime build resolves the earlier libffi/XZ provenance gap; see [Validation](docs/VALIDATION.en.md) for the evidence and its limits. This check does not replace physical-controller testing, human review or a security audit.
