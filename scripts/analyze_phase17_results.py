"""Review existing Phase 17 evidence without rerunning or modifying experiments."""
import argparse
import collections
import csv
import json
from pathlib import Path
import statistics

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np


def read(root,name):
    path=root/name
    if not path.exists():path=root/name.replace('/','__')
    return json.loads(path.read_text())


def review(source,output,commit):
    root=Path(source);out=Path(output);out.mkdir(parents=True,exist_ok=True)
    report=read(root,'analysis/calibration_report.json');metrics=read(root,'runs/metrics/metrics.json')
    batch=read(root,'runs/batch_manifest.json');config=read(root,'pilot_config.json')
    indexed={m['experiment_id']:m for m in metrics};rows=[];audits=[]
    for r in report['runs']:
        name=r['experiment_id'];m=indexed[name];s=read(root,f'runs/{name}/run/summary.json')
        arrivals=read(root,f'runs/{name}/run/waypoint_arrivals.json');faults=read(root,f'runs/{name}/run/scenario_events.json')
        unique={(a['task_id'],a['index']) for a in arrivals};expected=m['diagnostic']['unique_productive_work']
        checks=dict(summary_matches_metric_success=s['mission_execution_success']==m['primary']['mission']['success'],
            report_matches_summary=r['mission_complete']==s['mission_execution_success'],
            waypoint_units_match=len(unique)==expected,
            successful_time_matches=(m['primary']['completion_time']['value_s']==r['successful_time_s']),
            fault_observation_matches=any(e['event']=='actor_silenced' for e in faults)==r['fault_observed'],
            no_metric_evidence_issues=not m['evidence_issues'])
        if not all(checks.values()):raise ValueError('Inconsistent evidence: '+name+': '+str(checks))
        safety=m['primary']['safety'];diag=m['diagnostic'];time=m['primary']['completion_time']
        row=dict(experiment_id=name,architecture=r['architecture'],team_size=r['team_size'],network=r['condition'],
            fault=r['failure'],seed=r['seed'],success=r['mission_complete'],completed_tasks=m['primary']['mission']['completed_tasks'],
            unique_waypoints=len(unique),route_work_fraction=r['route_work_fraction'],successful_time_s=r['successful_time_s'],
            observation_time_s=time['observation_time_s'],censored=time['censored'],delivered_fraction_resolved=r['delivered_fraction_resolved'],
            mean_delivered_delay_s=r['mean_delivered_delay_s'],fault_observed=r['fault_observed'],fault_owned_tasks=bool(r['fault_owned_tasks']),
            fault_during_motion=r['fault_during_motion'],replacement_acceptances=sum(t['recovery_time_s'] is not None for rec in m['primary']['recovery'] for t in rec['tasks']),
            productive_resumptions=sum(t['productive_resume_time_s'] is not None for rec in m['primary']['recovery'] for t in rec['tasks']),
            productive_llm_decisions=r['productive_llm_decisions'],llm_calls=diag['llm_calls'],
            llm_mean_response_s=diag['llm_response_latency_mean_s'],fallback_policy_invocations=diag['fallback_policy_invocations'],
            invalid_outputs=diag['invalid_structured_outputs'],task_reassignments=diag['task_reassignments'],role_changes=diag['role_changes'],
            corrective_guardian_interventions=safety['corrective_guardian_interventions'],
            unverifiable_state_rejections=safety['unverifiable_state_rejections'],all_dispatched_actions_guarded=s['all_dispatched_actions_guarded'])
        rows.append(row);audits.append(dict(experiment_id=name,checks=checks))
    if len(rows)!=48 or batch['finished_runs']!=48:raise ValueError('Expected the complete 48-run pilot matrix')
    with (out/'run_metrics.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    faults=[r for r in rows if r['fault']!='none'];controls=[r for r in rows if r['fault']=='none'];d=[r for r in rows if r['architecture']=='D']
    summary=dict(source_commit=commit,source_dataset='results/phase17/pinned_run1',runs=len(rows),successes=sum(r['success'] for r in rows),
        runtime_errors=batch['errors'],censored=sum(r['censored'] for r in rows),
        nominal_controls=dict(successes=sum(r['success'] for r in controls if r['network']=='nominal'),runs=12),
        severe_controls=dict(successes=sum(r['success'] for r in controls if r['network']=='severe'),runs=12),
        fault_runs=dict(runs=len(faults),successes=sum(r['success'] for r in faults),observed=sum(r['fault_observed'] for r in faults),
            owned=sum(r['fault_owned_tasks'] for r in faults),moving=sum(r['fault_during_motion'] for r in faults),
            replacement_acceptances=sum(r['replacement_acceptances'] for r in faults),productive_resumptions=sum(r['productive_resumptions'] for r in faults)),
        llm=dict(runs=len(d),calls=sum(r['llm_calls'] for r in d),productive_decisions=sum(r['productive_llm_decisions'] for r in d),
            invalid_outputs=sum(r['invalid_outputs'] for r in d),fallback_policy_invocations=sum(r['fallback_policy_invocations'] for r in d)),
        safety=dict(all_runs_dispatched_actions_guarded=all(r['all_dispatched_actions_guarded'] for r in rows),
            collisions='not_observed_by_this_sensor_setup',sampled_separation_violations=sum(m['primary']['safety']['sampled_separation_violations'] for m in metrics),
            restricted_zone_entries_sampled=sum(m['primary']['safety']['restricted_zone_entries_sampled'] for m in metrics),
            corrective_guardian_interventions=sum(r['corrective_guardian_interventions'] for r in rows),unverifiable_state_rejections=sum(r['unverifiable_state_rejections'] for r in rows)),
        eligible_for_freeze=report['eligible_for_freeze'],freeze_blockers=report['freeze_blockers'],
        source_hash_sets=len({json.dumps(r['source_hashes'],sort_keys=True) for r in report['runs']}),
        configuration=config,calibration=report['calibration'],cells=report['cells'],independent_checks=audits,
        review_scope='All 48 stored summaries, metric records, waypoint-arrival lists, fault-event lists and calibration rows; selected raw histories/protocol logs inspected separately. Not a full re-evaluation of every large trace.')
    spot_checks={}
    for case in ['C_n4_nominal_loss_s41','D_n4_nominal_loss_s41','C_n4_severe_control_s41','D_n4_severe_control_s41']:
        name=f'runs/{case}/run/Drone2/decision_history.jsonl';path=root/name
        if not path.exists():path=root/name.replace('/','__')
        if not path.exists():continue
        history=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        errors=[e for e in history if e['event']=='policy_error']
        spot_checks[case]=dict(agent_id='Drone2',policy_event_counts=dict(collections.Counter(e['event'] for e in history)),
            policy_error_reason_counts=dict(collections.Counter(e.get('reason_code','unspecified') for e in errors)))
    summary['raw_history_spot_checks']=spot_checks
    (out/'review_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'savefig.dpi':170})
    groups=[(n,net,fault) for n in (2,4) for net in ('nominal','severe') for fault in ('none','drone_failure_midmission')]
    success=np.array([[sum(r['success'] for r in rows if (r['team_size'],r['network'],r['fault'],r['architecture'])==(n,net,f,a)) for a in 'CD'] for n,net,f in groups])
    work=np.array([[statistics.mean(r['route_work_fraction'] for r in rows if (r['team_size'],r['network'],r['fault'],r['architecture'])==(n,net,f,a)) for a in 'CD'] for n,net,f in groups])
    fig,axes=plt.subplots(1,2,figsize=(12,8.5),layout='constrained')
    labels=[f'{n} drones | {net} | '+('no fault' if f=='none' else 'Drone1 silent at 73 s') for n,net,f in groups]
    for ax,data,title,cmap,vmax in [(axes[0],success,'Completed missions per three seeds','Blues',3),(axes[1],work,'Mean unique waypoint-work fraction','YlGnBu',1)]:
        image=ax.imshow(data,cmap=cmap,vmin=0,vmax=vmax,aspect='auto');ax.set_xticks([0,1],['C: deterministic','D: pinned LLM'])
        ax.set_yticks(range(8),labels if ax==axes[0] else ['']*8);ax.set_title(title,pad=12)
        for i in range(8):
            for j in range(2):ax.text(j,i,f'{int(data[i,j])}/3' if ax==axes[0] else f'{data[i,j]:.1%}',ha='center',va='center',color='white' if data[i,j]>vmax*.6 else 'black',fontsize=13)
        fig.colorbar(image,ax=ax,fraction=.04,pad=.02)
    fig.suptitle('Phase 17 pinned pilot: 16/48 complete; all 24 fault missions incomplete\nSeeds 41–43; 600-second horizon; kinematic mock flight',fontsize=14)
    fig.savefig(out/'mission_outcomes.png',bbox_inches='tight');plt.close(fig)
    colors={'C':'#2463a6','D':'#b13778'};fig,ax=plt.subplots(figsize=(11,5.5),layout='constrained')
    for i,(n,net) in enumerate([(2,'nominal'),(2,'severe'),(4,'nominal'),(4,'severe')]):
        for a,offset in [('C',-.15),('D',.15)]:
            selected=sorted([r for r in controls if r['team_size']==n and r['network']==net and r['architecture']==a],key=lambda r:r['seed'])
            for k,r in enumerate(selected):
                y=r['successful_time_s'] if r['success'] else r['observation_time_s']
                ax.scatter(i+offset+(k-1)*.055,y,marker='o' if r['success'] else '^',color=colors[a],s=65,zorder=3)
    ax.axhline(600,color='gray',ls=':',lw=1);ax.set_ylim(0,640);ax.set_ylabel('Completion time or censored observation time (s)')
    ax.set_xticks(range(4),['2 drones\nNominal','2 drones\nSevere','4 drones\nNominal','4 drones\nSevere']);ax.grid(axis='y',alpha=.2)
    ax.legend(handles=[Line2D([],[],color=colors[a],marker='o',ls='',label=a) for a in 'CD']+
        [Line2D([],[],color='gray',marker='o',ls='',label='Completed'),Line2D([],[],color='gray',marker='^',ls='',label='Incomplete at horizon')],loc='lower right')
    ax.set_title('No-fault controls: show all seeds, including censored failures\nThree seeds per architecture/condition; triangles are not completion times')
    fig.savefig(out/'control_completion_times.png',bbox_inches='tight');plt.close(fig)
    fig,axes=plt.subplots(1,3,figsize=(15,4.8),layout='constrained')
    ax=axes[0]
    for i,net in enumerate(['nominal','severe']):
        for a,offset in [('C',-.12),('D',.12)]:
            vals=[r['delivered_fraction_resolved'] for r in controls if r['network']==net and r['architecture']==a]
            ax.scatter(np.linspace(i+offset-.04,i+offset+.04,len(vals)),vals,c=colors[a],s=35,alpha=.8)
    ax.set_xticks([0,1],['Nominal','Severe']);ax.set_ylim(0,1.08);ax.set_ylabel('Delivered / resolved recipient packets');ax.set_title('Control network delivery\nPending packets excluded')
    ax.legend(handles=[Line2D([],[],color=colors[a],marker='o',ls='',label=a) for a in 'CD'],loc='lower left')
    for idx,a in enumerate('CD'):
        rr=[r for r in faults if r['architecture']==a];moving=sum(r['fault_during_motion'] for r in rr)
        axes[1].bar(idx,moving,color=colors[a]);axes[1].bar(idx,len(rr)-moving,bottom=moving,color='#d9d9d9')
        axes[1].text(idx,moving/2,f'{moving}/12',ha='center',va='center',color='white',fontsize=13)
    axes[1].set_xticks([0,1],['C','D']);axes[1].set_ylim(0,13);axes[1].set_ylabel('Fault runs');axes[1].set_title('Fault interrupted active movement\nAll 24 faults interrupted owned tasks')
    axes[1].legend(handles=[plt.Rectangle((0,0),1,1,color='#777',label='Moving'),plt.Rectangle((0,0),1,1,color='#d9d9d9',label='Not moving')],loc='upper right')
    ax=axes[2];stages=['Fault\nobserved','Task\nowned','Active\nmovement','Replacement\naccepted','Productive\nresume']
    vals=[24,24,sum(r['fault_during_motion'] for r in faults),sum(r['replacement_acceptances'] for r in faults),sum(r['productive_resumptions'] for r in faults)]
    ax.bar(range(5),vals,color=['#457b9d','#457b9d','#e9a23b','#c94b4b','#c94b4b']);ax.set_xticks(range(5),stages,fontsize=8);ax.set_ylim(0,27);ax.set_title('Recovery evidence in fault cases\nLease expiration alone is not recovery')
    for i,v in enumerate(vals):ax.text(i,v+.5,str(v),ha='center')
    fig.suptitle('Communication degradation is observable; fault exposure and recovery still need work',fontsize=13)
    fig.savefig(out/'calibration_and_recovery.png',bbox_inches='tight');plt.close(fig)
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-dir',default='results/phase17/pinned_run1')
    p.add_argument('--output-dir',default='results/phase17/pinned_run1/review');p.add_argument('--source-commit',required=True)
    a=p.parse_args();s=review(a.source_dir,a.output_dir,a.source_commit)
    print(json.dumps({k:s[k] for k in ['source_commit','runs','successes','runtime_errors','censored','fault_runs','llm','safety','eligible_for_freeze','freeze_blockers']},indent=2))
