"""Phase 15 predeclared route metrics. No fabricated sensing or successful times."""
from collections import Counter,defaultdict
from datetime import datetime,timezone
import copy
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import zipfile
from .suite import read_trace
from agentic_uav.control.oba_recovery import segment_hits_box

ROOT=Path(__file__).resolve().parents[2]
CONTRACT_PATH=ROOT/'configs/phase15/metrics.v1.json'
DEFINITION_PATH=ROOT/'docs/phase15_evaluation_metrics.md'
UNSAFE_REASONS={'altitude_bounds','geofence','restricted_zone','maximum_speed','maximum_speed_clamped',
    'battery_reserve','drone_separation','peer_reachable_region_conflict','conflicting_reserved_trajectory',
    'landing_site_not_surveyed_clear','not_over_landing_site','landing_tolerance_exceeds_site_radius',
    'ground_above_vehicle_in_NED_frame','landing_corridor_outside_flight_bounds','landing_corridor_intersects_keepout_margin'}
INVALID_OUTPUT_PREFIXES=('invalid_json','decision_fields','assessment_','invalid_tool','tool_parameters',
    'invalid_parameter','outgoing_','invalid_recipient','message_tool_mismatch','invalid_confidence',
    'response_size_or_type','nonfinite_json','duplicate_json_key')


