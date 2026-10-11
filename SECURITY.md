# Security and local data

Lift Trace is a local prototype. Its HTTP server binds to `127.0.0.1` for OBS and a browser on the same PC. Do not expose it through port forwarding or a public proxy; it is not designed for untrusted network clients.

The runtime reads a selected controller and serves the overlay. It does not require account credentials, game-memory access, administrator privileges or input connections from an iPad or another device. The desktop manager and OBS helper stop only servers they started. An existing healthy server is reused without taking ownership.

## Windows downloads

Download the Windows ZIP from this project's GitHub **Releases → Assets**. It includes the Python runtime, so users do not need a separate Python installation. The source ZIP is for contributors.

The current app is an **unsigned prototype**. If Windows or security software blocks it, do not disable protections or elevate the application to bypass the block. Confirm the source of the download and report the exact message to the maintainer. Published SHA-256 hashes can detect a damaged or changed archive; they do not establish publisher identity by themselves.

The bundled runtimes retain their own licenses. The verified Windows build includes matching notices and records how its runtime files match the pinned official Python distribution. See [Validation](docs/VALIDATION.md) for the check's scope. This verifies distributor traceability and file integrity, not security or application quality. Custom-runtime builds can still report unresolved provenance. Build dependencies are maintained separately from user installation instructions.

## Diagnostics

Settings and logs are created in `data/` beside the app by default. If that folder cannot be written, a startup log may be saved under `%TEMP%/LiftTrace/`. Logs can include usernames, paths and device details. Review relevant excerpts before attaching them to a public issue; do not share the entire working folder.

Use a clean release archive for redistribution. The release allowlists exclude local settings, private credentials, game assets, captures and unrelated services.

The code and documentation were developed with extensive AI assistance. Neither that disclosure nor passing automated tests is a security audit. Completed checks and unverified areas are listed in [Validation](docs/VALIDATION.md).

## Reporting a vulnerability

Use the hosting repository's private vulnerability-reporting channel if one is available. This release does not define a separate security address. If no private channel is listed, request one without disclosing vulnerability details. Do not post credentials, personal data or a working exploit in a public issue while seeking a private route.

No long-term support or security-update schedule is promised for this prototype. Reports should identify the exact version and whether the problem affects the Windows app, source execution or both.
