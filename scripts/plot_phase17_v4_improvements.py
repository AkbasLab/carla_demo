#!/usr/bin/env python3
"""Reproduce the V4 report figures from saved, possibly ZIP-packed evidence."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator
from agentic_uav.experiments.metrics import Evidence

CASES=[('D · 2 drones\nControl', 'D',2,10,'control'),
       ('D · 2 drones\nPolicy failure','D',2,10,'loss'),
       ('C · 4 drones\nControl','C',4,20,'control'),
       ('C · 4 drones\nPolicy failure','C',4,20,'loss')]
COLORS=['#7b8794','#007c91']


def load(arch,team,seed,kind,updated):
    base=ROOT/'results/phase17'
    if updated:
        folder=base/'severe_recovery_v4_verified'/f'severe_{arch}_n{team}_s{seed}'
    else:
        folder=base/'severe_recovery_v4'/('severe_D_n2_s10' if arch=='D' else 'severe_cd_n4_s20')
    case=f'{arch}_n{team}_severe_{kind}_s{seed}'
    row=next(r for r in json.loads((folder/'v2_manifest.json').read_text())['rows'] if r['experiment_id']==case)
    evidence=Evidence(folder/'runs'/case/'run')
    summary=evidence.read('summary.json')
    history=[r for aid in summary['decisions_by_agent'] for r in evidence.read(aid+'/decision_history.jsonl')]
    return dict(row=row,arrivals=evidence.read('waypoint_arrivals.json'),
        protocol=evidence.read('protocol_events.json'),
        health=sum(r['event']=='peer_health_changed' for r in history),
        source=str(folder.relative_to(ROOT)))


def save(fig,path):
    fig.savefig(path.with_suffix('.png'),dpi=180,bbox_inches='tight')
    fig.savefig(path.with_suffix('.pdf'),bbox_inches='tight')
    plt.close(fig)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'docs/figures/phase17_v4')
    args=parser.parse_args();out=args.output_dir;out.mkdir(parents=True,exist_ok=True)
    data=[[load(a,n,s,k,updated) for _,a,n,s,k in CASES] for updated in [False,True]]
    labels=[c[0] for c in CASES];x=np.arange(4);width=.34
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(2,2,figsize=(13,9),layout='constrained')
    for ax,title,extract,limit in [
        (axes[0,0],'Completed tasks',lambda d:d['row']['completed_tasks'],4),
        (axes[0,1],'Unique required waypoint arrivals',lambda d:len({(r['task_id'],r['index']) for r in d['arrivals']}),16),
        (axes[1,0],'Peer-health transitions (logarithmic axis)',lambda d:d['health'],None)]:
        for i,name in enumerate(['Previous code','Corrected code']):
            values=[extract(d) for d in data[i]]
            bars=ax.bar(x+(i-.5)*width,values,width,color=COLORS[i],label=name)
            ax.bar_label(bars,padding=3)
        ax.set_title(title);ax.set_xticks(x,labels);ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True)
        if limit:
            ax.axhline(limit,color='#4b5563',ls=':',lw=1);ax.set_ylim(0,limit*1.2)
            ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        else:ax.set_yscale('log');ax.set_ylim(1,15000)
    ax=axes[1,1]
    for i,name in enumerate(['Previous code','Corrected code']):
        for j,d in enumerate(data[i]):
            complete=d['row']['mission_complete'];t=d['row']['time_s']
            ax.scatter(j+(i-.5)*width,t,marker='o' if complete else '^',color=COLORS[i],s=75)
            if complete:ax.annotate(f'{t:.1f}',(j+(i-.5)*width,t),xytext=(0,-16),textcoords='offset points',ha='center',fontsize=9)
    ax.axhline(240,color='#4b5563',ls=':',lw=1)
    ax.set_ylim(0,275);ax.set_xticks(x,labels);ax.set_ylabel('Seconds')
    ax.set_title('Completion time / observation horizon');ax.grid(axis='y',alpha=.18)
    ax.legend(handles=[Line2D([],[],marker='o',color='none',markerfacecolor='#4b5563',label='Completed'),
        Line2D([],[],marker='^',color='none',markerfacecolor='#4b5563',label='Incomplete at horizon')],loc='lower left')
    axes[0,0].legend(loc='upper left')
    fig.suptitle('Phase 17 V4: mixed severe-communication outcomes\nOne paired development run per case; mock flight; network and safety limits retained',fontsize=14)
    save(fig,out/'severe_comparison')

    fig,axes=plt.subplots(3,1,figsize=(13,9),layout='constrained',sharex=True)
    selections=[(1,'SEARCH_SECTOR_A','D, two drones: replacement Sector A'),
                (0,'SEARCH_SECTOR_D','D, two drones: late Sector D work'),
                (3,'SEARCH_SECTOR_C','C, four drones: repeated Sector C claims')]
    for ax,(idx,task,title) in zip(axes,selections):
        d=data[1][idx];team=CASES[idx][2];agents=[f'Drone{i}' for i in range(1,team+1)];mapping={a:i for i,a in enumerate(agents)}
        for event,marker,color in [('claim_sent','s','#007c91'),('task_released','x','#b45309')]:
            for r in d['protocol']:
                if r['event']==event and r.get('task_id')==task and r['agent_id'] in mapping:
                    y=mapping[r['agent_id']];ax.scatter(r['time_s'],y,marker=marker,color=color,s=50)
                    if event=='claim_sent':ax.annotate(f"v{r['version']}",(r['time_s'],y),xytext=(0,9),textcoords='offset points',ha='center',fontsize=8)
        for r in d['arrivals']:
            if r['task_id']==task:
                y=mapping[r['agent_id']];ax.scatter(r['time_s'],y,color='#15803d',marker='o',s=45)
                ax.annotate(f"WP{r['index']+1}",(r['time_s'],y),xytext=(0,-16-12*(r['index']%2)),textcoords='offset points',ha='center',fontsize=8)
        if d['row']['fault_s'] is not None:ax.axvline(d['row']['fault_s'],color='#9333ea',ls=':',lw=1)
        ax.set_yticks(range(team),agents);ax.set_ylim(-.6,team-.4);ax.set_title(title,loc='left')
        ax.grid(alpha=.15);ax.set_xlim(0,245)
    axes[-1].set_xlabel('Elapsed mission time (s)')
    fig.legend(handles=[Line2D([],[],marker=m,color=c,ls='',label=l) for m,c,l in
        [('s','#007c91','Local claim sent (version labelled)'),('x','#b45309','Task released'),
         ('o','#15803d','Observed required waypoint'),('|','#9333ea','Injected policy failure (dotted line)')]],
        loc='outside lower center',ncol=2)
    fig.suptitle('Corrected-code timelines: claims are not productive recovery\nLocal protocol events; no continuous trajectories or global ownership consensus implied',fontsize=13)
    save(fig,out/'remaining_task_timelines')
    records=[]
    for version,group in zip(['previous','corrected'],data):
        for label,d in zip(labels,group):
            records.append(dict(version=version,case=label.replace('\n',' '),source=d['source'],
                completed_tasks=d['row']['completed_tasks'],mission_complete=d['row']['mission_complete'],
                time_s=d['row']['time_s'],unique_waypoints=len({(r['task_id'],r['index']) for r in d['arrivals']}),
                peer_health_transitions=d['health']))
    (out/'figure_data.json').write_text(json.dumps(records,indent=2)+'\n')
    print(out)


if __name__=='__main__':main()
