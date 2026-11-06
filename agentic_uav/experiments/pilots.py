"""Phase 17 pilot design, calibration audit and explicit final-configuration lock.

Pilot outcomes diagnose methodology. Validation D uses replay, never fabricated
inference. A final lock requires actual pinned pilots and written rationale.
"""
from collections import Counter, defaultdict
import copy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics

from agentic_uav.comm.degraded import NetworkConfig
from agentic_uav.experiments.runner import PROJECT_ROOT, run_batch, write_json
from agentic_uav.policy.structured import OllamaProvider


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def pathref(path):
    path=Path(path).resolve()
    try:return str(path.relative_to(PROJECT_ROOT))
    except ValueError:return str(path)


def resolve(path):
    path=Path(path)
    return path if path.is_absolute() else PROJECT_ROOT/path


def validate_config(c):
    required={'schema_version','pilot_seeds','held_out_seeds','architectures','team_sizes','conditions','failure_profiles',
              'mission_source','network_profiles','settings','duration_s','fail_at_s','model','calibration'}
    if set(c)!=required or c['schema_version']!=1:raise ValueError('Invalid pilot configuration fields')
    for field in ('pilot_seeds','held_out_seeds'):
        values=c[field]
        if not isinstance(values,list) or not values or len(values)!=len(set(values)) or any(type(s) is not int or s<0 for s in values):
            raise ValueError('Seeds must be distinct nonnegative integers')
    if set(c['pilot_seeds'])&set(c['held_out_seeds']):raise ValueError('Pilot and held-out seeds must be disjoint')
    for key,values in [('architectures',['C','D']),('team_sizes',[2,4]),('conditions',['nominal','severe']),
                       ('failure_profiles',['none','drone_failure_midmission'])]:
        if c[key]!=values:raise ValueError('Pilot matrix requires '+key+'='+str(values))
    if set(c['network_profiles'])!=set(c['conditions']):raise ValueError('Specify both network profiles')
    c=copy.deepcopy(c)
    for name,values in c['network_profiles'].items():c['network_profiles'][name]=asdict(NetworkConfig(**values))
    nominal=c['network_profiles']['nominal']
    if nominal['packet_loss_probability'] or nominal['partitions']:raise ValueError('Nominal must have no intentional packet loss or partitions')
    forbidden={'architecture','mission_config','condition','network','seed','policy','scenario','output_dir','initial_assignments','clock_mode','ticks'}
    if not isinstance(c['settings'],dict) or forbidden&set(c['settings']):raise ValueError('Invalid shared pilot settings')
    for key in ('duration_s','fail_at_s'):
        if type(c[key]) not in (int,float) or not math.isfinite(c[key]) or c[key]<=0:raise ValueError('Invalid '+key)
    if c['fail_at_s']>=c['duration_s']:raise ValueError('Fault must fall inside the mission budget')
    dt=c['settings'].get('dt',.1)
    if type(dt) not in (int,float) or not math.isfinite(dt) or dt<=0:raise ValueError('Invalid dt')
    if not math.isclose(c['duration_s']/dt,round(c['duration_s']/dt)):raise ValueError('Budget must contain a whole number of ticks')
    if set(c['model'])!={'provider','model','model_digest','ollama_url'} or c['model']['provider']!='ollama':raise ValueError('Pinned local model required')
    # Constructor validates identity syntax without contacting a model server.
    OllamaProvider(c['model']['model'],c['model']['model_digest'],c['model']['ollama_url'])
    g=c['calibration']
    if set(g)!={'min_seeds','min_severe_resolved_delivery_fraction','max_severe_to_nominal_delivery_ratio'} or type(g['min_seeds']) is not int or g['min_seeds']<3:
        raise ValueError('Calibration requires at least three repeated seeds')
    if not 0<g['min_severe_resolved_delivery_fraction']<1 or not 0<g['max_severe_to_nominal_delivery_ratio']<1:raise ValueError('Invalid calibration thresholds')
    return c