def dump(path,value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def contract():
    value=json.loads(CONTRACT_PATH.read_text())
    fixed=dict(schema_version=1,definition_id='phase15.route_metrics.v1',mission_score_mode='strict_route_success',
        work_unit='required_task_waypoint',continuity_reference='unique_matched_nominal_run',
        separation_threshold='mission_guardian_min_separation_m',unavailable_policy='null_with_reason',
        failed_time_policy='censored_not_successful_time',recovery_acceptance='replacement_local_ownership_acceptance',
        token_policy='reported_provider_usage_only')
    if set(value)!=set(fixed)|{'role_return_window_s'} or any(value.get(k)!=v for k,v in fixed.items()):
        raise ValueError('Unsupported metric definition or score mode')
    window=value['role_return_window_s']
    if type(window) not in (int,float) or not math.isfinite(window) or window<=0:raise ValueError('Invalid role-return window')
    return value


def evaluator_hash():return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def register(root):
    """Called before the first run, never retroactively by the evaluator."""
    root=Path(root);raw=CONTRACT_PATH.read_bytes()
    target=root/'metric_contract.json'
    if target.exists():raise ValueError('Metric contract already registered')
    target.write_bytes(raw)
    (root/'metric_definitions.md').write_bytes(DEFINITION_PATH.read_bytes())
    value=dict(definition_id=contract()['definition_id'],registered_at_utc=datetime.now(timezone.utc).isoformat(),
        contract_sha256=hashlib.sha256(raw).hexdigest(),evaluator_source_sha256=evaluator_hash(),
        definitions_sha256=hashlib.sha256(DEFINITION_PATH.read_bytes()).hexdigest())
    dump(root/'metric_registration.json',value)
    return value


class Evidence:
    def __init__(self,folder):self.folder=Path(folder);self.issues=[]
    def read(self,name):
        try:
            path=self.folder/name
            if not path.exists() and not (self.folder/'traces.zip').exists():return None
            if name.endswith('.jsonl'):
                if path.exists():text=path.read_text()
                else:
                    with zipfile.ZipFile(self.folder/'traces.zip') as archive:text=archive.read(name).decode()
                value=[];lines=text.splitlines()
                for index,line in enumerate(lines):
                    if not line:continue
                    try:value.append(json.loads(line))
                    except ValueError:
                        self.issues.append(dict(artifact=name,error='invalid_jsonl_record',line=index+1))
                        if index!=len(lines)-1:raise
            else:value=read_trace(self.folder,name)
            json.dumps(value,allow_nan=False)
            return value
        except (FileNotFoundError,KeyError):return None
        except Exception as exc:
            self.issues.append(dict(artifact=name,error=type(exc).__name__));return None


def ratio(numerator,denominator):return numerator/denominator if denominator else None


def percentile(values,p):
    if not values:return None
    values=sorted(values);x=(len(values)-1)*p;lo=int(x);hi=min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(x-lo)


def work_metrics(arrivals,required_units):
    if any(not isinstance(a.get('task_id'),str) or type(a.get('index')) is not int or a['index']<0 for a in arrivals):raise ValueError('Invalid recorded waypoint unit')
    keys=[(a['task_id'],a['index']) for a in arrivals]
    productive=set(keys)&set(required_units)
    return dict(unique_productive_work=len(productive),total_work=len(keys),
        repeated_required_work=sum(k in required_units for k in keys)-len(productive),
        route_work_fraction=ratio(len(productive),len(required_units)),
        coordination_efficiency=ratio(len(productive),len(keys)))


def communication_metrics(messages,end_s,completed_tasks):
    if messages is None:return dict(available=False,reason='message_log_missing')
    ids={m['message_id'] for m in messages}
    logical=lambda mid:re.sub(r':tx:\d+$','',mid)
    sends=Counter(logical(mid) for mid in ids)
    delivered=[m for m in messages if m['status']=='delivered' and m['actual_delivery_time']<=end_s]
    repeats=Counter((logical(m['message_id']),m['recipient_id']) for m in delivered)
    begun=[m for m in messages if m.get('transmission_time',m['sent_time'])<=end_s]
    return dict(available=True,unique_message_sends=len(ids),recipient_packet_attempts=len(messages),
        attempted_bytes=sum(m['size_bytes'] for m in messages),bytes_transmitted=sum(m['size_bytes'] for m in begun),
        messages_per_completed_task=ratio(len(ids),completed_tasks),retry_message_sends=sum(n-1 for n in sends.values()),
        duplicate_transport_deliveries=sum(n-1 for n in repeats.values()),
        expired_messages=sum(m['status']=='expired' for m in messages),
        dropped_messages=sum(m['status']=='dropped' for m in messages),
        pending_messages=sum(m['status']=='queued' for m in messages),delivered_messages=len(delivered),
        not_yet_transmitted_packets=len(messages)-len(begun),
        semantic_duplicate_messages=None,semantic_duplicate_reason='no_stable_business_id_for_recreated_transactions')


def safety_metrics(flight,audit,guardian,telemetry):
    result=dict(collisions=None,collision_reason='collision_observations_not_collected',
        sampled_separation_violations=None,separation_violation_episodes=None,minimum_sampled_separation_m=None,
        restricted_zone_entries_sampled=None,restricted_zone_crossings_inferred=None,
        guardian_interventions=None,unsafe_proposal_evaluations=None,guardian_fallbacks=None,emergency_fallbacks=None)
    collisions=defaultdict(list)
    for e in telemetry:
        state=e['data']['observation']
        if type(state.get('collision')) is bool:collisions[e['agent_id']].append((e['simulation_time_s'],state['collision']))
    if collisions:
        result['collisions']=sum(sum(value and (i==0 or not samples[i-1][1]) for i,(_,value) in enumerate(samples))
            for samples in (sorted(s) for s in collisions.values()))
        result['collision_reason']=None
    if flight:
        grouped=defaultdict(dict)
        for e in flight:grouped[e['time_s']][e['agent_id']]=e['position']
        threshold=guardian.get('min_separation_m',2.)
        count=episodes=0;previous=set();distances=[]
        for _,positions in sorted(grouped.items()):
            current=set()
            for a,b in itertools.combinations(sorted(positions),2):
                distance=math.dist(positions[a],positions[b]);distances.append(distance)
                if distance<threshold:current.add((a,b))
            count+=len(current);episodes+=len(current-previous);previous=current
        result.update(sampled_separation_violations=count if distances else None,separation_violation_episodes=episodes if distances else None,
            sampled_pair_observations=len(distances),
            minimum_sampled_separation_m=min(distances) if distances else None,separation_threshold_m=threshold)
        entries=crossings=0;previous_position={};inside=set()
        for e in sorted(flight,key=lambda e:(e['time_s'],e['agent_id'])):
            aid=e['agent_id'];p=e['position']
            for i,box in enumerate(guardian.get('keepouts',[])):
                key=(aid,i);now_inside=all(box[f'{axis}_min']<=p[j]<=box[f'{axis}_max'] for j,axis in enumerate('xyz'))
                if now_inside and key not in inside:entries+=1
                if now_inside:inside.add(key)
                else:inside.discard(key)
                if aid in previous_position and segment_hits_box(previous_position[aid],p,box,0):
                    start=previous_position[aid]
                    was_inside=all(box[f'{axis}_min']<=start[j]<=box[f'{axis}_max'] for j,axis in enumerate('xyz'))
                    if not was_inside:crossings+=1
            previous_position[aid]=p
        result.update(restricted_zone_entries_sampled=entries,restricted_zone_crossings_inferred=crossings)
    if audit is not None:
        outcomes=Counter(e['outcome'] for e in audit)
        routine=sum(e['outcome']=='APPROVE_WITH_MODIFICATION' and set(e['reasons'])=={'bounded_motion_segment'} for e in audit)
        fallback=Counter(e['fallback'] for e in audit if e.get('fallback') and e.get('selected_action'))
        result.update(guardian_evaluations=len(audit),guardian_interventions=sum(e['outcome']!='APPROVE' for e in audit),
            routine_segment_modifications=routine,corrective_guardian_interventions=sum(e['outcome']!='APPROVE' for e in audit)-routine,
            intervention_rate=ratio(sum(e['outcome']!='APPROVE' for e in audit),len(audit)),outcomes=dict(outcomes),
            unsafe_proposal_evaluations=sum(bool(set(e['reasons'])&UNSAFE_REASONS) for e in audit),
            unverifiable_state_rejections=sum(any(r in ('stale_or_future_peer_belief','missing_peer_beliefs','stale_or_future_state') for r in e['reasons']) for e in audit),
            guardian_fallbacks=sum(fallback.values()),fallback_types=dict(fallback),
            emergency_fallbacks=sum(fallback[k] for k in ('LAND_AT_SAFE_LOCATION','CLIMB_OR_DESCEND_TO_SAFE_LAYER','RETURN_HOME')))
    return result


def acceptances(events):
    result=[]
    for order,e in enumerate(events):
        if e['event_type']!='TASK_ASSIGNED':continue
        d=e['data']
        if d.get('owner')==e.get('agent_id') and 'task_id' in d:
            result.append(dict(time_s=e['simulation_time_s'],agent_id=e['agent_id'],task_id=d['task_id'],
                version=d.get('version'),order=order))
    return result


def recovery_metrics(events,arrivals,completed_events,partitions,end_s):
    assignments=acceptances(events);result=[]
    unique=[];seen=set()
    for arrival in sorted(arrivals,key=lambda a:a['time_s']):
        key=(arrival['task_id'],arrival['index'])
        if key not in seen:unique.append(arrival);seen.add(key)
    for order,e in enumerate(events):
        if e['event_type']!='FAULT_INJECTED':continue
        start=e['simulation_time_s'];failed=e['agent_id'];owners={}
        for a in assignments:
            if (a['time_s'],a['order'])<(start,order):owners[a['task_id']]=a['agent_id']
        for release in events[:order]:
            if release['event_type']!='TASK_RELEASED':continue
            d=release['data'].get('details',release['data']);tid=d.get('task_id')
            # Apply only releases following the most recent acceptance.
            last=max((a['time_s'] for a in assignments if a['task_id']==tid and a['time_s']<=start),default=-1)
            if release['simulation_time_s']>=last and owners.get(tid)==release.get('agent_id'):owners[tid]=None
        done={x['task_id'] for x in completed_events if x['time_s']<=start}
        snapshot=next((s for s in reversed(events[:order]) if s['event_type']=='TASK_STATE_SNAPSHOT' and s['agent_id']==failed and s['data'].get('scope')=='fault_onset' and s['simulation_time_s']==start),None)
        tasks=([t['task_id'] for t in snapshot['data']['tasks'] if t['status']=='assigned' and t['assigned_agent']==failed and
            t['lease_expires_at'] is not None and t['lease_expires_at']>start and t['task_id'] not in done] if snapshot else
            [t for t,owner in owners.items() if owner==failed and t not in done])
        item=dict(kind='actor_failure',agent_id=failed,onset_s=start,affected_tasks=tasks,tasks=[],
            ownership_evidence='fault_onset_snapshot' if snapshot else 'assignment_event_reconstruction',
            applicability='applicable' if tasks else 'no_owned_unfinished_task_at_onset')
        for tid in tasks:
            replacement=next((a for a in assignments if a['task_id']==tid and a['agent_id']!=failed and (a['time_s'],a['order'])>(start,order)),None)
            productive=next((a for a in unique if a['task_id']==tid and a['agent_id']!=failed and a['time_s']>=start),None)
            item['tasks'].append(dict(task_id=tid,replacement_agent=replacement['agent_id'] if replacement else None,
                recovery_time_s=replacement['time_s']-start if replacement else None,
                productive_resume_time_s=productive['time_s']-start if productive else None,
                acceptance_censored=replacement is None,productive_resume_censored=productive is None,
                observed_until_s=end_s))
        result.append(item)
    motion_ids={e['data']['command_id'] for e in events if e['event_type']=='SKILL_STARTED' and e['data'].get('kind') in ('MOVE','RETURN_HOME','TAKEOFF')}
    cancellations={(e['agent_id'],e['simulation_time_s']) for e in events if e['event_type']=='SKILL_CANCELLED' and e['data']['command_id'] in motion_ids}
    for partition in partitions:
        start=partition['start_s'];stop=partition['end_s'];members={p for g in partition['groups'] for p in g}
        if start>end_s:continue
        interruptions=[e for e in events if e['event_type']=='GUARDIAN_INTERVENED' and e['agent_id'] in members and
            start<=e['simulation_time_s']<=stop and (e['agent_id'],e['simulation_time_s']) in cancellations and any(r in ('stale_or_future_peer_belief','communication_or_belief_uncertainty','runtime_timeout_or_state_violation')
            for r in e['data']['audit']['reasons'])]
        resumed=[a for a in unique if any(e['agent_id']==a['agent_id'] and a['time_s']>e['simulation_time_s'] for e in interruptions)]
        result.append(dict(kind='partition',onset_s=start,end_s=stop,recovery_time_s=None,
            acceptance_applicability='no_failed_owner_defined',interruption_observed=bool(interruptions),
            productive_resume_time_s=min(a['time_s'] for a in resumed)-start if resumed else None,
            productive_resume_censored=bool(interruptions) and not resumed,
            productive_resume_applicability='observed_interruption' if interruptions else 'no_observed_interruption'))
    return result


def additional_components(events,mission):
    result={};reasons={}
    sensors={e['data'].get('sensor') for e in events if e['event_type']=='SENSOR_INITIALIZED'}
    cell_events=[e for e in events if e['event_type']=='SEARCH_CELL_OBSERVED']
    cells=mission.get('search_cells')
    if cells and (cell_events or 'area_coverage' in sensors):
        seen=[e['data']['cell_id'] for e in events if e['event_type']=='SEARCH_CELL_OBSERVED' and e['data'].get('cell_id') in cells]
        result.update(area_coverage_fraction=len(set(seen))/len(set(cells)),redundant_cell_observations=len(seen)-len(set(seen)))
    else:result.update(area_coverage_fraction=None,redundant_cell_observations=None);reasons['area_coverage']='no_declared_cell_denominator_or_coverage_sensor'
    targets=mission.get('target_ids')
    if targets and ('target_detection' in sensors or any(e['event_type']=='TARGET_DETECTED' for e in events)):
        verified={e['data']['target_id'] for e in events if e['event_type']=='TARGET_DETECTED' and e['data'].get('verified') is True}
        result['target_detection_fraction']=len(verified&set(targets))/len(set(targets))
    else:result['target_detection_fraction']=None;reasons['target_detection']='no_declared_targets_and_verified_detector'
    if mission.get('requires_safe_return') and ('safe_return' in sensors or any(e['event_type']=='SAFE_RETURN_VERIFIED' for e in events)):
        returned={e['agent_id'] for e in events if e['event_type']=='SAFE_RETURN_VERIFIED' and e['data'].get('verified') is True}
        result['safe_return_fraction']=len(returned&set(mission['vehicles']))/len(mission['vehicles'])
    else:result['safe_return_fraction']=None;reasons['safe_return']='safe_return_not_required_or_verification_not_collected'
    result['unavailable_reasons']=reasons
    return result


def diagnostic_metrics(events,histories,responses,flight,snapshots,required_tasks,completed_tasks,end_s,c,work):
    changes=sorted([e for e in histories if e['event']=='role_changed'],key=lambda e:e['time_s'])
    oscillations=0;previous={}
    for e in changes:
        old=previous.get(e['agent_id'])
        if old and e['role']==old['previous'] and e['time_s']-old['time_s']<=contract()['role_return_window_s']:oscillations+=1
        previous[e['agent_id']]=e
    owner_changes=restarts=0;latest={}
    for a in sorted(acceptances(events),key=lambda e:(e['time_s'],e['order'])):
        old=latest.get(a['task_id'])
        if old and old['agent_id']!=a['agent_id']:owner_changes+=1
        elif old and old['version']!=a['version']:restarts+=1
        latest[a['task_id']]=a
    dead={e['agent_id'] for e in events if e['event_type']=='FAULT_INJECTED'}
    orphaned=multiple=None
    if snapshots and set(c.get('initial_assignments',{}))<=set(snapshots):
        owners=defaultdict(set)
        for aid,e in snapshots.items():
            if aid in dead:continue
            for t in e['data']['tasks']:
                if t['status']=='assigned' and t['assigned_agent']==aid and t['lease_expires_at'] is not None and t['lease_expires_at']>end_s:
                    owners[t['task_id']].add(aid)
        orphaned=sum(not owners[t] for t in required_tasks-completed_tasks)
        multiple=sum(len(owners[t])>1 for t in required_tasks-completed_tasks)
    distances={};samples=defaultdict(list)
    if flight is not None:
        for e in flight:samples[e['agent_id']].append(e)
        for aid,values in samples.items():
            values.sort(key=lambda e:e['time_s']);distances[aid]=sum(math.dist(a['position'],b['position']) for a,b in zip(values,values[1:]))
    telemetry=[e for e in events if e['event_type']=='OBSERVATION_RECEIVED' and e['data'].get('source')=='own_telemetry']
    battery=defaultdict(dict)
    for e in telemetry:
        value=e['data']['observation'].get('battery')
        if isinstance(value,(float,int)):battery[e['agent_id']][e['simulation_time_s']]=value
    drops={aid:values[min(values)]-values[max(values)] for aid,values in battery.items() if len(values)>1}
    llm_calls=sum(e['event_type']=='LLM_CALLED' for e in events)
    usage=[e['data'] for e in events if e['event_type']=='LLM_USAGE']
    input_tokens=[u['prompt_eval_count'] for u in usage if type(u.get('prompt_eval_count')) is int and u['prompt_eval_count']>=0]
    output_tokens=[u['eval_count'] for u in usage if type(u.get('eval_count')) is int and u['eval_count']>=0]
    latencies=[r['latency_s'] for r in responses if 'error_type' not in r and 'latency_s' in r]
    errors=[e for e in histories if e['event']=='policy_error']
    return dict(**work,task_reassignments=owner_changes,same_owner_restarts=restarts,
        orphaned_tasks_at_end=orphaned,multiple_self_declared_owners_at_end=multiple,
        orphan_reason=None if orphaned is not None else 'final_task_snapshots_missing_or_incomplete',role_changes=len(changes),
        role_oscillation_candidates=oscillations,unnecessary_role_oscillations=None,
        unnecessary_oscillation_reason='mission_need_oracle_not_defined',
        invalid_structured_outputs=sum(e.get('reason_code','').startswith(INVALID_OUTPUT_PREFIXES) for e in errors),
        stale_context_or_version_rejections=sum(e.get('reason_code') in ('stale_decision_context','stale_task_version') for e in errors),
        llm_calls=llm_calls,llm_response_latency_mean_s=ratio(sum(latencies),len(latencies)) if llm_calls else None,
        llm_response_latency_p95_s=percentile(latencies,.95) if llm_calls else None,
        response_errors=sum('error_type' in r for r in responses),
        token_usage=dict(input_tokens=sum(input_tokens) if len(input_tokens)==llm_calls else None,
            output_tokens=sum(output_tokens) if len(output_tokens)==llm_calls else None,
            reported_input_token_subtotal=sum(input_tokens),reported_output_token_subtotal=sum(output_tokens),
            complete=llm_calls==len(input_tokens)==len(output_tokens),calls_with_usage=len(usage),
            reason=None if llm_calls==len(input_tokens)==len(output_tokens) else 'missing_or_abandoned_provider_usage'),
        fallback_policy_invocations=sum(e['event']=='deterministic_fallback' for e in histories),
        role_deadline_fallbacks=sum(e['event']=='role_deadline_fallback' for e in histories),
        fallback_replacement_enabled=c.get('ablations',{}).get('fallback_policy',False),
        distance_travelled_m=sum(distances.values()) if distances else None,distance_by_agent_m=distances,
        battery_decrease_percent_by_agent=drops if drops else None,energy_joules=None,
        conflicting_claim_corrections=len({(e.get('task_id'),e.get('version'),e.get('previous'),e.get('winner')) for e in histories if e['event']=='claim_corrected'}))


def evaluate_run(folder):
    folder=Path(folder);outer=Evidence(folder);manifest=outer.read('manifest.json')
    if manifest is None:raise ValueError('Phase 14 manifest missing or corrupt')
    if manifest.get('experiment_id')!=folder.name or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',folder.name):raise ValueError('Unsafe or mismatched experiment ID')
    ev=Evidence(folder/'run');detail=ev.read('manifest.json') or {}
    c=manifest.get('effective_configuration',{})
    mission=detail.get('shared_inputs',{}).get('mission',{})
    required={(t['task_id'],i) for t in mission.get('tasks',[]) for i,_ in enumerate(t['waypoints'])}
    tasks={task for task,_ in required}
    events=outer.read('events.jsonl') or []
    summary=ev.read('summary.json')
    protocol=ev.read('protocol_events.json')
    if protocol is None:
        protocol=[dict(event='work_completed',time_s=e['simulation_time_s'],agent_id=e['agent_id'],**e['data'])
            for e in events if e['event_type']=='TASK_COMPLETED']
    arrivals=ev.read('waypoint_arrivals.json')
    if arrivals is None:
        arrivals=[dict(time_s=e['simulation_time_s'],agent_id=e['agent_id'],**e['data']) for e in events if e['event_type']=='WAYPOINT_ARRIVED']
    flight=ev.read('flight_trace.json');audit=ev.read('guardian_audit.json');effects=ev.read('executed_actions.json');messages=ev.read('messages.json')
    histories=list(protocol);responses=[]
    for aid in mission.get('vehicles',{}):
        histories.extend(ev.read(aid+'/decision_history.jsonl') or [])
        responses.extend(ev.read(aid+'/responses.jsonl') or [])
    starts=[e['simulation_time_s'] for e in events if e['event_type']=='MISSION_STARTED']
    started=bool(starts);start=min(starts) if starts else None
    end=summary['time_s'] if summary is not None else max((e['simulation_time_s'] for e in events if e['simulation_time_s'] is not None),default=None)
    end=0 if end is None else end
    completed_events=[e for e in protocol if e['event']=='work_completed']
    reported_completed={e['task_id'] for e in completed_events}&tasks
    seen_units={(a['task_id'],a['index']) for a in arrivals}
    completed={t for t in reported_completed if {unit for unit in required if unit[0]==t}<=seen_units}
    work=work_metrics(arrivals,required)
    guarded=None
    if effects is not None and audit is not None:
        accepted={e['selected_action']['command_id'] for e in audit if e.get('selected_action') and e.get('mission_effect',{}).get('executed')}
        guarded=all(e['command_id'] in accepted for e in effects)
    duplicates=len([e for e in completed_events if e['task_id'] in tasks])-len(reported_completed)
    error=manifest.get('error') or (summary or {}).get('error')
    verified_success=bool(started and tasks and completed==tasks and work['unique_productive_work']==len(required) and
        duplicates==0 and guarded is True and error is None)
    status=('completed' if verified_success else 'not_started' if not started else 'error' if error else
        'interrupted' if manifest['status'] in ('running','interrupted') else
        'evidence_error' if (summary or {}).get('mission_execution_success') else
        'failed_success_criterion' if (summary or {}).get('mission_complete') else 'timeout')
    primary=dict(mission=dict(success=verified_success if started else None,mission_score=int(verified_success) if started else None,
        required_tasks=len(tasks),completed_tasks=len(completed),guarded_effects_verified=guarded,
        components=dict(route_work_fraction=work['route_work_fraction'],**additional_components(events,mission))),
        completion_time=dict(value_s=end-start if verified_success else None,status=status,
            observation_time_s=end-start if started else None,timeout_budget_s=manifest.get('budget_s'),
            censored=bool(started and not verified_success),clock=detail.get('effective_clock')),
        continuity_retention=dict(value=None,route_work_retention=None,reason='nominal_reference_not_matched_yet'),
        recovery=recovery_metrics(events,arrivals,completed_events,detail.get('shared_inputs',{}).get('network',{}).get('partitions',[]),end),
        safety=safety_metrics(flight,audit,mission.get('guardian',{}),[e for e in events if e['event_type']=='OBSERVATION_RECEIVED' and e['data'].get('source')=='own_telemetry']),
        communication=communication_metrics(messages,end,len(completed)))
    primary['safety']['stale_message_decisions']=sum(m.get('influenced_decision',False) and m['status']=='delivered' and
        m['actual_delivery_time']>=m['expires_at'] for m in messages) if messages is not None else None
    snapshots={e['agent_id']:e for e in events if e['event_type']=='TASK_STATE_SNAPSHOT' and e['data'].get('scope','final')=='final'}
    diagnostics=diagnostic_metrics(events,histories,responses,flight,snapshots,tasks,completed,end,c,work)
    area=primary['mission']['components']['area_coverage_fraction']
    diagnostics.update(area_searched_percent=100*area if area is not None else None,
        redundant_search_cell_observations=primary['mission']['components']['redundant_cell_observations'],
        stale_message_decisions=primary['safety']['stale_message_decisions'])
    claims=defaultdict(set)
    for record in protocol:
        if record['event']=='claim_sent':claims[(record['task_id'],record['version'])].add(record['owner'])
    for event in events:
        message=event['data'].get('envelope',{}) if event['event_type']=='MESSAGE_SENT' else {}
        payload=message.get('payload',{})
        if message.get('message_type')=='TASK_AWARD' and payload.get('owner')==message.get('sender_id'):
            claims[(payload['task_id'],payload['version'])].add(payload['owner'])
    diagnostics.update(conflicting_task_claim_epochs=sum(len(owners)>1 for owners in claims.values()),
        competing_task_claims=sum(max(0,len(owners)-1) for owners in claims.values()))
    cfg=copy.deepcopy(c)
    for key in ('condition','network','output_dir','mission_config','policy'):cfg.pop(key,None)
    identity=detail.get('effective_provider',{})
    match=dict(configuration=cfg,mission=mission,architecture=manifest.get('architecture'),scenario_id=manifest.get('scenario_id'),
        seed=manifest.get('random_seed'),failure_profile=manifest.get('failure_profile'),
        policy={k:identity.get(k) for k in ('provider','model','digest','options')},
        sources=manifest.get('provenance',{}).get('source_sha256'))
    key=hashlib.sha256(json.dumps(match,sort_keys=True,allow_nan=False).encode()).hexdigest() if c and mission else None
    issues=outer.issues+ev.issues
    if (summary or {}).get('mission_execution_success') and not verified_success:issues.append(dict(artifact='summary.json',error='success_not_supported_by_independent_evidence'))
    if manifest.get('source_changed_during_run'):issues.append(dict(artifact='manifest.json',error='source_changed_during_run'))
    unavailable=dict(energy_joules='no_calibrated_energy_model',unnecessary_role_oscillations='mission_need_oracle_not_defined')
    if not flight:unavailable['sampled_safety_and_distance']='flight_trace_missing_or_empty'
    if audit is None:unavailable['guardian_evaluations']='guardian_audit_missing'
    if diagnostics['battery_decrease_percent_by_agent'] is None:unavailable['battery_decrease']='multiple_own_telemetry_samples_missing'
    if not required:unavailable['route_work_fraction']='required_mission_units_missing'
    return dict(schema_version=1,definition_id=contract()['definition_id'],experiment_id=manifest['experiment_id'],run_id=manifest.get('run_id'),
        architecture=manifest.get('architecture'),scenario_id=manifest.get('scenario_id'),network_profile=manifest.get('network_profile'),
        random_seed=manifest.get('random_seed'),match_key=key,evidence_issues=issues,
        primary=primary,diagnostic=diagnostics,unavailable_reasons=unavailable)


def match_continuity(rows):
    for row in rows:
        refs=[r for r in rows if r['network_profile']=='nominal' and r['match_key'] and r['match_key']==row['match_key']]
        metric=row['primary']['continuity_retention']
        if row['evidence_issues']:metric['reason']='run_evidence_inconsistent';continue
        if not refs:metric['reason']='no_matched_nominal';continue
        if len(refs)>1:metric['reason']='ambiguous_nominal_replicates';continue
        baseline=refs[0];metric['nominal_experiment_id']=baseline['experiment_id']
        if baseline['evidence_issues']:metric['reason']='nominal_evidence_inconsistent';continue
        denominator=baseline['primary']['mission']['mission_score'];numerator=row['primary']['mission']['mission_score']
        metric['value']=ratio(numerator,denominator) if numerator is not None else None
        metric['reason']=None if metric['value'] is not None else 'nominal_score_zero_or_unknown' if not denominator else 'mission_not_started'
        a=row['primary']['mission']['components']['route_work_fraction'];b=baseline['primary']['mission']['components']['route_work_fraction']
        metric['route_work_retention']=ratio(a,b) if a is not None else None
        metric['route_work_reason']=None if metric['route_work_retention'] is not None else 'nominal_or_degraded_route_work_unavailable_or_zero'


def evaluation_error_row(identifier,error):
    return dict(schema_version=1,definition_id=contract()['definition_id'],experiment_id=identifier,
        architecture=None,scenario_id=None,network_profile=None,random_seed=None,match_key=None,
        evidence_issues=[dict(artifact='run_evidence',error=type(error).__name__,message=str(error))],
        primary=dict(mission=dict(success=None,mission_score=None,components=dict(route_work_fraction=None)),
            completion_time=dict(value_s=None,status='evidence_error',observation_time_s=None,censored=False),
            continuity_retention=dict(value=None,route_work_retention=None,reason='invalid_run_evidence'),
            safety=dict(guardian_interventions=None,sampled_separation_violations=None),communication={}),
        diagnostic=dict(coordination_efficiency=None,llm_calls=None))


def evaluate_batch(root,output_dir=None):
    root=Path(root);out=Path(output_dir) if output_dir else root/'metrics'
    if out.exists() and any(out.iterdir()):raise ValueError('Use an empty metric output directory')
    batch=json.loads((root/'batch_manifest.json').read_text())
    registration_path=root/'metric_registration.json';prespecified=False;registration=None
    if registration_path.exists():
        registration=json.loads(registration_path.read_text())
        prespecified=(registration['evaluator_source_sha256']==evaluator_hash() and
            registration['contract_sha256']==hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() and
            (root/'metric_contract.json').read_bytes()==CONTRACT_PATH.read_bytes() and
            registration.get('definitions_sha256')==hashlib.sha256(DEFINITION_PATH.read_bytes()).hexdigest() and
            (root/'metric_definitions.md').read_bytes()==DEFINITION_PATH.read_bytes())
    rows=[]
    identifiers={run['experiment_id'] for run in batch['runs']}
    identifiers.update(p.parent.name for p in root.glob('*/manifest.json'))
    for number,identifier in enumerate(sorted(identifiers,key=str)):
        safe=isinstance(identifier,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',identifier)
        folder=root/identifier if safe else None
        try:
            if folder is None:raise ValueError('Unsafe experiment ID')
            row=evaluate_run(folder)
            if registration:
                manifest=json.loads((folder/'manifest.json').read_text())
                prespecified=prespecified and manifest.get('metric_registration')==registration and datetime.fromisoformat(registration['registered_at_utc'])<=datetime.fromisoformat(manifest['started_at_utc'])
        except Exception as exc:row=evaluation_error_row(identifier if safe else f'invalid_run_{number}',exc)
        rows.append(row)
    match_continuity(rows)
    out.mkdir(parents=True,exist_ok=True)
    for row in rows:dump(out/(row['experiment_id']+'.metrics.json'),row)
    dump(out/'metrics.json',rows)
    compact=[]
    for row in rows:
        p=row['primary'];d=row['diagnostic']
        compact.append(dict(experiment_id=row['experiment_id'],architecture=row['architecture'],condition=row['network_profile'],seed=row['random_seed'],
            mission_success=p['mission']['success'],mission_score=p['mission']['mission_score'],completion_time_s=p['completion_time']['value_s'],
            time_status=p['completion_time']['status'],observation_time_s=p['completion_time']['observation_time_s'],
            continuity_retention=p['continuity_retention']['value'],route_work_retention=p['continuity_retention']['route_work_retention'],
            route_work_fraction=p['mission']['components']['route_work_fraction'],coordination_efficiency=d['coordination_efficiency'],
            guardian_interventions=p['safety']['guardian_interventions'],separation_violations=p['safety']['sampled_separation_violations'],
            communication_bytes=p['communication'].get('bytes_transmitted'),llm_calls=d['llm_calls'],evidence_issues=len(row['evidence_issues'])))
    if compact:
        with (out/'metrics.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(compact[0]),lineterminator='\n');writer.writeheader();writer.writerows(compact)
    summary=dict(definition_id=contract()['definition_id'],prespecified=bool(prespecified),evaluation_type='predeclared' if prespecified else 'retrospective',
        evaluator_source_sha256=evaluator_hash(),experiments_evaluated=len(rows),mission_successes=sum(r['primary']['mission']['success'] is True for r in rows),
        not_started=sum(r['primary']['completion_time']['status']=='not_started' for r in rows),
        censored_missions=sum(r['primary']['completion_time']['censored'] for r in rows),
        evidence_issues=sum(len(r['evidence_issues']) for r in rows),
        limitations=['Route waypoint work is not area coverage','Absent collision/target/return sensing is not a zero measurement',
            'Recovery acceptance is local ownership, not consensus or safe execution','Physical/between-sample safety is not certified',
            'Retrospective analysis does not establish preregistration'])
    dump(out/'evaluation_summary.json',summary)
    lines=['# Phase 15 evaluation',f"Definition: {summary['definition_id']}. Type: {summary['evaluation_type']}.",
        '', '| Experiment | Success | Completed time (s) | Observation status | Route work | Continuity |', '|---|---|---:|---|---:|---:|']
    for r in compact:lines.append(f"| {r['experiment_id']} | {r['mission_success']} | {r['completion_time_s']} | {r['time_status']} | {r['route_work_fraction']} | {r['continuity_retention']} |")
    lines+=['','Missing measurements and reference failures have explicit reasons in the per-run JSON. Successful times are never filled with timeout endpoints.',*summary['limitations']]
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    return summary
