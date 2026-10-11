# Contributing

[한국어](CONTRIBUTING.md) · [日本語](CONTRIBUTING.ja.md) · [English](CONTRIBUTING.en.md)

Reports and contributions are welcome in Korean, English and Japanese. Start with the [user guide](docs/USER_GUIDE.en.md) to install the app, or [Development](docs/DEVELOPMENT.en.md) to change its source.

## Report a problem

Open an issue using the repository's bug-report template. Include whichever details you can confirm:

- Lift Trace version and whether you downloaded the **Windows app** or ran the **source**.
- Windows or other OS and OBS versions. **Python version is only needed for source execution.**
- The buttons and steps you used, what you expected and what happened. Copy the exact error message where possible.
- Controller model and connection mode, if the problem involves input.
- Whether you started the app yourself or with OBS, and whether Lift Trace was already running.
- For placement or speed problems: OBS canvas resolution, source dimensions and scale, green number, LIFT, SUDDEN+, speed correction and display delay.
- Relevant log lines with personal paths and device identifiers removed.

It is fine to leave an unfamiliar field unknown. An accurate description of your steps is more useful than guessed values. Do not attach the entire `data/` folder, OBS profiles, game assets or private recordings. Follow [Security](SECURITY.en.md) for sensitive security reports.

## Propose a change

Keep each change focused on one purpose and explain how it changes user-visible behavior. See [Development](docs/DEVELOPMENT.en.md) for setup and checks. Users and contributors share one source tree; the Windows package adds the runtime, not a separate product.

Preserve the standard-library application runtime and the overlay-only distribution boundary unless a design change is agreed. Add build packages to the pinned build requirements, not user installation instructions. Hardware-specific defaults must remain configurable. Do not add personal paths or assumptions about one PC.

Add meaningful tests for changed behavior. State what you checked manually and which device and mode you used, without implying untested compatibility. Startup/shutdown changes must preserve preexisting servers. Controller setup changes must cover press/release order, repeated buttons, ambiguous axes, cancellation and disconnection.

## Documentation and translation

Keep Korean, Japanese and English documentation and interface text consistent. Translations must not alter functionality or support claims.

- Preserve code, commands, API names and file paths. Match button and field names to the actual interface in that language.
- Use **입력 노트 / input notes / 入力ノーツ** for key and scratch visualization, and keep the product name **Lift Trace** unchanged. Input notes show controller activity, not chart data.
- Lead README and user-guide readers to the **Windows app**; keep developer commands in the development guide. Identify downloads by the stable filename prefix and `.zip` ending, without a fixed version number.
- Explain one action and the result to check at a time. Do not assume knowledge of addresses, ports, servers or development. Enter game values before checking input notes: default LIFT 0 has no automatically calculated display area.
- Describe scratch directions as **clockwise ↻** and **counterclockwise ↺**, viewed from above the turntable.

Check that each language matches the application, and note any translation or review still pending. An AI editorial pass does not establish that a speaker of that language or a first-time user reviewed the result.

## Branches and review

Use `main` for accepted work and a short-lived branch for each focused change. There is no separate `develop` branch.

1. Start from the current `main` with a descriptive branch name such as `fix/scratch-direction` or `docs/setup-guide`. Use a fork if you do not have repository write access.
2. Make the change, run the relevant checks, and open a pull request (PR) targeting `main`. Explain the change, test results and remaining gaps.
3. The maintainer reviews the change and its results before merging. After merge, the working branch can be deleted.

A PR does not need its own version bump. The maintainer chooses a version and tested commit when changes are ready for release. `main` can therefore contain work newer than the latest published release. See [Releasing](docs/RELEASING.en.md) for tags, artifacts and publication.

## Pull requests and licensing

Describe the problem, final behavior and relevant validation. Add user-visible changes to an **Unreleased** section in [Changelog](CHANGELOG.en.md), creating it if needed; leave published version entries intact. New public files must be added to release allowlists. Check packaging changes against an extracted archive.

Contributions are provided under the project's [MIT License](LICENSE). Only contribute code and assets you have the right to share. Bundled third-party runtimes retain their own licenses, so preserve their notices. Do not add copyrighted game captures to public documentation.

## AI-assisted contributions

AI tools are welcome. The contributor is responsible for reviewing the result, understanding the changed behavior and explaining relevant decisions when asked. Check generated code and documentation against the actual application. Plausible wording and passing tests alone do not establish correctness.

If AI substantially drafted or changed a contribution, briefly say so in the PR and state what you verified yourself. A short sentence is enough; no prompt transcript is required. Check the source and license of reused material, including AI suggestions. Do not claim human, hardware or independent review that did not happen.

For documentation changes, read the steps in order and compare button names with the interface. You can ask fluent speakers to report unnatural wording and first-time users to report unclear steps. An AI editorial pass helps prepare for that process but is not evidence of human review. Record completed checks and remaining gaps in [Validation](docs/VALIDATION.en.md).