def materialize_missions(c,root):
    source=read(resolve(c['mission_source']))
    if len(source['vehicles'])!=4 or len(source['tasks'])!=4:raise ValueError('Pilot source requires four vehicles and four tasks')
    fixtures=root/'fixtures';fixtures.mkdir()
    missions={}
    for n in c['team_sizes']:
        m=copy.deepcopy(source)
        m['mission']=f'{n} drones complete the same four search routes using local beliefs and delivered messages.'
        m['vehicles']=dict(list(m['vehicles'].items())[:n])
        # Keep work constant across team sizes. Longer routes expose mid-task faults.
        for task in m['tasks']:
            y=task['waypoints'][0][1];z=task['waypoints'][0][2]
            task['waypoints']=[[6,y,z],[12,y,z],[12,y+3,z],[6,y+3,z]]
        from agentic_uav.control.runtime_guardian import Action,Config,RuntimeGuardian,State
        guardian=RuntimeGuardian(Config(**m['guardian']))
        first=m['tasks'][0]['waypoints']
        feasible=False
        for aid,v in m['vehicles'].items():
            action=Action('pilot_route_preflight',aid,'MOVE',0,30,tuple(tuple(p) for p in first),1)
            check=guardian.evaluate(action,State(aid,tuple(v['start_position']),0,80,tuple(v['home'])),0)
            feasible=feasible or check.outcome.value in ('APPROVE','APPROVE_WITH_MODIFICATION')
        if not feasible:raise ValueError('No agent can bid for the first pilot route under the current guardian contract')
        path=fixtures/f'team_{n}.json';write_json(path,m);missions[n]=pathref(path)
    return missions


def matrix(c,profile,missions,seeds):
    if profile not in ('validation','pinned'):raise ValueError('Choose validation or pinned profile')
    entries=[]
    for seed,arch,n,condition,failure in itertools.product(seeds,c['architectures'],c['team_sizes'],c['conditions'],c['failure_profiles']):
        mission=read(resolve(missions[n]));ids=list(mission['vehicles'])
        assignments={aid:[] for aid in ids}
        for i,task in enumerate(mission['tasks']):assignments[ids[i%n]].append(task['task_id'])
        policy=c['model'] if profile=='pinned' else dict(provider='replay',model=None,model_digest=None,ollama_url=c['model']['ollama_url'])
        settings=copy.deepcopy(c['settings'])
        settings.update(mission_config=missions[n],initial_assignments=assignments,network=c['network_profiles'][condition],
                        policy=policy,clock_mode='wall' if profile=='pinned' else 'simulated',
                        ticks=round(c['duration_s']/settings.get('dt',.1)),
                        scenario=dict(fail_agent=ids[0] if failure!='none' else None,fail_at_s=c['fail_at_s']))
        name=f'{arch}_n{n}_{condition}_{"loss" if failure!="none" else "control"}_s{seed}'
        from .comparison import configuration
        configuration(dict(settings,architecture=arch,condition=condition,seed=seed))
        entries.append(dict(experiment_id=name,architecture=arch,scenario='phase17_four_routes',team_size=n,
                            network_profile=condition,failure_profile=failure,random_seed=seed,
                            planner='deterministic' if arch=='C' else policy['model'] if profile=='pinned' else 'replay',settings=settings))
    return dict(schema_version=1,experiments=entries)


def prepare(config_path,root,profile='validation'):
    root=Path(root).resolve();c=validate_config(read(config_path))
    if root.exists() and any(root.iterdir()):raise ValueError('Use a fresh pilot output folder')
    root.mkdir(parents=True,exist_ok=True)
    missions=materialize_missions(c,root)
    write_json(root/'pilot_config.json',c)
    batch=matrix(c,profile,missions,c['pilot_seeds']);write_json(root/'pilot_batch.json',batch)
    files=[root/'pilot_config.json',root/'pilot_batch.json',*[resolve(p) for p in missions.values()]]
    plan=dict(schema_version=1,profile=profile,pilot_seeds=c['pilot_seeds'],held_out_seeds=c['held_out_seeds'],
              planned_experiments=len(batch['experiments']),mission_files=missions,
              files_sha256={str(p.relative_to(root)):digest(p) for p in files},
              notes=['Validation D is replay, not LLM evidence','Fixed fault timing is audited for actual owned moving work',
                     'Four tasks held constant across two and four drones','Pilot and held-out seeds must never overlap'])
    write_json(root/'pilot_plan.json',plan)
    return plan


