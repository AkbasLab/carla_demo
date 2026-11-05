"""Phase 14 auditable serial batch runner, separate from active Phase 13 suites."""
import copy
from datetime import datetime,timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import traceback
import uuid
from . import comparison
from .event_logging import EventLog, EVENT_TYPES, instrument, utc_now

PROJECT_ROOT=Path(__file__).resolve().parents[2]
ARCHITECTURES={'centralized_fleet_controller':'A','independent_persistent_agents':'B',
    'deterministic_decentralized':'C','agentic_decentralized':'D',**{a:a for a in 'ABCD'}}
REQUIRED={'experiment_id','architecture','scenario','team_size','network_profile','failure_profile','random_seed','planner'}


def write_json(path,data):
    path=Path(path);temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n');temporary.replace(path)


def provenance():
    def git(*args):
        try:return subprocess.check_output(['git',*args],cwd=PROJECT_ROOT,stderr=subprocess.DEVNULL,text=True,timeout=10).strip()
        except (OSError,subprocess.SubprocessError):return None
    sources=list((PROJECT_ROOT/'agentic_uav').rglob('*.py'))+[PROJECT_ROOT/'scripts/run_phase14_experiments.py']
    versions={}
    for package in ('numpy','requests','jsonschema','ollama','airsim'):
        try:versions[package]=metadata.version(package)
        except metadata.PackageNotFoundError:versions[package]=None
    return dict(git_commit_sha=git('rev-parse','HEAD'),git_tracked_dirty=bool(git('status','--porcelain','--untracked-files=no')),
        source_sha256={str(p.relative_to(PROJECT_ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(sources) if p.exists()},
        software_versions=dict(python=sys.version,implementation=platform.python_implementation(),platform=platform.platform(),packages=versions))


def resolve(path):
    path=Path(path);return path if path.is_absolute() else PROJECT_ROOT/path


def snapshot(path,folder,manifest):
    path=resolve(path);raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    target=folder/'configuration_files'/f'{digest[:12]}_{path.name}'
    target.parent.mkdir(exist_ok=True);target.write_bytes(raw)
    manifest['configuration_files'].append(dict(source_path=str(path),snapshot_path=str(target.relative_to(folder)),sha256=digest))
    return json.loads(raw)


def compile_experiment(entry,folder,manifest):
    missing=REQUIRED-set(entry)
    if missing:raise ValueError('Missing experiment fields: '+', '.join(sorted(missing)))
    unknown=set(entry)-REQUIRED-{'comparison_config','settings'}
    if unknown:raise ValueError('Unknown experiment fields: '+', '.join(sorted(unknown)))
    if entry['architecture'] not in ARCHITECTURES:raise ValueError('Unknown architecture')
    for key in ('scenario','failure_profile','planner'):
        if not isinstance(entry[key],str) or not entry[key]:raise ValueError('Invalid '+key)
    base=snapshot(entry['comparison_config'],folder,manifest) if entry.get('comparison_config') else {}
    overrides=entry.get('settings',{})
    if not isinstance(overrides,dict) or set(overrides)&{'architecture','condition','seed','output_dir'}:
        raise ValueError('Architecture, network, seed and output must use the experiment fields')
    for k,v in overrides.items():
        if k in ('policy','scenario','ablations','resilience') and isinstance(v,dict):base[k]={**base.get(k,{}),**v}
        else:base[k]=copy.deepcopy(v)
    base.update(architecture=ARCHITECTURES[entry['architecture']],condition=entry['network_profile'],seed=entry['random_seed'],output_dir=str(folder/'run'))
    c=comparison.configuration(base)
    mission=snapshot(c['mission_config'],folder,manifest)
    if type(entry['team_size']) is not int or entry['team_size']!=len(mission['vehicles']):raise ValueError('team_size differs from mission vehicles')
    if entry['failure_profile'] not in ('none','drone_failure_midmission','relay_failure'):raise ValueError('Unknown failure_profile')
    if (entry['failure_profile']=='none')!=(c['scenario']['fail_agent'] is None):raise ValueError('failure_profile differs from configured injection')
    if entry['failure_profile']=='relay_failure' and mission['vehicles'].get(c['scenario']['fail_agent'],{}).get('role')!='RELAY':
        raise ValueError('relay_failure must identify a configured relay')
    effective='deterministic' if c['architecture'] in 'AC' or c['ablations']['fallback_policy'] else c['policy']['model'] if c['policy']['provider']=='ollama' else 'replay'
    if entry['planner']!=effective:raise ValueError('planner must match the actual policy/model: '+str(effective))
    manifest.update(effective_configuration=c,architecture=c['architecture'],scenario_id=entry['scenario'],random_seed=c['seed'],
        team_size=entry['team_size'],network_profile=c['condition'],failure_profile=entry['failure_profile'],
        requested_model=dict(planner=entry['planner'],**c['policy']),budget_s=c['ticks']*c['dt'])
    return c


def run_experiment(entry,root,batch_configuration_path=None):
    folder=Path(root)/entry['experiment_id'];folder.mkdir()
    initial=provenance();run_id=uuid.uuid4().hex
    manifest=dict(schema_version=1,run_id=run_id,experiment_id=entry['experiment_id'],requested_configuration=copy.deepcopy(entry),
        architecture=entry.get('architecture'),scenario_id=entry.get('scenario'),random_seed=entry.get('random_seed'),
        started_at_utc=utc_now(),finished_at_utc=None,status='running',run_completed=False,mission_complete=None,
        error=None,configuration_files=[],provenance=initial,model_identity_verified=False,
        instrumentation='phase14_scoped_observers_v1')
    write_json(folder/'manifest.json',manifest)
    log=EventLog(folder/'events.jsonl',entry['experiment_id'],run_id)
    log.emit('RUN_STARTED',requested_configuration=entry)
    summary=None
    try:
        if batch_configuration_path:snapshot(batch_configuration_path,folder,manifest)
        c=compile_experiment(entry,folder,manifest)
        write_json(folder/'manifest.json',manifest)
        with instrument(comparison,log):summary=comparison.run_comparison(c)
        manifest.update(run_completed=summary['error'] is None,mission_complete=summary['mission_complete'],
            status='error' if summary['error'] else 'completed' if summary['mission_complete'] else 'incomplete',error=summary['error'])
        if summary['error']:write_json(folder/'error.json',dict(stage='runtime',**summary['error']))
        kind='RUN_FAILED' if summary['error'] else 'MISSION_COMPLETED' if summary['mission_complete'] else 'MISSION_INCOMPLETE'
        log.emit(kind,summary['time_s'],mission_complete=summary['mission_complete'],error=summary['error'])
    except (Exception,KeyboardInterrupt,SystemExit) as exc:
        manifest.update(status='interrupted' if isinstance(exc,(KeyboardInterrupt,SystemExit)) else 'error',
            error=dict(type=type(exc).__name__,message=str(exc)[:2000]))
        write_json(folder/'error.json',dict(**manifest['error'],traceback=traceback.format_exc()))
        log.emit('RUN_FAILED',error=manifest['error'])
    finally:
        def read_optional(path):
            try:return json.loads(path.read_text()) if path.exists() else None
            except (OSError,ValueError) as exc:
                log.emit('ARTIFACT_READ_ERROR',path=str(path.relative_to(folder)),error_type=type(exc).__name__)
                manifest['artifact_read_errors']=manifest.get('artifact_read_errors',[])+[str(path.relative_to(folder))]
                return None
        phase13_manifest=folder/'run/manifest.json'
        details=read_optional(phase13_manifest)
        if details and 'effective_provider' in details:
            manifest['effective_provider']=details['effective_provider']
            manifest['model_identity_verified']=details['effective_provider']['provider']=='ollama'
        after=provenance()
        manifest.update(finished_at_utc=utc_now(),source_changed_during_run=initial['source_sha256']!=after['source_sha256'],
            event_counts=dict(log.counts),event_coverage={name:log.counts[name] for name in EVENT_TYPES})
        manifest['failure_observed']=False
        scenario=folder/'run/scenario_events.json'
        events=read_optional(scenario)
        if events:manifest['failure_observed']=any(e['event']=='actor_silenced' for e in events)
        log.emit('RUN_FINISHED',status=manifest['status'])
        manifest['event_counts']=dict(log.counts)
        write_json(folder/'manifest.json',manifest)
    return dict(experiment_id=entry['experiment_id'],status=manifest['status'],run_completed=manifest['run_completed'],
        mission_complete=manifest['mission_complete'],error=manifest['error'],result_dir=str(folder))


def run_batch(configuration_path,output_dir):
    configuration_path=resolve(configuration_path)
    batch=json.loads(configuration_path.read_text())
    if set(batch)!={'schema_version','experiments'} or batch['schema_version']!=1:raise ValueError('Expected schema_version=1 and experiments list')
    entries=batch['experiments']
    if not isinstance(entries,list) or not entries:raise ValueError('Batch must contain experiments')
    ids=[e.get('experiment_id') for e in entries if isinstance(e,dict)]
    if len(ids)!=len(entries) or any(not isinstance(i,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',i) for i in ids) or len(set(ids))!=len(ids):
        raise ValueError('Experiment IDs must be unique safe folder names')
    root=Path(output_dir)
    if root.exists() and any(root.iterdir()):raise ValueError('Use an empty output folder; previous results are never overwritten')
    root.mkdir(parents=True,exist_ok=True)
    write_json(root/'batch_configuration.json',batch)
    result=dict(schema_version=1,started_at_utc=utc_now(),finished_at_utc=None,status='running',planned_experiments=len(entries),runs=[])
    write_json(root/'batch_manifest.json',result)
    for entry in entries:
        row=run_experiment(entry,root,configuration_path);result['runs'].append(row)
        write_json(root/'batch_manifest.json',result)
        if row['status']=='interrupted':break
    result.update(finished_at_utc=utc_now(),status='interrupted' if any(r['status']=='interrupted' for r in result['runs']) else 'finished',
        finished_runs=sum(r['run_completed'] for r in result['runs']),successful_missions=sum(r['mission_complete'] is True and r['error'] is None for r in result['runs']),
        errors=sum(r['status']=='error' for r in result['runs']))
    write_json(root/'batch_manifest.json',result)
    return result
