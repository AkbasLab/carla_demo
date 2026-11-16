"""Inspect saved fixed-time prechecks; no simulation or model calls."""
import argparse
import collections
import json
import math
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def read(path):
    return json.loads(path.read_text())


def analyze(root, output):
    output.mkdir(parents=True, exist_ok=True)
    rows=[]; evidence={}; hashes=[]
    for arch in 'ABCD':
        for condition in ('control','loss'):
            run=root/f'fixed_time_v4_precheck_{arch}1'/f'{arch}_n4_nominal_{condition}_s10'/'run'
            summary=read(run/'summary.json'); trace=read(run/'flight_trace.json')
            arrivals=read(run/'waypoint_arrivals.json'); events=read(run/'scenario_events.json')
            protocol=read(run/'protocol_events.json'); guardian=read(run/'guardian_audit.json')
            manifest=read(run/'manifest.json'); hashes.append(manifest['source_hashes'])
            faults=[e for e in events if e['event']=='actor_silenced']
            fault=faults[0] if faults else None
            row=dict(architecture=arch,condition=condition,tasks=len(summary['completed_task_ids']),
                mission_complete=summary['mission_complete'],time_s=summary['time_s'],error=summary['error'],
                policy_errors=summary.get('policy_errors_by_agent',{}),
                productive_llm_decisions=sum(summary.get('llm_productive_decisions_by_agent',{}).values()),
                guardian_reasons=dict(collections.Counter(r for e in guardian for r in e['reasons'])))
            if fault:
                t=fault['time_s']; agent=fault['agent_id']
                pre=max((x for x in trace if x['agent_id']==agent and x['time_s']<t),key=lambda x:x['time_s'])
                speed=math.sqrt(sum(v*v for v in pre['velocity']))
                owned=[x['task_id'] for x in pre['owned_tasks'] if x['lease_expires_at']>t]
                task=pre['execution_task_id'] or (owned[0] if owned else None)
                executions=sorted((x for x in protocol if x['event']=='execution_started' and x.get('task_id')==task
                    and x['agent_id']!=agent and x['time_s']>t),key=lambda x:x['time_s'])
                # Required visit identity includes index: repeated laps count as separate visits, not extra area.
                seen={(x['task_id'],x['index']) for x in arrivals if x['time_s']<=t}
                productive=[]
                for x in sorted((x for x in arrivals if x['time_s']>t),key=lambda x:x['time_s']):
                    k=(x['task_id'],x['index'])
                    if k not in seen and x['task_id']==task and x['agent_id']!=agent:productive.append(x)
                    seen.add(k)
                row.update(fault_s=t,pre_fault_sample_s=pre['time_s'],speed_mps=speed,
                    owned_tasks=owned,execution_task_id=pre['execution_task_id'],active_command_kind=pre['active_command_kind'],
                    interrupted_owned_motion=bool(owned and pre['execution_task_id'] in owned and speed>0.01 and pre['active_command_kind']=='MOVE'),
                    first_replacement_execution_s=executions[0]['time_s'] if executions else None,
                    first_new_replacement_arrival_s=productive[0]['time_s'] if productive else None,
                    pre_fault_position=pre['position'])
            rows.append(row); evidence[arch,condition]=(trace,arrivals,protocol)
    (output/'inspection.json').write_text(json.dumps(dict(rows=rows,source_hashes_match=all(h==hashes[0] for h in hashes)),indent=2)+'\n')
    colors=dict(A='#377eb8',B='#4daf4a',C='#d6ad22',D='#a93479')
    fig,axs=plt.subplots(1,2,figsize=(12,4.5),constrained_layout=True)
    for i,arch in enumerate('ABCD'):
        for condition,offset,hatch in [('control',-.18,None),('loss',.18,'//')]:
            r=next(x for x in rows if x['architecture']==arch and x['condition']==condition)
            axs[0].bar(i+offset,r['tasks'],width=.34,color=colors[arch],hatch=hatch,alpha=.9)
            axs[0].text(i+offset,r['tasks']+.06,f"{r['tasks']}/4",ha='center')
            axs[1].scatter(i+offset,r['time_s'],color=colors[arch],marker='o' if r['mission_complete'] else '^',s=80)
            axs[1].annotate(f"{r['time_s']:.1f}",(i+offset,r['time_s']),xytext=(0,8),textcoords='offset points',ha='center',fontsize=9)
    for ax in axs:ax.set_xticks(range(4),list('ABCD'));ax.grid(axis='y',alpha=.2)
    axs[0].set_ylim(0,4.7);axs[0].set_ylabel('Completed tasks');axs[0].set_title('Solid: control; hatched: fixed-time fault')
    axs[1].set_ylim(0,270);axs[1].axhline(240,color='gray',ls=':');axs[1].set_ylabel('Completion / observation time (s)');axs[1].set_title('Circles: complete; triangles: incomplete')
    fig.suptitle('Fixed-time prechecks: four drones, nominal communication, seed 10\nSingle runs; incomplete observations are not completion times')
    fig.savefig(output/'outcomes.png',dpi=180);plt.close(fig)
    fig,axs=plt.subplots(2,2,figsize=(12,7),constrained_layout=True)
    for ax,arch in zip(axs.flat,'ABCD'):
        tr,_,_=evidence[arch,'loss']; own=[x for x in tr if x['agent_id']=='Drone1' and 25<=x['time_s']<=50]
        ax.plot([x['time_s'] for x in own],[math.sqrt(sum(v*v for v in x['velocity'])) for x in own],color=colors[arch])
        ax.axvline(40,color='red',ls='--',label='Fixed fault');ax.set_ylim(-.05,1.2)
        r=next(x for x in rows if x['architecture']==arch and x['condition']=='loss')
        ax.set_title(f"{arch}: owned moving work {'YES' if r['interrupted_owned_motion'] else 'NO'} before fault")
        ax.set_xlabel('Mission time (s)');ax.set_ylabel('Drone1 speed (m/s)');ax.grid(alpha=.2)
    fig.suptitle('Fault exposure: use the last sample BEFORE cancellation\nAll four actors own Sector A; D has not begun execution')
    fig.savefig(output/'fault_exposure.png',dpi=180);plt.close(fig)
    fig,axs=plt.subplots(2,2,figsize=(12,7),constrained_layout=True)
    for ax,arch in zip(axs.flat,'ABCD'):
        _,arr,_=evidence[arch,'loss']
        for task in ['SEARCH_SECTOR_'+x for x in 'ABCD']:
            seen=set();ts=[0];counts=[0]
            for e in sorted((e for e in arr if e['task_id']==task),key=lambda x:x['time_s']):
                if e['index'] not in seen:seen.add(e['index']);ts.append(e['time_s']);counts.append(len(seen))
            ts.append(240);counts.append(len(seen));ax.step(ts,counts,where='post',label=task[-1])
        ax.axvline(40,color='red',ls='--');ax.set_ylim(0,13);ax.set_xlim(0,240)
        ax.set_title(f'{arch}: failure-run progress');ax.set_ylabel('Distinct required waypoint indices');ax.set_xlabel('Mission time (s)');ax.grid(alpha=.2);ax.legend(title='Sector',ncol=4,fontsize=8)
    fig.suptitle('Recovery progress: 12 required visits per task\nRepeated visits are declared route work, not unique area searched')
    fig.savefig(output/'recovery_progress.png',dpi=180);plt.close(fig)
    return rows


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--results-root',type=Path,default=Path('results/phase17'))
    p.add_argument('--output-dir',type=Path,default=Path('docs/figures/phase18_fixed_time_prechecks'))
    a=p.parse_args();rows=analyze(a.results_root,a.output_dir)
    print(json.dumps(rows,indent=2))
