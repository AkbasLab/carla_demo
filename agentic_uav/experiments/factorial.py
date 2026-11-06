"""Prospectively frozen Phase 18 factorial design and auditable, resumable replications.

A failed mission is an experimental outcome, not a technical exclusion. This module
never replaces a seed with a more favorable one and never executes held-out runs
without a Phase 17 lock and an independently seeded extension validation.
"""
import copy
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import fcntl
import hashlib
import itertools
import json
import math
from pathlib import Path
import random

from . import metrics
from .architectures import CONTROLLER
from .comparison import configuration
from .pilots import digest, read, resolve, pathref, verify_frozen, _run_evidence
from .runner import PROJECT_ROOT, provenance, run_experiment, write_json
from agentic_uav.comm.degraded import NetworkConfig
from agentic_uav.policy.mission import load_mission
from agentic_uav.policy.structured import OllamaProvider

CONDITIONS = ('nominal', 'moderate', 'severe', 'partitioned')
FAILURES = ('none', 'drone_failure_midmission')
TECHNICAL_EXCLUSIONS = (
    'not_started', 'runtime_error_or_interruption', 'missing_or_corrupt_artifacts',
    'configuration_or_provenance_mismatch', 'model_identity_mismatch',
    'inconsistent_metric_evidence', 'incomplete_decision_audit',
)
VALID_UNFAVORABLE_OUTCOMES = (
    'mission_timeout', 'incomplete_work', 'failed_recovery', 'safety_violation',
    'guardian_rejection', 'handled_invalid_llm_output', 'inference_timeout',
    'fallback_use', 'no_productive_llm_decisions', 'mission_finished_before_fault',
)


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def validate_design(c):
    required = {'schema_version', 'architectures', 'team_sizes', 'conditions', 'failure_profiles',
                'test_seeds', 'development_seeds', 'validation_seeds', 'replications',
                'max_attempts_per_seed', 'order_seed', 'network_profiles', 'partition_interval_s',
                'validation_nominal_success_floor', 'rationale'}
    if set(c) != required or c['schema_version'] != 1:
        raise ValueError('Unexpected Phase 18 design fields')
    for key, allowed in [('architectures', tuple('ABCD')), ('team_sizes', (2, 4, 8)),
                         ('conditions', CONDITIONS), ('failure_profiles', FAILURES)]:
        values = c[key]
        if not isinstance(values, list) or not values or len(set(values)) != len(values) or any(v not in allowed for v in values):
            raise ValueError('Invalid factor: ' + key)
    if not {2, 4} <= set(c['team_sizes']):
        raise ValueError('Two- and four-drone validation must precede eight drones')
    for key in ('test_seeds', 'development_seeds', 'validation_seeds'):
        values = c[key]
        if not isinstance(values, list) or not values or any(type(s) is not int or s < 0 for s in values) or len(set(values)) != len(values):
            raise ValueError('Invalid seed set: ' + key)
    if any(set(c[a]) & set(c[b]) for a,b in itertools.combinations(('test_seeds','development_seeds','validation_seeds'),2)):
        raise ValueError('Development, validation and held-out seeds must be disjoint')
    if type(c['replications']) is not int or c['replications'] < 1 or len(c['test_seeds']) != c['replications']:
        raise ValueError('Declare exactly one held-out seed per required replication')
    if len(c['validation_seeds']) < 3:
        raise ValueError('At least three extension-validation seeds required')
    if type(c['max_attempts_per_seed']) is not int or not 1 <= c['max_attempts_per_seed'] <= 3:
        raise ValueError('Technical retry limit must be 1 to 3')
    if type(c['order_seed']) is not int or c['order_seed'] < 0:
        raise ValueError('Invalid run-order seed')
    floor = c['validation_nominal_success_floor']
    if type(floor) not in (int,float) or not .5 <= floor <= 1:
        raise ValueError('Invalid prospective nominal stability floor')
    interval=c['partition_interval_s']
    if not isinstance(interval,list) or len(interval)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in interval) or not 0<=interval[0]<interval[1]:
        raise ValueError('Invalid partition interval')
    if set(c['network_profiles']) != set(CONDITIONS) or set(c['rationale']) != set(CONDITIONS) | {'scenario_family','selection_reason'}:
        raise ValueError('All four profiles and their prospective rationale required')
    for name, values in c['network_profiles'].items():
        if values.get('partitions'):
            raise ValueError('Partition groups are generated for the actual team size')
        NetworkConfig(**values)
    for text in c['rationale'].values():
        if not isinstance(text,str) or len(text.strip())<40 or 'TODO' in text.upper():
            raise ValueError('Supply substantive prospective rationale, then calibrate it')
    return copy.deepcopy(c)


