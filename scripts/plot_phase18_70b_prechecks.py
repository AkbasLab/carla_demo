"""Compare saved original and 70B prechecks without model or simulation calls."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    root=Path('results/phase17');out=Path('docs/figures/phase18_70b_prechecks');out.mkdir(parents=True,exist_ok=True)
    rows=[]
    for arch in 'BD':
        for model in ('original','70b'):
            batch=f'fixed_time_v4_precheck_{arch}1' if model=='original' else f'fixed_time_v4_precheck_{arch}70b_run1'
            for condition in ('control','loss'):
                name=f'{arch}_n4_nominal_{condition}_s10'+('_70b' if model=='70b' else '')
                run=root/batch/name/'run';s=json.loads((run/'summary.json').read_text())
                responses=[json.loads(line) for f in run.glob('Drone*/responses.jsonl') for line in f.read_text().splitlines()]
                arrivals=json.loads((run/'waypoint_arrivals.json').read_text())
                row=dict(architecture=arch,model=model,condition=condition,tasks=len(s['completed_task_ids']),
                    complete=s['mission_complete'],time_s=s['time_s'],productive_llm_decisions=sum(s['llm_productive_decisions_by_agent'].values()),
                    responses=len(responses),timeouts=sum(x.get('error_type')=='TimeoutError' for x in responses),
                    recorded_latency_s=[x.get('latency_s') for x in responses],
                    arrivals=len(arrivals),fallback_authorized_arrivals=sum(x.get('authorization_source')=='deterministic_fallback' for x in arrivals))
                rows.append(row)
    (out/'comparison.json').write_text(json.dumps(rows,indent=2)+'\n')
    fig,axs=plt.subplots(1,2,figsize=(12,4.6),constrained_layout=True)
    labels=[]
    for i,(arch,cond) in enumerate((('B','control'),('B','loss'),('D','control'),('D','loss'))):
        labels.append(f'{arch} {cond}')
        for model,offset,color in [('original',-.18,'#3973ac'),('70b',.18,'#bb563c')]:
            r=next(x for x in rows if x['architecture']==arch and x['condition']==cond and x['model']==model)
            axs[0].bar(i+offset,r['tasks'],width=.34,color=color,label=model if i==0 else None)
            axs[0].text(i+offset,r['tasks']+.1,f"{r['tasks']}/4",ha='center')
            axs[1].bar(i+offset,r['productive_llm_decisions'],width=.34,color=color)
            axs[1].text(i+offset,r['productive_llm_decisions']+.1,str(r['productive_llm_decisions']),ha='center')
    for ax in axs:ax.set_xticks(range(4),labels);ax.grid(axis='y',alpha=.2);ax.set_ylim(0,5)
    axs[0].set_title('Mission task completion');axs[0].set_ylabel('Completed tasks');axs[0].legend()
    axs[1].set_title('Productive LLM decisions');axs[1].set_ylabel('Decision count')
    fig.suptitle('Pinned-model prechecks: four drones, nominal communication, seed 10\n70B D completes through fallback; no productive 70B LLM decisions recorded')
    fig.savefig(out/'model_comparison.png',dpi=180);plt.close(fig)


if __name__=='__main__':main()
