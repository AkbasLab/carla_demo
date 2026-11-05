"""Rerun the matched Phase 13 matrix at explicitly recorded duration budgets."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentic_uav.experiments.followup import run_followup


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', default='configs/phase13/comparison.pinned.example.json')
    p.add_argument('--profile', choices=['pinned', 'validation'], default='pinned')
    p.add_argument('--durations', type=float, nargs='+', default=[300, 600, 1200])
    p.add_argument('--seeds', type=int, nargs='+', default=[42])
    p.add_argument('--workers', type=int, default=1)
    p.add_argument('--output-dir', default='results/phase13/duration_followup_run1')
    p.add_argument('--resume', action='store_true')
    p.add_argument('--plan-only', action='store_true')
    a = p.parse_args()
    result = run_followup(json.loads(Path(a.config).read_text()), a.seeds, a.output_dir,
        a.durations, a.profile, a.workers, a.resume, a.plan_only)
    print(json.dumps(result, indent=2))
    if result.get('suite_checks_passed') is False:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