def cells(c):
    return [dict(architecture=a,team_size=n,network_profile=p,failure_profile=f)
            for a,n,p,f in itertools.product(c['architectures'],c['team_sizes'],c['conditions'],c['failure_profiles'])]


def cell_id(cell):
    return f"{cell['architecture']}_n{cell['team_size']}_{cell['network_profile']}_{'loss' if cell['failure_profile']!='none' else 'control'}"


def plan(config_path, output_dir):
    c=validate_design(read(resolve(config_path)));out=Path(output_dir).resolve()
    out.mkdir(parents=True,exist_ok=False)
    value=dict(schema_version=1,stage='draft_not_authorized_for_held_out_execution',design_sha256=sha(c),
               cells=cells(c),cell_count=len(cells(c)),replications=c['replications'],
               planned_runs=len(cells(c))*c['replications'],
               maximum_attempts=len(cells(c))*c['replications']*c['max_attempts_per_seed'],
               prerequisites=['verified Phase 17 pinned calibration lock',
                              'matching extension validation on disjoint seeds',
                              'pinned local model and unchanged source/metric hashes'],
               technical_exclusions=list(TECHNICAL_EXCLUSIONS),valid_unfavorable_outcomes=list(VALID_UNFAVORABLE_OUTCOMES))
    write_json(out/'design.json',c);write_json(out/'plan.json',value)
    return value


def locked_inputs(c, phase17_root):
    root=resolve(phase17_root);lock=verify_frozen(root);pilot=read(root/'pilot_config.json')
    if lock.get('profile')!='pinned' or not set(c['test_seeds'])<=set(lock['held_out_seeds']):
        raise ValueError('Held-out seeds must have been reserved by the pinned Phase 17 lock')
    if set(c['validation_seeds']) & (set(lock['pilot_seeds'])|set(lock['held_out_seeds'])):
        raise ValueError('Extension validation seeds overlap the Phase 17 pilot or held-out pool')
    if not set(lock['pilot_seeds'])<=set(c['development_seeds']):
        raise ValueError('Declare previously inspected pilot seeds as development')
    for name in ('nominal','severe'):
        if asdict(NetworkConfig(**c['network_profiles'][name])) != asdict(NetworkConfig(**pilot['network_profiles'][name])):
            raise ValueError('Nominal/severe must match the calibrated Phase 17 profiles')
    if c['partition_interval_s'][1]>=pilot['duration_s']:
        raise ValueError('Partition must end before the observation horizon')
    frozen_batch=read(root/'final_batch.json')['experiments'];missions={}
    for n in (2,4):
        paths={e['settings']['mission_config'] for e in frozen_batch if e['team_size']==n}
        if len(paths)!=1:raise ValueError('Expected one frozen scenario fixture per team size')
        path=resolve(next(iter(paths)))
        if str(path.relative_to(root)) not in lock['files_sha256']:
            raise ValueError('Mission is not covered by the Phase 17 lock')
        missions[n]=read(path)
    if pilot['model']['model_digest'].removeprefix('sha256:') != lock['model']['digest']:
        raise ValueError('Phase 17 model identity differs from its configuration')
    return root,lock,pilot,missions


def materialize(missions, sizes, root):
    target=root/'fixtures';target.mkdir();paths={}
    for n in sizes:
        m=copy.deepcopy(missions[4 if n==8 else n])
        if n==8:
            # Fixed four-task workload. Added agents start in a separated second row.
            for i,vehicle in enumerate(list(m['vehicles'].values()),5):
                v=copy.deepcopy(vehicle);v['start_position'][0]-=8;v['home'][0]-=8
                v['frame_offset_m']=list(v['start_position']);v['frame_offset_m'][2]=0
                m['vehicles'][f'Drone{i}']=v
            m['mission']='Eight drones complete the same four search routes using delivered messages and runtime assurance.'
        path=target/f'team_{n}.json';write_json(path,m)
        load_mission(path,allowed_team_sizes=(2,4,8));paths[str(n)]=str(path)
    return paths


