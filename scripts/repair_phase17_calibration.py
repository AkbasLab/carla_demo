"""Reconcile the existing Phase 17 cohort without changing runtime rules or running missions.

Selection is the earliest finished attempt with complete evidence, regardless of outcome.
Earlier technical failures and later replicates are retained and indexed separately.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentic_uav.experiments.metrics import (CONTRACT_PATH, DEFINITION_PATH,
    evaluate_batch, evaluator_hash)
from agentic_uav.experiments.pilots import analyze

REQUIRED = ['manifest.json', 'events.jsonl'] + ['run/' + n for n in (
    'manifest.json', 'summary.json', 'flight_trace.json', 'messages.json',
    'protocol_events.json', 'guardian_audit.json', 'waypoint_arrivals.json',
    'executed_actions.json', 'scenario_events.json')]
ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def ref(path):
    return str(Path(path).resolve().relative_to(ROOT))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def select_attempt(candidates):
    eligible = [c for c in candidates if c['finished'] and not c['issues']]
    return min(eligible, key=lambda c: (c['started_at_utc'], c['path'])) if eligible else None


def registration_valid(manifest, registration):
    try:
        return (registration['evaluator_source_sha256'] == evaluator_hash()
            and registration['contract_sha256'] == sha(CONTRACT_PATH)
            and registration['definitions_sha256'] == sha(DEFINITION_PATH)
            and datetime.fromisoformat(registration['registered_at_utc'])
                <= datetime.fromisoformat(manifest['started_at_utc']))
    except (KeyError, TypeError, ValueError):
        return False


def compatible(manifest, entry, baseline):
    issues = []
    if manifest.get('provenance', {}).get('source_sha256') != baseline:
        issues.append('runtime_source_mismatch')
    if manifest.get('source_changed_during_run'):
        issues.append('runtime_source_changed_during_run')
    # Runner canonicalization converts numeric ints to floats. Dictionary equality
    # intentionally treats these as equal, while checking every original field.
    requested = manifest.get('requested_configuration', {})
    if requested != entry:
        issues.append('requested_configuration_mismatch')
    return issues


def candidate(folder, entry, baseline):
    manifest = read(folder / 'manifest.json')
    issues = compatible(manifest, entry, baseline)
    finished = manifest.get('run_completed') is True and manifest.get('error') is None
    missing = [name for name in REQUIRED if not (folder / name).is_file()]
    if finished:
        issues.extend('missing:' + name for name in missing)
        if not registration_valid(manifest, manifest.get('metric_registration', {})):
            issues.append('metric_registration_invalid')
    return dict(path=ref(folder), started_at_utc=manifest['started_at_utc'],
        status=manifest['status'], finished=finished, issues=issues,
        run_id=manifest.get('run_id'), manifest_sha256=sha(folder / 'manifest.json'),
        summary_sha256=sha(folder / 'run/summary.json') if (folder / 'run/summary.json').is_file() else None)


def preserve(root, path, label):
    if not path.exists():
        return
    target = root / 'attempts' / label / path.name
    if target.exists():
        raise ValueError('Archive already exists: ' + str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(target))


def repair(root, related, batch_size=2):
    root = root.resolve()
    if not 1 <= batch_size <= 4:
        raise ValueError('Use batches of one to four cases')
    if (root / 'consolidation.json').exists():
        raise ValueError('Already reconciled; preserve this snapshot and use a new reconciliation output for future attempts')
    entries = read(root / 'pilot_batch.json')['experiments']
    baseline = read(root / 'runs' / entries[0]['experiment_id'] / 'manifest.json')['provenance']['source_sha256']
    # Preserve stale derived records before replacing them. Raw manifests/logs are
    # never rewritten, including their original output paths and registrations.
    for path in [root/'analysis', root/'runs/metrics', root/'runs/batch_manifest.json']:
        preserve(root, path, 'before_consolidation')
    index = []; selected = {}; missing = []
    for entry in entries:
        identifier = entry['experiment_id']
        folders = {p.parent for parent in [root, *related]
            for p in parent.rglob('manifest.json')
            if p.parent.name == identifier and p.parent.parent.name not in ('run', 'configuration_files')}
        attempts = [candidate(folder, entry, baseline) for folder in sorted(folders)]
        chosen = select_attempt(attempts)
        canonical = root/'runs'/identifier
        if chosen:
            source = ROOT/chosen['path']
            # A nested case must be moved out before archiving/replacing its parent.
            if canonical.exists() and source != canonical:
                preserve(root, canonical, 'unselected_canonical')
                if not source.exists():
                    source = root/'attempts/unselected_canonical'/identifier/source.relative_to(canonical)
            if source != canonical:
                canonical.parent.mkdir(parents=True, exist_ok=True)
                if root in source.parents:
                    shutil.move(str(source), str(canonical))
                else:
                    # An externally stored repair remains intact. Git deduplicates
                    # identical blobs; the new case does not duplicate remote bytes.
                    shutil.copytree(source, canonical)
            selected[identifier] = canonical
        else:
            missing.append(entry)
        index.append(dict(experiment_id=identifier, attempts=attempts,
            selected_run_id=chosen['run_id'] if chosen else None,
            selected_original_path=chosen['path'] if chosen else None,
            selected_path=ref(canonical) if chosen else None,
            needs_execution=chosen is None))
    rows=[]
    for entry in entries:
        path=root/'runs'/entry['experiment_id']
        if path in selected.values() or (path/'manifest.json').exists():
            manifest=read(path/'manifest.json')
            rows.append(dict(experiment_id=entry['experiment_id'],status=manifest['status'],
                run_completed=manifest.get('run_completed',False),mission_complete=manifest.get('mission_complete'),
                error=manifest.get('error'),result_dir=ref(path)))
    batch=dict(schema_version=1,status='partial',planned_experiments=len(entries),runs=rows,
        finished_runs=sum(r['run_completed'] for r in rows),
        successful_missions=sum(r['mission_complete'] is True for r in rows),
        errors=sum(r['error'] is not None for r in rows),
        consolidation_note='Earliest complete compatible attempt; unsuccessful outcomes retained; no new missions executed.')
    write(root/'runs/batch_manifest.json',batch)
    evaluation=evaluate_batch(root/'runs')
    # Each retry has its own genuine pre-run registration. The legacy batch
    # evaluator expects one identical timestamp and therefore calls this merged
    # dataset retrospective. Explicitly audit each original registration instead;
    # never manufacture an earlier registration or edit raw manifests.
    registration_audit=[]
    for row in rows:
        identifier = row['experiment_id']
        path = root/'runs'/identifier
        manifest=read(path/'manifest.json')
        registration_audit.append(dict(experiment_id=identifier,
            registration=manifest['metric_registration'],
            valid=registration_valid(manifest,manifest['metric_registration'])))
    evaluation.update(prespecified=all(r['valid'] for r in registration_audit),
        evaluation_type='recomputed_from_individual_pre_run_registrations',
        registration_audit='../../consolidation.json')
    write(root/'runs/metrics/evaluation_summary.json',evaluation)
    report_path=root/'runs/metrics/REPORT.md'
    report_path.write_text(report_path.read_text().replace('Type: retrospective.',
        'Type: recomputed from individually verified pre-run registrations.'))
    batch['evaluation']=evaluation
    write(root/'runs/batch_manifest.json',batch)
    generated=root/'pending_batches';generated.mkdir(exist_ok=True)
    batches=[]
    for number,start in enumerate(range(0,len(missing),batch_size),1):
        path=generated/f'batch_{number:02d}.json'
        group=missing[start:start+batch_size]
        write(path,dict(schema_version=1,experiments=group))
        batches.append(dict(config=ref(path),experiment_ids=[e['experiment_id'] for e in group],
            output_dir=f'results/phase17/main_calibration_pending_run1/batch_{number:02d}'))
    record=dict(schema_version=1,source_commit='7b5d3dad99f820cf9606f89ab8a9ccc2e1a7bb27',
        selection_rule='earliest finished compatible attempt with complete required evidence, irrespective of mission outcome',
        expected_cases=len(entries),selected_finished_cases=len(selected),missing_cases=len(missing),
        attempts=index,metric_registration_audit=registration_audit,pending_batches=batches,
        notes=['Original runtime manifests and raw logs are immutable.',
               'Historical warmup failures restored from commit 886c2213952b074d419d66ec636a57b78ed967c9.',
               'Interrupted and never-started cases require execution; valid mission timeouts do not.',
               'No remaining mission has been executed by this script.'])
    write(root/'consolidation.json',record)
    report=analyze(root,plots=False)
    report_md = root/'analysis/REPORT.md'
    report_md.write_text(report_md.read_text().rstrip() + '\n')
    # Make missing cohort members explicit in the summary without fabricating
    # runtime manifests or changing the plan/metric definitions.
    record['freeze_blockers']=report['freeze_blockers']
    write(root/'consolidation.json',record)
    return dict(selected=len(selected),missing=len(missing),pending_batches=len(batches),
        evaluation=evaluation,freeze_blockers=report['freeze_blockers'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot-dir',required=True,type=Path)
    parser.add_argument('--related-dir',action='append',default=[],type=Path)
    parser.add_argument('--batch-size',type=int,default=2)
    args=parser.parse_args()
    print(json.dumps(repair(args.pilot_dir,args.related_dir,args.batch_size),indent=2))


if __name__=='__main__':
    main()
