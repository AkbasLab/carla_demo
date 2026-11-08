"""V2 architecture selection, shared support, baseline semantics and crash regression."""
import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agentic_uav.experiments import pilot_v2_runner as runner
from agentic_uav.experiments.comparison import run_comparison,configuration
from agentic_uav.experiments.architectures import FleetController
from agentic_uav.experiments.metrics import Evidence
from agentic_uav.policy.mission import load_mission
from agentic_uav.coordination.contract_net import TaskStatus


class AllArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.config=json.loads(Path('configs/phase17/resilience_v2.json').read_text())

    def build(self,architectures,stage='focused',team=2):
        folder=self.root/('build_'+stage+'_'+str(team)+'_'+''.join(architectures));folder.mkdir()
        return runner.build(self.config,folder,stage,team,11,'replay','alive','owned_motion',architectures)

    def test_selection_pairs_and_shared_inputs(self):
        batch=self.build(list('ABCD'))['experiments']
        self.assertEqual(len(batch),8)
        self.assertEqual([e['architecture'] for e in batch],list('AABBCCDD'))
        controls=[e for e in batch if e['failure_profile']=='none']
        for e in controls:self.assertEqual(e['settings'],controls[0]['settings'])
        for e in batch:
            parsed=configuration(dict(e['settings'],architecture=e['architecture']))
            self.assertTrue(parsed['pilot_resilience_v2']['enabled'])
            self.assertEqual(parsed['ticks']*parsed['dt'],240)
        self.assertEqual(len(self.build(['B'])['experiments']),2)
        self.assertEqual(runner.selected_architectures(self.config,'focused'),['C','D'])

    def test_invalid_selection_and_smoke(self):
        for selection in ([],['A','A'],['E']):
            with self.assertRaises(ValueError):runner.selected_architectures(self.config,'focused',selection)
        with self.assertRaises(ValueError):runner.selected_architectures(self.config,'smoke',['B'])
        self.assertEqual(runner.selected_architectures(self.config,'smoke',['C','A']),['A','C'])

    def test_ab_replay_integration_and_fixed_baseline_semantics(self):
        # Exercises actual runner logging/packing with fixtures, not Ollama evidence.
        config=self.root/'config.json';config.write_text(json.dumps(self.config))
        with contextlib.redirect_stdout(io.StringIO()):
            result=runner.execute(config,self.root/'ab',stage='focused',team_size=2,seed=11,
                profile='replay',architectures=['A','B'])
        self.assertEqual(result['completed_runs'],4)
        self.assertTrue(result['all_runs_technically_valid'])
        self.assertEqual(result['architectures'],['A','B'])
        for row in result['rows']:
            folder=self.root/'ab/runs'/row['experiment_id'];e=Evidence(folder/'run')
            summary=e.read('summary.json');self.assertIsNone(summary['error'])
            self.assertTrue(summary['all_dispatched_actions_guarded'])
            self.assertEqual(row['sampled_separation_violations'],0)
            if row['architecture']=='B':
                protocol=e.read('protocol_events.json')
                self.assertFalse(any(x['event'] in ('claim_sent','bid_computed','task_announced') for x in protocol))
                if row['fault_requested']:
                    self.assertTrue(row['fault_observed']);self.assertFalse(row['mission_complete'])
                    self.assertNotIn('SEARCH_SECTOR_A',summary['completed_task_ids'])
                    self.assertNotIn('SEARCH_SECTOR_C',summary['completed_task_ids'])
                else:self.assertTrue(row['mission_complete'])
            elif not row['fault_requested']:
                self.assertTrue(row['mission_complete'])
            else:
                self.assertTrue(row['fault_owned']);self.assertTrue(row['fault_during_move'])
                self.assertIsNotNone(row['replacement_s'])
                controller=e.read('controller_events.json')
                reassigned=[x for x in controller if x['event']=='central_assignment'
                    and x['task_id']=='SEARCH_SECTOR_A' and x['time_s']>row['fault_s']]
                self.assertTrue(reassigned)
                self.assertTrue(all(x['owner']!='Drone1' for x in reassigned))
            if row['fault_requested']:
                events=Evidence(folder).read('events.jsonl')
                after=[x['data']['envelope'] for x in events if x['event_type']=='MESSAGE_SENT'
                       and x['agent_id']=='Drone1' and x['simulation_time_s']>row['fault_s']]
                self.assertTrue(after)
                self.assertTrue(all(m['message_type']=='STATUS_UPDATE' for m in after))
                if row['architecture']=='A':
                    self.assertTrue(any('FleetController' in m['recipient_ids'] for m in after))

    def test_central_controller_does_not_mistake_live_telemetry_for_live_policy(self):
        _,_,tasks,_=load_mission('configs/phase12/mission.example.json')
        sent=[];opts=dict(resilience={'enabled':True},pilot_resilience_v2={'enabled':True,'coordination_timeout_s':3},
            state_timeout_s=2,lease_seconds=75,bid_window=6,beacon_interval_s=.5,command_timeout_s=3,minimum_battery_percent=20)
        c=FleetController(SimpleNamespace(send=sent.append),tasks[:1],['Drone1','Drone2'],opts);c.bootstrap_ready=True
        c.states={aid:dict(position=[0,0,-3],battery=80,role='SCOUT',observed_at=10) for aid in ['Drone1','Drone2']}
        c.policy_heartbeats={'Drone1':0,'Drone2':10};c.step(10)
        self.assertEqual(next(iter(c.tasks.values())).assigned_agent,'Drone2')
        self.assertTrue(sent)

    def test_severe_c_control_no_missing_rejection_cache_for_either_team_size(self):
        for team in (2,4):
            entry=self.build(['C'],'severe',team)['experiments'][0]
            values=dict(entry['settings'],architecture='C',condition='severe',seed=11,
                        output_dir=str(self.root/f'severe_{team}'))
            summary=run_comparison(values)
            self.assertIsNone(summary['error'])
            self.assertTrue(summary['all_dispatched_actions_guarded'])

    def test_model_admission_delay_does_not_abandon_b_prebriefed_work(self):
        from agentic_uav.policy.evidence import admit_requests
        entry=self.build(['B'],team=4)['experiments'][0]
        def delayed(agents,now,capacity):
            if now<30:
                for agent in agents:
                    if agent.request_waiting_since is None:agent.request_waiting_since=now
                return []
            return admit_requests(agents,now,capacity)
        output=self.root/'delayed_b'
        with patch('agentic_uav.experiments.comparison.admit_requests',side_effect=delayed):
            summary=run_comparison(dict(entry['settings'],architecture='B',seed=11,output_dir=str(output)))
        self.assertIsNone(summary['error']);self.assertTrue(summary['mission_complete'])
        self.assertEqual(len(summary['completed_task_ids']),4)
        for aid in ['Drone1','Drone2','Drone3','Drone4']:
            history=Evidence(output).read(aid+'/decision_history.jsonl')
            self.assertFalse(any(x['event']=='blocked_task_released' for x in history))
