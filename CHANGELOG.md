# Changelog

Changes to the public overlay distribution are recorded here. Internal development iterations are included in the first public version below.

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

Native controller input and OBS automatic startup are Windows-only. The overlay does not read game charts, judgments, speed settings or BPM. A held input note does not identify a chart long note. Continuous same-direction scratch movement cannot be divided into individual chart notes. Compatibility, simultaneous input with INFINITAS and exact capture synchronization require validation in the user's environment. The Windows app is an unsigned prototype. First-time installation on another PC and human language review are still pending; see [Validation](docs/VALIDATION.md) and the [technical reference](docs/REFERENCE.md).

The official-runtime build resolves the earlier libffi/XZ provenance gap; see [Validation](docs/VALIDATION.md) for the evidence and its limits. This check does not replace physical-controller testing, human review or a security audit.
