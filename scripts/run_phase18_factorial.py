"""Phase 18: draft, validate, freeze and resume the main factorial experiment."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agentic_uav.experiments.factorial import plan, validate_extensions, write_validation_report, prepare, execute, summarize


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('plan','validate','prepare'):
        p=sub.add_parser(name)
        p.add_argument('--config',default='configs/phase18/factorial.example.json')
        p.add_argument('--output-dir',required=True)
        if name!='plan':p.add_argument('--phase17-lock',required=True)
        if name=='prepare':p.add_argument('--validation-dir',required=True)
    p=sub.add_parser('analyze-validation');p.add_argument('--validation-dir',required=True)
    for name in ('run','summarize'):
        p=sub.add_parser(name);p.add_argument('--definition-dir',required=True);p.add_argument('--output-dir',required=True)
        if name=='run':p.add_argument('--max-runs',type=int)
    args=parser.parse_args()
    if args.command=='plan':result=plan(args.config,args.output_dir)
    elif args.command=='validate':result=validate_extensions(args.config,args.phase17_lock,args.output_dir)
    elif args.command=='analyze-validation':result=write_validation_report(args.validation_dir)
    elif args.command=='prepare':result=prepare(args.config,args.phase17_lock,args.validation_dir,args.output_dir)
    elif args.command=='run':result=execute(args.definition_dir,args.output_dir,args.max_runs)
    else:result=summarize(args.definition_dir,args.output_dir)
    print(json.dumps({k:v for k,v in result.items() if k not in ('runs','cells','attempt_records','selected_metrics')},indent=2))
    return 1 if args.command in ('validate','analyze-validation') and not result['eligible_for_main'] else 0

if __name__=='__main__':raise SystemExit(main())
