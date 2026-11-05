"""Duration sensitivity study; preserve architectures, faults, and safety rules."""
from collections import Counter
import copy
import csv
import hashlib
import json
import math
from pathlib import Path
from .suite import build_plan, read_trace, run_suite
from .comparison import configuration


def duration_plan(base, seeds, root, durations, profile):
    if not durations or len(set(durations)) != len(durations):
        raise ValueError('Provide distinct positive duration budgets')
    base = configuration(base)
    plans = []
    for duration in durations:
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
            raise ValueError('Invalid duration')
        dt = base.get('dt', .1)
        ticks = duration / dt
        if not math.isclose(ticks, round(ticks), abs_tol=1e-7):
            raise ValueError('Duration must be a multiple of dt')
        config = copy.deepcopy(base)
        config['ticks'] = round(ticks)
        folder = Path(root) / f'budget_{duration:g}s'
        plans.append(dict(budget_s=duration, folder=str(folder),
                          plan=build_plan(config, seeds, folder, profile)))
    return plans


def diagnostic(row):
    """Observed evidence flags, not inferred root causes or fabricated successes."""
    out = dict(row)
    out.update(last_waypoint_time_s=None, seconds_since_last_waypoint=None,
               observed_guard_reasons={}, independent_failure_without_reassignment=False)
    if row['status'] != 'completed':
        return out
    run = Path(row['run_dir'])
    arrivals = read_trace(run, 'waypoint_arrivals.json')
    last = max((e['time_s'] for e in arrivals), default=None)
    audit = read_trace(run, 'guardian_audit.json')
    out.update(last_waypoint_time_s=last,
               seconds_since_last_waypoint=row['observation_end_s'] - last if last is not None else None,
               observed_guard_reasons=dict(Counter(r for e in audit for r in e.get('reasons', []))),
               independent_failure_without_reassignment=(row['architecture'] == 'B' and
                   row['failure_injected'] is True and row['mission_complete'] is False))
    return out


def summarize_followup(root, plans):
    root = Path(root)
    rows = []
    for entry in plans:
        source = Path(entry['folder']) / 'metrics.json'
        if not source.exists():
            continue
        for row in json.loads(source.read_text()):
            rows.append(dict(budget_s=entry['budget_s'], **diagnostic(row)))
    (root / 'duration_metrics.json').write_text(json.dumps(rows, indent=2) + '\n')
    compact = [{k: v for k, v in r.items() if k != 'observed_guard_reasons'} for r in rows]
    if compact:
        with (root / 'duration_metrics.csv').open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(compact[0]), lineterminator='\n')
            writer.writeheader(); writer.writerows(compact)
    groups = {}
    for row in rows:
        groups.setdefault(row['case_id'], []).append(row)
    comparisons = []
    for case_id, members in sorted(groups.items()):
        members.sort(key=lambda r: r['budget_s'])
        eligible = [r for r in members if r['status'] == 'completed']
        smallest = eligible[0] if eligible else None
        comparisons.append(dict(case_id=case_id, observed_budgets=[r['budget_s'] for r in eligible],
            first_successful_budget_s=next((r['budget_s'] for r in eligible if r['mission_execution_success']), None),
            completed_after_shorter_incomplete=bool(smallest and not smallest['mission_execution_success'] and
                any(r['mission_execution_success'] for r in eligible[1:])),
            all_observed_budgets_incomplete=bool(eligible) and all(not r['mission_execution_success'] for r in eligible)))
    result = dict(completed_runs=sum(r['status'] == 'completed' for r in rows),
        successful_missions=sum(r['mission_execution_success'] is True for r in rows),
        completed_after_shorter_incomplete=sum(c['completed_after_shorter_incomplete'] for c in comparisons),
        cases=comparisons,
        caveats=['New independent runs at each budget, not continuation or identical LLM-output replays',
                 'Budget changes horizon-dependent leases/TTL/context; this is budget sensitivity, not pure CPU timing',
                 'B has no task reassignment; a permanently lost worker can leave its fixed task incomplete',
                 'More time cannot guarantee resolution of safety or protocol stalls; no safety rules are relaxed'])
    (root / 'duration_summary.json').write_text(json.dumps(result, indent=2) + '\n')
    lines = ['# Phase 13 duration follow-up', '',
        'All architectures and planned cases are rerun at each common budget; the original pilot is preserved.',
        'Completion is measured from the existing guarded mission criterion, never inferred from elapsed time.', '',
        '| Budget (s) | Finished tests | Successful missions | Incomplete missions | Runtime errors |',
        '|---|---:|---:|---:|---:|']
    for entry in plans:
        members = [r for r in rows if r['budget_s'] == entry['budget_s']]
        lines.append(f"| {entry['budget_s']:g} | {sum(r['status']=='completed' for r in members)} | "
            f"{sum(r['mission_execution_success'] is True for r in members)} | "
            f"{sum(r['mission_complete'] is False for r in members)} | {sum(r['status']=='error' for r in members)} |")
    lines += ['', *result['caveats'], '',
        'duration_metrics.json includes guard reason counts, arrival times and observed failure flags.',
        'Cross-budget completion differences are descriptive; use repeated seeds before statistical claims.']
    (root / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    return result


def run_followup(base, seeds, root, durations=(300, 600, 1200), profile='pinned',
                 workers=1, resume=False, plan_only=False):
    if type(workers) is not int or workers < 1:
        raise ValueError('Workers must be a positive integer')
    plans = duration_plan(base, seeds, root, durations, profile)
    if profile == 'pinned' and workers != 1:
        raise ValueError('Pinned runs require one worker')
    root = Path(root)
    manifest = dict(study='phase13_duration_sensitivity', profile=profile,
        durations_s=list(durations), seeds=seeds, plans=plans,
        followup_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    target = root / 'followup_manifest.json'
    if target.exists():
        if not resume or json.loads(target.read_text()) != manifest:
            raise ValueError('Use a new folder or resume with identical inputs and source')
    elif root.exists() and any(root.iterdir()):
        raise ValueError('Use an empty output folder')
    root.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2) + '\n')
    if plan_only:
        return dict(plan_only=True, planned_runs=sum(len(p['plan']['cases']) for p in plans),
                    manifest=str(target))
    suites = []
    for entry in plans:
        suites.append(run_suite(entry['plan']['base_configuration'], seeds, entry['folder'],
                                profile, workers, resume=resume))
        summarize_followup(root, plans)  # Preserve completed budgets if a later run is interrupted.
        if suites[-1]['statuses'].get('blocked_model_unavailable'):
            break  # Fail visibly; do not burn through other budgets or substitute replay.
    result = summarize_followup(root, plans)
    result['suite_checks_passed'] = all(not s['runtime_errors'] and not s['validation_failures'] and
        not s['mismatched_input_checks'] and not s['statuses'].get('blocked_model_unavailable') and
        s['reproducibility_checks_passed'] is not False for s in suites)
    (root / 'duration_summary.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