def verify_plan(root):
    root=Path(root);plan=read(root/'pilot_plan.json')
    for path,sha in plan['files_sha256'].items():
        if digest(root/path)!=sha:raise ValueError('Pilot plan file changed: '+path)
    return plan


def run_pilots(config_path,root,profile='validation'):
    root=Path(root).resolve();prepare(config_path,root,profile)
    if profile=='pinned':
        c=read(root/'pilot_config.json');m=c['model']
        try:identity=OllamaProvider(m['model'],m['model_digest'],m['ollama_url'],c['settings']['inference_timeout'],c['pilot_seeds'][0]).verify()
        except Exception as exc:
            write_json(root/'pilot_error.json',dict(stage='model_preflight',error_type=type(exc).__name__,message=str(exc)[:500]))
            raise
        write_json(root/'model_preflight.json',identity)
    result=run_batch(root/'pilot_batch.json',root/'runs',evaluate=True)
    analyze(root)
    return result


def _run_evidence(folder):
    manifest=read(folder/'manifest.json');summary=read(folder/'run/summary.json') if (folder/'run/summary.json').exists() else None
    files=['flight_trace.json','messages.json','protocol_events.json','guardian_audit.json','waypoint_arrivals.json',
           'executed_actions.json','scenario_events.json','manifest.json','summary.json']
    missing=[f for f in files if not (folder/'run'/f).is_file()]
    if not (folder/'events.jsonl').exists():missing.append('events.jsonl')
    events=[json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines()] if (folder/'events.jsonl').exists() else []
    counts=Counter(e['event_type'] for e in events)
    if dict(counts)!=manifest.get('event_counts'):missing.append('event_count_mismatch')
    trace=read(folder/'run/flight_trace.json') if (folder/'run/flight_trace.json').exists() else []
    if not trace or not all({'owned_tasks','execution_task_id','role','active','communication_estimate'}<=r.keys() for r in trace):missing.append('task_role_communication_trace')
    fault=[e for e in events if e['event_type']=='FAULT_INJECTED'];owned=[];moving=False;active={}
    for e in events:
        data=e['data'];aid=e['agent_id']
        if e['event_type']=='SKILL_STARTED':active[aid]=(data['command_id'],data['kind'])
        elif e['event_type'] in ('SKILL_COMPLETED','SKILL_CANCELLED') and active.get(aid,(None,))[0]==data['command_id']:active.pop(aid,None)
        elif e['event_type']=='FAULT_INJECTED':moving=active.get(aid,(None,None))[1]=='MOVE'
        elif e['event_type']=='TASK_STATE_SNAPSHOT' and data.get('scope')=='fault_onset':
            owned=[t['task_id'] for t in data['tasks'] if t['status']=='assigned' and t['assigned_agent']==aid]
    messages=read(folder/'run/messages.json') if (folder/'run/messages.json').exists() else []
    statuses=Counter(r['status'] for r in messages);resolved=sum(statuses[k] for k in ('delivered','dropped','expired'))
    delays=[r['actual_delivery_time']-r['creation_time'] for r in messages if r['status']=='delivered']
    return dict(log_issues=missing,event_counts=dict(counts),fault_observed=bool(fault),fault_owned_tasks=owned,fault_during_motion=moving,
                delivered_fraction_resolved=statuses['delivered']/resolved if resolved else None,pending_packets=statuses['queued'],
                mean_delivered_delay_s=statistics.mean(delays) if delays else None,
                configured_loss=manifest.get('effective_configuration',{}).get('network',{}).get('packet_loss_probability'),
                runtime_error=manifest.get('error'),mission_complete=bool(summary and summary['mission_execution_success']),
                completed_tasks=len(summary['completed_task_ids']) if summary else None,
                llm_inference=bool(summary and summary['llm_inference']),
                productive_llm_decisions=sum(summary.get('llm_productive_decisions_by_agent',{}).values()) if summary else 0,
                model=manifest.get('effective_provider'),source_hashes=manifest['provenance']['source_sha256'])


