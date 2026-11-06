"""Run simulator-free tests and retain per-test results plus the Phase 16 coverage map."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import io
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


class RecordedResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.records=[]

    def record(self,test,status,detail=None):
        self.records.append(dict(test_id=test.id(),status=status,detail=detail))

    def addSuccess(self,test):
        super().addSuccess(test);self.record(test,'passed')

    def addFailure(self,test,err):
        super().addFailure(test,err);self.record(test,'failed',self._exc_info_to_string(err,test))

    def addError(self,test,err):
        super().addError(test,err);self.record(test,'error',self._exc_info_to_string(err,test))

    def addSkip(self,test,reason):
        super().addSkip(test,reason);self.record(test,'skipped',reason)

    def addSubTest(self,test,subtest,err):
        super().addSubTest(test,subtest,err)
        if err is not None:
            self.record(test,'failed',self._exc_info_to_string(err,test))

    def addExpectedFailure(self,test,err):
        super().addExpectedFailure(test,err);self.record(test,'expected_failure')

    def addUnexpectedSuccess(self,test):
        super().addUnexpectedSuccess(test);self.record(test,'unexpected_success')


def flatten(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def run(output_dir,layer='all'):
    root=Path(__file__).resolve().parents[1]
    if Path.cwd()!=root:
        raise ValueError('Run from the repository root')
    out=Path(output_dir)
    if out.exists() and any(out.iterdir()):
        raise ValueError('Use a new verification output directory')
    coverage=json.loads((root/'configs/phase16/coverage.json').read_text())
    tests=list(flatten(unittest.defaultTestLoader.discover('tests',pattern='test_*.py')))
    known={t.id() for t in tests}
    requested={t for group in coverage['layers'].values() for topics in group.values() for t in topics}
    missing=sorted(requested-known)
    if missing:
        raise ValueError('Coverage map references missing tests: '+str(missing))
    if layer!='all':
        selected={t for ids in coverage['layers'][layer].values() for t in ids}
        tests=[t for t in tests if t.id() in selected]
    out.mkdir(parents=True,exist_ok=True)
    source_paths=sorted([*root.glob('agentic_uav/**/*.py'), *root.glob('scripts/*.py'), *root.glob('tests/*.py'), root/'configs/phase16/coverage.json'])
    hashes=lambda: {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    before=hashes()
    started=datetime.now(timezone.utc).isoformat()
    log=io.StringIO()
    with redirect_stdout(log), redirect_stderr(log):
        result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=RecordedResult).run(unittest.TestSuite(tests))
    (out/'unittest.log').write_text(log.getvalue())
    statuses={r['test_id']:r['status'] for r in result.records}
    mapped={name:{topic:{t:statuses.get(t,'not_run') for t in ids} for topic,ids in topics.items()}
            for name,topics in coverage['layers'].items()}
    git=subprocess.run(['git','rev-parse','HEAD'],capture_output=True,text=True)
    summary=dict(mode='phase16_simulator_free_verification',layer=layer,started_at_utc=started,
        finished_at_utc=datetime.now(timezone.utc).isoformat(),python=platform.python_version(),
        git_commit=git.stdout.strip() if git.returncode==0 else None,
        tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        passed=result.wasSuccessful() and before==hashes(),source_sha256=before,source_changed_during_run=before!=hashes(),tests=result.records,coverage=mapped,
        live_airsim_regressions={c:'not_run' for c in coverage['manual_airsim_cases']},
        limitations=['Simulator-free success does not establish AirSim flight or physical safety',
                     'Fixed configured targets, not a randomized target placer',
                     'Actual-model residual variability is outside deterministic replay tests'])
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('tests','coverage')},indent=2))
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',required=True)
    p.add_argument('--layer',choices=['all','unit','integration','determinism'],default='all')
    args=p.parse_args()
    raise SystemExit(0 if run(args.output_dir,args.layer)['passed'] else 1)
