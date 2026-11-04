"""Run the guide's matched scenarios and ablations into separate, figure-ready folders."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agentic_uav.experiments.suite import run_suite


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='configs/phase13/comparison.example.json')
    p.add_argument('--profile',choices=['validation','pinned'],default='validation')
    p.add_argument('--seeds',type=int,nargs='+',default=[42])
    p.add_argument('--workers',type=int,default=1)
    p.add_argument('--output-dir',default='results/phase13/automated_validation')
    p.add_argument('--resume',action='store_true');p.add_argument('--keep-raw-traces',action='store_true')
    a=p.parse_args(argv)
    result=run_suite(json.loads(Path(a.config).read_text()),a.seeds,a.output_dir,a.profile,a.workers,not a.keep_raw_traces,a.resume)
    print(json.dumps(result,indent=2))
    if result['runtime_errors'] or result['validation_failures'] or result['mismatched_input_checks'] or result['reproducibility_checks_passed'] is False or result['statuses'].get('blocked_model_unavailable'):raise SystemExit(1)

if __name__=='__main__':main()
