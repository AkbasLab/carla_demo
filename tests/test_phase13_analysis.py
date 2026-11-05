import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from agentic_uav.experiments.comparison import run_comparison

spec=importlib.util.spec_from_file_location('phase13_analysis',Path(__file__).resolve().parents[1]/'scripts/analyze_phase13_suite.py')
analysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(analysis)


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.run_dir=self.root/'baselines/nominal/A/control/seed_42/run'
        run_comparison(dict(architecture='A',ticks=100,dt=.1,bid_window=.5,lease_seconds=10,decision_interval=.2,beacon_interval_s=.2,output_dir=str(self.run_dir)))

    def audit(self):return analysis.audit_case(self.root,self.run_dir/'summary.json')

    def test_success_requires_independent_arrivals_and_guarded_effects(self):
        row,detail,_,_=self.audit()
        self.assertTrue(row['audit_passed']);self.assertEqual(row['unique_waypoints'],8)
        self.assertTrue(row['mission_execution_success']);self.assertIsNotNone(row['completion_time_s'])

    def test_missing_arrival_is_not_hidden_by_success_summary(self):
        path=self.run_dir/'waypoint_arrivals.json';points=json.loads(path.read_text());path.write_text(json.dumps(points[:-1]))
        row,detail,_,_=self.audit()
        self.assertFalse(row['audit_passed']);self.assertFalse(detail['checks']['completed_tasks_have_arrival_evidence'])

    def test_missing_guard_record_is_not_hidden_by_declared_coverage(self):
        path=self.run_dir/'guardian_audit.json';records=json.loads(path.read_text());path.write_text(json.dumps(records[1:]))
        row,detail,_,_=self.audit()
        self.assertFalse(row['guarded_effects_verified']);self.assertFalse(row['audit_passed'])

    def test_requested_but_unobserved_failure_is_not_evaluable(self):
        path=self.run_dir/'manifest.json';m=json.loads(path.read_text());m['effective_configuration']['scenario']['fail_agent']='Drone1'
        path.write_text(json.dumps(m));row,_,_,_=self.audit()
        self.assertTrue(row['failure_requested']);self.assertFalse(row['failure_injected']);self.assertFalse(row['failure_case_evaluable'])

    def test_incomplete_observation_does_not_become_successful_completion_time(self):
        other=self.root/'short'
        run_comparison(dict(architecture='C',ticks=10,dt=.1,output_dir=str(other)))
        row,_,_,_=analysis.audit_case(self.root,other/'summary.json')
        self.assertFalse(row['mission_complete']);self.assertIsNone(row['completion_time_s']);self.assertGreater(row['observation_end_s'],0)

    def test_replay_suite_cannot_be_labelled_as_pinned_model_evidence(self):
        (self.root/'suite_manifest.json').write_text(json.dumps(dict(profile='validation',cases=[])))
        with self.assertRaises(ValueError):analysis.analyze(self.root,self.root/'figures')

    def test_completed_retry_is_selected_without_counting_original_attempt(self):
        import shutil
        retry=self.run_dir.with_name('run_attempt_002');shutil.copytree(self.run_dir,retry)
        (self.run_dir.parent/'metrics.json').write_text(json.dumps(dict(run_dir='/opt/carla_demo/'+str(retry.relative_to(self.root)))))
        self.assertEqual(analysis.selected_summaries(self.root),[retry/'summary.json'])
        row,_,_,_=analysis.audit_case(self.root,retry/'summary.json')
        self.assertEqual(row['case_id'],'baselines/nominal/A/control/seed_42')


if __name__=='__main__':unittest.main()
