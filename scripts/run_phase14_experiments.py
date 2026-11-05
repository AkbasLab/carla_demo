"""Run a Phase 14 configuration list with manifests and streaming JSONL events."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agentic_uav.experiments.runner import run_batch


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--batch',default='configs/phase14/batch.example.json')
    p.add_argument('--output-dir',default='results/phase14/local_batch_run1')
    a=p.parse_args();result=run_batch(a.batch,a.output_dir)
    print(json.dumps(result,indent=2))
    if result['errors'] or result['status']=='interrupted':raise SystemExit(1)


if __name__=='__main__':main()
