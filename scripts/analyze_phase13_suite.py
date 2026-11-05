"""Audit a partial Phase 13 suite and plot observed outcomes without hiding censoring."""
import argparse
from collections import Counter,defaultdict
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agentic_uav.experiments.suite import read_trace

CONDITIONS=['nominal','moderate','severe','partitioned']
ARCHITECTURES=list('ABCD')
COLORS={'A':'#4477AA','B':'#228833','C':'#CCBB44','D':'#AA3377'}
NAMES={'A':'Centralized','B':'Independent LLM','C':'Decentralized rules','D':'Decentralized LLM'}


def optional(run,name,default):
    try:return read_trace(run,name)
    except (FileNotFoundError,KeyError):return default


def selected_summaries(root):
    """Follow the case index to the latest completed attempt, never double-count retries."""
    root=Path(root)
    selected={p.parent.parent:p for p in root.glob('**/run/summary.json')}
    for metrics in root.glob('**/metrics.json'):
        if metrics.parent==root:continue
        data=json.loads(metrics.read_text())
        if not isinstance(data,dict) or not data.get('run_dir'):continue
        name=Path(data['run_dir']).name
        if name!='run' and not (name.startswith('run_attempt_') and name[12:].isdigit()):continue
        target=metrics.parent/name/'summary.json'
        if target.exists():selected[metrics.parent]=target
        else:selected.pop(metrics.parent,None)
    return sorted(selected.values())


