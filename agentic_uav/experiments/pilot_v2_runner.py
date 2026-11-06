"""Small, explicitly changed Phase 17 scenarios with lossless evidence packing."""
import copy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path,PurePosixPath
import zipfile

from . import metrics
from .pilot_plots import plot_run
from .pilots import read,resolve,pathref,materialize_missions,_run_evidence
from .runner import run_experiment,write_json,provenance
from agentic_uav.comm.degraded import preset
from dataclasses import asdict
from agentic_uav.policy.structured import OllamaProvider


def size(root):
    return sum(p.stat().st_size for p in Path(root).rglob('*') if p.is_file())


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pack_evidence(folder):
    """Verify byte-for-byte round trips before removing redundant raw copies.

    Phase 15 Evidence reads these ZIP locations directly. Graphs are rendered
    before packing; legacy Phase 17 plotters need restore_evidence first.
    """
    folder=Path(folder);index=[]
    targets=[(folder,['events.jsonl'])]
    inner=folder/'run'
    names=['flight_trace.json','messages.json','guardian_audit.json','executed_actions.json','retry_events.json']
    names += [str(p.relative_to(inner)) for p in inner.glob('*/*.jsonl')]
    targets.append((inner,names))
    for root,names in targets:
        files=[root/n for n in names if (root/n).exists()]
        if not files:continue
        archive=root/'traces.zip'
        if archive.exists():raise ValueError('Archive already exists: '+str(archive))
        hashes={str(p.relative_to(root)):sha(p) for p in files}
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for p in files:z.write(p,str(p.relative_to(root)))
        with zipfile.ZipFile(archive) as z:
            if z.testzip() is not None:raise ValueError('Corrupt archive')
            if any(hashlib.sha256(z.read(name)).hexdigest()!=digest for name,digest in hashes.items()):raise ValueError('Archive verification failed')
        # Seal the index before deletion so interrupted packing remains recoverable.
        index.append(dict(archive=str(archive.relative_to(folder)),sha256=sha(archive),members_sha256=hashes,
                          uncompressed_bytes=sum(p.stat().st_size for p in files),compressed_bytes=archive.stat().st_size))
        write_json(folder/'evidence_archives.json',dict(schema_version=1,archives=index))
        for p in files:p.unlink()
    return index


def restore_evidence(folder):
    folder=Path(folder).resolve();index=read(folder/'evidence_archives.json');restored=0
    for group in index['archives']:
        archive=folder/group['archive']
        if sha(archive)!=group['sha256']:raise ValueError('Archive hash differs: '+str(archive))
        with zipfile.ZipFile(archive) as z:
            if set(z.namelist())!=set(group['members_sha256']):raise ValueError('Unexpected archive members')
            for name,digest in group['members_sha256'].items():
                rel=PurePosixPath(name)
                if rel.is_absolute() or '..' in rel.parts or '\\' in name:raise ValueError('Unsafe archive path')
                target=archive.parent/name
                if target.exists():
                    if sha(target)!=digest:raise ValueError('Existing file differs: '+str(target))
                    continue
                raw=z.read(name)
                if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Member checksum failed')
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);restored+=1
    return dict(restored_files=restored,archives_retained=True)


def build(config,root,stage,team_size,seed,profile,telemetry,fault_mode):
    if stage not in ('smoke','focused','severe') or team_size not in (2,4):raise ValueError('Invalid stage/team size')
    if type(seed) is not int or seed<0 or seed in config['protected_seeds']:raise ValueError('Use a development seed outside the old pilot and held-out pools')
    if profile not in ('replay','pinned') or telemetry not in ('alive','silent') or fault_mode not in ('owned_motion','fixed_time'):raise ValueError('Invalid V2 profile')
    c=copy.deepcopy(config['pilot_template']);c['team_sizes']=[team_size]
    paths=materialize_missions(c,root)
    mission=read(resolve(paths[team_size]));ids=list(mission['vehicles']);assignments={a:[] for a in ids}
    for i,t in enumerate(mission['tasks']):assignments[ids[i%team_size]].append(t['task_id'])
    policy=c['model'] if profile=='pinned' else dict(provider='replay',model=None,model_digest=None,ollama_url=c['model']['ollama_url'])
    condition='severe' if stage=='severe' else 'nominal';entries=[]
    for arch in ('C',) if stage=='smoke' else ('C','D'):
        for fault in (False,True):
            settings=copy.deepcopy(config['settings'])
            settings.update(mission_config=paths[team_size],initial_assignments=assignments,policy=policy,
                clock_mode='wall' if profile=='pinned' and stage!='smoke' else 'simulated',
                ticks=round(config['duration_s']/settings['dt']),network=asdict(preset(condition)),
                scenario=dict(fail_agent=ids[0] if fault else None,fail_at_s=config['earliest_fault_s']),
                pilot_resilience_v2=dict(enabled=True,independent_telemetry=telemetry=='alive',fault_mode=fault_mode,
                    fault_displacement_m=config['fault_displacement_m'],blocked_release_after_s=config['blocked_release_after_s']))
            scenario=('phase17_v2_policy_stop_telemetry_alive' if telemetry=='alive' else 'phase17_v2_full_agent_silence')+'_'+fault_mode
            entries.append(dict(experiment_id=f'{arch}_n{team_size}_{condition}_{"loss" if fault else "control"}_s{seed}',
                architecture=arch,scenario=scenario,team_size=team_size,network_profile=condition,
                failure_profile='drone_failure_midmission' if fault else 'none',random_seed=seed,
                planner='deterministic' if arch=='C' else policy['model'] if profile=='pinned' else 'replay',settings=settings))
    return dict(schema_version=1,experiments=entries)


