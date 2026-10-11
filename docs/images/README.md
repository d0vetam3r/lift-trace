# README demo artwork

`lift-trace-demo.gif` is an original synthetic illustration, not game footage.
It uses `web/demo.json`, `TrailEngine`, and the application's `drawPreview`
renderer. The upper lane and controller indicators are illustrative. The lower
lane uses the same input-note renderer as the app. No game artwork, chart, music,
controller photo, or captured user settings are included.

The animation is 900 × 620 pixels, 25 frames per second, and 7.2 seconds long.
Its frame rate is chosen for the README file size; it does not describe the app's
rendering rate or demonstrate real game/OBS synchronization.

## Regenerate (optional developer tools)

App users do not need these tools. From the repository root, install the optional
canvas package and Pillow in a separate Python environment:

```text
npm install --no-save --package-lock=false @napi-rs/canvas@0.1.100
python -m venv .venv
```

On Windows:

```text
.venv\Scripts\python.exe -m pip install Pillow==12.3.0
node tools/render_readme_demo.mjs --python .venv\Scripts\python.exe
```

On macOS or Linux:

```text
.venv/bin/python -m pip install Pillow==12.3.0
node tools/render_readme_demo.mjs --python .venv/bin/python
```

The default output is `docs/images/lift-trace-demo.gif`. Use `--output FILE.gif`
for another location and `--preview FILE.png` to save a representative frame.
Run `node tools/render_readme_demo.mjs --help` for the options. System fonts can
change the exact pixels between computers; this is a reproducible rendering
procedure, not a byte-identical image build guarantee.
