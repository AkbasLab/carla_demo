"""Secondary diagnostic counts, separate from the registered primary metrics.

Counts describe logged local events, not unique physical incidents or consensus.
Existing runs are analysed retrospectively without modifying their evidence.
"""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from .metrics import Evidence, evaluate_run, percentile, acceptances


def analyse_run(folder, evaluation=None, *, mode='retrospective'):
    folder=Path(folder);evidence=Evidence(folder/'run')
    summary=evidence.read('summary.json') or {}
    protocol=evidence.read('protocol_events.json')
    controller=evidence.read('controller_events.json')
    arrivals=evidence.read('waypoint_arrivals.json')
    audit=evidence.read('guardian_audit.json')
    detail=evidence.read('manifest.json')
    mission=(detail or {}).get('shared_inputs',{}).get('mission')
    required=({(t['task_id'],i) for t in mission.get('tasks',[]) for i,_ in enumerate(t['waypoints'])}
              if mission is not None else None)
    outer=Evidence(folder);envelopes=outer.read('events.jsonl')
    assignments=acceptances(envelopes or [])
    agents=list(summary.get('decisions_by_agent',{}))
    history=[];responses=[];missing=[]
    for aid in agents:
        for name,target in [('decision_history.jsonl',history),('responses.jsonl',responses)]:
            records=evidence.read(f'{aid}/{name}')
            if records is None:missing.append(f'{aid}/{name}')
            else:target.extend(records)
    for name,value in [('summary.json',summary),('protocol_events.json',protocol),
                       ('waypoint_arrivals.json',arrivals),('guardian_audit.json',audit),('manifest.json',detail)]:
        if value is None or (name=='summary.json' and not value):missing.append(name)
    histories_complete=bool(agents) and not any(p.endswith('decision_history.jsonl') for p in missing)
    responses_complete=bool(agents) and not any(p.endswith('responses.jsonl') for p in missing)
    events=Counter(r['event'] for r in history)
    policy_errors=Counter(r.get('reason_code','unspecified') for r in history if r['event']=='policy_error')
    protocol_counts=Counter(r['event'] for r in protocol or [])
    reasons=Counter(reason for r in audit or [] for reason in r.get('reasons',[]))
    versions={};releases=Counter();central_releases=Counter();claims=Counter()
    for r in list(protocol or [])+list(controller or []):
        tid=r.get('task_id')
        if tid is None:continue
        if r['event'] in ('claim_sent','central_assignment'):
            versions.setdefault(tid,set()).add(r['version']);claims[tid]+=1
        if r['event']=='task_released':releases[tid]+=1
        if r['event']=='central_task_released':central_releases[tid]+=1
    unique={(r['task_id'],r['index']) for r in arrivals or []}
    if required is not None:unique &= required
    tasks=set(versions)|set(releases)|set(central_releases)|{r[0] for r in unique}
    tasks|={tid for tid,_ in required or []}
    recovery=[]
    first_arrivals=[];seen=set()
    for arrival in sorted(arrivals or [],key=lambda r:r['time_s']):
        key=(arrival['task_id'],arrival['index'])
        if required is None or key not in required:continue
        if key not in seen:first_arrivals.append(arrival);seen.add(key)
    evaluation=evaluation if evaluation is not None else evaluate_run(folder)
    for fault in evaluation['primary']['recovery']:
        if fault['kind']!='actor_failure':continue
        for task in fault['tasks']:
            accepted=task['recovery_time_s']
            accepted_s=None if accepted is None else fault['onset_s']+accepted
            agent=task.get('replacement_agent')
            acceptance=next((a for a in assignments if a['task_id']==task['task_id'] and
                a['agent_id']==agent and accepted_s is not None and abs(a['time_s']-accepted_s)<1e-6),None)
            version=acceptance['version'] if acceptance else None
            boundaries=[a['time_s'] for a in assignments if acceptance and a['task_id']==task['task_id'] and
                a['time_s']>=accepted_s and a['order']>acceptance['order'] and
                (a['agent_id'],a['version'])!=(agent,version)]
            for event in envelopes or []:
                payload=event.get('data',{});payload=payload.get('details',payload)
                if (accepted_s is not None and event['event_type']=='TASK_RELEASED' and
                        event.get('agent_id')==agent and payload.get('task_id')==task['task_id'] and
                        event['simulation_time_s']>=accepted_s):boundaries.append(event['simulation_time_s'])
            until=min(boundaries,default=math.inf)
            # The primary evaluator's global resumption may belong to another
            # agent/epoch. Never subtract mismatched events to invent an interval.
            arrival=next((r for r in first_arrivals if accepted_s is not None and
                acceptance is not None and version is not None and r.get('version')==version and
                r['task_id']==task['task_id'] and r.get('agent_id')==agent and accepted_s<=r['time_s']<until),None)
            available=arrivals is not None and required is not None and (accepted_s is None or version is not None)
            recovery.append(dict(task_id=task['task_id'],fault_s=fault['onset_s'],
                replacement_agent=agent,replacement_accepted_s=accepted_s,
                replacement_version=version,acceptance_episode_end_s=until if math.isfinite(until) else None,
                observed_until_s=task.get('observed_until_s',summary.get('time_s')),
                first_productive_arrival_s=arrival['time_s'] if arrival else None,
                acceptance_to_arrival_s=arrival['time_s']-accepted_s if arrival else None,
                censored=(arrival is None) if available else None,
                unavailable_reason=None if available else 'required_geometry_arrivals_or_acceptance_epoch_missing',
                definition='Registered replacement acceptance to that agent/epoch\'s first globally unique required arrival, before release or superseding acceptance'))
    latency=[r['latency_s'] for r in responses if type(r.get('latency_s')) in (int,float)
             and math.isfinite(r['latency_s']) and r['latency_s']>=0]
    result=dict(schema_version=1,definition_id='phase17_secondary_mechanisms_v1',
        evaluator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),collection_mode=mode,
        experiment_id=folder.name,architecture=summary.get('architecture'),
        mission_complete=summary.get('mission_complete'),
        waypoint_arrivals=dict(records=len(arrivals) if arrivals is not None else None,
            unique_required_waypoints=len(unique) if arrivals is not None and required is not None else None),
        progress_and_leases=dict(
            observed_progress_reports=protocol_counts['progress_reported'] if protocol is not None else None,
            local_lease_expiration_events=protocol_counts['lease_expired'] if protocol is not None else None,
            central_lease_expiration_events=sum(r['event']=='central_lease_expired' for r in controller) if controller is not None else None,
            note='Local reports/expirations can refer to the same task epoch; they are not consensus counts'),
        task_lifecycle_complete=protocol is not None and (summary.get('architecture')!='A' or controller is not None),
        task_lifecycle={tid:dict(claim_events=claims[tid],claimed_versions=sorted(versions.get(tid,set())),
            release_events=releases[tid],central_release_observations=central_releases[tid],
            unique_waypoint_arrivals=sum(t==tid for t,_ in unique) if arrivals is not None and required is not None else None) for tid in sorted(tasks)},
        recovery=recovery,
        policy=dict(errors=dict(policy_errors) if histories_complete else None,
            error_events=sum(policy_errors.values()) if histories_complete else None,
            fallback_activations=events['deterministic_fallback'] if histories_complete else None,
            peer_health_transitions=events['peer_health_changed'] if histories_complete else None,
            approach_selections=events['alternative_approach_selected'] if histories_complete else None,
            approach_invalidations=events['alternative_approach_invalidated'] if histories_complete else None),
        inference=dict(llm_inference=summary.get('llm_inference'),
            calls=evaluation['diagnostic'].get('llm_calls'),
            response_records=len(responses) if responses_complete else None,
            failed_response_records=sum(bool(r.get('error')) for r in responses) if responses_complete else None,
            latency_s=dict(mean=sum(latency)/len(latency),p95=percentile(latency,.95),maximum=max(latency),
                scope='all_reported_responses_including_failures')
                if latency and responses_complete and summary.get('llm_inference') else None),
        guardian=dict(evaluations=len(audit) if audit is not None else None,
            rejected_evaluations=sum(r['outcome']=='REJECT_AND_REPLAN' for r in audit) if audit is not None else None,
            reason_occurrences=dict(reasons) if audit is not None else None,
            registered_safety_metrics=evaluation['primary']['safety']),
        sources=dict(result_directory=str(folder),artifacts=['run/summary.json','run/waypoint_arrivals.json',
            'run/protocol_events.json','run/controller_events.json','run/guardian_audit.json',
            'run/<agent>/decision_history.jsonl','run/<agent>/responses.jsonl','run/manifest.json','events.jsonl'],
            measurement_sources=dict(waypoint_arrivals=['run/waypoint_arrivals.json','run/manifest.json'],
                progress_and_leases=['run/protocol_events.json','run/controller_events.json'],
                recovery=['events.jsonl','run/waypoint_arrivals.json','run/manifest.json'],
                policy=['run/<agent>/decision_history.jsonl'],inference=['run/<agent>/responses.jsonl','events.jsonl'],
                guardian=['run/guardian_audit.json']),
            packed_evidence_supported=True),
        missing_artifacts=missing+(['events.jsonl'] if envelopes is None else [])+
            (['controller_events.json'] if summary.get('architecture')=='A' and controller is None else []),
        evidence_issues=evidence.issues+outer.issues,
        limitations=['Secondary diagnostics do not replace or retroactively register primary metrics',
            'Zero event count does not establish support for instrumentation in older source versions',
            'Guardian reason occurrences are not unique physical incidents or collisions'])
    return result


