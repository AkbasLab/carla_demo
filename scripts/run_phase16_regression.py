"""Run one observed-flight regression; AirSim is opt-in and requires local calibration."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentic_uav.experiments.regression import CASES, run_regression


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case',choices=CASES,required=True)
    p.add_argument('--mission-config',required=True)
    p.add_argument('--output-dir',required=True)
    p.add_argument('--backend',choices=['mock','airsim'],default='mock')
    p.add_argument('--execute-live',action='store_true')
    p.add_argument('--host',default='127.0.0.1')
    for name,default in [('duration',120.),('dt',.1),('speed',1.),('lease-seconds',20.),('fail-at',1.),('rpc-timeout',2.),('setup-timeout',90.)]:
        p.add_argument('--'+name,type=float,default=default)
    result=run_regression(**vars(p.parse_args()))
    print(json.dumps(result,indent=2))
    return 0 if result['passed'] else 1

if __name__=='__main__':
    raise SystemExit(main())
