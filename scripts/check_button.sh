#!/usr/bin/env bash
# Use the same Python environment as the hardware game, without starting its LCDs.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ -x .venv/bin/python ]]; then
    exec .venv/bin/python -m vttt.button_check "$@"
fi
exec python3 -m vttt.button_check "$@"
