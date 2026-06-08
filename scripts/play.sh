#!/usr/bin/env bash
set -e

python -m src.predict play \
  --checkpoint results/saved_models/vanish_runs/checkpoints/best.pt \
  --human_first \
  --search_depth 6
