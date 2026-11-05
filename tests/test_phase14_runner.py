import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agentic_uav.experiments import comparison
from agentic_uav.experiments.runner import run_batch
from agentic_uav.experiments.event_logging import EVENT_TYPES, EventLog, instrument
from agentic_uav.policy.structured import OllamaProvider, ModelIdentityError
from agentic_uav.comm.protocol import AgentMessage, MessageType as MT
from agentic_uav.comm.degraded import NetworkConfig


class Phase14Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.entry=dict(experiment_id='first',architecture='deterministic_decentralized',scenario='four_sector_search',
            team_size=4,network_profile='nominal',failure_profile='none',random_seed=42,planner='deterministic',
            settings=dict(ticks=200,dt=.1,clock_mode='simulated',bid_window=.5,lease_seconds=10,beacon_interval_s=.2))
    def run_cases(self,entries,name='batch'):
        source=self.root/(name+'.json');source.write_text(json.dumps(dict(schema_version=1,experiments=entries)))
        result=run_batch(source,self.root/name)
        return result,self.root/name
    def read(self,path):return json.loads(path.read_text())
    def events(self,folder):return [json.loads(s) for s in (folder/'events.jsonl').read_text().splitlines()]

    def test_manifest_and_streamed_events_cover_actual_completed_mission(self):
        result,root=self.run_cases([self.entry]);folder=root/'first';m=self.read(folder/'manifest.json');events=self.events(folder)
        self.assertEqual(result['successful_missions'],1)
        self.assertTrue(m['run_completed']);self.assertTrue(m['mission_complete'])
        self.assertIsNotNone(m['provenance']['git_commit_sha']);self.assertIn('python',m['provenance']['software_versions'])
        self.assertTrue(m['started_at_utc']<=m['finished_at_utc']);self.assertTrue(m['configuration_files'])
        self.assertFalse(m['source_changed_during_run']);self.assertFalse(m['model_identity_verified'])
        kinds={e['event_type'] for e in events}
        self.assertTrue({'MISSION_STARTED','MISSION_COMPLETED','OBSERVATION_RECEIVED','BELIEF_UPDATED',
            'MESSAGE_SENT','MESSAGE_RECEIVED','TASK_ANNOUNCED','TASK_BID','TASK_ASSIGNED',
            'DECISION_PROPOSED','SKILL_STARTED','SKILL_COMPLETED'}<=kinds)
        self.assertNotIn('LLM_CALLED',kinds);self.assertEqual(m['event_coverage']['LLM_CALLED'],0)
        self.assertEqual(set(m['event_coverage']),set(EVENT_TYPES))
        self.assertEqual(len({e['event_id'] for e in events}),len(events))
        self.assertTrue(all(e['experiment_id']=='first' and e['wall_time_utc'] for e in events))
        self.assertTrue(any('envelope' in e['data'] for e in events if e['event_type']=='MESSAGE_SENT'))

    def test_incomplete_fault_run_is_preserved_without_false_mission_completed(self):
        entry=copy.deepcopy(self.entry);entry.update(failure_profile='drone_failure_midmission')
        entry['settings']['scenario']=dict(fail_agent='Drone1',fail_at_s=1)
        result,root=self.run_cases([entry]);folder=root/'first';m=self.read(folder/'manifest.json')
        self.assertTrue(m['run_completed']);self.assertFalse(m['mission_complete']);self.assertEqual(m['status'],'incomplete')
        self.assertTrue(m['failure_observed']);kinds={e['event_type'] for e in self.events(folder)}
        self.assertIn('FAULT_INJECTED',kinds);self.assertNotIn('MISSION_COMPLETED',kinds)
        self.assertIn('GUARDIAN_INTERVENED',kinds);self.assertTrue((folder/'run/summary.json').exists())

    def test_bad_configuration_keeps_manifest_error_and_continues_batch(self):
        bad=copy.deepcopy(self.entry);bad['team_size']=3
        good=copy.deepcopy(self.entry);good['experiment_id']='second'
        result,root=self.run_cases([bad,good])
        self.assertEqual(result['errors'],1);self.assertEqual(result['successful_missions'],1)
        m=self.read(root/'first/manifest.json');self.assertEqual(m['status'],'error');self.assertFalse(m['run_completed'])
        self.assertTrue(m['finished_at_utc']);self.assertTrue((root/'first/error.json').exists())
        self.assertNotIn('MISSION_COMPLETED',{e['event_type'] for e in self.events(root/'first')})
        self.assertTrue((root/'second/run/summary.json').exists())

    def test_model_verification_failure_precedes_flight_and_still_has_manifest(self):
        entry=copy.deepcopy(self.entry);entry.update(architecture='agentic_decentralized',planner='test:pinned')
        entry['settings'].update(clock_mode='wall',policy=dict(provider='ollama',model='test:pinned',model_digest='a'*64))
        with patch.object(OllamaProvider,'verify',side_effect=ModelIdentityError('model_digest_mismatch')):
            result,root=self.run_cases([entry])
        m=self.read(root/'first/manifest.json');self.assertEqual(m['status'],'error');self.assertFalse(m['model_identity_verified'])
        self.assertTrue((root/'first/run/preflight_error.json').exists())
        self.assertNotIn('MISSION_STARTED',{e['event_type'] for e in self.events(root/'first')})

    def test_runtime_crash_preserves_partial_events_and_stops_no_later_cases(self):
        with patch.object(comparison.MockFlight,'advance',side_effect=RuntimeError('injected execution crash')):
            result,root=self.run_cases([self.entry])
        m=self.read(root/'first/manifest.json');self.assertEqual(m['status'],'error')
        self.assertEqual(m['error']['type'],'RuntimeError');self.assertTrue((root/'first/error.json').exists())
        self.assertIn('MISSION_STARTED',{e['event_type'] for e in self.events(root/'first')})
        self.assertTrue((root/'first/run/summary.json').exists())

    def test_instrumentation_restores_classes_even_when_context_raises(self):
        original=comparison.MockFlight;log=EventLog(self.root/'events.jsonl','test','test')
        with self.assertRaises(RuntimeError):
            with instrument(comparison,log):
                self.assertIsNot(comparison.MockFlight,original);raise RuntimeError('stop')
        self.assertIs(comparison.MockFlight,original)

    def test_existing_results_and_invalid_folder_names_are_never_overwritten(self):
        source=self.root/'config.json';source.write_text(json.dumps(dict(schema_version=1,experiments=[self.entry])))
        root=self.root/'existing';root.mkdir();(root/'keep.txt').write_text('keep')
        with self.assertRaises(ValueError):run_batch(source,root)
        self.assertEqual((root/'keep.txt').read_text(),'keep')
        bad=copy.deepcopy(self.entry);bad['experiment_id']='../escape'
        source.write_text(json.dumps(dict(schema_version=1,experiments=[bad])))
        with self.assertRaises(ValueError):run_batch(source,self.root/'unsafe')

    def test_wrapped_and_direct_runner_agree_on_deterministic_outcome(self):
        result,root=self.run_cases([self.entry]);manifest=self.read(root/'first/manifest.json')
        c=copy.deepcopy(manifest['effective_configuration']);c['output_dir']=str(self.root/'direct')
        direct=comparison.run_comparison(c);wrapped=self.read(root/'first/run/summary.json')
        for key in ('mission_complete','time_s','completed_task_ids','duplicate_task_completions','all_dispatched_actions_guarded'):
            self.assertEqual(direct[key],wrapped[key])

    def test_drops_and_delivered_target_reports_have_distinct_provenance(self):
        log=EventLog(self.root/'network.jsonl','test','test');clock=[0.]
        with instrument(comparison,log):
            lost=comparison.DegradedMessageBus(['a','b'],lambda:clock[0],NetworkConfig(packet_loss_probability=1),42)
            lost.endpoint('a').send(AgentMessage('lost',MT.TARGET_FOUND,'a',['b'],'test',0,1,5,dict(target_id='T1')))
            self.assertFalse(lost.endpoint('b').receive_available())
            good=comparison.DegradedMessageBus(['a','b'],lambda:clock[0],NetworkConfig(latency_ms_mean=0,latency_ms_jitter=0),42)
            good.endpoint('a').send(AgentMessage('received',MT.TARGET_FOUND,'a',['b'],'test',0,1,5,dict(target_id='T1')))
            self.assertEqual(len(good.endpoint('b').receive_available()),1)
        events=[json.loads(s) for s in (self.root/'network.jsonl').read_text().splitlines()]
        found=[e for e in events if e['event_type']=='TARGET_FOUND']
        self.assertEqual(len(found),1);self.assertEqual(found[0]['data']['message_id'],'received')
        self.assertEqual(found[0]['data']['source'],'delivered_report')
        self.assertEqual(log.counts['MESSAGE_DROPPED'],1)

    def test_keyboard_interrupt_preserves_attempt_and_stops_batch(self):
        other=copy.deepcopy(self.entry);other['experiment_id']='second'
        with patch.object(comparison.MockFlight,'__init__',side_effect=KeyboardInterrupt):
            result,root=self.run_cases([self.entry,other])
        self.assertEqual(result['status'],'interrupted');self.assertEqual(len(result['runs']),1)
        manifest=self.read(root/'first/manifest.json')
        self.assertEqual(manifest['status'],'interrupted');self.assertIsNotNone(manifest['finished_at_utc'])
        self.assertFalse((root/'second').exists())

    def test_run_ids_differ_between_independent_batches(self):
        _,one=self.run_cases([self.entry],'one');_,two=self.run_cases([self.entry],'two')
        self.assertNotEqual(self.read(one/'first/manifest.json')['run_id'],self.read(two/'first/manifest.json')['run_id'])

    def test_requested_model_label_cannot_misrepresent_replay_or_rules(self):
        bad=copy.deepcopy(self.entry);bad['planner']='llama3.1:latest'
        result,root=self.run_cases([bad]);self.assertEqual(result['errors'],1)
        self.assertIn('planner must match',self.read(root/'first/manifest.json')['error']['message'])


if __name__=='__main__':unittest.main()
