"""Replay the Phase 9 mock mission over a seeded degraded application network."""
import argparse
import json
import math
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from run_phase9_roles import run
from agentic_uav.comm.degraded import NetworkConfig,preset


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--condition',choices=['nominal','moderate','severe','partitioned'],default='nominal')
    p.add_argument('--network-config',help='JSON override of the selected preset')
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--ticks',type=int,default=1200);p.add_argument('--dt',type=float,default=.1)
    p.add_argument('--fail-agent',choices=['none','Drone1','Drone2','Drone3','Drone4'],default='none')
    p.add_argument('--fail-at',type=float,default=2.)
    p.add_argument('--critical-task',action='store_true');p.add_argument('--target-at',type=float,default=5.)
    p.add_argument('--output-dir',default='results/phase10/nominal')
    a=p.parse_args()
    if a.ticks<1 or not math.isfinite(a.dt) or a.dt<=0 or any(not math.isfinite(t) or t<0 for t in [a.fail_at,a.target_at]):p.error('Invalid timing')
    from dataclasses import asdict
    config=asdict(preset(a.condition))
    if a.network_config:config.update(json.loads(Path(a.network_config).read_text()))
    run(ticks=a.ticks,dt=a.dt,output_dir=a.output_dir,fail_agent=None if a.fail_agent=='none' else a.fail_agent,
        fail_at=a.fail_at,critical_task=a.critical_task,target_at=a.target_at,network_config=NetworkConfig(**config),seed=a.seed)

if __name__=='__main__':main()
