#!/usr/bin/env python3
"""Plot the two Phase 17 result cohorts without pooling attempts or seeds."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from agentic_uav.experiments.metrics import Evidence

BASE=ROOT/'results/phase17/severe_recovery_v4'
OUT=ROOT/'docs/figures/phase17_architecture_comparisons'


def batch(name):
    manifest=json.loads((BASE/name/'v2_manifest.json').read_text())
    return {r['experiment_id']:r for r in manifest['rows']}


def save(fig,name):
    for ext in ['png','pdf']:fig.savefig(OUT/f'{name}.{ext}',dpi=180,bbox_inches='tight')
    plt.close(fig)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    sources=[]
    specs=[('abcd_n2_s10',2,10),('abcd_n2_s12',2,12),('abcd_n4_s13',4,13)]
    fig,axes=plt.subplots(1,2,figsize=(13,6),layout='constrained')
    for ax,kind,title in zip(axes,['control','loss'],['No injected policy failure','Injected policy failure']):
        values=[];rows=[]
        for folder,n,seed in specs:
            records=batch(folder)
            selected=[records[f'{a}_n{n}_severe_{kind}_s{seed}'] for a in 'ABCD']
            rows.append(selected);values.append([r['completed_tasks'] for r in selected])
            for r in selected:sources.append(dict(cohort='34874ca_full_ABCD',folder=folder,row=r))
        im=ax.imshow(values,cmap='Blues',vmin=0,vmax=4,aspect='auto')
        for y,selected in enumerate(rows):
            for x,r in enumerate(selected):
                outcome=f"{r['time_s']:.1f} s" if r['mission_complete'] else 'incomplete'
                ax.text(x,y,f"{r['completed_tasks']}/4\n{outcome}",ha='center',va='center',
                    color='white' if r['completed_tasks']>=3 else '#111827',fontsize=11)
        ax.set_xticks(range(4),['A\nCentralized','B\nIndependent\nLLM','C\nDecentralized\nrules','D\nDecentralized\nLLM'])
        ax.set_yticks(range(3),['2 drones · seed 10','2 drones · seed 12','4 drones · seed 13'])
        ax.set_title(title)
    fig.colorbar(im,ax=axes,label='Tasks completed',ticks=range(5),shrink=.7)
    fig.suptitle('Commit 34874ca cohort: three complete matched A/B/C/D batches\nSevere networking in both panels; successful times only; incomplete cases observed to ≈240 s',fontsize=13)
    save(fig,'matched_abcd_outcomes')

    specs=[('cd_n2_s15',2,15),('cd_n2_s5',2,5),('cd_n4_s20',4,20)]
    columns=[('C','control','C control','#475569'),('C','loss','C failure','#007c91'),
             ('D','control','D control','#8b5cf6'),('D','loss','D failure','#c2410c')]
    rows=[];diagnostics=[]
    for folder,n,seed in specs:
        records=batch(folder);selected=[];diag=[]
        for a,kind,_,_ in columns:
            r=records[f'{a}_n{n}_severe_{kind}_s{seed}'];selected.append(r)
            e=Evidence(BASE/folder/'runs'/r['experiment_id']/'run')
            summary=e.read('summary.json')
            history=[x for aid in summary['decisions_by_agent'] for x in e.read(aid+'/decision_history.jsonl')]
            protocol=e.read('protocol_events.json')
            d=dict(approach_invalidations=sum(x['event']=='alternative_approach_invalidated' for x in history),
                local_lease_expirations=sum(x['event']=='lease_expired' for x in protocol),
                unique_waypoints=len({(x['task_id'],x['index']) for x in e.read('waypoint_arrivals.json')}))
            diag.append(d);sources.append(dict(cohort='a4e2143_CD',folder=folder,row=r,diagnostics=d))
        rows.append(selected);diagnostics.append(diag)
    fig,axes=plt.subplots(3,1,figsize=(13,12),layout='constrained')
    values=[[r['completed_tasks'] for r in rr] for rr in rows]
    im=axes[0].imshow(values,cmap='Blues',vmin=0,vmax=4,aspect='auto')
    for y,rr in enumerate(rows):
        for x,r in enumerate(rr):
            outcome=f"{r['time_s']:.1f} s" if r['mission_complete'] else f"{diagnostics[y][x]['unique_waypoints']}/16 waypoints; incomplete"
            axes[0].text(x,y,f"{r['completed_tasks']}/4 tasks\n{outcome}",ha='center',va='center',
                color='white' if r['completed_tasks']>=3 else '#111827',fontsize=10)
    labels=['2 drones · seed 15','2 drones · seed 5','4 drones · seed 20']
    axes[0].set_yticks(range(3),labels);axes[0].set_xticks(range(4),[c[2] for c in columns])
    axes[0].set_title('Mission completion: all six C missions finish; none of these six D missions finish')
    fig.colorbar(im,ax=axes[0],label='Tasks completed',ticks=range(5),shrink=.8)
    for ax,key,title in [(axes[1],'approach_invalidations','Approach invalidations: repeated replanning remains prominent in D'),
                         (axes[2],'local_lease_expirations','Local lease-expiration events (not unique fleet-wide expirations)')]:
        for i,(_,_,label,color) in enumerate(columns):
            bars=ax.bar(np.arange(3)+(i-1.5)*.19,[d[i][key] for d in diagnostics],.19,label=label,color=color)
            ax.bar_label(bars,padding=3)
        ax.set_xticks(range(3),labels);ax.set_title(title);ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True)
        ax.margins(y=.18)
    axes[1].legend(ncol=4)
    fig.suptitle('Commit a4e2143 cohort: severe C/D outcomes and mechanisms\nSame corrected core implementation; development observations, not an additional algorithm revision',fontsize=13)
    save(fig,'latest_cd_outcomes_and_churn')
    (OUT/'figure_data.json').write_text(json.dumps(sources,indent=2)+'\n')
    print(OUT)


if __name__=='__main__':main()
