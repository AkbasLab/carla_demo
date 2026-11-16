"""Prepare a fixed-time candidate and small per-architecture nominal checks.

No flight, inference, held-out execution or calibration approval is performed.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agentic_uav.experiments.pilots import prepare,read,resolve
from agentic_uav.experiments.factorial import verify_common_fault_time


def build_checks(config_path,output_dir):
    config=read(resolve(config_path));verify_common_fault_time(config)
    root=Path(output_dir).resolve();plan=prepare(config_path,root,'pinned')
    entries=read(root/'pilot_batch.json')['experiments']
    seed=config['pilot_seeds'][0];team=max(config['team_sizes'])
    templates=[e for e in entries if e['architecture']=='C' and e['random_seed']==seed
               and e['team_size']==team and e['network_profile']=='nominal']
    paths={}
    for architecture in 'ABCD':
        selected=[]
        for template in templates:
            entry=copy.deepcopy(template);entry['architecture']=architecture
            entry['experiment_id']=architecture+entry['experiment_id'][1:]
            entry['scenario']='phase18_fixed_time_calibration_precheck'
            entry['planner']='deterministic' if architecture in 'AC' else config['model']['model']
            selected.append(entry)
        path=root/f'precheck_{architecture}.json'
        path.write_text(json.dumps(dict(schema_version=1,experiments=selected),indent=2)+'\n')
        paths[architecture]=str(path)
    return dict(prepared=True,calibration_approved=False,fault_time_s=config['fail_at_s'],
        route_repetitions=config.get('route_repetitions',1),planned_calibration_runs=plan['planned_experiments'],
        precheck_team_size=team,precheck_seed=seed,cases_per_precheck=len(templates),precheck_batches=paths)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='configs/phase18/calibration_v4.candidate.json')
    parser.add_argument('--output-dir',required=True)
    args=parser.parse_args();print(json.dumps(build_checks(args.config,args.output_dir),indent=2))


if __name__=='__main__':main()
