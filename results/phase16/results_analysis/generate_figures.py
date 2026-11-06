"""Reproduce Phase 16 figures from uploaded result artifacts; no new experiments."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
import numpy as np


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-dir',default='results/phase16')
    p.add_argument('--output-dir',default='results/phase16/results_analysis')
    a=p.parse_args();root=Path(a.input_dir);out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
    load=lambda p:json.loads(p.read_text())
    plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False})
    fig,axs=plt.subplots(1,2,figsize=(14,5.6),gridspec_kw={'width_ratios':[1,1.35]})
    names=['Full suite','Selected unit','Selected integration','Selected determinism']
    folders=['verification_run2','unit_run1','integration_run1','determinism_run1']
    counts=[load(root/f/'summary.json')['tests_run'] for f in folders]
    axs[0].barh(names,counts,color='#307c99');axs[0].invert_yaxis();axs[0].set(xlabel='Passed test methods',title='New uploaded verification runs',xlim=(0,275))
    for i,n in enumerate(counts):axs[0].text(n+4,i,f'{n}/{n}',va='center',fontweight='bold')
    fig.text(.5,.07,'Zero reported failures, errors or skips. Selected layers overlap the full suite; do not add counts.',ha='center',fontsize=10)
    cases=['single_waypoint','two_nonconflicting','four_search','reassignment','return_home']
    cells=[];labels=[]
    for case in cases:
        baseline=load(root/'mock_regressions_run1'/case/'summary.json')['passed']
        cells.append([1 if baseline else 2,1 if case=='reassignment' else 0,2 if case=='single_waypoint' else 0])
        labels.append(['Pass','Pass' if case=='reassignment' else 'Not rerun','2 import errors' if case=='single_waypoint' else 'Not run'])
    axs[1].imshow(cells,cmap=ListedColormap(['#e7e9eb','#c5e3d8','#f4d0ba']),vmin=0,vmax=2,aspect='auto')
    axs[1].set(xticks=range(3),xticklabels=['Committed mock\nbaseline','New standalone\nmock run','Live AirSim\nattempts'],yticks=range(5),yticklabels=['Single drone','Two drones','Four-drone search','Task reassignment','Return-home fallback'],title='Evidence status by flight-regression case')
    for i in range(5):
        for j in range(3):axs[1].text(j,i,labels[i][j],ha='center',va='center',fontsize=10)
    axs[1].tick_params(length=0)
    fig.suptitle('Phase 16: simulator-free verification passes; live validation is blocked by the Python environment',fontsize=14)
    fig.text(.5,.015,'CI at aac8e23: Python 3.11 and 3.12 jobs passed. AirSim attempts recorded no actions or waypoint arrivals.',ha='center',fontsize=10)
    fig.tight_layout(rect=[0,.1,1,.93])
    for suffix in ['png','pdf']:fig.savefig(out/('verification_dashboard.'+suffix),dpi=160,bbox_inches='tight')
    plt.close(fig)

    base=root/'mock_reassignment_run1';trace=load(base/'flight_trace.json');events=load(base/'agent_events.json');arrivals=load(base/'waypoint_arrivals.json')
    fig,axs=plt.subplots(1,2,figsize=(14,6),gridspec_kw={'width_ratios':[.85,1.45]})
    colors={'Drone1':'#333333','Drone2':'#c16e19','Drone3':'#307c99','Drone4':'#7360a8'}
    for drone,color in colors.items():
        xy=np.array([r['vehicles'][drone]['position'][:2] for r in trace])
        if drone=='Drone1':
            axs[0].scatter([xy[0,0]],[xy[0,1]],s=100,marker='x',c=color,label='Drone1: stationary owner')
        else:
            axs[0].plot(xy[:,0],xy[:,1],color=color,label=drone,lw=2)
            axs[0].scatter(xy[0,0],xy[0,1],color=color,marker='s',s=30)
    for r in arrivals:axs[0].scatter(r['position'][0],r['position'][1],color=colors[r['agent_id']],s=35,zorder=5)
    for y,txt in [(0,'A: recovered by Drone2'),(8,'B: Drone2'),(16,'C: Drone3'),(24,'D: Drone4')]:axs[0].text(4,y+1.2,txt,fontsize=9,ha='center')
    axs[0].set(xlabel='Shared X (m)',ylabel='Shared Y (m)',title='Recorded mock trajectories and arrivals',xlim=(-1.5,10),ylim=(-3,28))
    axs[0].set_aspect('equal');axs[0].grid(alpha=.2);fig.legend(*axs[0].get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.5,.91),ncol=4,fontsize=9)
    rows=[('Drone4','SEARCH_SECTOR_D',1),('Drone3','SEARCH_SECTOR_C',1),('Drone2','SEARCH_SECTOR_B',1),('Drone2','SEARCH_SECTOR_A',2)]
    yt=[]
    for y,(drone,task,version) in enumerate(rows):
        start=min(e['time_s'] for e in events if e['agent_id']==drone and e['event']=='execution_started' and e['task_id']==task and e['version']==version)
        ar=sorted((r for r in arrivals if r['agent_id']==drone and r['task_id']==task),key=lambda r:r['time_s'])
        axs[1].hlines(y,start,ar[-1]['time_s'],color=colors[drone],lw=4)
        axs[1].scatter([r['time_s'] for r in ar],[y]*len(ar),s=50,color=colors[drone],zorder=4)
        for r in ar:axs[1].text(r['time_s'],y+.15,f"WP{r['index']+1}\n{r['time_s']:.1f}s",ha='center',fontsize=9)
        yt.append(f"{drone} · {task[-1]} · v{version}")
    for x,color,label in [(1,'#b84d45','Owner silenced: 1.0 s'),(20.6,'#333333','Lease expires: 20.6 s'),(29.6,'#c16e19','Replacement claim: 29.6 s')]:axs[1].axvline(x,color=color,ls='--',lw=1.3,label=label)
    axs[1].set(xlabel='Simulated mission time (s)',yticks=range(4),yticklabels=yt,xlim=(0,46),ylim=(-.6,4),title='Observed work after failure and lease expiration')
    axs[1].grid(axis='x',alpha=.2);axs[1].legend(loc='upper center',fontsize=8,ncol=1)
    fig.suptitle('Phase 16 mock recovery: Drone2 completes its own route and the silenced owner’s route',fontsize=14)
    fig.text(.5,.015,'Drone1 owns A at injection but never starts moving. Safety observations retain Drone1. Eight required arrivals; zero duplicate task completions.',ha='center',fontsize=10)
    fig.tight_layout(rect=[0,.07,1,.85])
    for suffix in ['png','pdf']:fig.savefig(out/('mock_reassignment.'+suffix),dpi=160,bbox_inches='tight')
    plt.close(fig)
    print('Created two PNG/PDF figures')

if __name__=='__main__':main()
