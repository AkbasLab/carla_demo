import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agentic_uav.experiments.followup import duration_plan, diagnostic, run_followup, summarize_followup
from agentic_uav.experiments.suite import execute_case


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'study'
        self.base = dict(policy=dict(provider='ollama', model='test:pinned', model_digest='a'*64))

    def test_full_matrix_at_each_budget_keeps_safety_network_and_failure_inputs(self):
        plans = duration_plan(self.base, [42], self.root, [300, 600, 1200], 'pinned')
        self.assertEqual([len(p['plan']['cases']) for p in plans], [40, 40, 40])
        for cases in zip(*(p['plan']['cases'] for p in plans)):
            self.assertEqual(len({c['case_id'] for c in cases}), 1)
            configs = [copy.deepcopy(c['configuration']) for c in cases]
            for c in configs:
                for key in ('ticks', 'output_dir', 'mission_config'): c.pop(key)
            self.assertEqual(configs[0], configs[1]); self.assertEqual(configs[1], configs[2])
        self.assertEqual(plans[-1]['plan']['cases'][0]['configuration']['ticks'], 12000)

    def test_reject_invalid_or_fractional_tick_budget(self):
        for budgets in ([300, 300], [0], [-1], [float('nan')], [.15]):
            with self.assertRaises(ValueError): duration_plan(self.base, [42], self.root, budgets, 'pinned')

    def test_plan_only_does_not_contact_model_or_run_experiments(self):
        with patch('agentic_uav.experiments.followup.run_suite') as run:
            result = run_followup(self.base, [42], self.root, plan_only=True)
        run.assert_not_called(); self.assertEqual(result['planned_runs'], 120)
        self.assertTrue((self.root / 'followup_manifest.json').exists())
        with self.assertRaises(ValueError): run_followup(self.base, [42], self.root, plan_only=True)
        with self.assertRaises(ValueError): run_followup(self.base, [42], self.root, [600], resume=True, plan_only=True)

    def test_blocked_model_stops_without_fake_later_budgets(self):
        blocked = dict(runtime_errors=0, validation_failures=0, mismatched_input_checks=0,
            statuses={'blocked_model_unavailable': 40}, reproducibility_checks_passed=None)
        with patch('agentic_uav.experiments.followup.run_suite', return_value=blocked) as run:
            result = run_followup(self.base, [42], self.root)
        self.assertEqual(run.call_count, 1); self.assertFalse(result['suite_checks_passed'])
        self.assertEqual(result['completed_runs'], 0)

    def test_real_short_and_long_runs_remain_censored_until_waypoints_complete(self):
        plans = duration_plan(dict(bid_window=.5, lease_seconds=10, beacon_interval_s=.2),
            [42], self.root, [1, 12], 'validation')
        for entry in plans:
            case = next(c for c in entry['plan']['cases'] if c['case_id']=='baselines/nominal/A/control/seed_42')
            row = execute_case((case, True))
            (Path(entry['folder']) / 'metrics.json').write_text(json.dumps([row]))
        result = summarize_followup(self.root, plans)
        self.assertEqual(result['completed_after_shorter_incomplete'], 1)
        rows = json.loads((self.root / 'duration_metrics.json').read_text())
        self.assertIsNone(rows[0]['completion_time_s']); self.assertIsNone(rows[0]['last_waypoint_time_s'])
        self.assertTrue(rows[1]['mission_execution_success']); self.assertGreater(rows[1]['last_waypoint_time_s'], 0)

    def test_observed_failure_guard_reasons_are_reported_not_removed(self):
        plans = duration_plan(dict(bid_window=.5, lease_seconds=10, beacon_interval_s=.2),
            [42], self.root, [12], 'validation')
        case = next(c for c in plans[0]['plan']['cases'] if c['group']=='drone1_failure' and
                    c['architecture']=='B' and c['condition']=='nominal')
        case['configuration']['scenario']['fail_at_s'] = 1
        row = execute_case((case, True)); detail = diagnostic(row)
        self.assertTrue(row['failure_injected']); self.assertFalse(row['mission_complete'])
        self.assertTrue(detail['independent_failure_without_reassignment'])
        self.assertGreater(detail['observed_guard_reasons']['stale_or_future_peer_belief'], 0)

    def test_pinned_parallel_workers_rejected(self):
        with self.assertRaises(ValueError): run_followup(self.base, [42], self.root, workers=2, plan_only=True)


if __name__ == '__main__': unittest.main()
