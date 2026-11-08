"""Small Phase 17 recovery batches: run smoke first, then four pinned cases at a time."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agentic_uav.experiments.pilot_v2_runner import execute,restore_evidence


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    r=sub.add_parser('run');r.add_argument('--config',default='configs/phase17/resilience_v2.json')
    r.add_argument('--stage',choices=['smoke','focused','severe'],default='smoke')
    r.add_argument('--profile',choices=['pinned','replay'],default='pinned')
    r.add_argument('--team-size',type=int,choices=[2,4],default=4);r.add_argument('--seed',type=int,default=7)
    r.add_argument('--architectures',nargs='+',choices=list('ABCD'),
                   help='Select any subset; default C/D (C for smoke). Each architecture runs control and fault.')
    r.add_argument('--telemetry',choices=['alive','silent'],default='alive')
    r.add_argument('--fault-trigger',choices=['owned_motion','fixed_time'],default='owned_motion')
    r.add_argument('--no-compress',action='store_true');r.add_argument('--output-dir',required=True)
    r=sub.add_parser('restore');r.add_argument('--run-dir',required=True)
    a=p.parse_args()
    if a.command=='restore':result=restore_evidence(a.run_dir)
    else:
        result=execute(a.config,a.output_dir,stage=a.stage,team_size=a.team_size,seed=a.seed,profile=a.profile,
            telemetry=a.telemetry,fault_mode=a.fault_trigger,compress=not a.no_compress,architectures=a.architectures)
        result={k:v for k,v in result.items() if k not in ('rows','source')}
    print(json.dumps(result,indent=2))
    return 1 if result.get('status') in ('interrupted','stopped_on_error','stopped_at_data_budget') else 0

if __name__=='__main__':raise SystemExit(main())
