"""Rebuild the Phase 17 V2 matrix review; never reruns or modifies experiment inputs."""
import argparse
import collections
import csv
from datetime import datetime
import json
from pathlib import Path
import re
import statistics

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np


def load(path):return json.loads(Path(path).read_text())


def analyze(source,output,commit,bundle=None):
    source=Path(source);out=Path(output);out.mkdir(parents=True,exist_ok=True)
    if bundle:
        data=load(bundle)
        if data['commit']!=commit:raise ValueError('Bundle source commit mismatch')
    else:
        manifests=[];evaluations=[];summaries=[]
        for p in sorted(source.glob('*/v2_manifest.json')):
            manifests.append(dict(path=str(p),data=load(p)))
            evaluations.extend(load(p.parent/'analysis/metrics.json'))
            for row in manifests[-1]['data']['rows']:
                q=p.parent/'runs'/row['experiment_id']/'run/summary.json'
                summaries.append(dict(path=str(q),data=load(q)))
        data=dict(commit=commit,manifests=manifests,metrics=evaluations,summaries=summaries)
    # IDs are unique over this matrix, irrespective of downloaded cache layout.
    summaries={x['path'].split('/runs/')[-1].split('/')[0]:x['data'] for x in data['summaries']}
    metrics={x['experiment_id']:x for x in data['metrics']};rows=[];audits=[]
    for batch in data['manifests']:
        if batch['data']['status']!='finished':raise ValueError('Batch not finished: '+batch['path'])
        for raw in batch['data']['rows']:
            r=dict(raw);name=r['experiment_id'];m=metrics[name];s=summaries[name]
            matched=re.fullmatch(r'([CD])_n([24])_(nominal|severe)_(control|loss)_s(\d+)',name)
            if not matched:raise ValueError('Unexpected case ID: '+name)
            r.update(team_size=int(matched[2]),network=matched[3],fault=matched[4]=='loss',batch=batch['path'])
            checks=dict(success_agrees=r['mission_complete']==m['primary']['mission']['success']==s['mission_execution_success'],
                task_count_agrees=r['completed_tasks']==m['primary']['mission']['completed_tasks']==len(s['completed_task_ids']),
                work_agrees=r['route_work_fraction']==m['diagnostic']['route_work_fraction'],
                inference_calls_agree=r['llm_calls']==m['diagnostic']['llm_calls'],
                productive_decisions_agree=r['productive_llm_decisions']==sum(s['llm_productive_decisions_by_agent'].values()),
                no_top_level_error=r['error'] is None and s['error'] is None,
                no_metric_issues=not r['metric_issues'] and not m['evidence_issues'])
            if not all(checks.values()):raise ValueError('Inconsistent evidence: '+name+': '+str(checks))
            r['applied_llm_decisions']=sum(s['decisions_by_agent'].values()) if r['architecture']=='D' else 0
            r['fallbacks']=sum(s['fallbacks_by_agent'].values())
            r['timeout_errors']=sum(x.get('inference_timeout',0) for x in s['policy_errors_by_agent'].values())
            r['http_errors']=sum(x.get('HTTPError',0) for x in s['policy_errors_by_agent'].values())
            r['peer_region_policy_errors']=sum(x.get('unsafe_action:peer_reachable_region_conflict',0) for x in s['policy_errors_by_agent'].values())
            rows.append(r);audits.append(dict(experiment_id=name,checks=checks))
    if len(rows)!=48 or len({r['experiment_id'] for r in rows})!=48:raise ValueError('Expected 48 unique cases')
    faults=[r for r in rows if r['fault']];d=[r for r in rows if r['architecture']=='D']
    starts=[datetime.fromisoformat(x['data']['started_at_utc']) for x in data['manifests']]
    ends=[datetime.fromisoformat(x['data']['finished_at_utc']) for x in data['manifests']]
    summary=dict(source_commit=commit,runs=48,batches=len(data['manifests']),successes=sum(r['mission_complete'] for r in rows),
        architecture_successes={a:sum(r['mission_complete'] for r in rows if r['architecture']==a) for a in 'CD'},
        fault=dict(runs=24,owned_moving=sum(r['fault_owned'] and r['fault_during_move'] for r in faults),
            accepted=sum(r['replacement_s'] is not None for r in faults),productive=sum(r['productive_resume_s'] is not None for r in faults),completed=sum(r['mission_complete'] for r in faults)),
        llm=dict(calls=sum(r['llm_calls'] for r in d),timeouts=sum(r['timeout_errors'] for r in d),http_errors=sum(r['http_errors'] for r in d),
            applied_decisions=sum(r['applied_llm_decisions'] for r in d),productive_decisions=sum(r['productive_llm_decisions'] for r in d),
            fallback_invocations=sum(r['fallbacks'] for r in d),successful_runs_with_applied_llm_decisions=sum(r['mission_complete'] and r['applied_llm_decisions']>0 for r in d)),
        safety=dict(guarded_runs=sum(r['all_dispatched_actions_guarded'] for r in rows),
            separation_violation_samples=sum(r['sampled_separation_violations'] for r in rows),
            restricted_zone_entries=sum(m['primary']['safety']['restricted_zone_entries_sampled'] for m in data['metrics']),
            collisions=None,collision_reason='not_collected',unverifiable_state_rejections=sum(m['primary']['safety']['unverifiable_state_rejections'] for m in data['metrics']),
            corrective_interventions=sum(m['primary']['safety']['corrective_guardian_interventions'] for m in data['metrics'])),
        peer_region_policy_errors_C=sum(r['peer_region_policy_errors'] for r in rows if r['architecture']=='C'),
        stored_bytes=sum(x['data']['stored_bytes'] for x in data['manifests']),raw_case_bytes=sum(r['raw_bytes'] for r in rows),
        elapsed_span_s=(max(ends)-min(starts)).total_seconds(),mission_time_sum_s=sum(r['time_s'] for r in rows),
        all_batch_checks_passed=all(x['data']['diagnostic_checks_passed'] for x in data['manifests']),
        cross_checks=audits,limitations=['Pilot evidence, three seeds per cell; not a final architecture ranking',
            'V1/V2 have different seeds, fault/telemetry semantics and time budgets',
            'Summaries/metrics cross-checked for all cases; raw responses inspected only in selected archives',
            'Storage totals are manifest snapshots, not a full recomputation of Git repository size'])
    (out/'analysis_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    keys=[k for k in rows[0] if k not in ('metric_issues','error')]
    with (out/'run_metrics.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'savefig.dpi':160})
    colors={'C':'#2463a6','D':'#ac3476'};groups=[(n,p) for n in [2,4] for p in ['nominal','severe']]
    fig,axes=plt.subplots(1,2,figsize=(10,5.8),layout='constrained')
    for ax,fault,title in [(axes[0],False,'No-fault controls'),(axes[1],True,'Policy-stop fault, telemetry alive')]:
        values=np.array([[sum(r['mission_complete'] for r in rows if (r['team_size'],r['network'],r['fault'],r['architecture'])==(n,p,fault,a)) for a in 'CD'] for n,p in groups])
        image=ax.imshow(values,cmap='Blues',vmin=0,vmax=3,aspect='auto')
        ax.set_xticks([0,1],['C: deterministic','D: pinned-model policy']);ax.set_yticks(range(4),[f'{n} drones | {p}' for n,p in groups]);ax.set_title(title,pad=12)
        for i in range(4):
            for j in range(2):ax.text(j,i,f'{values[i,j]}/3',ha='center',va='center',fontsize=19,color='white' if values[i,j]>=2 else 'black')
    fig.colorbar(image,ax=axes,ticks=[0,1,2,3],fraction=.025,label='Completed missions per three seeds')
    fig.suptitle('Phase 17 V2 pinned matrix: 19/48 missions complete\nSeeds 7–9; 240-second horizon; kinematic mock flight',fontsize=14)
    fig.savefig(out/'completion_matrix.png',bbox_inches='tight');plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,5),layout='constrained')
    values=[summary['fault'][k] for k in ['owned_moving','accepted','productive','completed']];axes[0].bar(range(4),values,color=['#457b9d','#457b9d','#e6a03c','#409273'])
    axes[0].set_xticks(range(4),['Owned active\nMOVE interrupted','Replacement\naccepted','Productive work\nresumed','Mission\ncompleted']);axes[0].set_ylim(0,28);axes[0].set_ylabel('Fault cases / 24');axes[0].set_title('Reassignment is now observed; execution still lags')
    for i,v in enumerate(values):axes[0].text(i,v+.5,str(v),ha='center',fontsize=14)
    vals=[summary['llm'][k] for k in ['calls','timeouts','http_errors','applied_decisions','productive_decisions']]
    axes[1].bar(range(5),vals,color=['#457b9d','#c85353','#d69b41','#8564ae','#409273']);axes[1].set_xticks(range(5),['LLM\ncalls','Timeout\nerrors','HTTP\nerrors','Applied\nLLM decisions','Productive\nLLM decisions']);axes[1].set_ylim(0,195);axes[1].set_title('D: inference availability is the dominant bottleneck')
    for i,v in enumerate(vals):axes[1].text(i,v+3,str(v),ha='center',fontsize=13)
    fig.suptitle('Recovery and inference counters — counts are not mutually exclusive request categories',fontsize=12)
    fig.savefig(out/'recovery_and_inference.png',bbox_inches='tight');plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(13,5.3),layout='constrained')
    for i,(n,p) in enumerate(groups):
        for a,offset in [('C',-.15),('D',.15)]:
            selected=sorted([r for r in rows if (r['team_size'],r['network'],r['fault'],r['architecture'])==(n,p,False,a)],key=lambda r:r['seed'])
            for j,r in enumerate(selected):axes[0].scatter(i+offset+(j-1)*.05,r['time_s'],s=55,marker='o' if r['mission_complete'] else '^',color=colors[a])
    axes[0].axhline(240,color='gray',ls=':',lw=1);axes[0].set_ylim(0,270);axes[0].set_xticks(range(4),[f'{n} drones\n{p.title()}' for n,p in groups]);axes[0].set_ylabel('Completion or censored observation time (s)');axes[0].set_title('No-fault controls: retain unsuccessful runs')
    axes[0].legend(handles=[Line2D([],[],color=colors[a],marker='o',ls='',label=a) for a in 'CD']+[Line2D([],[],marker='^',color='gray',ls='',label='Incomplete at horizon')],fontsize=8,loc='lower right');axes[0].grid(axis='y',alpha=.2)
    old=2476022072/1e6;current=summary['stored_bytes']/1e6
    axes[1].bar([0,1],[old,current],color=['#999999','#409273']);axes[1].set_xticks([0,1],['Original pilot\ntracked raw files','V2 matrix\ncompressed + figures']);axes[1].set_ylabel('Stored data (decimal MB)');axes[1].set_title('Storage snapshots; different scenarios and horizons')
    for i,v in enumerate([old,current]):axes[1].text(i,v+35,f'{v:,.1f} MB',ha='center',fontsize=12)
    axes[1].set_ylim(0,2800);fig.suptitle('V2 timing and storage — not a controlled V1/V2 performance comparison',fontsize=12)
    fig.savefig(out/'timing_and_storage.png',bbox_inches='tight');plt.close(fig)
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-dir',default='results/phase17/v2_matrix_run1');p.add_argument('--output-dir',default='results/phase17/v2_matrix_run1/review');p.add_argument('--source-commit',required=True);p.add_argument('--bundle',help='Optional downloaded review cache')
    a=p.parse_args();s=analyze(a.source_dir,a.output_dir,a.source_commit,a.bundle)
    print(json.dumps({k:s[k] for k in ['runs','successes','fault','llm','stored_bytes']},indent=2))
