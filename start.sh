#!/usr/bin/env bash
set -eu
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    exec "$candidate" server.py "$@"
  fi
done

printf '%s\n' 'Lift Trace requires Python 3.10 or newer.' \
  'No compatible python3 or python command was found.' \
  'Install or enable Python, then run this launcher again.' >&2
exit 1