def analyze(root,plots=True):
    root=Path(root).resolve();plan=verify_plan(root);c=read(root/'pilot_config.json');batch=read(root/'pilot_batch.json')
    output=root/'analysis';output.mkdir(exist_ok=True);rows=[]
    metrics=read(root/'runs/metrics/metrics.json') if (root/'runs/metrics/metrics.json').exists() else []
    evaluations={r['experiment_id']:r for r in metrics}
    from .pilot_plots import plot_run
    for entry in batch['experiments']:
        folder=root/'runs'/entry['experiment_id']
        try:
            evidence=_run_evidence(folder)
        except (OSError,ValueError,KeyError,TypeError) as exc:evidence=dict(log_issues=[type(exc).__name__+': '+str(exc)[:200]],mission_complete=False,runtime_error='missing/corrupt evidence')
        ev=evaluations.get(entry['experiment_id'])
        row=dict(experiment_id=entry['experiment_id'],architecture=entry['architecture'],team_size=entry['team_size'],
                 condition=entry['network_profile'],failure=entry['failure_profile'],seed=entry['random_seed'],**evidence,
                 metric_issues=ev.get('evidence_issues',[]) if ev else ['metric_evaluation_missing'],
                 route_work_fraction=ev['primary']['mission']['components']['route_work_fraction'] if ev else None,
                 successful_time_s=ev['primary']['completion_time']['value_s'] if ev else None)
        if plots and not evidence['log_issues']:
            try:plot_run(folder,output/(entry['experiment_id']+'.png'))
            except (OSError,ValueError,KeyError,TypeError) as exc:row['log_issues'].append('timeline_render_failed: '+str(exc)[:200])
        rows.append(row)
    cells=[]
    for arch,n,condition,failure in itertools.product(c['architectures'],c['team_sizes'],c['conditions'],c['failure_profiles']):
        selected=[r for r in rows if (r['architecture'],r['team_size'],r['condition'],r['failure'])==(arch,n,condition,failure)]
        times=[r['successful_time_s'] for r in selected if r['successful_time_s'] is not None]
        cells.append(dict(architecture=arch,team_size=n,condition=condition,failure=failure,runs=len(selected),successes=sum(r['mission_complete'] for r in selected),
                          median_successful_time_s=statistics.median(times) if times else None))
    issues=[]
    if plan['profile']!='pinned':issues.append('validation_replay_cannot_select_final_agentic_configuration')
    if len(c['pilot_seeds'])<c['calibration']['min_seeds']:issues.append('insufficient_repeated_seeds')
    if any(r['log_issues'] or r['metric_issues'] or r['runtime_error'] for r in rows):issues.append('incomplete_or_inconsistent_run_evidence')
    evaluation=read(root/'runs/metrics/evaluation_summary.json') if (root/'runs/metrics/evaluation_summary.json').exists() else {}
    if not evaluation.get('prespecified') or evaluation.get('evidence_issues',1):issues.append('metric_registration_or_evaluation_not_verified')
    if any(r.get('source_hashes')!=rows[0].get('source_hashes') for r in rows):issues.append('implementation_changed_across_pilots')
    failures=[r for r in rows if r['failure']!='none']
    if any(not r.get('fault_observed') or not r.get('fault_owned_tasks') or not r.get('fault_during_motion') for r in failures):issues.append('fault_did_not_interrupt_owned_moving_work')
    actual=[r for r in rows if r['architecture']=='D']
    if any(not r.get('llm_inference') or not r.get('event_counts',{}).get('LLM_CALLED') for r in actual):issues.append('actual_llm_calls_missing')
    if any(not r.get('productive_llm_decisions') for r in actual if r['condition']=='nominal' and r['failure']=='none'):issues.append('nominal_agentic_execution_not_demonstrated')
    identities=[r.get('model') for r in actual]
    def stable_identity(i):
        return dict(provider=i.get('provider'),model=i.get('model'),digest=i.get('digest'),
                    options={k:v for k,v in i.get('options',{}).items() if k!='seed'})
    if (not identities or any(not i or i.get('provider')!='ollama' for i in identities)
            or any(stable_identity(i)!=stable_identity(identities[0] or {}) for i in identities if i)
            or any(r.get('model',{}).get('options',{}).get('seed')!=r['seed'] for r in actual if r.get('model'))
            or any(i.get('model')!=c['model']['model'] or i.get('digest')!=c['model']['model_digest'].removeprefix('sha256:')
                   or i.get('options',{}).get('temperature')!=0 for i in identities if i)):
        issues.append('model_identity_not_consistent')
    controls=[r for r in rows if r['failure']=='none'];severe=[r for r in controls if r['condition']=='severe'];nominal=[r for r in controls if r['condition']=='nominal']
    severe_rate=sum(r['mission_complete'] for r in severe)/len(severe);nominal_rate=sum(r['mission_complete'] for r in nominal)/len(nominal)
    if severe_rate in (0,1):issues.append('severe_control_outcomes_degenerate_all_fail_or_all_succeed')
    if nominal_rate<.5:issues.append('nominal_control_not_a_usable_reference')
    fraction=lambda rs:statistics.mean(r['delivered_fraction_resolved'] for r in rs if r.get('delivered_fraction_resolved') is not None) if any(r.get('delivered_fraction_resolved') is not None for r in rs) else None
    sr,nr=fraction(severe),fraction(nominal)
    if sr is None or sr<c['calibration']['min_severe_resolved_delivery_fraction']:issues.append('severe_communication_mostly_unusable')
    if sr is None or nr is None or nr==0 or sr/nr>c['calibration']['max_severe_to_nominal_delivery_ratio']:issues.append('nominal_severe_delivery_not_distinguishable')
    report=dict(schema_version=1,profile=plan['profile'],planned_runs=plan['planned_experiments'],observed_successes=sum(r['mission_complete'] for r in rows),
                eligible_for_freeze=not issues,freeze_blockers=issues,cells=cells,runs=rows,
                calibration=dict(nominal_control_success_rate=nominal_rate,severe_control_success_rate=severe_rate,
                                 nominal_mean_resolved_delivery_fraction=nr,severe_mean_resolved_delivery_fraction=sr,
                                 network_profiles=c['network_profiles'],thresholds=c['calibration']),
                limitations=['Pilot-only observations; no final architecture or LLM advantage claim','Replay is not real-model evidence',
                             'Resolved delivery excludes pending packets; delays apply only to delivered packets',
                             'Configured network parameters are not calibrated RF','Fixed fault must actually interrupt work; failed checks require another pilot, not evidence deletion'])
    write_json(output/'calibration_report.json',report)
    lines=['# Phase 17 pilot calibration',f"Profile: {plan['profile']}. {len(rows)} planned cases; {report['observed_successes']} missions completed.",'',
           'These are methodology pilots, not final comparisons. Every successful time excludes censored runs.','',
           '| Architecture | Team | Network | Fault | Successes / runs | Median successful time (s) |','|---|---:|---|---|---:|---:|']
    for cell in cells:lines.append(f"| {cell['architecture']} | {cell['team_size']} | {cell['condition']} | {cell['failure']} | {cell['successes']}/{cell['runs']} | {cell['median_successful_time_s']} |")
    lines+=['','## Communication-level calibration',
            'These are candidate application-network settings, not calibrated radio claims. Latency jitter is a uniform half-width; delivery delays also include queueing and polling. Pending packets are excluded from resolved delivery ratios.','',
            '| Level | Independent loss | Latency mean +/- half-width (ms) | Recipient packets/s | Egress bytes/s | Control mission success | Mean resolved delivery fraction |',
            '|---|---:|---:|---:|---:|---:|---:|']
    for name,rate,delivered in [('nominal',nominal_rate,nr),('severe',severe_rate,sr)]:
        net=c['network_profiles'][name]
        lines.append(f"| {name} | {net['packet_loss_probability']} | {net['latency_ms_mean']} +/- {net['latency_ms_jitter']} | {net['message_rate_limit']} | {net['bandwidth_bytes_per_second']} | {rate} | {delivered} |")
    lines+=['','All-success or all-failure severe controls, mostly unusable delivery, inadequate nominal references, missing model evidence, or ineffective fault timing require more calibration. Do not remove those runs or relax the guardian to manufacture recovery.',
            '','## Final selection status',f"Eligible for freeze: {report['eligible_for_freeze']}.",'']+['- '+i for i in issues]
    lines+=['','## Individual timelines','Each plot contains trajectories, local ownership, roles, traffic, heartbeat age, task claims, policy proposals, guardian outcomes and mission progress. Missing evidence is flagged; no-event paths remain explicitly empty.','']
    lines += [f"- [{r['experiment_id']}]({r['experiment_id']}.png)" for r in rows if (output/(r['experiment_id']+'.png')).exists()]
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    return report


