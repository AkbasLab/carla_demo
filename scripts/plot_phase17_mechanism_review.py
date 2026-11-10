#!/usr/bin/env python3
"""Plot selected saved mechanism reviews, retaining distinct seed-15 attempts."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

GROUPS=[('C · n2 · seed 10','severe_C_n2_s10','C_n2'),
        ('C · n4 · seed 15','severe_C_D_n2_s15','C_n4'),
        ('C · n4 · seed 20','severe_C_n4_s20','C_n4'),
        ('D · n2 · seed 10','severe_D_n2_s10','D_n2'),
        ('D · n4 · seed 15\nCombined batch','severe_C_D_n2_s15','D_n4'),
        ('D · n4 · seed 15\nSeparate batch','severe_D_n4_s15','D_n4')]


def main():
    base=ROOT/'results/phase17/mechanism_review_v1'
    out=ROOT/'docs/figures/phase17_mechanism_review';out.mkdir(parents=True,exist_ok=True)
    groups=[]
    for label,folder,prefix in GROUPS:
        records=json.loads((base/folder/'mechanisms.json').read_text())
        chosen=[next(r for r in records if r['experiment_id'].startswith(prefix+'_') and
                     f'_severe_{kind}_' in r['experiment_id']) for kind in ['control','loss']]
        groups.append((label,folder,chosen))
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(2,1,figsize=(13,9),layout='constrained')
    x=np.arange(len(groups));width=.35
    for i,(name,color) in enumerate([('No policy failure','#64748b'),('Policy failure','#007c91')]):
        vals=[g[2][i]['waypoint_arrivals']['unique_required_waypoints'] for g in groups]
        bars=axes[0].bar(x+(i-.5)*width,vals,width,color=color,label=name)
        axes[0].bar_label(bars,labels=[f'{v}/16'+(' ✓' if g[2][i]['mission_complete'] else '') for v,g in zip(vals,groups)],padding=3)
        vals=[g[2][i]['policy']['approach_invalidations'] for g in groups]
        bars=axes[1].bar(x+(i-.5)*width,vals,width,color=color)
        axes[1].bar_label(bars,padding=3)
    axes[0].axhline(16,color='#334155',ls=':',lw=1);axes[0].set_ylim(0,19)
    axes[0].set_title('Observed required waypoint work; ✓ = mission complete')
    axes[1].set_title('Approach invalidations: a diagnostic count, not a success score')
    axes[1].set_ylim(0,31)
    for ax in axes:
        ax.set_xticks(x,[g[0] for g in groups]);ax.set_axisbelow(True);ax.grid(axis='y',alpha=.2)
    axes[0].legend(loc='lower left')
    fig.suptitle('Phase 17 mechanism reviews: severe communication\n12 evaluable executions; repeated seed-15 attempts remain separate; interrupted seed-8 record excluded from outcome bars',fontsize=13)
    for ext in ['png','pdf']:fig.savefig(out/f'work_and_replanning.{ext}',dpi=180,bbox_inches='tight')
    plt.close(fig)
    fig,ax=plt.subplots(figsize=(13,6),layout='constrained')
    for y,(label,folder,records) in enumerate(groups):
        record=records[1];r=record['recovery'][0]
        delay=r['replacement_accepted_s']-r['fault_s']
        ax.barh(y,delay,color='#2563eb',height=.55)
        if r['acceptance_to_arrival_s'] is not None:
            remaining=r['acceptance_to_arrival_s'];color='#15803d';hatch=None
            text=f'First new arrival; mission {"complete" if record["mission_complete"] else "incomplete"}'
        else:
            remaining=r['observed_until_s']-r['replacement_accepted_s'];color='#ffedd5';hatch='///'
            text='No replacement arrival before horizon'
        ax.barh(y,remaining,left=delay,color=color,hatch=hatch,edgecolor='#9a3412' if hatch else color,height=.55)
        ax.text(delay+remaining+2,y,text,va='center',fontsize=9)
    ax.set_yticks(range(len(groups)),[g[0] for g in groups]);ax.invert_yaxis()
    ax.set_xlim(0,340);ax.set_xlabel('Seconds since injected policy failure')
    ax.set_title('Recovery: accepting work is different from reaching its first new waypoint')
    ax.grid(axis='x',alpha=.2);ax.set_axisbelow(True)
    fig.legend(handles=[Patch(color='#2563eb',label='Failure → replacement acceptance'),
        Patch(color='#15803d',label='Acceptance → first productive arrival'),
        Patch(facecolor='#ffedd5',edgecolor='#9a3412',hatch='///',label='Observed wait; arrival censored')],loc='outside lower center',ncol=1)
    for ext in ['png','pdf']:fig.savefig(out/f'recovery_intervals.{ext}',dpi=180,bbox_inches='tight')
    plt.close(fig)
    (out/'figure_sources.json').write_text(json.dumps([dict(label=label,review_folder=folder,
        records=records) for label,folder,records in groups],indent=2)+'\n')
    print(out)


if __name__=='__main__':main()
