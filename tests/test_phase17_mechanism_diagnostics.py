"""Secondary measurements retain censoring, local-event scope and ZIP parity."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from agentic_uav.experiments.mechanism_diagnostics import analyse_run,analyse_batch,report


class MechanismDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)/'case';self.run=self.folder/'run';self.run.mkdir(parents=True)
        self.write('summary.json',dict(architecture='D',mission_complete=False,llm_inference=True,
            decisions_by_agent={'Drone1':1,'Drone2':1}))
        self.write('manifest.json',dict(shared_inputs=dict(mission=dict(tasks=[
            dict(task_id='A',waypoints=[[0,0,-3]]),dict(task_id='B',waypoints=[[1,0,-3]])]))))
        self.events=[dict(event_type='TASK_ASSIGNED',agent_id='Drone2',simulation_time_s=t,
            data=dict(task_id=tid,owner='Drone2',version=version)) for tid,t,version in [('B',13,1),('A',15,2)]]
        self.save_events()
        self.write('protocol_events.json',[
            dict(event='claim_sent',task_id='A',version=1),dict(event='task_released',task_id='A'),
            dict(event='claim_sent',task_id='A',version=2),dict(event='progress_reported'),
            dict(event='progress_reported'),dict(event='lease_expired'),dict(event='lease_expired')])
        self.write('waypoint_arrivals.json',[dict(task_id='A',version=2,index=0,agent_id='Drone2',time_s=19),
            dict(task_id='A',version=2,index=0,agent_id='Drone2',time_s=20)])
        self.write('guardian_audit.json',[dict(outcome='REJECT_AND_REPLAN',reasons=['peer_reachable_region_conflict'])])
        self.write('Drone1/decision_history.jsonl',[dict(event='policy_error',reason_code='unsafe_action'),
            dict(event='deterministic_fallback'),dict(event='peer_health_changed'),dict(event='alternative_approach_invalidated')])
        self.write('Drone2/decision_history.jsonl',[])
        self.write('Drone1/responses.jsonl',[dict(latency_s=2),dict(latency_s=4,error='failure')])
        self.write('Drone2/responses.jsonl',[])
        self.evaluation=dict(diagnostic=dict(llm_calls=3),primary=dict(safety={'corrective_guardian_interventions':1},
            recovery=[dict(kind='actor_failure',onset_s=10,tasks=[
                dict(task_id='A',replacement_agent='Drone2',recovery_time_s=5,productive_resume_time_s=9),
                dict(task_id='B',replacement_agent='Drone2',recovery_time_s=3,productive_resume_time_s=None)])]))

    def write(self,name,value):
        p=self.run/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(''.join(json.dumps(r)+'\n' for r in value) if name.endswith('.jsonl') else json.dumps(value))

    def analyse(self):return analyse_run(self.folder,self.evaluation)

    def save_events(self):
        (self.folder/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in self.events))

    def test_counts_and_per_task_censoring(self):
        d=self.analyse()
        self.assertEqual(d['waypoint_arrivals'],dict(records=2,unique_required_waypoints=1))
        self.assertEqual(d['progress_and_leases']['local_lease_expiration_events'],2)
        self.assertEqual(d['task_lifecycle']['A']['claimed_versions'],[1,2])
        self.assertEqual(d['task_lifecycle']['A']['release_events'],1)
        self.assertEqual(d['recovery'][0]['acceptance_to_arrival_s'],4)
        self.assertEqual(d['recovery'][0]['first_productive_arrival_s'],19)
        self.assertIsNone(d['recovery'][1]['acceptance_to_arrival_s'])
        self.assertTrue(d['recovery'][1]['censored'])
        self.assertEqual(d['policy']['fallback_activations'],1)
        self.assertEqual(d['inference']['latency_s']['mean'],3)
        self.assertEqual(d['inference']['failed_response_records'],1)
        self.assertEqual(d['guardian']['reason_occurrences']['peer_reachable_region_conflict'],1)

    def test_plain_and_losslessly_packed_evidence_match(self):
        before=self.analyse()
        files=[self.run/'guardian_audit.json']+list(self.run.glob('*/*.jsonl'))
        with zipfile.ZipFile(self.run/'traces.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for p in files:archive.write(p,str(p.relative_to(self.run)))
        for p in files:p.unlink()
        with zipfile.ZipFile(self.folder/'traces.zip','w',zipfile.ZIP_DEFLATED) as archive:
            archive.write(self.folder/'events.jsonl','events.jsonl')
        (self.folder/'events.jsonl').unlink()
        self.assertEqual(before,self.analyse())

    def test_missing_measurements_are_not_reported_as_zero(self):
        (self.run/'Drone2/decision_history.jsonl').unlink();(self.run/'guardian_audit.json').unlink()
        (self.run/'protocol_events.json').unlink()
        d=self.analyse()
        self.assertIsNone(d['policy']['peer_health_transitions'])
        self.assertIsNone(d['guardian']['rejected_evaluations'])
        self.assertFalse(d['task_lifecycle_complete'])
        self.assertIn('unavailable',report([d]))
        self.assertIn('Drone2/decision_history.jsonl',d['missing_artifacts'])

    def test_replay_has_no_llm_latency_estimate(self):
        self.write('summary.json',dict(architecture='C',llm_inference=False,decisions_by_agent={'Drone1':0,'Drone2':0}))
        self.assertIsNone(self.analyse()['inference']['latency_s'])

    def test_controller_observation_does_not_double_count_local_release(self):
        self.write('controller_events.json',[dict(event='central_task_released',task_id='A')])
        d=self.analyse()['task_lifecycle']['A']
        self.assertEqual(d['release_events'],1)
        self.assertEqual(d['central_release_observations'],1)

    def test_other_agent_or_repeated_work_cannot_fake_replacement_resumption(self):
        self.write('waypoint_arrivals.json',[dict(task_id='A',version=1,index=0,agent_id='Drone1',time_s=12),
            dict(task_id='A',version=2,index=0,agent_id='Drone2',time_s=19)])
        self.assertIsNone(self.analyse()['recovery'][0]['acceptance_to_arrival_s'])
        self.assertTrue(self.analyse()['recovery'][0]['censored'])

    def test_released_or_superseded_assignment_cannot_borrow_later_arrival(self):
        self.events.append(dict(event_type='TASK_RELEASED',agent_id='Drone2',simulation_time_s=17,
            data=dict(task_id='A',version=2)))
        self.save_events()
        d=self.analyse()['recovery'][0]
        self.assertIsNone(d['acceptance_to_arrival_s']);self.assertTrue(d['censored'])
        self.assertEqual(d['acceptance_episode_end_s'],17)
        self.events[-1]=dict(event_type='TASK_ASSIGNED',agent_id='Drone2',simulation_time_s=18,
            data=dict(task_id='A',owner='Drone2',version=3))
        self.save_events()
        self.write('waypoint_arrivals.json',[dict(task_id='A',version=3,index=0,agent_id='Drone2',time_s=19)])
        self.assertIsNone(self.analyse()['recovery'][0]['acceptance_to_arrival_s'])

    def test_nonrequired_waypoints_and_unknown_epoch_are_not_productive_evidence(self):
        self.write('waypoint_arrivals.json',[dict(task_id='A',version=2,index=99,agent_id='Drone2',time_s=19)])
        self.assertEqual(self.analyse()['waypoint_arrivals']['unique_required_waypoints'],0)
        self.assertIsNone(self.analyse()['recovery'][0]['acceptance_to_arrival_s'])
        (self.folder/'events.jsonl').unlink()
        self.assertIsNone(self.analyse()['recovery'][0]['censored'])

    def test_retrospective_outputs_do_not_replace_original_manifest(self):
        batch=Path(self.temp.name)/'batch';batch.mkdir()
        manifest=batch/'v2_manifest.json';original=json.dumps(dict(rows=[dict(experiment_id='case')]))
        manifest.write_text(original)
        out=Path(self.temp.name)/'analysis'
        with patch('agentic_uav.experiments.mechanism_diagnostics.analyse_run',return_value=self.analyse()):
            result=analyse_batch(batch,out)
        self.assertEqual(result['runs'],1);self.assertTrue(result['retrospective'])
        self.assertEqual(manifest.read_text(),original)
        self.assertTrue((out/'MECHANISMS.md').exists())
        with self.assertRaises(FileExistsError):analyse_batch(batch,out)
        with self.assertRaises(ValueError):analyse_batch(batch,batch/'new_analysis')