def audit_case(root,path):
    summary=json.loads(path.read_text());run=path.parent;folder=run.parent
    manifest=json.loads((run/'manifest.json').read_text());config=manifest['effective_configuration']
    arrivals=read_trace(run,'waypoint_arrivals.json');scenario=read_trace(run,'scenario_events.json')
    protocol=read_trace(run,'protocol_events.json');audit=read_trace(run,'guardian_audit.json')
    effects=read_trace(run,'executed_actions.json');messages=read_trace(run,'messages.json')
    histories={aid:optional(run,aid+'/decision_history.jsonl',[]) for aid in summary['decisions_by_agent']}
    replies=[r for aid in histories for r in optional(run,aid+'/responses.jsonl',[])]
    completed={e['task_id'] for e in protocol if e['event']=='work_completed'}
    arrival_keys={(a['task_id'],a['index']) for a in arrivals}
    mission=manifest['shared_inputs']['mission'];routes={t['task_id']:t['waypoints'] for t in mission['tasks']}
    selected={e['selected_action']['command_id'] for e in audit if e.get('selected_action') and e.get('mission_effect',{}).get('executed')}
    actual_llm={}
    for aid,events in histories.items():
        accepted={e['request_id'] for e in events if e['event']=='policy_decision_applied' and e.get('source')=='llm' and e.get('flight_phase')=='AIRBORNE' and e['decision']['selected_tool'] in ('start_search','go_to_waypoint','act_as_relay','return_home')}
        actual_llm[aid]=len({e['request_id'] for e in events if e['event']=='policy_progress_observed' and e.get('source')=='llm' and e.get('request_id') in accepted})
    checks=dict(completed_ids_match=completed==set(summary['completed_task_ids']),
        completed_tasks_have_arrival_evidence=all((tid,i) in arrival_keys for tid in completed for i in range(len(routes[tid]))),
        executed_actions_have_guarded_effects=all(e['command_id'] in selected for e in effects),
        productive_llm_counts_match=actual_llm==summary['llm_productive_decisions_by_agent'],
        no_expired_delivery=all(m['actual_delivery_time']<m['expires_at'] for m in messages if m['status']=='delivered'))
    injection=any(e['event']=='actor_silenced' for e in scenario)
    counts=Counter(m['status'] for m in messages);resolved=sum(counts[k] for k in ('delivered','dropped','expired'))
    latency=[r['latency_s'] for r in replies if 'latency_s' in r and not r.get('error_type')]
    reasons=Counter(r for e in audit for r in set(e['reasons']))
    policy_errors=Counter(e.get('reason_code') for events in histories.values() for e in events if e['event']=='policy_error')
    claimed={e['task_id'] for e in protocol if e['event']=='claim_sent'};started={e['task_id'] for e in protocol if e['event']=='execution_started'}
    identity=manifest['effective_provider']
    row=dict(case_id=str(folder.relative_to(root)),architecture=summary['architecture'],condition=summary['condition'],
        group=str(folder.relative_to(root)).split('/')[0],seed=summary['seed'],provider=summary['provider'],llm_inference=summary['llm_inference'],
        bid_window_s=config['bid_window'],horizon_s=config['ticks']*config['dt'],
        mission_complete=summary['mission_complete'],mission_execution_success=summary['mission_execution_success'],
        completed_tasks=len(completed),total_tasks=len(routes),raw_arrivals=len(arrivals),unique_waypoints=len(arrival_keys),
        completion_time_s=summary['time_s'] if summary['mission_execution_success'] else None,observation_end_s=summary['time_s'],
        failure_requested=config['scenario']['fail_agent'] is not None,failure_injected=injection,
        failure_case_evaluable=injection if config['scenario']['fail_agent'] else None,
        duplicates=summary['duplicate_task_completions'],guarded_effects_verified=checks['executed_actions_have_guarded_effects'],
        productive_llm_decisions=sum(actual_llm.values()),policy_errors=sum(policy_errors.values()),
        fallbacks=sum(summary['fallbacks_by_agent'].values()),role_changes=summary['role_changes'],lease_expirations=summary['lease_expirations'],
        recipient_packets=len(messages),delivered=counts['delivered'],dropped=counts['dropped'],expired=counts['expired'],pending=counts['queued'],
        delivery_resolved_pct=100*counts['delivered']/resolved if resolved else None,
        inference_responses=len(replies),inference_latency_mean_s=statistics.mean(latency) if latency and summary['llm_inference'] else None,
        inference_latency_max_s=max(latency) if latency and summary['llm_inference'] else None,
        guard_evaluations=len(audit),guard_rejections=sum(e['outcome']=='REJECT_AND_REPLAN' for e in audit),
        stale_state_guard_decisions=reasons['stale_or_future_peer_belief'],
        active_command_policy_errors=policy_errors['active_command_requires_completion'],
        award_packets_dropped=sum(m['message_type']=='TASK_AWARD' and m['status']=='dropped' for m in messages),
        claimed_unstarted_tasks=len(claimed-started),shared_inputs_sha256=summary['shared_inputs_sha256'],
        model=identity.get('model'),model_digest=identity.get('digest'),audit_passed=all(checks.values()))
    details=dict(case_id=row['case_id'],checks=checks,guardian_reasons=dict(reasons),policy_errors=dict(policy_errors),
        claims=[e for e in protocol if e['event']=='claim_sent'],
        claimed_unstarted_task_ids=sorted(claimed-started),completed_task_ids=sorted(completed),histories=histories)
    return row,details,arrivals,manifest


def save_figure(fig,out,name):
    for extension in ('png','pdf'):fig.savefig(out/(name+'.'+extension),dpi=180,bbox_inches='tight')


