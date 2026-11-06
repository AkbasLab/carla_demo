"""Phase 17 pilot matrix, individual inspection, calibration and guarded final freeze."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agentic_uav.experiments.pilots import prepare,run_pilots,analyze,freeze,verify_frozen,run_frozen


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    for name in ('prepare','run'):
        q=sub.add_parser(name);q.add_argument('--config',default='configs/phase17/pilot.example.json')
        q.add_argument('--profile',choices=['validation','pinned'],default='validation');q.add_argument('--output-dir',required=True)
    q=sub.add_parser('analyze');q.add_argument('--pilot-dir',required=True)
    q=sub.add_parser('freeze');q.add_argument('--pilot-dir',required=True);q.add_argument('--output-dir',required=True);q.add_argument('--rationale',required=True)
    q=sub.add_parser('verify-frozen');q.add_argument('--frozen-dir',required=True)
    q=sub.add_parser('run-frozen');q.add_argument('--frozen-dir',required=True);q.add_argument('--output-dir',required=True)
    a=p.parse_args()
    if a.command=='prepare':result=prepare(a.config,a.output_dir,a.profile)
    elif a.command=='run':
        r=run_pilots(a.config,a.output_dir,a.profile);result={k:v for k,v in r.items() if k!='runs'}
        if r['errors'] or r.get('evaluation_error') or r['status']=='interrupted':print(json.dumps(result,indent=2));return 1
    elif a.command=='analyze':
        r=analyze(a.pilot_dir);result={k:v for k,v in r.items() if k not in ('runs','cells')}
    elif a.command=='freeze':result=freeze(a.pilot_dir,a.output_dir,a.rationale)
    elif a.command=='verify-frozen':verify_frozen(a.frozen_dir);result=dict(verified=True)
    else:
        r=run_frozen(a.frozen_dir,a.output_dir);result={k:v for k,v in r.items() if k!='runs'}
        if r['errors'] or r.get('evaluation_error') or r['status']=='interrupted':print(json.dumps(result,indent=2));return 1
    print(json.dumps(result,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
