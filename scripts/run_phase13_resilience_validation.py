"""Offline engineering checks for v2; D uses replay, never real-model evidence."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agentic_uav.experiments.suite import build_plan, execute_case, summarize, read_trace


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='configs/phase13/comparison.resilient.pinned.json')
    p.add_argument('--seeds',type=int,nargs='+',default=[42,43,44])
    p.add_argument('--output-dir',default='results/phase13/resilience_v2_validation')
    a=p.parse_args();root=Path(a.output_dir)
    if root.exists() and any(root.iterdir()):p.error('Use an empty validation folder')
    base=json.loads(Path(a.config).read_text())
    if not base.get('resilience',{}).get('enabled'):p.error('This validator requires resilience v2')
    plan=build_plan(base,a.seeds,root,'validation')
    plan['cases']=[c for c in plan['cases'] if c['group']=='baselines' and
                   c['condition'] in ('moderate','severe') and c['architecture'] in 'ACD']
    plan['limitations'].append('Targeted engineering subset; D uses replay, not Ollama')
    root.mkdir(parents=True,exist_ok=True)
    (root/'suite_manifest.json').write_text(json.dumps(plan,indent=2)+'\n')
    fixture=Path(plan['role_fixture_path']);fixture.parent.mkdir(parents=True,exist_ok=True)
    fixture.write_text(json.dumps(plan['role_fixture'],indent=2)+'\n')
    rows=[];evidence=[]
    for case in plan['cases']:
        row=execute_case((case,True));rows.append(row)
        print(f"{len(rows)}/{len(plan['cases'])} {case['case_id']}: {row['completed_tasks']}/4",flush=True)
        if row['status']=='completed':
            run=Path(row['run_dir'])
            evidence.append(dict(case_id=case['case_id'],summary=read_trace(run,'summary.json'),
                waypoint_arrivals=read_trace(run,'waypoint_arrivals.json'),
                validation=json.loads((run.parent/'validation.json').read_text()),
                trace_index=json.loads((run/'trace_index.json').read_text())))
        (root/'validation_evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    result=summarize(root,plan,rows);print(json.dumps(result,indent=2))
    if result['runtime_errors'] or result['validation_failures'] or result['mismatched_input_checks']:raise SystemExit(1)


if __name__=='__main__':main()