def entries(c,pilot,missions,seeds,stage):
    result=[];rng=random.Random(c['order_seed'])
    # Block by common seed and condition, randomize only architecture order.
    for seed,n,p,f in itertools.product(seeds,c['team_sizes'],c['conditions'],c['failure_profiles']):
        architectures=list(c['architectures']);rng.shuffle(architectures)
        m=read(missions[str(n)]);ids=list(m['vehicles']);assignments={a:[] for a in ids}
        for i,t in enumerate(m['tasks']):assignments[ids[i%n]].append(t['task_id'])
        network=asdict(NetworkConfig(**c['network_profiles'][p]))
        if p=='partitioned':
            network['partitions']=[dict(start_s=c['partition_interval_s'][0],end_s=c['partition_interval_s'][1],
                                       groups=[ids[:n//2]+[CONTROLLER],ids[n//2:]])]
        for a in architectures:
            settings=copy.deepcopy(pilot['settings'])
            settings.update(mission_config=missions[str(n)],initial_assignments=assignments,network=network,
                            policy=pilot['model'],clock_mode='wall',
                            ticks=round(pilot['duration_s']/settings['dt']),
                            scenario=dict(fail_agent=ids[0] if f!='none' else None,fail_at_s=pilot['fail_at_s']))
            configuration(dict(settings,architecture=a,condition=p,seed=seed))
            cell=dict(architecture=a,team_size=n,network_profile=p,failure_profile=f)
            result.append(dict(experiment_id=f'{cell_id(cell)}_s{seed}',**cell,scenario='phase18_fixed_four_routes',
                               random_seed=seed,planner='deterministic' if a in 'AC' else pilot['model']['model'],settings=settings))
    return dict(schema_version=1,experiments=result)


def model_preflight(pilot, seed):
    m=pilot['model']
    return OllamaProvider(m['model'],m['model_digest'],m['ollama_url'],pilot['settings']['inference_timeout'],seed).verify()


def write_validation_report(root):
    root=Path(root).resolve();meta=read(root/'validation_definition.json');c=meta['design']
    planned=read(root/'batch.json')['experiments'];rows=[];blockers=[];nominal=defaultdict(list);network_evidence=defaultdict(list)
    for entry in planned:
        folder=root/'runs'/entry['experiment_id']
        assessment=assess_attempt(folder,entry,meta['source_sha256'])
        evidence=None
        if assessment['technical_valid']:
            evidence=_run_evidence(folder)
            packets=read(folder/'run/messages.json')
            evidence['partition_drops']=sum(r.get('drop_reason')=='partition' for r in packets)
            if entry['failure_profile']=='none':network_evidence[entry['network_profile']].append(evidence)
            if entry['network_profile']=='partitioned' and not evidence['partition_drops']:
                blockers.append('ineffective_partition_exposure:'+entry['experiment_id'])
            if entry['network_profile']=='nominal' and entry['failure_profile']=='none':
                nominal[(entry['architecture'],entry['team_size'])].append(evidence['mission_complete'])
            if entry['failure_profile']!='none' and not (evidence['fault_observed'] and evidence['fault_owned_tasks'] and evidence['fault_during_motion']):
                blockers.append('ineffective_fault_exposure:'+entry['experiment_id'])
        else:blockers.append('technical_invalid:'+entry['experiment_id'])
        rows.append(dict(experiment_id=entry['experiment_id'],**assessment,evidence=evidence))
    for a,n in itertools.product(c['architectures'],c['team_sizes']):
        values=nominal[(a,n)]
        if len(values)!=len(c['validation_seeds']) or sum(values)/len(values)<c['validation_nominal_success_floor']:
            blockers.append(f'nominal_not_stable:{a}:n{n}')
    severe=network_evidence['severe']
    if severe and not 0<sum(r['mission_complete'] for r in severe)<len(severe):
        blockers.append('severe_controls_all_succeed_or_all_fail')
    report=dict(schema_version=1,design_sha256=meta['design_sha256'],eligible_for_main=not blockers,
                network_calibration={name:dict(runs=len(rows),successes=sum(r['mission_complete'] for r in rows),
                    delivered_fractions=[r['delivered_fraction_resolved'] for r in rows],
                    mean_delivered_delays_s=[r['mean_delivered_delay_s'] for r in rows]) for name,rows in network_evidence.items()},
                blockers=blockers,runs=rows,validation_only=True)
    write_json(root/'validation_report.json',report)
    return report


def validate_extensions(config_path,phase17_root,output_dir):
    c=validate_design(read(resolve(config_path)));p17,lock,pilot,missions=locked_inputs(c,phase17_root)
    out=Path(output_dir).resolve();out.mkdir(parents=True,exist_ok=False)
    paths=materialize(missions,c['team_sizes'],out)
    batch=entries(c,pilot,paths,c['validation_seeds'],'validation');write_json(out/'batch.json',batch)
    meta=dict(schema_version=1,design=c,design_sha256=sha(c),phase17_root=str(p17),phase17_lock_sha256=digest(p17/'freeze_manifest.json'),
              source_sha256=source_hashes(),pilot=pilot,
              fixture_sha256={p:digest(p) for p in paths.values()})
    write_json(out/'validation_definition.json',meta)
    try:write_json(out/'model_preflight.json',model_preflight(pilot,c['validation_seeds'][0]))
    except Exception as exc:
        write_json(out/'preflight_error.json',dict(type=type(exc).__name__,message=str(exc)));raise
    # Validate the smaller cases before launching any eight-drone cases.
    batches=[('small', [e for e in batch['experiments'] if e['team_size']!=8])]
    if 8 in c['team_sizes']:batches.append(('eight',[e for e in batch['experiments'] if e['team_size']==8]))
    (out/'runs').mkdir()
    registration=metrics.register(out/'runs')
    for label,group in batches:
        for entry in group:
            run_experiment(entry,out/'runs',out/'batch.json',registration)
        report=write_validation_report(out)
        if label=='small' and 8 in c['team_sizes']:
            smaller={e['experiment_id'] for e in group}
            if any(not r['technical_valid'] for r in report['runs'] if r['experiment_id'] in smaller) or any(
                    b.startswith('nominal_not_stable:') and not b.endswith(':n8') for b in report['blockers']):
                break
    verify_frozen(p17)
    return write_validation_report(out)


def source_hashes():
    value=provenance()['source_sha256']
    for p in [PROJECT_ROOT/'scripts/run_phase18_factorial.py',metrics.DEFINITION_PATH,metrics.CONTRACT_PATH]:
        value[pathref(p)]=digest(p)
    return value


def check_hashes(hashes):
    for name,expected in hashes.items():
        if digest(resolve(name))!=expected:raise ValueError('Frozen source/evidence changed: '+name)


def prepare(config_path,phase17_root,validation_root,output_dir):
    c=validate_design(read(resolve(config_path)));p17,lock,pilot,missions=locked_inputs(c,phase17_root)
    validation=Path(validation_root).resolve();meta=read(validation/'validation_definition.json')
    if meta['design']!=c or meta['design_sha256']!=sha(c) or meta['source_sha256']!=source_hashes() or meta['phase17_lock_sha256']!=digest(p17/'freeze_manifest.json'):
        raise ValueError('Validation does not match the prospective design/Phase 17 lock')
    check_hashes(meta['source_sha256']);check_hashes(meta['fixture_sha256'])
    # Reconstruct expected fixture contents from the pinned pilot inputs.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        original=materialize(missions,c['team_sizes'],Path(tmp))
        if any(read(original[str(n)])!=read(validation/'fixtures'/f'team_{n}.json') for n in c['team_sizes']):
            raise ValueError('Validation fixtures differ from the locked scenario family')
    expected=entries(c,pilot,{str(n):str(validation/'fixtures'/f'team_{n}.json') for n in c['team_sizes']},c['validation_seeds'],'validation')
    if read(validation/'batch.json')!=expected:raise ValueError('Validation batch differs from frozen inputs')
    # A hand-edited ready flag is insufficient; derive readiness again from raw runs.
    report=write_validation_report(validation)
    if not report['eligible_for_main']:raise ValueError('Extension validation not ready: '+', '.join(report['blockers'][:8]))
    out=Path(output_dir).resolve();out.mkdir(parents=True,exist_ok=False)
    paths=materialize(missions,c['team_sizes'],out)
    write_json(out/'design.json',c);write_json(out/'pilot_inputs.json',pilot)
    write_json(out/'final_batch.json',entries(c,pilot,paths,c['test_seeds'],'held_out'))
    write_json(out/'exclusion_policy.json',dict(technical_exclusions=TECHNICAL_EXCLUSIONS,valid_unfavorable_outcomes=VALID_UNFAVORABLE_OUTCOMES,
        selection='first technically valid attempt per cell and seed, regardless of mission outcome',
        retries='same seed only, at most max_attempts_per_seed; retain all attempts'))
    evidence={str(p):digest(p) for p in validation.rglob('*') if p.is_file() and p.suffix in ('.json','.jsonl')}
    files={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}
    value=dict(schema_version=1,frozen_at_utc=utc(),design_sha256=sha(c),phase17_root=str(p17),
               phase17_lock_sha256=digest(p17/'freeze_manifest.json'),source_sha256=source_hashes(),
               files_sha256=files,validation_evidence_sha256=evidence)
    write_json(out/'definition_lock.json',value)
    return dict(cell_count=len(cells(c)),planned_runs=len(cells(c))*c['replications'],definition=str(out),ready_for_execution=True)


def verify_definition(root):
    root=Path(root).resolve();lock=read(root/'definition_lock.json')
    verify_frozen(lock['phase17_root'])
    if digest(Path(lock['phase17_root'])/'freeze_manifest.json')!=lock['phase17_lock_sha256']:
        raise ValueError('Phase 17 lock replaced')
    check_hashes(lock['source_sha256']);check_hashes(lock['validation_evidence_sha256'])
    if source_hashes()!=lock['source_sha256']:
        raise ValueError('Frozen source file set changed')
    for name,value in lock['files_sha256'].items():
        if digest(root/name)!=value:raise ValueError('Phase 18 definition changed: '+name)
    return lock


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def decision_audit(folder, mission, policy, seed):
    """A missing response is valid only when an explicit timeout/abandonment is logged."""
    reasons=[]
    for aid in mission.get('vehicles',{}):
        p=folder/aid;prompts=jsonl(p/'prompts.jsonl');responses=jsonl(p/'responses.jsonl')
        history=jsonl(p/'decision_history.jsonl');specs=jsonl(p/'request_specs.jsonl')
        ids=[r['request_id'] for r in prompts];request_ids=set(ids)
        terminal={r['token'] for r in responses}|{r['request_id'] for r in history
            if r['event'] in ('inference_timeout','inference_abandoned_at_shutdown')}
        specs_by_id={r['request_id']:r for r in specs}
        if len(ids)!=len(request_ids) or request_ids-set(specs_by_id) or request_ids-terminal or {r['token'] for r in responses}-request_ids:
            reasons.append('incomplete_decision_audit')
        for prompt in prompts:
            if not isinstance(prompt.get('prompt'),str):reasons.append('incomplete_decision_audit')
            spec=specs_by_id.get(prompt['request_id'],{});req=spec.get('request',{})
            if spec.get('model_digest')!=policy['model_digest'].removeprefix('sha256:') or req.get('model')!=policy['model'] or not req.get('messages') or req.get('options',{}).get('seed')!=seed or req.get('options',{}).get('temperature')!=0 or not any(m.get('role')=='user' and m.get('content')==prompt.get('prompt') for m in req.get('messages',[])):
                reasons.append('incomplete_decision_audit')
        for response in responses:
            if response.get('error_type')=='ModelIdentityError':reasons.append('model_identity_mismatch')
            if not ('raw' in response or 'error_type' in response):reasons.append('incomplete_decision_audit')
            if not any(r['time_s']==response['simulation_time_s'] and r['event'] in
                       ('policy_decision_applied','policy_error','late_response_discarded') for r in history):
                reasons.append('incomplete_decision_audit')
    return reasons


def assess_attempt(folder,entry,sources):
    """Outcome-blind technical validity. Returned metrics retain unfavorable results."""
    folder=Path(folder);reasons=[];evaluation=None
    try:
        m=read(folder/'manifest.json');s=read(folder/'run/summary.json');detail=read(folder/'run/manifest.json')
        events=jsonl(folder/'events.jsonl')
        if not any(e['event_type']=='MISSION_STARTED' for e in events):reasons.append('not_started')
        if m.get('error') or s.get('error') or not m.get('run_completed') or not m.get('finished_at_utc'):
            reasons.append('runtime_error_or_interruption')
        if m.get('requested_configuration')!=entry or m.get('source_changed_during_run') or any(
                m.get('provenance',{}).get('source_sha256',{}).get(k)!=v for k,v in sources.items() if k.startswith('agentic_uav/') or k=='scripts/run_phase14_experiments.py'):
            reasons.append('configuration_or_provenance_mismatch')
        actual=m.get('effective_configuration',{});expected=configuration(dict(entry['settings'],architecture=entry['architecture'],
                    condition=entry['network_profile'],seed=entry['random_seed'],output_dir=str(folder/'run')))
        if actual!=expected:reasons.append('configuration_or_provenance_mismatch')
        for name in ('flight_trace.json','messages.json','protocol_events.json','guardian_audit.json',
                     'executed_actions.json','waypoint_arrivals.json','scenario_events.json'):
            data=read(folder/'run'/name)
            if not isinstance(data,list):raise ValueError('Expected list artifact: '+name)
        if dict(Counter(e['event_type'] for e in events))!=m.get('event_counts'):
            reasons.append('missing_or_corrupt_artifacts')
        # Verify scene, fault, and network inputs against the same frozen entry.
        shared=detail.get('shared_inputs',{})
        if shared.get('mission')!=read(resolve(entry['settings']['mission_config'])) or shared.get('scenario')!=expected['scenario'] or shared.get('network')!=expected['network']:
            reasons.append('configuration_or_provenance_mismatch')
        if sha(shared)!=s.get('shared_inputs_sha256'):reasons.append('configuration_or_provenance_mismatch')
        if entry['architecture'] in 'BD':
            identity=m.get('effective_provider',{});policy=entry['settings']['policy']
            if not m.get('model_identity_verified') or identity.get('provider')!='ollama' or identity.get('model')!=policy['model'] or identity.get('digest')!=policy['model_digest'].removeprefix('sha256:') or identity.get('options',{}).get('temperature')!=0 or identity.get('options',{})!=OllamaProvider(policy['model'],policy['model_digest'],policy['ollama_url'],seed=entry['random_seed']).options:
                reasons.append('model_identity_mismatch')
            if policy.get('provider')=='ollama':
                reasons.extend(decision_audit(folder/'run',shared.get('mission',{}),policy,entry['random_seed']))
        evaluation=metrics.evaluate_run(folder)
        if evaluation['evidence_issues']:reasons.append('inconsistent_metric_evidence')
    except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError):
        reasons.append('missing_or_corrupt_artifacts')
    reasons=sorted(set(reasons))
    return dict(technical_valid=not reasons,exclusion_reasons=reasons,metrics=evaluation)


def summarize(definition,output_dir,verify=True):
    definition=Path(definition).resolve();out=Path(output_dir).resolve()
    if verify:verify_definition(definition)
    c=read(definition/'design.json');planned=read(definition/'final_batch.json')['experiments']
    sources=read(definition/'definition_lock.json')['source_sha256'];records=[];selected=[];cell_stats={}
    for entry in planned:
        key=cell_id(entry);stats=cell_stats.setdefault(key,dict(cell={k:entry[k] for k in ('architecture','team_size','network_profile','failure_profile')},
                required_replications=c['replications'],valid_seeds=[],mission_successes=0,technical_exclusions=0,exhausted_seeds=[],missing_seeds=[]))
        chosen=None;attempts=0
        for attempt in range(1,c['max_attempts_per_seed']+1):
            folder=out/'attempts'/f"{entry['experiment_id']}_a{attempt}"
            if not folder.exists():break
            attempts+=1;expected=copy.deepcopy(entry);expected['experiment_id']=folder.name
            assessment=assess_attempt(folder,expected,sources)
            records.append(dict(case_id=entry['experiment_id'],seed=entry['random_seed'],attempt=attempt,result_dir=str(folder),**assessment))
            if assessment['technical_valid']:
                chosen=assessment['metrics'];break
            stats['technical_exclusions']+=1
        if chosen:
            selected.append(chosen);stats['valid_seeds'].append(entry['random_seed'])
            stats['mission_successes']+=int(chosen['primary']['mission']['success'] is True)
        elif attempts==c['max_attempts_per_seed']:stats['exhausted_seeds'].append(entry['random_seed'])
        else:stats['missing_seeds'].append(entry['random_seed'])
    metrics.match_continuity(selected)
    matched=[]
    for n,p,failure in itertools.product(c['team_sizes'],c['conditions'],c['failure_profiles']):
        members=[v for v in cell_stats.values() if v['cell']['team_size']==n and v['cell']['network_profile']==p and v['cell']['failure_profile']==failure]
        seeds=set.intersection(*(set(v['valid_seeds']) for v in members)) if len(members)==len(c['architectures']) else set()
        matched.append(dict(team_size=n,network_profile=p,failure_profile=failure,common_valid_seeds=sorted(seeds)))
    report=dict(schema_version=1,updated_at_utc=utc(),definition_sha256=digest(definition/'definition_lock.json'),
                planned_runs=len(planned),attempts=len(records),valid_replications=len(selected),
                successful_missions=sum(s['mission_successes'] for s in cell_stats.values()),
                exit_criterion_passed=len(selected)==len(planned),matched_seed_blocks=matched,cells=cell_stats,attempt_records=records,selected_metrics=selected,
                note='Completion of replications does not require successful missions. All technical exclusions remain visible.')
    out.mkdir(parents=True,exist_ok=True);write_json(out/'replication_report.json',report)
    return report


def execute(definition,output_dir,max_runs=None):
    definition=Path(definition).resolve();out=Path(output_dir).resolve();lock=verify_definition(definition)
    if max_runs is not None and (type(max_runs) is not int or max_runs<1):raise ValueError('max-runs must be positive')
    out.mkdir(parents=True,exist_ok=True)
    with (out/'.runner.lock').open('a') as guard:
        try:fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Another runner holds this result directory')
        registration_path=out/'execution_registration.json';identity=digest(definition/'definition_lock.json')
        if registration_path.exists():
            if read(registration_path)['definition_sha256']!=identity:raise ValueError('Results belong to a different frozen definition')
            metric_registration=read(out/'metric_registration.json')
        else:
            if any(p.name not in ('.runner.lock',) for p in out.iterdir()):raise ValueError('Use a fresh result directory')
            metric_registration=metrics.register(out)
            write_json(registration_path,dict(definition_sha256=identity,registered_at_utc=utc(),metric_registration=metric_registration))
        if metric_registration['evaluator_source_sha256']!=metrics.evaluator_hash() or digest(out/'metric_contract.json')!=metric_registration['contract_sha256'] or digest(out/'metric_definitions.md')!=metric_registration['definitions_sha256']:
            raise ValueError('Metric registration changed')
        pilot=read(definition/'pilot_inputs.json');c=read(definition/'design.json')
        try:write_json(out/'model_preflight.json',model_preflight(pilot,c['test_seeds'][0]))
        except Exception as exc:
            write_json(out/'preflight_error.json',dict(at_utc=utc(),type=type(exc).__name__,message=str(exc)));raise
        (out/'attempts').mkdir(exist_ok=True);(out/'attempt_definitions').mkdir(exist_ok=True)
        count=0
        for entry in read(definition/'final_batch.json')['experiments']:
            for attempt in range(1,c['max_attempts_per_seed']+1):
                check_hashes(lock['source_sha256'])
                for name,expected_hash in lock.get('files_sha256',{}).items():
                    if digest(definition/name)!=expected_hash:raise ValueError('Phase 18 definition changed: '+name)
                current=copy.deepcopy(entry);current['experiment_id']+=f'_a{attempt}'
                folder=out/'attempts'/current['experiment_id']
                if folder.exists():
                    assessment=assess_attempt(folder,current,lock['source_sha256'])
                else:
                    if max_runs is not None and count>=max_runs:return summarize(definition,out)
                    path=out/'attempt_definitions'/f"{current['experiment_id']}.json"
                    write_json(path,dict(schema_version=1,experiments=[current]))
                    outcome=run_experiment(current,out/'attempts',path,metric_registration);count+=1
                    assessment=assess_attempt(folder,current,lock['source_sha256'])
                    write_json(folder/'technical_assessment.json',assessment)
                    write_json(out/'progress.json',dict(updated_at_utc=utc(),last_attempt=current['experiment_id'],
                        attempts_executed_this_invocation=count,technical_valid=assessment['technical_valid'],
                        exclusion_reasons=assessment['exclusion_reasons']))
                    if outcome['status']=='interrupted':return summarize(definition,out)
                if 'model_identity_mismatch' in assessment['exclusion_reasons']:
                    raise ValueError('Model identity drift: stop the batch and investigate retained evidence')
                if assessment['technical_valid']:break
        return summarize(definition,out)
