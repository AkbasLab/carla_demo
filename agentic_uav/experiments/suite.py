"""Auditable Phase 13 test matrix; full traces per case, never fake model runs."""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor,as_completed
import copy
import csv
import hashlib
import json
from pathlib import Path
import statistics
import zipfile
from .comparison import configuration,run_comparison
from agentic_uav.policy.structured import OllamaProvider

CONDITIONS=('nominal','moderate','severe','partitioned')
CORE_FILES={'manifest.json','summary.json','waypoint_arrivals.json','executed_actions.json','scenario_events.json','controller_events.json'}


def read_trace(run_dir,name):
    """Future figure scripts can read either raw JSON/JSONL or the lossless archive."""
    run_dir=Path(run_dir);path=run_dir/name
    if path.exists():text=path.read_text()
    else:
        with zipfile.ZipFile(run_dir/'traces.zip') as archive:text=archive.read(name).decode()
    return [json.loads(line) for line in text.splitlines() if line] if name.endswith('.jsonl') else json.loads(text)


def archive_traces(run_dir):
    run_dir=Path(run_dir)
    files=sorted(p for p in run_dir.rglob('*') if p.is_file() and p.name not in CORE_FILES and p.suffix in ('.json','.jsonl'))
    checksums={str(p.relative_to(run_dir)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    target=run_dir/'traces.zip'
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for p in files:
            info=zipfile.ZipInfo(str(p.relative_to(run_dir)),date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,p.read_bytes())
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:raise ValueError('Trace archive failed CRC verification')
        for name,digest in checksums.items():
            if hashlib.sha256(archive.read(name)).hexdigest()!=digest:raise ValueError('Trace archive roundtrip mismatch')
    for p in files:p.unlink()  # Only newly produced case files, after verified lossless preservation.
    index=dict(format='zip-deflate',files_sha256=checksums,archive_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    (run_dir/'trace_index.json').write_text(json.dumps(index,indent=2)+'\n')


def source_hashes():
    paths=list(Path('agentic_uav').rglob('*.py'))+[Path('scripts/run_phase13_suite.py'),Path('scripts/run_phase13_comparison.py')]
    return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def build_plan(base,seeds,root,profile='validation'):
    root=Path(root);base=configuration(base)
    if profile not in ('validation','pinned'):raise ValueError('Choose validation or pinned profile')
    if not seeds or len(seeds)!=len(set(seeds)) or any(type(s) is not int or s<0 for s in seeds):raise ValueError('Seeds must be distinct nonnegative integers')
    base['clock_mode']='simulated' if profile=='validation' else 'wall'
    if profile=='validation':base['policy'].update(provider='replay',model=None,model_digest=None)
    elif base['policy']['provider']!='ollama':raise ValueError('Pinned profile requires a pinned Ollama configuration')
    # The guide's role ablation requires a role-bearing mission, not four scouts.
    role_path=root/'fixtures'/'relay_reserve_mission.json'
    mission=json.loads(Path(base['mission_config']).read_text())
    ids=list(mission['vehicles'])
    if len(ids)!=4:raise ValueError('Four actors required')
    for aid,role in zip(ids,['SCOUT','SCOUT','RELAY','RESERVE']):mission['vehicles'][aid]['role']=role
    cases=[]
    def add(group,condition,architecture,seed,variant='control',control_id=None,**overrides):
        key=f'{group}/{condition}/{architecture}/{variant}/seed_{seed}'
        c=copy.deepcopy(base);c.update(architecture=architecture,condition=condition,seed=seed)
        c['scenario']=dict(fail_agent=None,fail_at_s=8.)
        c['ablations']=dict(persistent_memory=True,task_leases=True,dynamic_roles=True,perfect_communication=False,fallback_policy=False)
        for k,v in overrides.items():
            if k in ('scenario','ablations'):c[k].update(v)
            else:c[k]=v
        c['output_dir']=str(root/key/'run')
        cases.append(dict(case_id=key,group=group,condition=condition,architecture=architecture,seed=seed,
            variant=variant,control_id=control_id,configuration=configuration(c)))
        return key
    for seed in seeds:
        baseline={};failure={}
        for condition in CONDITIONS:
            for architecture in 'ABCD':
                baseline[condition,architecture]=add('baselines',condition,architecture,seed)
                failure[condition,architecture]=add('drone1_failure',condition,architecture,seed,
                    scenario=dict(fail_agent=ids[0],fail_at_s=8.))
        role_controls={}
        for architecture in 'CD':
            role_controls[architecture]=add('relay_failure','nominal',architecture,seed,
                mission_config=str(role_path),scenario=dict(fail_agent=ids[2],fail_at_s=8.))
        add('ablations','nominal','D',seed,'without_memory',baseline['nominal','D'],ablations=dict(persistent_memory=False))
        add('ablations','moderate','D',seed,'without_task_leases',failure['moderate','D'],
            scenario=dict(fail_agent=ids[0],fail_at_s=8.),ablations=dict(task_leases=False))
        add('ablations','nominal','D',seed,'without_dynamic_roles',role_controls['D'],
            mission_config=str(role_path),scenario=dict(fail_agent=ids[2],fail_at_s=8.),ablations=dict(dynamic_roles=False))
        add('ablations','severe','D',seed,'perfect_communication',baseline['severe','D'],ablations=dict(perfect_communication=True))
        add('ablations','nominal','D',seed,'fallback_policy',baseline['nominal','D'],ablations=dict(fallback_policy=True))
        add('relay_failure','nominal','D',seed,'fallback_policy',role_controls['D'],
            mission_config=str(role_path),scenario=dict(fail_agent=ids[2],fail_at_s=8.),ablations=dict(fallback_policy=True))
        if profile=='validation':add('reproducibility','moderate','C',seed,'repeat',baseline['moderate','C'])
    return dict(schema_version=1,profile=profile,seeds=list(seeds),base_configuration=base,
        role_fixture=mission,role_fixture_path=str(role_path),cases=cases,source_hashes=source_hashes(),
        limitations=['Validation B/D are replay, not LLM evidence','One seed is a pilot, not a statistical reliability estimate',
            'Incomplete guarded missions are outcomes; a completed batch does not imply successful recovery',
            'No live AirSim comparison; full traces are stored losslessly per case'])


def validate_run(case,summary,run_dir):
    messages=read_trace(run_dir,'messages.json');events=read_trace(run_dir,'protocol_events.json')
    injection=any(e['event']=='actor_silenced' for e in read_trace(run_dir,'scenario_events.json'))
    checks=dict(no_runtime_error=summary['error'] is None,guarded_dispatch=summary['all_dispatched_actions_guarded'],
        no_expired_delivery=all(m['actual_delivery_time']<m['expires_at'] for m in messages if m['status']=='delivered'),
        no_duplicate_task_completion=summary['duplicate_task_completions']==0)
    if case['architecture']=='A':checks['central_has_no_peer_bidding']=not any(m['message_type']=='TASK_BID' for m in messages)
    if case['architecture']=='B':checks['independent_has_no_negotiation']=all(m['message_type'] in ('HEARTBEAT','STATUS_UPDATE') for m in messages)
    if case['group']=='baselines' and case['condition']=='nominal':checks['nominal_completion']=summary['mission_execution_success']
    if not summary['llm_inference']:checks['no_false_llm_credit']=not summary['llm_exit_criterion_observed']
    if not case['configuration']['ablations']['task_leases']:checks['no_automatic_lease_expiry']=not any(e['event']=='lease_expired' for e in events)
    if not case['configuration']['ablations']['dynamic_roles']:checks['no_role_changes']=summary['role_changes']==0
    if case['configuration']['ablations']['perfect_communication']:checks['no_intentional_network_drops']=not summary['network_drop_reasons']
    return dict(checks=checks,passed=all(checks.values()),mission_complete=summary['mission_complete'],
        failure_requested=case['configuration']['scenario']['fail_agent'] is not None,failure_injected=injection,
        role_change_path_exercised=summary['role_changes']>0,lease_expiry_path_exercised=summary['lease_expirations']>0)


def case_metrics(case,status,summary=None,run_dir=None,validation=None):
    row=dict(case_id=case['case_id'],group=case['group'],architecture=case['architecture'],condition=case['condition'],
        seed=case['seed'],variant=case['variant'],control_id=case['control_id'],status=status,
        provider=None,llm_inference=False,mission_complete=None,mission_execution_success=None,completed_tasks=None,
        observation_end_s=None,completion_time_s=None,time_censored=None,duplicate_task_completions=None,
        guarded_dispatch=None,validation_passed=None,recipient_packets=None,unique_messages=None,delivered=None,dropped=None,expired=None,pending=None,
        delivery_ratio_resolved=None,application_latency_mean_s=None,inference_latency_mean_s=None,
        fallbacks=None,deadline_bids=None,blocked_task_releases=None,role_changes=None,lease_expirations=None,
        productive_llm_decisions=None,shared_inputs_sha256=None,run_dir=str(run_dir) if run_dir else None)
    row.update(failure_requested=case['configuration']['scenario']['fail_agent'] is not None,failure_injected=None)
    if summary is None:return row
    messages=read_trace(run_dir,'messages.json');counts=Counter(m['status'] for m in messages)
    latency=[m['actual_delivery_time']-m['creation_time'] for m in messages if m['status']=='delivered']
    responses=[]
    for aid in summary['decisions_by_agent']:
        try:responses.extend(read_trace(run_dir,aid+'/responses.jsonl'))
        except (KeyError,FileNotFoundError):pass
    inference=[r['latency_s'] for r in responses if 'latency_s' in r and 'error_type' not in r]
    resolved=sum(counts[k] for k in ('delivered','dropped','expired'))
    row.update(provider=summary['provider'],llm_inference=summary['llm_inference'],mission_complete=summary['mission_complete'],
        mission_execution_success=summary['mission_execution_success'],completed_tasks=len(summary['completed_task_ids']),
        observation_end_s=summary['time_s'],completion_time_s=summary['time_s'] if summary['mission_execution_success'] else None,
        time_censored=not summary['mission_complete'],duplicate_task_completions=summary['duplicate_task_completions'],
        guarded_dispatch=summary['all_dispatched_actions_guarded'],validation_passed=validation['passed'] if validation else None,
        failure_injected=validation['failure_injected'] if validation else None,
        recipient_packets=len(messages),unique_messages=len({m['message_id'] for m in messages}),delivered=counts['delivered'],
        dropped=counts['dropped'],expired=counts['expired'],pending=counts['queued'],
        delivery_ratio_resolved=counts['delivered']/resolved if resolved else None,
        application_latency_mean_s=statistics.mean(latency) if latency else None,
        inference_latency_mean_s=statistics.mean(inference) if inference and summary['llm_inference'] else None,
        fallbacks=sum(summary['fallbacks_by_agent'].values()),deadline_bids=sum(summary['deadline_bids_by_agent'].values()),
        blocked_task_releases=sum(summary['blocked_task_releases_by_agent'].values()),role_changes=summary['role_changes'],lease_expirations=summary['lease_expirations'],
        productive_llm_decisions=sum(summary['llm_productive_decisions_by_agent'].values()),shared_inputs_sha256=summary['shared_inputs_sha256'])
    return row


def execute_case(job):
    case,compress=job;folder=Path(case['configuration']['output_dir']).parent;folder.mkdir(parents=True,exist_ok=True)
    (folder/'test_definition.json').write_text(json.dumps(case,indent=2)+'\n')
    (folder/'status.json').write_text(json.dumps(dict(status='running',case_id=case['case_id']))+'\n')
    run_dir=Path(case['configuration']['output_dir'])
    try:
        summary=run_comparison(case['configuration']);validation=validate_run(case,summary,run_dir)
        row=case_metrics(case,'completed' if summary['error'] is None else 'error',summary,run_dir,validation)
        (folder/'validation.json').write_text(json.dumps(validation,indent=2)+'\n')
        if compress:archive_traces(run_dir)
    except Exception as exc:
        row=case_metrics(case,'error',run_dir=run_dir)
        (folder/'runner_error.json').write_text(json.dumps(dict(type=type(exc).__name__,message=str(exc)[:500]),indent=2)+'\n')
    (folder/'metrics.json').write_text(json.dumps(row,indent=2)+'\n')
    (folder/'status.json').write_text(json.dumps(dict(status=row['status'],case_id=case['case_id']),indent=2)+'\n')
    return row


def summarize(root,plan,rows):
    root=Path(root);rows=sorted(rows,key=lambda r:r['case_id'])
    with (root/'metrics.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(rows)
    (root/'metrics.json').write_text(json.dumps(rows,indent=2)+'\n')
    by_id={r['case_id']:r for r in rows};checks=[]
    for case in plan['cases']:
        control_id=case['control_id']
        if not control_id or control_id not in by_id:continue
        row=by_id[case['case_id']];control=by_id[control_id]
        match=row['shared_inputs_sha256']==control['shared_inputs_sha256'] if row['shared_inputs_sha256'] and control['shared_inputs_sha256'] else None
        item=dict(case_id=case['case_id'],control_id=control_id,shared_inputs_match=match)
        if case['group']=='reproducibility' and row['status']=='completed' and control['status']=='completed':
            first=read_trace(row['run_dir'],'messages.json');second=read_trace(control['run_dir'],'messages.json')
            item['message_replay_identical']=first==second
        if case['variant']=='perfect_communication':item['intentional_difference']='effective network only'
        checks.append(item)
    grouped={}
    for row in rows:
        if row['group'] in ('baselines','drone1_failure','relay_failure') and row['variant']=='control' and row['shared_inputs_sha256']:
            grouped.setdefault((row['group'],row['condition'],row['seed']),[]).append(row)
    for group,members in grouped.items():
        checks.append(dict(comparison_group=list(group),shared_inputs_match=len({r['shared_inputs_sha256'] for r in members})==1))
    (root/'matched_checks.json').write_text(json.dumps(checks,indent=2)+'\n')
    statuses=Counter(r['status'] for r in rows)
    result=dict(profile=plan['profile'],planned_cases=len(plan['cases']),statuses=dict(statuses),
        completed_simulations=statuses['completed'],successful_missions=sum(r['mission_execution_success'] is True for r in rows),
        incomplete_missions=sum(r['mission_complete'] is False for r in rows),runtime_errors=statuses['error'],
        validation_failures=sum(r['validation_passed'] is False for r in rows),actual_llm_runs=sum(r['llm_inference'] for r in rows),
        reproducibility_checks_passed=all(c['message_replay_identical'] for c in checks if 'message_replay_identical' in c) if any('message_replay_identical' in c for c in checks) else None,
        mismatched_input_checks=sum(c['shared_inputs_match'] is False for c in checks if 'intentional_difference' not in c),
        limitations=plan['limitations'])
    (root/'suite_summary.json').write_text(json.dumps(result,indent=2)+'\n')
    lines=['# Phase 13 automated suite',f"Profile: **{plan['profile']}**. Cases: {len(rows)}. Actual LLM runs: {result['actual_llm_runs']}.",
        'Incomplete missions are experimental outcomes; they are not automatically runtime/test failures.',
        '', '| Test | Status | Tasks completed | Mission success | End time (s) |', '|---|---|---:|---|---:|']
    for r in rows:lines.append(f"| {r['case_id']} | {r['status']} | {r['completed_tasks']} | {r['mission_execution_success']} | {r['observation_end_s']} |")
    lines+=['','Full per-case data are under each test folder. `run/traces.zip` preserves the large raw traces losslessly.',
        '`metrics.csv` is for future figures; unsuccessful completion times are blank rather than fabricated successes.',
        'Role/memory benefits cannot be inferred from replay. See individual validation files for whether a path was exercised.']
    (root/'REPORT.md').write_text('\n'.join(lines)+'\n')
    return result


def run_suite(base,seeds,root,profile='validation',workers=1,compress=True,resume=False):
    if type(workers) is not int or workers<1:raise ValueError('Workers must be a positive integer')
    if profile=='pinned' and workers!=1:raise ValueError('Pinned comparisons run serially to avoid model-server contention')
    root=Path(root);plan=build_plan(base,seeds,root,profile)
    old_path=root/'suite_manifest.json'
    if old_path.exists():
        if not resume:raise ValueError('Use a new suite folder or --resume')
        if json.loads(old_path.read_text())!=plan:raise ValueError('Cannot mix different suite inputs or source revisions on resume')
    elif root.exists() and any(root.iterdir()):raise ValueError('Use an empty suite folder')
    root.mkdir(parents=True,exist_ok=True);old_path.write_text(json.dumps(plan,indent=2)+'\n')
    fixture=Path(plan['role_fixture_path']);fixture.parent.mkdir(parents=True,exist_ok=True)
    fixture.write_text(json.dumps(plan['role_fixture'],indent=2)+'\n')
    unavailable=None
    if profile=='pinned':
        p=plan['base_configuration']['policy']
        try:availability=OllamaProvider(p['model'],p['model_digest'],p['ollama_url'],min(3.,plan['base_configuration']['inference_timeout'])).verify()
        except Exception as exc:unavailable=dict(type=type(exc).__name__,message=str(exc)[:500]);availability=dict(available=False,error=unavailable)
        (root/'model_availability.json').write_text(json.dumps(availability,indent=2)+'\n')
    rows=[];jobs=[]
    for case in plan['cases']:
        folder=Path(case['configuration']['output_dir']).parent
        if resume:
            if (folder/'metrics.json').exists():
                row=json.loads((folder/'metrics.json').read_text())
                if row['status']=='completed':rows.append(row);continue
            # Never overwrite partial evidence, including an interrupted run without metrics.
            attempts=sorted(p for p in folder.glob('run*') if p.is_dir())
            if attempts:
                case=copy.deepcopy(case);case['configuration']['output_dir']=str(folder/f'run_attempt_{len(attempts)+1:03d}')
        if unavailable:
            folder.mkdir(parents=True,exist_ok=True)
            (folder/'test_definition.json').write_text(json.dumps(case,indent=2)+'\n')
            row=case_metrics(case,'blocked_model_unavailable')
            (folder/'status.json').write_text(json.dumps(dict(status=row['status'],reason=unavailable),indent=2)+'\n')
            (folder/'metrics.json').write_text(json.dumps(row,indent=2)+'\n');rows.append(row)
        else:jobs.append((case,compress))
    if workers==1:
        for job in jobs:
            row=execute_case(job);rows.append(row);print(f"{len(rows)}/{len(plan['cases'])}: {row['case_id']} -> {row['status']}",flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for future in as_completed([pool.submit(execute_case,job) for job in jobs]):
                row=future.result();rows.append(row);print(f"{len(rows)}/{len(plan['cases'])}: {row['case_id']} -> {row['status']}",flush=True)
    return summarize(root,plan,rows)