def overview(rows,path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    fig,axes=plt.subplots(1,3,figsize=(15,4.5),layout='constrained')
    labels=[r['experiment_id'].replace('_s'+str(r['seed']), '').replace('_','\n',1) for r in rows]
    axes[0].bar(range(len(rows)),[r['completed_tasks'] for r in rows],color=['#3977a9' if r['mission_complete'] else '#cc8c3a' for r in rows]);axes[0].set_ylim(0,4.5);axes[0].set_ylabel('Verified completed tasks / 4')
    axes[0].set_title('Mission outcome')
    for i,r in enumerate(rows):
        axes[1].scatter(i,r['time_s'],marker='o' if r['mission_complete'] else '^',color='#3977a9' if r['mission_complete'] else '#cc8c3a',s=70)
    axes[1].set_ylabel('Completion / censored observation time (s)');axes[1].set_title('Incomplete runs are not completions')
    axes[1].legend(handles=[Line2D([],[],marker='o',ls='',color='#3977a9',label='Complete'),Line2D([],[],marker='^',ls='',color='#cc8c3a',label='Incomplete')],fontsize=8)
    faults=[r for r in rows if r['fault_observed']]
    for i,r in enumerate(faults):
        for k,marker,color in [('fault_s','x','#cc8c3a'),('replacement_s','o','#3977a9'),('productive_resume_s','s','#3f9675')]:
            if r[k] is not None:axes[2].scatter(r[k],i,marker=marker,color=color,s=55)
    axes[2].set_title('Fault → replacement → productive work');axes[2].set_xlabel('Mission time (s)')
    axes[2].set_yticks(range(len(faults)),[r['experiment_id'].split('_')[0] for r in faults]);axes[2].legend(handles=[Line2D([],[],marker=m,color=c,ls='',label=l) for m,c,l in [('x','#cc8c3a','Fault'),('o','#3977a9','Replacement accepted'),('s','#3f9675','Productive resume')]],fontsize=7)
    for ax in axes[:2]:ax.set_xticks(range(len(rows)),labels,fontsize=7)
    fig.suptitle('Phase 17 resilience V2 diagnostic batch — mock flight; see manifest for fault/telemetry assumptions')
    fig.savefig(path,dpi=140,bbox_inches='tight');plt.close(fig)


def execute(config_path,output_dir,*,stage='smoke',team_size=4,seed=7,profile='pinned',telemetry='alive',fault_mode='owned_motion',compress=True):
    config=read(resolve(config_path));root=Path(output_dir).resolve();root.mkdir(parents=True,exist_ok=False)
    if config['schema_version']!=1 or not 60<=config['duration_s']<=600:raise ValueError('Invalid V2 budget')
    batch=build(config,root,stage,team_size,seed,profile,telemetry,fault_mode)
    write_json(root/'configuration.json',config);write_json(root/'batch.json',batch)
    if stage!='smoke' and profile=='pinned':
        m=config['pilot_template']['model']
        try:identity=OllamaProvider(m['model'],m['model_digest'],m['ollama_url'],seed=seed).verify()
        except Exception as exc:
            write_json(root/'preflight_error.json',dict(type=type(exc).__name__,message=str(exc)));raise
        write_json(root/'model_preflight.json',identity)
    (root/'runs').mkdir();(root/'analysis').mkdir();registration=metrics.register(root/'runs');rows=[];evaluations=[]
    manifest=dict(schema_version=1,stage=stage,profile='deterministic_smoke' if stage=='smoke' else profile,
        started_at_utc=datetime.now(timezone.utc).isoformat(),finished_at_utc=None,status='running',planned_runs=len(batch['experiments']),
        completed_runs=0,source=provenance(),fault_trigger=fault_mode,telemetry=telemetry,
        data_budget_bytes=round(config['disk_budget_mb']*1024**2),rows=rows,
        held_out=False,eligible_for_final_freeze=False,
        limitations=['New explicit V2 scenario; not a like-for-like reproduction of pinned_run1',
            'Independent physical telemetry uses the same degraded bus but survives policy-process failure; not whole-vehicle radio failure',
            'Owned-motion trigger changes the experimental scenario; actual fault time can differ between architectures',
            'One development seed and one team size per invocation; small batches are diagnostics, not final calibration or LLM superiority evidence',
            'No live CARLA-Air flight; silence never proves absence; collision sensing remains unavailable'])
    write_json(root/'v2_manifest.json',manifest)
    for entry in batch['experiments']:
        if size(root)>=manifest['data_budget_bytes']:
            manifest['status']='stopped_at_data_budget';break
        outcome=run_experiment(entry,root/'runs',root/'batch.json',registration);folder=root/'runs'/entry['experiment_id']
        try:
            ev=metrics.evaluate_run(folder);evaluations.append(ev);evidence=_run_evidence(folder)
            summary=read(folder/'run/summary.json');recovery=[r for r in ev['primary']['recovery'] if r['kind']=='actor_failure']
            accepted=[recovery[0]['onset_s']+t['recovery_time_s'] for t in recovery[0]['tasks'] if t['recovery_time_s'] is not None] if recovery else []
            productive=[recovery[0]['onset_s']+t['productive_resume_time_s'] for t in recovery[0]['tasks'] if t['productive_resume_time_s'] is not None] if recovery else []
            row=dict(experiment_id=entry['experiment_id'],seed=seed,architecture=entry['architecture'],
                fault_requested=entry['failure_profile']!='none',mission_complete=ev['primary']['mission']['success'],completed_tasks=ev['primary']['mission']['completed_tasks'],
                time_s=summary['time_s'],route_work_fraction=ev['diagnostic']['route_work_fraction'],
                fault_observed=evidence['fault_observed'],fault_owned=bool(evidence['fault_owned_tasks']),fault_during_move=evidence['fault_during_motion'],
                fault_s=recovery[0]['onset_s'] if recovery else None,replacement_s=min(accepted) if accepted else None,
                productive_resume_s=min(productive) if productive else None,llm_calls=ev['diagnostic']['llm_calls'],
                productive_llm_decisions=sum(summary.get('llm_productive_decisions_by_agent',{}).values()),
                sampled_separation_violations=ev['primary']['safety']['sampled_separation_violations'],
                all_dispatched_actions_guarded=summary['all_dispatched_actions_guarded'],metric_issues=ev['evidence_issues'],
                error=outcome['error'])
            write_json(root/'analysis'/f"{entry['experiment_id']}.metrics.json",ev)
            plot_run(folder,root/'analysis'/f"{entry['experiment_id']}.png")
            before=size(folder)
            if compress:pack_evidence(folder)
            # A byte-level archive check is not enough: verify metric compatibility.
            after=metrics.evaluate_run(folder)
            if after!=ev:raise ValueError('Metrics changed after packing')
            row.update(raw_bytes=before,stored_bytes=size(folder),evidence_losslessly_packed=compress)
            rows.append(row)
        except Exception as exc:
            rows.append(dict(experiment_id=entry['experiment_id'],error=dict(type=type(exc).__name__,message=str(exc))))
        metrics.match_continuity(evaluations);write_json(root/'analysis/metrics.json',evaluations)
        manifest['completed_runs']=len(rows);manifest['stored_bytes']=size(root);write_json(root/'v2_manifest.json',manifest)
        print(json.dumps(rows[-1],indent=2),flush=True)
        if outcome['status']=='interrupted':manifest['status']='interrupted';break
        if rows[-1].get('error') or rows[-1].get('metric_issues'):
            manifest['status']='stopped_on_error';break
    else:manifest['status']='finished'
    if rows and all('completed_tasks' in r for r in rows):overview(rows,root/'analysis/overview.png')
    manifest['diagnostic_checks_passed']=len(rows)==manifest['planned_runs'] and all(
        not r.get('error') and not r.get('metric_issues') and r.get('mission_complete') is True and
        (not r.get('fault_requested') or (r.get('fault_observed') and r.get('fault_owned') and r.get('fault_during_move') and r.get('replacement_s') is not None and r.get('productive_resume_s') is not None)) for r in rows)
    manifest.update(finished_at_utc=datetime.now(timezone.utc).isoformat(),stored_bytes=size(root),successful_missions=sum(r.get('mission_complete') is True for r in rows))
    write_json(root/'v2_manifest.json',manifest)
    lines=['# Phase 17 resilience V2 diagnostic batch','',f"Stage: {stage}; {len(rows)}/{manifest['planned_runs']} runs; {manifest['successful_missions']} completed missions.",
        f"Stored size: {manifest['stored_bytes']/1024**2:.2f} MiB. Fault trigger: {fault_mode}. Telemetry: {telemetry}.",'',
        'This is a new declared scenario, not final calibration. Replay is not LLM inference. Successful state-triggered recovery does not validate full radio-loss recovery.','',
        '| Case | Completed tasks | Complete | Time (s) | Replacement accepted at (s) | Productive resume at (s) |','|---|---:|---|---:|---:|---:|']
    for r in rows:lines.append(f"| {r['experiment_id']} | {r.get('completed_tasks')} | {r.get('mission_complete')} | {r.get('time_s')} | {r.get('replacement_s')} | {r.get('productive_resume_s')} |")
    if (root/'analysis/overview.png').exists():lines+=['','![Overview](overview.png)']
    (root/'analysis/REPORT.md').write_text('\n'.join(lines)+'\n')
    return manifest
