"""Run matched seeds across Phase 10 conditions; keep compact per-run summaries."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import redirect_stdout
import csv
import io
import json
import math
from pathlib import Path
import statistics
from run_phase9_roles import run
from agentic_uav.comm.degraded import preset


def trial(job):
    condition,seed,ticks,dt,root=job
    with redirect_stdout(io.StringIO()):
        s=run(ticks=ticks,dt=dt,output_dir=Path(root)/condition/f'seed_{seed}',
              fail_agent=None,network_config=preset(condition),seed=seed,record_details=False)
    return dict(condition=condition,seed=seed,mission_complete=s['mission_complete'],
        tasks_completed=sum(s['completions_by_agent'].values()),time_s=s['time_s'],
        duplicate_task_completions=s['duplicate_task_completions'],lease_expirations=s['lease_expirations'],
        role_changes=s['role_changes'],health_transitions=s['health_transitions'])


def aggregate(rows):
    out={}
    for condition in sorted({r['condition'] for r in rows}):
        group=[r for r in rows if r['condition']==condition];n=len(group)
        successes=[r['time_s'] for r in group if r['mission_complete']];p=len(successes)/n
        z=1.95996398454;den=1+z*z/n
        center=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
        out[condition]=dict(trials=n,successful_missions=len(successes),success_rate=p,
            success_rate_wilson_95=[max(0.,center-half),min(1.,center+half)],
            completion_time_successful_mean_s=statistics.mean(successes) if successes else None,
            completion_time_successful_median_s=statistics.median(successes) if successes else None,
            mean_tasks_completed=statistics.mean(r['tasks_completed'] for r in group),
            runs_with_all_four_tasks_completed=sum(r['tasks_completed']==4 and r['duplicate_task_completions']==0 for r in group),
            mean_lease_expirations=statistics.mean(r['lease_expirations'] for r in group),
            runs_with_duplicate_completions=sum(r['duplicate_task_completions']>0 for r in group))
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seeds',nargs='+',type=int,default=list(range(1,31)))
    p.add_argument('--conditions',nargs='+',choices=['nominal','moderate','severe','partitioned'],default=['nominal','moderate','severe','partitioned'])
    p.add_argument('--ticks',type=int,default=1200);p.add_argument('--dt',type=float,default=.1)
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--output-dir',default='results/phase10/multiseed')
    a=p.parse_args()
    if a.ticks<1 or a.workers<1 or not math.isfinite(a.dt) or a.dt<=0:p.error('Invalid timing or workers')
    if len(set(a.seeds))!=len(a.seeds) or len(set(a.conditions))!=len(a.conditions):p.error('Duplicate seeds or conditions')
    root=Path(a.output_dir)
    if root.exists() and any(root.iterdir()):p.error('Use an empty output directory to avoid mixing sweeps')
    root.mkdir(parents=True,exist_ok=True)
    jobs=[(c,s,a.ticks,a.dt,a.output_dir) for c in a.conditions for s in a.seeds];rows=[]
    (root/'manifest.json').write_text(json.dumps(dict(seeds=a.seeds,conditions=a.conditions,ticks=a.ticks,dt=a.dt,
        failure_injection=None,details_recorded=False),indent=2)+'\n')
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        for future in as_completed([pool.submit(trial,j) for j in jobs]):
            rows.append(future.result())
            print(f'{len(rows)}/{len(jobs)} trials finished',flush=True)
    rows.sort(key=lambda r:(r['condition'],r['seed']))
    with (root/'trials.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator="\n");writer.writeheader();writer.writerows(rows)
    summary=aggregate(rows)
    (root/'comparison.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
