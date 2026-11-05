"""Evaluate existing Phase 14 evidence; absent pre-run registration is retrospective."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agentic_uav.experiments.metrics import evaluate_batch


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-dir',required=True)
    p.add_argument('--output-dir',required=True)
    a=p.parse_args();result=evaluate_batch(a.input_dir,a.output_dir)
    print(json.dumps(result,indent=2))
    if result['evidence_issues']:raise SystemExit(1)


if __name__=='__main__':main()
