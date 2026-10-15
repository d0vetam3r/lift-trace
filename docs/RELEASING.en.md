# Releasing

[한국어](RELEASING.md) · [日本語](RELEASING.ja.md) · [English](RELEASING.en.md)

[Development](DEVELOPMENT.en.md) · [Validation](VALIDATION.en.md) · [Changelog](../CHANGELOG.en.md)

Maintain **one source tree and two artifacts**: a ready-to-run Windows app for users, and the exact source used to build it for contributors. Build both from the release source, never by copying a personal working folder.

## Who does what

| Role | Responsibility |
| --- | --- |
| Contributor | Propose a focused change, run relevant checks and explain what remains unverified. Use a short-lived branch and a pull request to `main`; see [Contributing](../CONTRIBUTING.en.md#branches-and-review). |
| Maintainer | Review changes, choose the version and exact commit, assess real-use results and release notes, then authorize publication. |
| GitHub Actions | Run the configured tests and build steps, calculate hashes and save artifacts. A green run reports those checks; it does not decide whether the product is ready. |
| AI assistant | Help prepare changes, run tools and draft notes within the maintainer's authorization. Describe observed results and gaps accurately; AI review does not stand in for human or hardware testing. |

The maintainer chooses the version, release intent and notes on main. The release workflow then publishes automatically after tests, builds and draft verification pass. Uploading every file by hand is unnecessary; choosing what to publish remains the maintainer's responsibility.

## Prepare a version

1. Choose the next version when preparing a release, not for every pull request. Set it in `package.json`, update the UI version badge, and move the relevant Unreleased changes into a dated changelog entry. User download instructions identify files by their stable name prefixes; do not insert a specific version into those steps.
2. Review the explicit file lists in `tools/build_release.py`. Keep required runtime files, public documentation, tests and build tooling; exclude local settings, logs, recordings, OBS profiles, unrelated integrations and private paths.
3. Run the commands and relevant behavior checks in [Development](DEVELOPMENT.en.md). Update [Validation](VALIDATION.en.md) with the build tested, results and remaining gaps. Record which Windows/OBS versions and controllers were actually tested. Do not turn a target platform into an untested support claim or an AI review into a human review.
4. Build the source ZIP and Windows ZIP from the same clean source revision. Use the pinned `requirements-build.txt` inside a dedicated build environment.

Commit the final version, documentation and code before building. The release workflow creates `vX.Y.Z` at the verified commit, so do not create the tag in advance. The tag, `package.json` and both ZIPs must identify the same code and version. Record the commit and build run; never combine new source with an older executable.

Once a release is public, do not move its tag, overwrite its ZIPs, or replace its checksums with a different build. Fixes belong in a new version. Release-note wording may be clarified without replacing the published files. Tag protection rules could enforce this convention later; they are not currently configured as part of this workflow.

## Build and verify

On Windows x64, start in a clean checkout without an existing `.venv-build`. Use an available Python 3.10+ for preparation; the Windows package itself is built with the pinned official **Python 3.13.16 x64** runtime:

```powershell
python tools/prepare_runtime.py
artifacts\python-runtime\python\python.exe -m venv .venv-build
.venv-build\Scripts\python -m pip install -r requirements-build.txt
.venv-build\Scripts\python tools\build_windows.py --require-verified-runtime
python tools/build_release.py
python tools/smoke_windows.py
```

The Windows builder packages the application with PyInstaller; this is a maintainer dependency, never an installation step for ordinary users. The source builder also works without PyInstaller. `tools/smoke_windows.py` accepts an optional path to the Windows ZIP; by default it uses the current version in `artifacts/`.

The preparation command keeps the downloaded archive, Windows manifest and SPDX SBOM under `artifacts/python-runtime/downloads/`, and extracts the runtime into the adjacent `python/` folder. Keep both folders while building. Hashes and official download URLs are pinned in `tools/python-runtime.json`. No system-wide Python installation or PATH change is required.

The provenance check validates the official metadata, compares extracted files with the pinned archive and compares packaged DLL/PYD files with those originals. It establishes traceability to the official distribution; it does not reproduce that distribution from source or certify security, legal compliance or application quality.

The pinned-runtime procedure completed a verified Windows build; see [Validation](VALIDATION.en.md) for its scope and recorded results. Repeat it for each release. An ordinary custom-runtime build can still succeed while setting `bundledRuntime.runtimeProvenanceVerified: false`; do not treat that as a passing provenance check. The source ZIP bundles no runtime.

Expected downloadable files (`<version>` comes from `package.json`):

- `lift-trace-windows-x64-<version>.zip` — extract and run LiftTrace.exe.
- `lift-trace-source-<version>.zip` — sources, tests, docs and build tooling.
- `SHA256SUMS` — matching-version source and Windows archive hashes; per-archive `.sha256` files can also be included.

Before upload, extract the Windows ZIP into a clean directory and check:

- LiftTrace.exe starts without a system Python or Node.js on PATH. The complete `_internal` folder is included.
- The manager opens settings in Korean, Japanese and English; Quit and window close clean up an owned server.
- A preexisting healthy server is reused and preserved. An unrelated listener produces an understandable failure.
- Guided controller mapping, cancellation and the standalone demo work. Clockwise and counterclockwise setup steps detect opposite directions; both axis polarities produce the correct circular arrows and distinct light/deep coral colors.
- Automatic LIFT height, manual-height preservation, legacy settings and LIFT 0 guidance work. Enter game values or select a manual height before checking visible demo input notes. App size changes do not silently imply that OBS has resized.
- The explicit 1080p lane-size preset, X/Y calculation, copy buttons and saved position adjustments work in all three languages. Verify the guide's top-left/100% placement steps, old manual-position preservation and explicit OBS apply behavior; app edits alone must not move a scene item.
- OBS integration finds adjacent LiftTrace.exe, starts a new server and stops it when its OBS process exits; a reused server survives.
- Internal documentation links and illustrations resolve in the extracted folder.
- `LICENSE`, `THIRD_PARTY_NOTICES.md` and `licenses/` are present. Runtime components retain their own licenses; MIT applies to project code.
- Runtime notice sources match the bundled components, `bundledRuntime.runtimeProvenanceVerified` is true, and no `unverifiedComponents` remain. Inspect the recorded archive/metadata hashes and packaged binary mappings; retain `provenance/python-runtime.spdx.json`. Merely including license files does not complete this check.
- No `data/`, local credentials, captures or personal configuration appears in either ZIP.

The automated smoke test covers a headless packaged server and OBS-helper ownership with a synthetic parent process. It does not replace testing the desktop GUI, a physical controller, actual OBS rendering or game-capture timing.

`bundledRuntime.runtimeProvenanceVerified` describes the builder's distributor and file-integrity check only. It does not certify application quality, security, legal compliance or compatibility with a user's PC. Keep the other checks and limitations above separate from that field.

## GitHub workflow and publication

Ordinary verification uses `.github/workflows/verify.yml`; its Actions artifacts do not publish a release. Publication uses the separate `.github/workflows/release.yml`, named **Build and publish a release**.

1. Prepare reviewed code, a stable version in `package.json`, the matching UI badge, a dated changelog and `docs/releases/<version>.md`. Put only the same version on one line in the required `.github/release-intent`, for example `0.2.0`. Development versions with suffixes are rejected.
2. Merge these changes into `main`. A main push changing `package.json` or `.github/release-intent` starts the workflow. Alternatively choose **Actions → Build and publish a release → Run workflow → main**; there are no extra inputs. Other branches and forks cannot publish through this workflow.
3. Test the selected commit in four combinations: Windows/Ubuntu and Python 3.10/3.13, with Python/JavaScript checks and source packaging. Only after all pass does the Windows job prepare the official runtime and a fresh build environment, then run the `--require-verified-runtime` build, smoke checks and distribution verification.
4. The publication job downloads verified artifacts by ID from that same run. It attaches five files to a draft: source ZIP, Windows ZIP, each archive's `.sha256`, and `SHA256SUMS`. It verifies remote inventory, sizes and SHA-256 digests, rechecks that main still identifies the built commit, and verifies that `v<version>` directly identifies that exact commit before publishing and marking the release latest. If creating the new draft also creates its tag, the job verifies that tag without moving it.

The version, release intent and notes express the maintainer's choice to publish. Starting this process authorizes automatic publication once all gates pass, so settle the scope and disclose remaining checks before starting. Tests/builds use `contents: read`; only publication gets `contents: write`, using the repository's `GITHUB_TOKEN`. No personal access token is needed, and fork pull-request code is not run with publication credentials.

## Failure and retries

An existing release, including a draft, or an existing tag for the version causes failure; neither is reused or overwritten. A failure before remote state is created can be fixed and retried with the same version. A failure after creating a draft, assets or tag preserves that state: no automatic deletion, replacement or retagging occurs. The maintainer must inspect the cause and explicitly recover or choose a new version. Published assets and tags remain immutable.

Put **Windows app — no Python installation required** first in the release notes, identify the source ZIP as for contributors and link the checksums. State tested environments, remaining checks, unsigned prototype status and AI involvement, linking [Validation](VALIDATION.en.md). Successful automation does not establish physical-controller compatibility, game timing, installation on another PC or human language review. Hashes detect changed files; they do not establish publisher identity. Keep all three README download links pointing to the latest release.
