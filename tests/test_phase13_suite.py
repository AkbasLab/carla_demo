import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agentic_uav.experiments.suite import build_plan,archive_traces,read_trace,execute_case,summarize,run_suite
from agentic_uav.policy.structured import OllamaProvider,ModelIdentityError


class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'suite'
        self.base=dict(ticks=120,dt=.1,bid_window=.5,lease_seconds=10,beacon_interval_s=.2,decision_interval=.2)

    def test_complete_plan_has_one_folder_per_scenario_and_paired_controls(self):
        p=build_plan(self.base,[42],self.root)
        self.assertEqual(len(p['cases']),41)
        self.assertEqual(len({c['case_id'] for c in p['cases']}),41)
        ids={c['case_id'] for c in p['cases']}
        self.assertTrue(all(c['control_id'] is None or c['control_id'] in ids for c in p['cases']))
        self.assertEqual(sum(c['group']=='baselines' for c in p['cases']),16)
        self.assertEqual(sum(c['group']=='drone1_failure' for c in p['cases']),16)
        self.assertEqual(len(build_plan(self.base,[42,43],self.root)['cases']),82)

    def test_validation_is_explicitly_replay_and_pinned_is_serial_wall(self):
        base=dict(self.base,policy=dict(provider='ollama',model='test:pinned',model_digest='a'*64))
        p=build_plan(base,[42],self.root)
        self.assertTrue(all(c['configuration']['policy']['provider']=='replay' and c['configuration']['clock_mode']=='simulated' for c in p['cases']))
        p=build_plan(base,[42],self.root,'pinned')
        self.assertEqual(len(p['cases']),40)
        self.assertTrue(all(c['configuration']['clock_mode']=='wall' for c in p['cases']))
        with self.assertRaises(ValueError):run_suite(base,[42],self.root,'pinned',workers=2)

    def test_full_trace_archive_roundtrips_json_and_jsonl(self):
        self.root.mkdir();(self.root/'messages.json').write_text('[{"a": 1}]')
        (self.root/'summary.json').write_text('{"keep": true}')
        (self.root/'Drone1').mkdir();(self.root/'Drone1'/'responses.jsonl').write_text('{"raw": "ok"}\n')
        archive_traces(self.root)
        self.assertFalse((self.root/'messages.json').exists())
        self.assertTrue((self.root/'summary.json').exists())
        self.assertEqual(read_trace(self.root,'messages.json'),[{'a':1}])
        self.assertEqual(read_trace(self.root,'Drone1/responses.jsonl'),[{'raw':'ok'}])
        self.assertEqual(len(json.loads((self.root/'trace_index.json').read_text())['files_sha256']),2)

    def test_incomplete_mission_is_not_a_runtime_error_and_time_is_censored(self):
        p=build_plan(dict(self.base,ticks=40),[42],self.root)
        c=next(c for c in p['cases'] if c['group']=='baselines' and c['condition']=='moderate' and c['architecture']=='C')
        row=execute_case((c,True))
        self.assertEqual(row['status'],'completed');self.assertFalse(row['mission_complete'])
        self.assertTrue(row['time_censored']);self.assertIsNone(row['completion_time_s'])
        self.assertTrue(row['validation_passed']);self.assertFalse(row['llm_inference'])
        self.assertTrue((Path(c['configuration']['output_dir'])/'traces.zip').exists())

    def test_model_unavailable_creates_blocked_folders_without_fake_summaries(self):
        base=dict(self.base,policy=dict(provider='ollama',model='test:pinned',model_digest='a'*64))
        with patch.object(OllamaProvider,'verify',side_effect=ModelIdentityError('unavailable')),patch('agentic_uav.experiments.suite.run_comparison') as runner:
            result=run_suite(base,[42],self.root,'pinned')
        runner.assert_not_called()
        self.assertEqual(result['statuses']['blocked_model_unavailable'],40)
        self.assertEqual(result['actual_llm_runs'],0)
        self.assertIsNone(result['reproducibility_checks_passed'])
        self.assertEqual(len(list(self.root.rglob('test_definition.json'))),40)
        self.assertFalse(list(self.root.rglob('summary.json')))

    def test_replay_and_matching_are_checked_from_actual_saved_packets(self):
        p=build_plan(self.base,[42],self.root)
        a=next(c for c in p['cases'] if c['group']=='baselines' and c['condition']=='moderate' and c['architecture']=='C')
        b=next(c for c in p['cases'] if c['group']=='reproducibility')
        rows=[execute_case((c,True)) for c in (a,b)]
        p['cases']=[a,b]
        result=summarize(self.root,p,rows)
        self.assertTrue(result['reproducibility_checks_passed']);self.assertEqual(result['mismatched_input_checks'],0)
        self.assertTrue((self.root/'metrics.csv').exists())

    def test_resume_rejects_different_source_or_inputs(self):
        p=build_plan(self.base,[42],self.root);self.root.mkdir()
        p['source_hashes']['edited.py']='changed'
        (self.root/'suite_manifest.json').write_text(json.dumps(p))
        with self.assertRaises(ValueError):run_suite(self.base,[42],self.root,resume=True)


if __name__=='__main__':unittest.main()
