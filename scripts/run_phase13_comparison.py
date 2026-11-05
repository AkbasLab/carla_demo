"""Select a controlled Phase 13 architecture and ablations through configuration."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agentic_uav.experiments.comparison import run_comparison,configuration


def parse_configuration(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='configs/phase13/comparison.example.json')
    p.add_argument('--architecture',choices=list('ABCD'))
    p.add_argument('--condition',choices=['nominal','moderate','severe','partitioned'])
    p.add_argument('--seed',type=int);p.add_argument('--ticks',type=int);p.add_argument('--dt',type=float)
    p.add_argument('--output-dir');p.add_argument('--mission-config')
    p.add_argument('--provider',choices=['replay','ollama']);p.add_argument('--model');p.add_argument('--model-digest')
    p.add_argument('--fail-agent',choices=['none','Drone1','Drone2','Drone3','Drone4']);p.add_argument('--fail-at',type=float)
    p.add_argument('--without-memory',action='store_true');p.add_argument('--without-task-leases',action='store_true')
    p.add_argument('--without-dynamic-roles',action='store_true');p.add_argument('--perfect-communication',action='store_true')
    p.add_argument('--fallback-policy',action='store_true')
    a=p.parse_args(argv);values=json.loads(Path(a.config).read_text())
    for key in ('architecture','condition','seed','ticks','dt','output_dir','mission_config'):
        if getattr(a,key) is not None:values[key]=getattr(a,key)
    for key in ('provider','model','model_digest'):
        if getattr(a,key) is not None:values.setdefault('policy',{})[key]=getattr(a,key)
    if a.fail_agent is not None:values.setdefault('scenario',{})['fail_agent']=None if a.fail_agent=='none' else a.fail_agent
    if a.fail_at is not None:values.setdefault('scenario',{})['fail_at_s']=a.fail_at
    for attr,key,value in [('without_memory','persistent_memory',False),('without_task_leases','task_leases',False),
                          ('without_dynamic_roles','dynamic_roles',False),('perfect_communication','perfect_communication',True),('fallback_policy','fallback_policy',True)]:
        if getattr(a,attr):values.setdefault('ablations',{})[key]=value
    return configuration(values)

if __name__=='__main__':
    result=run_comparison(parse_configuration());print(json.dumps(result,indent=2))
    if result['error']:raise SystemExit(1)
