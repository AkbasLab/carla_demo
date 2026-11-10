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

    def test_diagnostic_groups_do_not_require_independent_agent_takeover(self):
        rows=[dict(experiment_id='B_control',architecture='B',fault_requested=False,mission_complete=True),
              dict(experiment_id='B_loss',architecture='B',fault_requested=True,mission_complete=False,fault_observed=True),
              dict(experiment_id='A_loss',architecture='A',fault_requested=True,mission_complete=False)]
        checks=runner.diagnostic_groups(rows,3)
        self.assertTrue(checks['normal_operation']['passed'])
        self.assertFalse(checks['recovery_capable']['passed'])
        self.assertEqual(checks['recovery_capable']['incomplete_cases'],['A_loss'])
        self.assertFalse(checks['independent_baseline']['recovery_required'])
        self.assertEqual(checks['independent_baseline']['completed_missions'],0)

    def test_ab_replay_integration_and_fixed_baseline_semantics(self):
        # Exercises actual runner logging/packing with fixtures, not Ollama evidence.
        config=self.root/'config.json';config.write_text(json.dumps(self.config))
        with contextlib.redirect_stdout(io.StringIO()):
            result=runner.execute(config,self.root/'ab',stage='focused',team_size=2,seed=11,
                profile='replay',architectures=['A','B'])
        self.assertEqual(result['completed_runs'],4)
        self.assertTrue(result['all_runs_technically_valid'])
        self.assertEqual(result['architectures'],['A','B'])
        self.assertTrue((self.root/'ab/analysis/MECHANISMS.md').exists())
        for row in result['rows']:
            folder=self.root/'ab/runs'/row['experiment_id'];e=Evidence(folder/'run')
            diagnostics=json.loads((self.root/'ab'/row['mechanism_diagnostics_file']).read_text())
            self.assertEqual(diagnostics['collection_mode'],'during_batch')
            self.assertEqual(diagnostics['waypoint_arrivals']['unique_required_waypoints'],
                len({(r['task_id'],r['index']) for r in e.read('waypoint_arrivals.json')}))
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
                history=e.read('Drone2/decision_history.jsonl')
                owned_times={x['time_s'] for x in e.read('flight_trace.json')
                    if x['agent_id']=='Drone2' and x['owned_tasks']}
                self.assertFalse(any(x['event']=='controller_command_timeout' and x['time_s'] in owned_times for x in history))
            else:
                self.assertTrue(row['fault_owned']);self.assertTrue(row['fault_during_move'])
                self.assertIsNotNone(row['replacement_s'])
                controller=e.read('controller_events.json')
                reassigned=[x for x in controller if x['event']=='central_assignment'
                    and x['task_id']=='SEARCH_SECTOR_A' and x['time_s']>row['fault_s']]
                self.assertTrue(reassigned)
                self.assertTrue(all(x['owner']!='Drone1' for x in reassigned))
                # The replay fault can physically block the first waypoint. Its
                # rejection must be delivered to the controller, not hidden.
                self.assertTrue(any(x['event']=='central_execution_blocked' for x in controller))
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

    def test_central_link_outage_still_stops_motion(self):
        entry=self.build(['A'])['experiments'][0]
        values=dict(entry['settings'],architecture='A',condition='nominal',seed=11,
            output_dir=str(self.root/'controller_outage'))
        values['network']['partitions']=[dict(start_s=5,end_s=15,
            groups=[['FleetController'],['Drone1','Drone2']])]
        summary=run_comparison(values)
        self.assertIsNone(summary['error']);self.assertTrue(summary['all_dispatched_actions_guarded'])
        evidence=Evidence(values['output_dir']);trace=evidence.read('flight_trace.json')
        for aid in ['Drone1','Drone2']:
            history=evidence.read(aid+'/decision_history.jsonl')
            self.assertTrue(any(x['event']=='controller_command_timeout' and 5<x['time_s']<15 for x in history))
            positions=[x['position'] for x in trace if x['agent_id']==aid and 10<=x['time_s']<=14]
            self.assertTrue(positions)
            self.assertTrue(all(p==positions[0] for p in positions))

    def test_central_safety_feedback_is_not_progress_or_lease_renewal(self):
        _,_,tasks,_=load_mission('configs/phase12/mission.example.json')
        c=FleetController(SimpleNamespace(),tasks[:1],['Drone1'],dict(lease_seconds=75,bid_window=6,
            pilot_resilience_v2=dict(rebid_cooldown_s=15)))
        t=next(iter(c.tasks.values()));t.status=TaskStatus.ASSIGNED;t.assigned_agent='Drone1'
        t.version=2;t.lease_expires_at=75
        report=dict(task_id=t.task_id,version=2,execution_status='approach_blocked',reasons=['peer_reachable_region_conflict'])
        self.assertTrue(c.progress('Drone1',report,10))
        self.assertEqual(t.lease_expires_at,75);self.assertEqual(c.checkpoints,{})
        self.assertEqual(c.events[-1]['event'],'central_execution_blocked')
        self.assertFalse(c.progress('Drone1',dict(report,version=1),11))
        self.assertTrue(c.progress('Drone1',dict(report,status='released',execution_status=None),12))
        self.assertEqual(t.status,TaskStatus.UNASSIGNED)
        self.assertEqual(c.cooldowns[('Drone1',t.task_id)],27)

    def test_central_blocked_assignment_requires_changed_delivered_geometry(self):
        _,_,tasks,_=load_mission('configs/phase12/mission.example.json')
        opts=dict(lease_seconds=75,bid_window=6,state_timeout_s=2,beacon_interval_s=.5,command_timeout_s=3,
            pilot_resilience_v2=dict(enabled=True,coordination_timeout_s=3))
        c=FleetController(SimpleNamespace(send=lambda m:None),tasks[:1],['Drone1','Drone2'],opts)
        c.states={aid:dict(position=[i*4,0,-3],battery=80,role='SCOUT' if i==0 else 'RESERVE',observed_at=10)
            for i,aid in enumerate(['Drone1','Drone2'])}
        c.policy_heartbeats={'Drone1':10,'Drone2':10}
        t=next(iter(c.tasks.values()));t.status=TaskStatus.ASSIGNED;t.assigned_agent='Drone1';t.version=1;t.lease_expires_at=75
        c.progress('Drone1',dict(task_id=t.task_id,version=1,execution_status='approach_blocked',reasons=['peer_reachable_region_conflict']),10)
        t.status=TaskStatus.UNASSIGNED;t.assigned_agent=None
        c.step(10)
        self.assertEqual(t.status,TaskStatus.UNASSIGNED)
        c.states['Drone2']['position']=[5,0,-3]  # New delivered observation, not a failure oracle.
        c.step(10)
        self.assertEqual(t.assigned_agent,'Drone1')
        self.assertTrue(any(e['event']=='central_approach_recheck' for e in c.events))

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
