"""Nine-panel per-run methodology inspection using observed Phase 14 artifacts."""
from collections import Counter
import json
from pathlib import Path


def plot_run(folder,target):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch
    import numpy as np
    folder=Path(folder);target=Path(target)
    load=lambda name:json.loads((folder/'run'/name).read_text())
    manifest=load('manifest.json');summary=load('summary.json');trace=load('flight_trace.json')
    mission=manifest['shared_inputs']['mission'];ids=list(mission['vehicles']);tasks=[t['task_id'] for t in mission['tasks']]
    events=[json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines()]
    packets=load('messages.json');audit=load('guardian_audit.json');arrivals=load('waypoint_arrivals.json');protocol=load('protocol_events.json')
    end=max(summary['time_s'],.01);colors={a:plt.get_cmap('tab10')(i) for i,a in enumerate(ids)}
    fig,grid=plt.subplots(3,3,figsize=(18,13));axs=grid.ravel()
    def empty(ax,text='None recorded'):ax.text(.5,.5,text,ha='center',va='center',transform=ax.transAxes,fontsize=9)
    for a in ids:
        rows=[r for r in trace if r['agent_id']==a]
        axs[0].plot([r['position'][0] for r in rows],[r['position'][1] for r in rows],color=colors[a],label=a)
        if rows:axs[0].scatter(rows[0]['position'][0],rows[0]['position'][1],color=colors[a],marker='s',s=15)
    axs[0].set(title='1. Observed mock trajectories',xlabel='Shared X (m)',ylabel='Shared Y (m)');axs[0].set_aspect('equal',adjustable='datalim');axs[0].legend(fontsize=7)
    def categorical(ax,key,title,labels,palette):
        times=sorted({r['time_s'] for r in trace});step=manifest['effective_configuration']['dt']
        if not times:empty(ax,'Trace unavailable');return
        lookup={(r['time_s'],r['agent_id']):r for r in trace}
        values=[[key(lookup[(t,a)]) for t in times] for a in ids]
        edges=times+[times[-1]+step]
        ax.pcolormesh(edges,np.arange(len(ids)+1),values,cmap=ListedColormap(palette),vmin=-.5,vmax=len(labels)-.5,shading='flat')
        ax.set(title=title,yticks=np.arange(len(ids))+.5,yticklabels=ids,xlabel='Mission time (s)',xlim=(0,end))
        ax.legend(handles=[Patch(facecolor=palette[i],label=l) for i,l in enumerate(labels)],fontsize=6,ncol=3,loc='upper right')
    def local_task_label(r):
        if not r['active']:return 'silenced'
        task=r.get('execution_task_id')
        if task:return ('move ' if r.get('active_command_kind')=='MOVE' else 'selected ')+task.removeprefix('SEARCH_SECTOR_')
        owned=sorted(t['task_id'].removeprefix('SEARCH_SECTOR_') for t in r.get('owned_tasks',[]))
        return 'owned '+','.join(owned) if owned else 'idle'
    tasklabels=sorted({local_task_label(r) for r in trace})
    categorical(axs[1],lambda r:tasklabels.index(local_task_label(r)),'2. Local task selection / full ownership set',
                tasklabels,[plt.get_cmap('tab20')(i%20) for i in range(len(tasklabels))])
    categorical(axs[2],lambda r:['SCOUT','RELAY','RESERVE'].index(r['role']),'3. Recorded role (including stopped actor)',
                ['SCOUT','RELAY','RESERVE'],['#8ac2d0','#efbc65','#b6a1d6'])
    bins=np.linspace(0,end,31)
    for status,color in [('delivered','#3b9274'),('dropped','#c25959'),('expired','#c89630'),('queued','#888888')]:
        ts=[m['creation_time'] for m in packets if m['status']==status]
        counts,_=np.histogram(ts,bins)
        axs[3].step(bins[:-1],counts,where='post',label=f'{status}: {len(ts)}',color=color)
    axs[3].set(title='4. Recipient outcomes by packet creation time',xlabel='Mission time (s)',ylabel='Packets / bin');axs[3].legend(fontsize=7)
    for a in ids:
        rows=[r for r in trace if r['agent_id']==a and r['active']]
        vals=[max((x['heartbeat_age_s'] for x in r['communication_estimate'].values() if x.get('heartbeat_age_s') is not None),default=float('nan')) for r in rows]
        axs[4].plot([r['time_s'] for r in rows],vals,color=colors[a],label=a)
    axs[4].set(title='5. Observed maximum peer heartbeat age',xlabel='Mission time (s)',ylabel='Age (s)');axs[4].legend(fontsize=7)
    claims=[e for e in events if e['event_type']=='TASK_ASSIGNED' and e['agent_id']==e['data'].get('owner')]
    for e in claims:
        task=e['data']['task_id'];a=e['agent_id']
        axs[5].scatter(e['simulation_time_s'],tasks.index(task),color=colors[a],s=20)
    axs[5].set(title='6. Local ownership acceptance / reassignment',xlabel='Mission time (s)',yticks=range(len(tasks)),yticklabels=[t.removeprefix('SEARCH_SECTOR_') for t in tasks],ylim=(-.5,len(tasks)-.5))
    axs[5].legend(handles=[Patch(color=colors[a],label=a) for a in ids],fontsize=7)
    if not claims:empty(axs[5])
    calls=[e for e in events if e['event_type']=='LLM_CALLED']
    proposals=[e for e in events if e['event_type']=='DECISION_PROPOSED']
    for e in calls:
        if e['agent_id'] in ids:axs[6].scatter(e['simulation_time_s'],ids.index(e['agent_id']),facecolors='none',edgecolors='#7055aa',marker='o',s=30)
    for e in proposals:
        if e['agent_id'] in ids:axs[6].scatter(e['simulation_time_s'],ids.index(e['agent_id']),color='#7055aa' if e['data']['source']=='llm' else '#999999',marker='x',s=15)
    for e in proposals[:16]:
        if e['agent_id'] in ids:axs[6].annotate(e['data']['decision']['selected_tool'],(e['simulation_time_s'],ids.index(e['agent_id'])),xytext=(1,4),textcoords='offset points',fontsize=5,rotation=30)
    axs[6].set(title=f'7. LLM calls: {len(calls)}; policy proposals: {len(proposals)}',xlabel='Mission time (s)',yticks=range(len(ids)),yticklabels=ids,ylim=(-.5,len(ids)))
    if not calls:axs[6].text(.5,.85,'No actual LLM calls (replay/rules)',transform=axs[6].transAxes,ha='center',fontsize=8)
    if not proposals:empty(axs[6])
    cats={'routine modification':('#999999','o'),'rejection':('#c25959','^'),'corrective modification':('#307c99','D'),'fallback':('#d58d25','*')}
    classified=[]
    for r in audit:
        if r['outcome']=='APPROVE':continue
        key='routine modification' if r['outcome']=='APPROVE_WITH_MODIFICATION' and set(r['reasons'])<= {'bounded_motion_segment'} else 'corrective modification' if r['outcome']=='APPROVE_WITH_MODIFICATION' else 'fallback' if r['outcome']=='EXECUTE_SAFE_FALLBACK' else 'rejection'
        classified.append((key,r))
    for key,(color,marker) in cats.items():
        rs=[r for k,r in classified if k==key and r['vehicle_id'] in ids]
        axs[7].scatter([r['time_s'] for r in rs],[ids.index(r['vehicle_id']) for r in rs],color=color,marker=marker,s=15,label=f'{key}: {len(rs)}')
    axs[7].set(title='8. Guardian outcomes requiring intervention',xlabel='Mission time (s)',yticks=range(len(ids)),yticklabels=ids);axs[7].legend(fontsize=7)
    if not classified:empty(axs[7],'No interventions recorded')
    seen=set();times=[0.];work=[0.]
    for r in sorted(arrivals,key=lambda r:r['time_s']):
        seen.add((r['task_id'],r['index']));times.append(r['time_s']);work.append(len(seen)/sum(len(t['waypoints']) for t in mission['tasks']))
    times.append(end);work.append(work[-1]);axs[8].step(times,work,where='post',label='Unique required waypoint work',color='#307c99')
    done=set();ct=[0.];cv=[0.]
    for r in sorted(protocol,key=lambda r:r['time_s']):
        if r['event']=='work_completed':done.add(r['task_id']);ct.append(r['time_s']);cv.append(len(done)/len(tasks))
    axs[8].step(ct+[end],cv+[cv[-1]],where='post',label='Unique tasks completed',color='#3b9274',ls='--')
    axs[8].set(title='9. Observed mission progress',xlabel='Mission time (s)',ylabel='Fraction',ylim=(0,1.05));axs[8].legend(fontsize=7)
    faults=[e['simulation_time_s'] for e in events if e['event_type']=='FAULT_INJECTED']
    for ax in axs[1:]:
        ax.set_xlim(0,end);ax.grid(alpha=.15)
        for x in faults:ax.axvline(x,color='#b94c4c',ls=':',alpha=.7,lw=1)
        for p in manifest['shared_inputs']['network']['partitions']:ax.axvspan(p['start_s'],p['end_s'],color='#999999',alpha=.15)
    identity=manifest['effective_provider'];kind='actual pinned LLM' if summary['llm_inference'] else 'replay / deterministic, no inference'
    fig.suptitle(f"Phase 17 pilot: {folder.name}\n{kind}; clock={manifest['effective_clock']}; completed={summary['mission_complete']}",fontsize=13)
    fig.text(.5,.01,'Dotted lines: injected actor silence. Shading: configured partitions only. Heartbeat gaps are observations, not proof of RF outage. Local ownership does not imply authorized movement.',ha='center',fontsize=8)
    fig.tight_layout(rect=[0,.035,1,.94]);target.parent.mkdir(parents=True,exist_ok=True);fig.savefig(target,dpi=120);plt.close(fig)
