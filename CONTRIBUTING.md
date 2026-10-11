# Contributing

English, Korean and Japanese reports and contributions are welcome. Use the [user guides](docs/USER_GUIDE.en.md) to install the Windows app; use [Development](docs/DEVELOPMENT.md) to work on its source.

## Report a problem

Open an issue with the repository's bug-report template. Include:

- Lift Trace version and whether you downloaded the **Windows app** or ran the **source**.
- Windows/OS and OBS versions. **Python version is only needed for source execution.**
- What you clicked, what you expected and what happened; copy the exact error text where possible.
- Controller model and connection mode, if the problem involves input.
- Manual application startup or OBS automatic startup, and whether another server was already running.
- For alignment problems: canvas resolution, source dimensions/scale, green number, LIFT, SUDDEN, speed correction and delay.
- Relevant log lines with personal paths and device identifiers removed.

If you do not know a technical field, say so; a clear description of the steps is more useful than guessing. Do not attach the entire `data/` folder, OBS profiles, game assets or private captures. For sensitive reports, follow [Security](SECURITY.md).

## Propose a change

Keep a change focused and describe the resulting user behavior. Read [Development](docs/DEVELOPMENT.md) for source setup and tests. Keep a single source tree for users and contributors; the Windows package adds the runtime, not a different product.

Preserve the standard-library application runtime and the overlay-only distribution boundary unless a deliberate design change is agreed. Build dependencies belong in the pinned build requirements, not user installation instructions. Hardware-specific defaults must remain configurable. Do not add personal paths or assumptions about one user's computer.

Add meaningful tests for behavior changes. Describe manual checks and the device/mode tested without implying broader compatibility. Startup/shutdown changes must preserve preexisting servers. Guided setup changes must test press/release order, repeated buttons, ambiguous axes, cancellation and disconnection.

Keep English, Korean and Japanese user documentation and interface text consistent. Use **input notes / 입력 노트 / 入力ノーツ** for the displayed key presses and scratch movements; keep the product name **Lift Trace** unchanged. These notes show controller input, not chart data. The README and user guide should lead users to the **Windows app**, while developer commands belong in the development guide. Identify downloads by the stable filename prefix and `.zip` ending, without a fixed version number. Explain user tasks with the actual button labels, one action at a time, and the result to check. Do not assume users understand addresses, ports, servers or software development. Entering game values must precede checking input notes: default LIFT 0 has no automatic display area. Describe scratch directions as clockwise ↻ and counterclockwise ↺, viewed from above. Developer documentation is currently English.

## Pull requests and licensing

Explain the problem, the final behavior and relevant validation. Update [CHANGELOG.md](CHANGELOG.md) for user-visible changes. New public files must be included in release allowlists, and a packaging change should be checked against an extracted archive.

Contributions are provided under the project's [MIT License](LICENSE). Only contribute code and assets you have the right to share. Bundled third-party runtimes retain their own licenses; preserve notices and avoid adding copyrighted game captures to public documentation.

## AI-assisted contributions

AI assistance is welcome. The person submitting a contribution is responsible for reviewing it, understanding the behavior it changes, and explaining the relevant decisions when asked. Check generated code and documentation against the actual application; plausible wording and passing tests alone do not establish correctness.

If AI substantially drafted or changed the contribution, mention that in the pull request and briefly state what you verified. A short sentence is enough; no prompt transcript is required. Check the source and license of any reused material, including suggestions from AI tools. Do not claim a human, hardware or independent review that did not happen.

For documentation changes, read the steps in order and compare button names with the interface. Ask fluent speakers to report unnatural wording and first-time users to report unclear steps. An AI editorial pass is useful preparation, but it is not evidence that either group has reviewed the result. Record completed checks and remaining gaps using [Validation](docs/VALIDATION.md).
