# Lift Trace

[English](README.md) · [한국어](README.ko.md) · [日本語](README.ja.md)

Show your **beatmania IIDX INFINITAS** key presses and scratch movements in OBS. Each key press or scratch movement creates an input note that falls below the game's judgment line. These notes show your controller inputs; they are not read from the game chart.

**Prototype.** For Windows 10/11 (64-bit). English, Korean and Japanese are available.

AI tools have been used extensively to develop the code and documentation. This is an early prototype; see [validation status and known gaps](docs/VALIDATION.md) for what has been checked and what still needs real-world testing and human review.

## I want to use it

**No programming, Python installation or command typing is needed.**

**[Download the Windows app](https://github.com/d0vetam3r/lift-trace/releases/latest)** from the latest release.

1. On this GitHub page, open **Releases**, then the latest version's **Assets**.
2. Download the file whose name starts with `lift-trace-windows-x64-` and ends with `.zip`. The numbers in between are the version and may change.
3. Right-click the downloaded file → **Extract All**. Open the extracted **LiftTrace** folder and double-click **LiftTrace.exe**.
4. Follow the [step-by-step user guide](docs/USER_GUIDE.en.md): enter the game's numbers, set up the controller, then copy the address into OBS.

The guide explains which buttons to click and what to check at each step. LIFT sets the overlay height automatically; you can also set the height manually. For a fullscreen 1080p game capture, use the lane-size preset and copy the calculated positions into OBS.

You need OBS Studio, INFINITAS and a compatible controller separately. Keep the extracted folder's files together. If the app will not open, see [help](docs/USER_GUIDE.en.md#troubleshooting).

## I want to contribute

Clone this repository or download the `lift-trace-source-*.zip` asset from Releases (`*` is the version number). The Windows app is built from the same source.

[Development](docs/DEVELOPMENT.md) · [Contributing](CONTRIBUTING.md) · [Technical reference](docs/REFERENCE.md) · [Validation](docs/VALIDATION.md) · [Releasing](docs/RELEASING.md)

The source ZIP and GitHub's “Source code” downloads are for contributors; users should choose the Windows ZIP above.

## About the project

The current display assumes a fullscreen game in a **1920 × 1080 OBS canvas**. Changing the overlay height does not change its calculated falling speed. Position and timing still need to be matched to your game capture. The tool displays inputs, not game judgments.

Project code is [MIT licensed](LICENSE). Bundled runtimes retain their own licenses. [Changelog](CHANGELOG.md) · [Security and local data](SECURITY.md)

Lift Trace is an independent project, not affiliated with or endorsed by KONAMI, DJ DAO/GAMO2 or the OBS Project. Product names belong to their respective owners.
