#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
if [[ -x .venv/bin/python ]]; then
    exec .venv/bin/python -m vttt --simulate "$@"
fi
exec python3 -m vttt --simulate "$@"
