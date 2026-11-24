#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "$root/tools/build_linux.py" ]]; then
    printf '%s\n' 'Builder files are missing. Extract the whole Linux .tar.gz with its folders intact.' >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' 'Python 3 is required. Install the Linux packages listed in BUILD.md.' >&2
    exit 1
fi
if [[ -d "${HOME:-}/.cargo/bin" ]] && ! command -v cargo >/dev/null 2>&1; then
    export PATH="$HOME/.cargo/bin:$PATH"
fi
exec python3 "$root/tools/build_linux.py" "$@"