def report(records):
    lines=['# Phase 17 mechanism diagnostics','',
        'Secondary diagnostic measurements; original evidence and primary metrics are unchanged. Missing measurements remain null.',
        '', '| Case | Unique waypoints | Progress reports | Local lease expirations | Claims | Releases | Health transitions | Policy errors | Policy fallbacks |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    show=lambda v:'unavailable' if v is None else str(v)
    for r in records:
        lifecycle=r['task_lifecycle'];p=r['policy'];leases=r['progress_and_leases']
        lines.append('| '+' | '.join(map(show,[r['experiment_id'],r['waypoint_arrivals']['unique_required_waypoints'],
            leases['observed_progress_reports'],leases['local_lease_expiration_events'],
            sum(t['claim_events'] for t in lifecycle.values()) if r['task_lifecycle_complete'] else None,
            sum(t['release_events'] for t in lifecycle.values()) if r['task_lifecycle_complete'] else None,
            p['peer_health_transitions'],p['error_events'],p['fallback_activations']]))+' |')
    lines+=['','Release counts are local events. Controller observations of the same releases are recorded separately in JSON, not double-counted.',
        'See each JSON file for per-task versions, censored acceptance-to-arrival intervals, inference latency, guardian counts and source artifacts.']
    lines+=['','## Guardian and inference diagnostics','',
        '| Case | Guardian evaluations | Rejected evaluations | Corrective interventions | LLM calls | Mean LLM latency (s) | P95 LLM latency (s) | Failed response records |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in records:
        g=r['guardian'];i=r['inference'];lat=i['latency_s'] or {}
        lines.append('| '+' | '.join(map(show,[r['experiment_id'],g['evaluations'],g['rejected_evaluations'],
            g['registered_safety_metrics'].get('corrective_guardian_interventions'),i['calls'],
            None if lat.get('mean') is None else round(lat['mean'],3),
            None if lat.get('p95') is None else round(lat['p95'],3),i['failed_response_records']]))+' |')
    lines+=['','## Replacement acceptance to productive arrival','',
        '| Case | Task | Acceptance timestamp (s) | First productive arrival (s) | Interval (s) | Arrival censored |',
        '|---|---|---:|---:|---:|---|']
    for r in records:
        for t in r['recovery']:
            lines.append('| '+' | '.join(map(show,[r['experiment_id'],t['task_id'],t['replacement_accepted_s'],
                t['first_productive_arrival_s'],t['acceptance_to_arrival_s'],t['censored']]))+' |')
    lines+=['','A missing arrival is censored, not a zero-second recovery. No rows means no affected failure task was identified.',
        '', '## Task lifecycle','',
        '| Case | Task | Claims | Claimed versions | Releases | Unique waypoint arrivals |',
        '|---|---|---:|---|---:|---:|']
    for r in records:
        for tid,t in r['task_lifecycle'].items():
            complete=r['task_lifecycle_complete']
            lines.append('| '+' | '.join(map(show,[r['experiment_id'],tid,t['claim_events'] if complete else None,
                ', '.join(map(str,t['claimed_versions'])) if complete else None,
                t['release_events'] if complete else None,t['unique_waypoint_arrivals']]))+' |')
    lines+=['','## Evidence sources','']
    lines+=['| Measurement | Logical source artifacts (also read from ZIP archives) |',
        '|---|---|',
        '| Required waypoint work | `run/waypoint_arrivals.json`, `run/manifest.json` |',
        '| Progress, claims, releases and leases | `run/protocol_events.json`, `run/controller_events.json` |',
        '| Acceptance-to-arrival interval | `events.jsonl`, `run/waypoint_arrivals.json`, `run/manifest.json` |',
        '| Health, approach changes, policy errors/fallbacks | `run/<agent>/decision_history.jsonl` |',
        '| Inference | `run/<agent>/responses.jsonl`, registered call counts from `events.jsonl` |',
        '| Guardian | `run/guardian_audit.json` and registered primary safety metrics |','',
        'LLM latency summarizes reported response records, including failures with a recorded latency; it is unavailable for replay/deterministic policies.','']
    for r in records:
        lines.append(f"- `{r['experiment_id']}`: `{r['sources']['result_directory']}`; missing artifacts: {r['missing_artifacts']}; evidence issues: {r['evidence_issues']}.")
    return '\n'.join(lines)+'\n'


def analyse_batch(batch_dir,output_dir):
    root=Path(batch_dir).resolve();out=Path(output_dir).resolve()
    if out==root or root in out.parents:
        raise ValueError('Retrospective output must be outside the original evidence directory')
    manifest=json.loads((root/'v2_manifest.json').read_text())
    # Separate new outputs: never replace an old manifest or registered analysis.
    out.mkdir(parents=True,exist_ok=False)
    records=[]
    for row in manifest['rows']:
        r=analyse_run(root/'runs'/row['experiment_id'])
        records.append(r);(out/f"{r['experiment_id']}.mechanisms.json").write_text(json.dumps(r,indent=2,allow_nan=False)+'\n')
    (out/'mechanisms.json').write_text(json.dumps(records,indent=2,allow_nan=False)+'\n')
    (out/'MECHANISMS.md').write_text(report(records))
    return dict(runs=len(records),output_dir=str(out),retrospective=True)