def freeze(root,output_dir,rationale_path):
    root=Path(root).resolve();report=analyze(root,plots=False)
    if not report['eligible_for_freeze']:raise ValueError('Pilot calibration not ready for freeze: '+', '.join(report['freeze_blockers']))
    rationale=read(rationale_path)
    if set(rationale)!={'nominal','severe','scenario_families','selection_reason'} or any(not isinstance(v,str) or len(v.strip())<40 or 'TODO' in v.upper() for v in rationale.values()):
        raise ValueError('Supply substantive rationale for both levels, scenario family and selection')
    plan=verify_plan(root);c=read(root/'pilot_config.json')
    # All runs must come from the current implementation before it is locked.
    sources=report['runs'][0]['source_hashes']
    for path,sha in sources.items():
        if digest(resolve(path))!=sha:raise ValueError('Implementation changed since pilots: '+path)
    out=Path(output_dir).resolve()
    if out.exists() and any(out.iterdir()):raise ValueError('Use a fresh final-lock directory')
    out.mkdir(parents=True,exist_ok=True);(out/'fixtures').mkdir()
    missions={}
    for n,path in plan['mission_files'].items():
        target=out/'fixtures'/Path(path).name;target.write_bytes(resolve(path).read_bytes());missions[int(n)]=pathref(target)
    write_json(out/'final_batch.json',matrix(c,'pinned',missions,c['held_out_seeds']))
    write_json(out/'rationale.json',rationale);write_json(out/'pilot_config.json',c)
    files={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}
    # Freeze prompt/tool/rule/metric/network/scenario implementation plus launcher.
    extra=[PROJECT_ROOT/'scripts/run_phase17_pilots.py',PROJECT_ROOT/'docs/phase15_evaluation_metrics.md',PROJECT_ROOT/'configs/phase15/metrics.v1.json']
    sources={**sources,**{pathref(p):digest(p) for p in extra}}
    evidence={str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file() and p.suffix in ('.json','.jsonl')}
    lock=dict(schema_version=1,frozen_at_utc=datetime.now(timezone.utc).isoformat(),pilot_root=pathref(root),
              pilot_seeds=c['pilot_seeds'],held_out_seeds=c['held_out_seeds'],profile='pinned',
              files_sha256=files,source_sha256=sources,pilot_evidence_sha256=evidence,
              model=report['runs'][next(i for i,r in enumerate(report['runs']) if r['architecture']=='D')]['model'])
    write_json(out/'freeze_manifest.json',lock)
    return lock


def verify_frozen(root):
    root=Path(root).resolve();lock=read(root/'freeze_manifest.json')
    for name,sha in lock['files_sha256'].items():
        if digest(root/name)!=sha:raise ValueError('Frozen configuration changed: '+name)
    for name,sha in lock['source_sha256'].items():
        if digest(resolve(name))!=sha:raise ValueError('Frozen implementation changed: '+name)
    for name,sha in lock['pilot_evidence_sha256'].items():
        if digest(resolve(lock['pilot_root'])/name)!=sha:raise ValueError('Pilot evidence changed since selection: '+name)
    return lock


def run_frozen(root,output_dir):
    root=Path(root).resolve();lock=verify_frozen(root)
    if set(lock['pilot_seeds'])&set(lock['held_out_seeds']):raise ValueError('Overlapping seed sets')
    c=read(root/'pilot_config.json');m=c['model']
    identity=OllamaProvider(m['model'],m['model_digest'],m['ollama_url'],c['settings']['inference_timeout'],c['held_out_seeds'][0]).verify()
    if identity.get('digest')!=lock['model'].get('digest'):raise ValueError('Frozen model digest differs')
    result=run_batch(root/'final_batch.json',output_dir,evaluate=True)
    verify_frozen(root)
    return result
