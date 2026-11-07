#!/usr/bin/env bash
set -euo pipefail

cd /opt/carla_demo

for seed in 7 8 9; do
  for team in 2 4; do
    for stage in focused severe; do
      echo "Running stage=${stage}, team=${team}, seed=${seed}"

      python -u scripts/run_phase17_resilience_v2.py run \
        --stage "$stage" \
        --profile pinned \
        --team-size "$team" \
        --seed "$seed" \
        --output-dir "results/phase17/v2_matrix_run1/${stage}_n${team}_s${seed}"
    done
  done
done

echo "All 48 experiments have finished."
