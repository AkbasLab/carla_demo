"""Compact sweeps must preserve the original mission outcome."""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_phase9_roles import run
from run_phase10_sweep import aggregate
from agentic_uav.comm.degraded import preset


class SweepTests(unittest.TestCase):
    def test_compact_summary_matches_detailed(self):
        with tempfile.TemporaryDirectory() as tmp,redirect_stdout(io.StringIO()):
            detailed=run(ticks=100,output_dir=Path(tmp)/'full',fail_agent=None,network_config=preset('moderate'),seed=7)
            compact=run(ticks=100,output_dir=Path(tmp)/'compact',fail_agent=None,network_config=preset('moderate'),seed=7,record_details=False)
            self.assertEqual(detailed,compact)
            self.assertEqual([p.name for p in (Path(tmp)/'compact').iterdir()],['summary.json'])

    def test_censored_runs_excluded_from_completion_time(self):
        rows=[dict(condition='moderate',mission_complete=ok,time_s=t,tasks_completed=n,lease_expirations=0,duplicate_task_completions=0)
              for ok,t,n in [(True,20,4),(False,119.9,3)]]
        s=aggregate(rows)['moderate']
        self.assertEqual(s['success_rate'],.5)
        self.assertEqual(s['completion_time_successful_mean_s'],20)
        self.assertEqual(s['mean_tasks_completed'],3.5)
        self.assertEqual(s['runs_with_all_four_tasks_completed'],1)
        self.assertLess(s['success_rate_wilson_95'][0],.5)
        self.assertGreater(s['success_rate_wilson_95'][1],.5)
