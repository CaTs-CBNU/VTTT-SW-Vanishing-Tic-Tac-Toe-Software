#!/usr/bin/env bash
set -e

python -m src.predict eval \
  --checkpoint results/saved_models/vanish_runs/checkpoints/best.pt \
  --games 200