def plot_results(rows,details,arrivals,out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    import numpy as np
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.titlesize':12})
    baseline={(r['condition'],r['architecture']):r for r in rows if r['group']=='baselines'}
    def matrix(ax,group,failure=False):
        lookup={(r['condition'],r['architecture']):r for r in rows if r['group']==group}
        values=np.full((4,4),np.nan)
        for i,c in enumerate(CONDITIONS):
            for j,a in enumerate(ARCHITECTURES):
                r=lookup.get((c,a))
                if r and (not failure or r['failure_injected']):values[i,j]=r['completed_tasks']
        cm=plt.get_cmap('YlGnBu').copy();cm.set_bad('#dddddd')
        ax.imshow(values,cmap=cm,vmin=0,vmax=4,aspect='auto')
        for i,c in enumerate(CONDITIONS):
            for j,a in enumerate(ARCHITECTURES):
                r=lookup.get((c,a));label='missing' if not r else 'not\ninjected' if failure and not r['failure_injected'] else f"{r['completed_tasks']}/4"
                ax.text(j,i,label,ha='center',va='center',color='white' if np.isfinite(values[i,j]) and values[i,j]>=3 else 'black',fontsize=12)
        ax.set_xticks(range(4),[a+'\n'+NAMES[a] for a in ARCHITECTURES],fontsize=9)
        ax.set_yticks(range(4),[c.capitalize() for c in CONDITIONS])
    fig,axes=plt.subplots(1,2,figsize=(13,4.5),gridspec_kw={'width_ratios':[1,1.1]})
    matrix(axes[0],'baselines');axes[0].set_title('No-failure baseline: tasks completed')
    for j,a in enumerate(ARCHITECTURES):
        for i,c in enumerate(CONDITIONS):
            r=baseline.get((c,a))
            if not r:continue
            x=i+(j-1.5)*.16
            axes[1].scatter(x,r['observation_end_s'],color=COLORS[a],marker='o' if r['mission_execution_success'] else '^',s=65)
            if r['mission_execution_success']:
                axes[1].annotate(f"{r['observation_end_s']:.1f}",(x,r['observation_end_s']),xytext=(0,7+9*(j%2)),textcoords='offset points',ha='center',fontsize=8)
    horizon=max(r['horizon_s'] for r in baseline.values())
    axes[1].set_xticks(range(4),[c.capitalize() for c in CONDITIONS]);axes[1].set_ylabel('Mission / observation time (s)');axes[1].set_ylim(0,horizon*1.12)
    axes[1].axhline(horizon,color='gray',ls=':',lw=1);axes[1].grid(axis='y',alpha=.2)
    axes[1].set_title('Circles: completed; triangles: incomplete at horizon')
    axes[1].legend(handles=[Patch(color=COLORS[a],label=a) for a in ARCHITECTURES],ncol=4,loc='upper left')
    fig.suptitle('Phase 13 pinned pilot — one run per condition, seed 42',fontsize=14)
    bid=next((r['bid_window_s'] for r in baseline.values() if r['architecture']=='D'),None)
    fig.text(.5,-.02,f'A/C are deterministic; B/D use the pinned LLM. D includes {bid:g} s auction and claim-settling waits.' if bid else 'Actual policies and timing are recorded in the per-case manifests.',ha='center',fontsize=9)
    fig.tight_layout();save_figure(fig,out,'baseline_performance');plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(13,4.7),gridspec_kw={'width_ratios':[1.15,1]})
    matrix(axes[0],'drone1_failure',True);axes[0].set_title('Drone1 failure trials: observed task completion')
    def find(part):return next((r for r in rows if part in r['case_id']),None)
    role_control=find('relay_failure/nominal/D/control/')
    comparisons=[('Memory',baseline.get(('nominal','D')),find('/without_memory/')),
        ('Leases',find('drone1_failure/moderate/D/control/'),find('/without_task_leases/')),
        ('Roles',role_control,find('/without_dynamic_roles/')),
        ('Network',baseline.get(('severe','D')),find('/perfect_communication/')),
        ('Policy',baseline.get(('nominal','D')),find('ablations/nominal/D/fallback_policy/'))]
    for i,(label,control,ablation) in enumerate(comparisons):
        for j,r in enumerate((control,ablation)):
            if not r:continue
            x=i+(j-.5)*.36
            axes[1].bar(x,r['completed_tasks'],color=COLORS['D'] if j==0 else '#b9a4b2',width=.34)
            axes[1].text(x,r['completed_tasks']+.08,f"{r['completed_tasks']}/4",ha='center',va='bottom',fontsize=9)
    axes[1].set_xticks(range(5),[x[0] for x in comparisons]);axes[1].set_ylim(0,5.2);axes[1].set_yticks(range(5));axes[1].set_ylabel('Tasks completed');axes[1].grid(axis='y',alpha=.2)
    axes[1].legend(handles=[Patch(color=COLORS['D'],label='Control'),Patch(color='#b9a4b2',label='Ablation')],ncol=2,loc='upper right')
    axes[1].set_title('Paired D ablations; timings and contexts in report')
    fig.suptitle('Failure and ablation outcomes — seed 42 pilot, n=1',fontsize=14)
    fig.text(.5,-.03,'Gray cell: mission ended before injection. Control contexts differ across ablations; compare within pairs only.',ha='center',fontsize=9)
    fig.tight_layout();save_figure(fig,out,'failure_and_ablations');plt.close(fig)

    fig,axes=plt.subplots(2,2,figsize=(12,7),sharex=True,sharey=True)
    for ax,a in zip(axes.flat,ARCHITECTURES):
        row=baseline.get(('nominal',a))
        if not row:ax.text(.5,.5,'Not uploaded',transform=ax.transAxes,ha='center');continue
        points=arrivals[row['case_id']]
        for i,aid in enumerate(['Drone1','Drone2','Drone3','Drone4']):
            pp=sorted([p for p in points if p['agent_id']==aid],key=lambda p:p['time_s'])
            if pp:
                ax.plot([p['time_s'] for p in pp],[i]*len(pp),color=COLORS[a],alpha=.6,lw=2)
                for p in pp:ax.scatter(p['time_s'],i,color=COLORS[a],marker='o' if p['index']==0 else 's',s=45)
                ax.text(pp[-1]['time_s']+2,i,f"{pp[-1]['time_s']:.1f} s",va='center',fontsize=9)
        ax.set_title(a+' — '+NAMES[a]);ax.set_yticks(range(4),['Drone1','Drone2','Drone3','Drone4']);ax.set_xlim(0,186);ax.set_ylim(-.5,3.5);ax.grid(axis='x',alpha=.2)
    axes[1,0].set_xlabel('Elapsed mission time (s)');axes[1,1].set_xlabel('Elapsed mission time (s)')
    fig.suptitle('Nominal recorded waypoint arrivals — circles WP1, squares WP2',fontsize=14)
    fig.text(.5,.01,'Arrival intervals are not continuous flight trajectories. Long C/D delays include configured protocol timers.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.03,1,1));save_figure(fig,out,'nominal_waypoint_arrivals');plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(12,4.5))
    for j,a in enumerate(ARCHITECTURES):
        x=np.arange(4)+(j-1.5)*.18
        vals=[baseline[c,a]['delivery_resolved_pct'] if (c,a) in baseline else np.nan for c in CONDITIONS]
        axes[0].bar(x,vals,width=.17,color=COLORS[a],label=a)
        vals=[100*baseline[c,a]['guard_rejections']/max(1,baseline[c,a]['guard_evaluations']) if (c,a) in baseline else np.nan for c in CONDITIONS]
        axes[1].bar(x,vals,width=.17,color=COLORS[a],label=a)
    for ax in axes:ax.set_xticks(range(4),[c.capitalize() for c in CONDITIONS]);ax.grid(axis='y',alpha=.2)
    axes[0].set_ylim(0,105);axes[0].set_ylabel('Delivered / resolved recipient packets (%)');axes[0].set_title('Observed application-message delivery');axes[0].legend(ncol=4)
    axes[1].set_ylim(0,105);axes[1].set_ylabel('REJECT_AND_REPLAN / guard evaluations (%)');axes[1].set_title('Guard outcomes include HOLD / fallback attempts')
    fig.suptitle('Communication and runtime-assurance diagnostics — baseline runs',fontsize=14)
    fig.text(.5,-.02,'Pending packets excluded from resolved delivery. Decision rates and traffic differ; these fractions are not RF quality or an LLM safety ranking.',ha='center',fontsize=9)
    fig.tight_layout();save_figure(fig,out,'communication_and_guard');plt.close(fig)

    d=baseline.get(('nominal','D'))
    if d:
        fig,ax=plt.subplots(figsize=(11,4));events=details[d['case_id']]['claims']
        for i,aid in enumerate(['Drone1','Drone2','Drone3','Drone4']):
            claims=[e['time_s'] for e in events if e['agent_id']==aid]
            auth=[e['time_s'] for e in details[d['case_id']]['histories'][aid] if e['event']=='search_authorized']
            points=[p['time_s'] for p in arrivals[d['case_id']] if p['agent_id']==aid]
            if not claims or not auth or not points:continue
            claim=min(claims);start=min(auth);end=max(points)
            ax.barh(i,claim,color='#cccccc',label='Before claim' if i==0 else None)
            ax.barh(i,start-claim,left=claim,color='#88CCEE',label='Claim dwell + inference/admission' if i==0 else None)
            ax.barh(i,end-start,left=start,color=COLORS['D'],label='Authorized route to last arrival' if i==0 else None)
            ax.text(end+1,i,f'{end:.1f} s',va='center')
        ax.set_yticks(range(4),['Drone1','Drone2','Drone3','Drone4']);ax.set_xlim(0,185)
        ax.set_xlabel('Elapsed mission time (s)');ax.set_title('Nominal D: recorded waiting, authorization and route phases')
        ax.legend(ncol=3,loc='lower right',bbox_to_anchor=(1,1.05),fontsize=9);ax.grid(axis='x',alpha=.2)
        fig.tight_layout();save_figure(fig,out,'nominal_d_timing');plt.close(fig)

    role_rows=[find('relay_failure/nominal/C/control/'),role_control,find('/without_dynamic_roles/'),find('relay_failure/nominal/D/fallback_policy/')]
    fig,ax=plt.subplots(figsize=(10,4))
    for i,r in enumerate(role_rows):
        if not r:continue
        ax.bar(i,r['role_changes'],color=COLORS['C'] if i==0 else COLORS['D'] if i==1 else '#b9a4b2')
        ax.text(i,r['role_changes']+.05,str(r['role_changes']),ha='center')
    ax.set_xticks(range(4),['C rules','D LLM','D roles disabled','D rule replacement'])
    ax.set_yticks([0,1]);ax.set_ylim(0,1.5);ax.set_ylabel('Observed role changes')
    ax.set_title('Relay-failure scenario: role changes are not mission recovery')
    fig.text(.5,.01,'All four runs complete 0/4 tasks. No restored RF reachability is measured.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.04,1,1));save_figure(fig,out,'role_recovery');plt.close(fig)


def analyze(root,out,source_commit=None):
    root=Path(root);out=Path(out)
    if out.exists() and any(out.iterdir()):raise ValueError('Use an empty analysis output directory')
    out.mkdir(parents=True,exist_ok=True)
    plan=json.loads((root/'suite_manifest.json').read_text())
    if plan.get('profile')!='pinned':raise ValueError('Analyze pinned results separately from offline replay validation')
    rows=[];details={};arrivals={};manifests={};run_paths={}
    for path in selected_summaries(root):
        row,detail,points,manifest=audit_case(root,path)
        rows.append(row);details[row['case_id']]=detail;arrivals[row['case_id']]=points;manifests[row['case_id']]=manifest
        run_paths[row['case_id']]=path.parent
    if not rows:raise ValueError('No completed run summaries found')
    found={r['case_id'] for r in rows};missing=[c['case_id'] for c in plan['cases'] if c['case_id'] not in found]
    groups=defaultdict(list)
    for r in rows:
        if r['group'] in ('baselines','drone1_failure','relay_failure'):groups[r['group'],r['condition'],r['seed']].append(r)
    matches=[dict(group=list(k),matched=len({r['shared_inputs_sha256'] for r in values})==1,cases=len(values)) for k,values in groups.items()]
    identities={(r['model'],r['model_digest']) for r in rows if r['llm_inference']}
    summary=dict(source_commit=source_commit,planned_cases=len(plan['cases']),uploaded_cases=len(rows),missing_cases=missing,
        successful_missions=sum(r['mission_execution_success'] for r in rows),actual_llm_runs=sum(r['llm_inference'] for r in rows),
        injected_failure_runs=sum(r['failure_injected'] for r in rows),successful_injected_failure_runs=sum(r['failure_injected'] and r['mission_execution_success'] for r in rows),
        failure_requested_but_not_observed=[r['case_id'] for r in rows if r['failure_requested'] and not r['failure_injected']],
        audit_failures=[r['case_id'] for r in rows if not r['audit_passed']],matched_input_checks=matches,
        verified_model_identities=[dict(model=m,digest=d) for m,d in sorted(identities)],
        analysis_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        selected_attempts={k:v.name for k,v in run_paths.items()},
        input_archives_sha256={k:hashlib.sha256((v/'traces.zip').read_bytes()).hexdigest() for k,v in run_paths.items() if (v/'traces.zip').exists()},
        limitations=['One seed / one run per case; no confidence intervals or general superiority claims',
            'Upload coverage is reported explicitly; absent cases are never counted as failed experiments',
            'Mock flight; guarded dispatch is not proof of physical collision avoidance or live safety',
            'Unsuccessful completion times are censored; no synthetic successful 300-second values'])
    with (out/'case_metrics.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)
    (out/'analysis_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    # Save compact independent verification, without duplicating archived raw histories.
    compact={k:{a:b for a,b in v.items() if a!='histories'} for k,v in details.items()}
    (out/'audit_checks.json').write_text(json.dumps(compact,indent=2)+'\n')
    baseline={(r['condition'],r['architecture']):r for r in rows if r['group']=='baselines'}
    lines=['# Phase 13 initial pinned-suite analysis',f'Source commit: `{source_commit}`. Scope: `{root}` only.',
        f"Uploaded {len(rows)} of {len(plan['cases'])} planned cases; {summary['actual_llm_runs']} use actual Ollama. All are mock-flight experiments.",
        '', '## No-failure baseline', '', '| Condition | A | B | C | D |','|---|---|---|---|---|']
    for condition in CONDITIONS:
        vals=[]
        for a in ARCHITECTURES:
            r=baseline.get((condition,a))
            vals.append('not uploaded' if r is None else f"{r['completion_time_s']:.1f} s; 4/4" if r['mission_execution_success'] else f"incomplete; {r['completed_tasks']}/4 at {r['observation_end_s']:.1f} s")
        lines.append('| '+condition+' | '+' | '.join(vals)+' |')
    table_end=len(lines)
    lines+=['','A is the fastest nominal baseline. B completes all four no-failure conditions in this pilot. C/D both complete only one task under moderate degradation and none under severe degradation. These data do not demonstrate an agentic decentralized performance advantage.',
        '','C/D retain 30-second auction and claim-settling waits. D nominal claims occur near 30, 60, 90 and 120 seconds; its searches start near 69, 100, 130 and 160 seconds. Thus the A/D timing gap combines protocol waiting, model latency and architectural differences. It is not a standalone measure of LLM reasoning quality.',
        'D remains a hybrid: deterministic contract-net ownership and deadline-protected bids support allocation. Productive LLM movement decisions establish policy execution, not by themselves LLM-driven negotiation or a benefit over the deterministic protocol.',
        '','## What the traces establish',
        '- Moderate D: the first TASK_AWARD from Drone1 to Drone4 is dropped near 30 s. Drone1 prompts continue to show Sector A owned but not executable; it expires near 210 s. Reliable award/acceptance retransmission is a debugging priority. More model reasoning alone cannot repair an undelivered ownership transition.',
        '- Moderate C additionally records many active_command_requires_completion errors. This is a rule-policy/executor scheduling issue; do not generalize it into a claim that decentralization itself is inferior.',
        '- D severe records claims but no execution_started events. Stale peer-state and communication uncertainty checks also reject actions. There is no evidence that simply increasing speed would resolve this stall.',
        '- Partitioning is scheduled at 5–12 s. C/D nominal searches begin much later. Their nearly unchanged partitioned completion times do not demonstrate resilience during active search.',
        '','## Failure and role scenarios',
        f"Observed injections: {summary['injected_failure_runs']}; completed missions after an observed injection: {summary['successful_injected_failure_runs']}.",
        'The nominal A failure-labelled run ends near 7.9 s, before its planned 8 s disruption; exclude it from failure-recovery success claims. Following actual failures, stale peer-state checks block motion. A surviving-agent claim near 188 s in D is evidence of reassignment, not mission recovery.',
        'The relay-failure C run changes one role but completes no task. D leaves Drone4 as RESERVE and also completes no task. These trials do not demonstrate successful relay replacement by the LLM or restored RF connectivity.',
        '','## Ablation results',
        '- Memory: nominal D completes in approximately 168.1 s with memory and 168.0 s without it, both 4/4. This is about one simulation tick apart, with one productive search authorization per drone. A single simple-route pair cannot establish a memory benefit or equivalence.',
        '- Leases: moderate Drone1-failure control and no-lease variant both complete 0/4. Their timing does not exercise a failed owner losing an established assignment: Drone1 is silenced before the first 30 s auction closes. This is insufficient evidence of the value of task leases.',
        '- Perfect communication: the severe-network D control completes 0/4, while the perfect-communication override completes 4/4 in 168.5 s. This supports a communication/protocol bottleneck in this pilot. The override changes latency, loss and capacity together, so it does not isolate packet loss alone.',
        '- LLM replacement: nominal deterministic replacement completes 4/4 in 158.3 s versus 168.1 s for the LLM control. No nominal completion benefit from the LLM is demonstrated on these simple fixed routes.',
        '- Roles: the LLM role-enabled control and role-disabled retry both complete 0/4 with zero role changes. The rule-policy replacement changes one role but still completes 0/4. A role transition alone does not establish mission recovery.',
        '- Upload coverage: all planned cases are present.' if not missing else '- Not yet uploaded:']
    lines += ['  - `'+case+'`' for case in missing]
    lines+=['','## Verification and interpretation',
        f"Independent audit failures: {len(summary['audit_failures'])}. Completed task IDs were checked against work_completed events and waypoint indices; actual effects were checked against executed guardian selections; productive LLM counts were recomputed from accepted request IDs and observed effects.",
        'All uploaded summaries report no runtime error and zero duplicate task completions. This does not certify physical flight safety or prove absence of between-sample violations. Decision and fallback rates differ substantially between deterministic and model policies, so raw fallback counts are not directly comparable reliability scores.',
        'Standalone A_nominal_run1/B_nominal_run1/C_nominal_run1/D_nominal_run1 folders and offline wiring data are excluded from this pinned-suite analysis.',
        'The role-disabled case uses run_attempt_002; its interrupted original is not counted as another trial.',
        '','## Next experimental steps',
        '1. Preserve these results as a pilot baseline and collect repeated matched trials.',
        '2. Add targeted failure timing after verified assignment but before completion; confirm injections and lease expiry in the actual logs.',
        '3. Test communication outages during active search, not only during auction waiting.',
        '4. Fix and separately evaluate reliable assignment acknowledgment and active-command scheduling. Keep safety constraints unchanged.',
        '5. Run multiple matched seeds; plot success proportions and successful-time distributions separately from censored outcomes.',
        '','## Figures',
        '- `baseline_performance.png/pdf`: task outcomes and completed versus censored times.',
        '- `failure_and_ablations.png/pdf`: evaluated injections and matched ablation pairs.',
        '- `nominal_waypoint_arrivals.png/pdf`: recorded arrival timelines, not reconstructed trajectories.',
        '- `communication_and_guard.png/pdf`: recipient delivery and recorded guard outcomes.',
        '- `nominal_d_timing.png/pdf`: claim waiting, authorization delay and observed route interval.',
        '- `role_recovery.png/pdf`: role transitions and their limited mission effect.',
        '','No smoothing, invented missing results, confidence intervals from one trial, or substitution of replay for LLM evidence is used.']
    if source_commit!='a7d40605d52438358df9d502c7967e1f17772d46':
        lines=lines[:table_end]+['','## Verification',f"Audit failures: {len(summary['audit_failures'])}. Missing cases: {len(missing)}.",
            'This is an automatically generated outcome table. Snapshot-specific causal interpretation requires review of the current traces.',
            'Incomplete times are censored. No statistical significance or general architectural superiority is inferred from one seed.']
    lines+=['','## Plot previews',
        '![Baseline performance](baseline_performance.png)',
        '![Failure and ablation outcomes](failure_and_ablations.png)',
        '![Nominal waypoint arrivals](nominal_waypoint_arrivals.png)',
        '![Nominal D timing](nominal_d_timing.png)',
        '![Role recovery](role_recovery.png)',
        '![Communication and guardian diagnostics](communication_and_guard.png)']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    plot_results(rows,details,arrivals,out)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-dir',default='results/phase13/automated_pinned_run1')
    p.add_argument('--output-dir',default='results/phase13/pinned_initial_analysis')
    p.add_argument('--source-commit')
    a=p.parse_args();print(json.dumps(analyze(a.input_dir,a.output_dir,a.source_commit),indent=2))
