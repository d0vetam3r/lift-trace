# Releasing

[Development](DEVELOPMENT.md) · [Validation](VALIDATION.md) · [Changelog](../CHANGELOG.md)

Maintain **one source tree and two artifacts**: a ready-to-run Windows app for users, and the exact source used to build it for contributors. Build both from the release source, never by copying a personal working folder.

## Who does what

| Role | Responsibility |
| --- | --- |
| Contributor | Propose a focused change, run relevant checks and explain what remains unverified. Use a short-lived branch and a pull request to `main`; see [Contributing](../CONTRIBUTING.md#branches-and-review). |
| Maintainer | Review changes, choose the version and exact commit, assess real-use results and release notes, then authorize publication. |
| GitHub Actions | Run the configured tests and build steps, calculate hashes and save artifacts. A green run reports those checks; it does not decide whether the product is ready. |
| AI assistant | Help prepare changes, run tools and draft notes within the maintainer's authorization. Describe observed results and gaps accurately; AI review does not stand in for human or hardware testing. |

An authorized tool or workflow can create a release; a person does not have to upload every file by hand. The maintainer remains responsible for choosing what to publish. The current workflow stops at build artifacts, as described below.

## Prepare a version

1. Choose the next version when preparing a release, not for every pull request. Set it in `package.json`, update the UI version badge, and move the relevant Unreleased changes into a dated changelog entry. User download instructions identify files by their stable name prefixes; do not insert a specific version into those steps.
2. Review the explicit file lists in `tools/build_release.py`. Keep required runtime files, public documentation, tests and build tooling; exclude local settings, logs, recordings, OBS profiles, unrelated integrations and private paths.
3. Run the commands and relevant behavior checks in [Development](DEVELOPMENT.md). Update [Validation](VALIDATION.md) with the build tested, results and remaining gaps. Record which Windows/OBS versions and controllers were actually tested. Do not turn a target platform into an untested support claim or an AI review into a human review.
4. Build the source ZIP and Windows ZIP from the same clean source revision. Use the pinned `requirements-build.txt` inside a dedicated build environment.

Commit the final version, documentation and code before building. Use a tag named `vX.Y.Z`, such as `v0.1.0`, pointing to that exact tested commit. The tag, `package.json`, source ZIP and Windows package must describe the same revision and version. Record the commit and build run; do not combine a new source archive with an older executable.

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

The pinned-runtime procedure completed a verified Windows build; see [Validation](VALIDATION.md) for its scope and recorded results. Repeat it for each release. An ordinary custom-runtime build can still succeed while setting `bundledRuntime.runtimeProvenanceVerified: false`; do not treat that as a passing provenance check. The source ZIP bundles no runtime.

Expected downloadable files (`<version>` comes from `package.json`):

- `lift-trace-windows-x64-<version>.zip` — extract and run LiftTrace.exe.
- `lift-trace-source-<version>.zip` — sources, tests, docs and build tooling.
- `SHA256SUMS` — matching-version source and Windows archive hashes; per-archive `.sha256` files can also be included.

Before upload, extract the Windows ZIP into a clean directory and check:

- LiftTrace.exe starts without a system Python or Node.js on PATH. The complete `_internal` folder is included.
- The manager opens settings in English, Korean and Japanese; Quit and window close clean up an owned server.
- A preexisting healthy server is reused and preserved. An unrelated listener produces an understandable failure.
- Guided controller mapping, cancellation and the standalone demo work. Clockwise and counterclockwise setup steps detect opposite directions; both axis polarities produce the correct circular arrows and distinct light/deep coral colors.
- Automatic LIFT height, manual-height preservation, legacy settings and LIFT 0 guidance work. Enter game values or select a manual height before checking visible demo input notes. App size changes do not silently imply that OBS has resized.
- The explicit 1080p lane-size preset, X/Y calculation, copy buttons and saved position adjustments work in all three languages. Verify the guide's top-left/100% placement steps, old manual-position preservation and explicit OBS apply behavior; app edits alone must not move a scene item.
- OBS integration finds adjacent LiftTrace.exe, starts a new server and stops it when its OBS process exits; a reused server survives.
- Internal documentation links and the original schematic resolve in the extracted folder.
- `LICENSE`, `THIRD_PARTY_NOTICES.md` and `licenses/` are present. Runtime components retain their own licenses; MIT applies to project code.
- Runtime notice sources match the bundled components, `bundledRuntime.runtimeProvenanceVerified` is true, and no `unverifiedComponents` remain. Inspect the recorded archive/metadata hashes and packaged binary mappings; retain `provenance/python-runtime.spdx.json`. Merely including license files does not complete this check.
- No `data/`, local credentials, captures or personal configuration appears in either ZIP.

The automated smoke test covers a headless packaged server and OBS-helper ownership with a synthetic parent process. It does not replace testing the desktop GUI, a physical controller, actual OBS rendering or game-capture timing.

`bundledRuntime.runtimeProvenanceVerified` describes the builder's distributor and file-integrity check only. It does not certify application quality, security, legal compliance or compatibility with a user's PC. Keep the other checks and limitations above separate from that field.

## GitHub workflow and publication

The current `.github/workflows/verify.yml` has two paths:

- **Push or pull request:** run Python/JavaScript tests on Windows and Ubuntu and build the source archive. The recorded 2026-10-12 push run passed all four test combinations; see [Validation](VALIDATION.md) for its commit and run.
- **Manual “Run workflow”:** run those tests, then prepare the pinned runtime, build the Windows package with `--require-verified-runtime`, run the smoke check and upload the ZIPs and hashes as an Actions artifact. The Windows job was skipped in the recorded push run; that run did not build an executable.

The workflow uses `contents: read`. **It does not create a draft release or publish a GitHub Release.** An Actions artifact is a build output attached to a workflow run, not the download offered under Releases.

For publication, choose the tested source revision, create its version tag and draft a GitHub Release. Upload the two ZIPs and checksums as release **Assets**. Put the Windows ZIP first in the release text with the label **Windows app — no Python installation required**; identify the source ZIP separately as **For contributors**.

State the tested environments, known limitations and signing status in the release notes. Link to the validation record and keep any uncompleted checks marked as pending. The current app is an **unsigned prototype**; do not describe it as signed or ask users to disable Windows/antivirus protections. Do not treat a checksum alone as proof of publisher identity. If signing is added later, sign before generating final archive hashes and update the documentation.

Review the draft's files, links and notes, then publish. Keep the download links in all three READMEs pointed at the latest release. Never upload only GitHub's automatically generated source archives as the user installation route.

## Possible next step: automate a draft release

**This is a proposed extension, not configured behavior.** The intended sequence would be: the maintainer selects a trusted commit and version → Actions checks, builds and hashes that revision → Actions attaches the outputs to a draft release → the maintainer reviews real-use results, notes and files, then authorizes publication. Do not infer hardware compatibility, timing accuracy or natural wording from successful automation. Pending checks must remain visible in the release notes.

If implemented, keep test/build jobs read-only and grant `contents: write` only to the job that creates the draft and attaches files. Use the repository's built-in `GITHUB_TOKEN`; this design does not need a personal access token. GitHub documents the [release permission](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions) and [job-level token permissions](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token#modifying-the-permissions-for-the-github_token).

Run the release job only for a maintainer-selected, trusted repository reference. Do not execute fork pull-request code with release credentials or pass secrets into it. Keep the release inputs tied to the reviewed commit, not an arbitrary branch name or an artifact supplied by an untrusted pull request. This follows GitHub's [fork-workflow credential boundary](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflows-in-forked-repositories).

Automation and AI assistance do not provide a security audit or legal certification. Hashes detect changed files but do not establish publisher identity, and this app is currently unsigned. Physical-controller tests, game/OBS timing checks and review by readers of each language remain separate responsibilities; record their actual scope in [Validation](VALIDATION.md).

