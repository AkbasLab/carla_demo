"""Phase 16 cross-layer regressions, rather than copies of existing rule unit tests."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agentic_uav.comm.degraded import DegradedMessageBus, NetworkConfig
from agentic_uav.comm.protocol import MessageType, new_message
from agentic_uav.coordination.contract_net import AllocationAgent, Geometry, MissionTask, TaskType
from agentic_uav.control.scenario_manager import ExperimentSchedule, ScenarioManager
from agentic_uav.experiments.regression import CASES, run_regression

MISSION = 'configs/phase12/mission.example.json'


class FlightRegressionTests(unittest.TestCase):
    def exercise(self, case, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_regression(case, MISSION, tmp, **kwargs)
            data = {p.stem: json.loads(p.read_text()) for p in Path(tmp).glob('*.json')}
        return summary, data

    def test_all_five_cases_use_observed_motion_and_guarded_effects(self):
        for case in CASES:
            with self.subTest(case=case):
                s, d = self.exercise(case)
                self.assertTrue(s['passed'], s)
                self.assertTrue(d['waypoint_arrivals'])
                selected = {a['selected_action']['command_id'] for a in d['guardian_audit']
                            if a['selected_action'] and a['mission_effect'].get('executed')}
                self.assertTrue(d['executed_actions'])
                self.assertTrue(all(a['command_id'] in selected for a in d['executed_actions']))
                for row in d['waypoint_arrivals']:
                    self.assertLessEqual(row['xy_error_m'], .4)
                    self.assertLessEqual(row['z_error_m'], .6)
                if case == 'reassignment':
                    self.assertEqual(s['affected_tasks'], ['SEARCH_SECTOR_A'])
                    self.assertEqual(s['recovered_tasks'], s['affected_tasks'])
                    self.assertTrue(any(e['event']=='lease_expired' for e in d['agent_events']))
                    # The stopped physical actor remains in subsequent safety input.
                    later = [r for r in d['guardian_audit'] if r['time_s'] > 2 and r['observed_state']['vehicle_id'] != 'Drone1']
                    self.assertTrue(later)
                    self.assertTrue(all('Drone1' in r['observed_state']['peers'] for r in later))
                if case == 'return_home':
                    self.assertTrue(s['return_home_observed'])
                    self.assertTrue(any(a['kind']=='RETURN_HOME' for a in d['executed_actions']))

    def test_timeout_preserves_partial_evidence_and_fails(self):
        s, d = self.exercise('four_search', duration=.5)
        self.assertFalse(s['passed'])
        self.assertFalse(s['mission_complete'])
        self.assertIsNone(s['error'])
        self.assertIn('flight_trace', d)
        self.assertIn('guardian_audit', d)

    def test_injection_after_completion_is_not_credited_as_recovery(self):
        s, _ = self.exercise('reassignment', fail_at=100)
        self.assertFalse(s['passed'])
        self.assertFalse(s['affected_tasks'])

    def test_adapter_exception_retains_error_and_cleanup(self):
        from agentic_uav.policy.backends import MockFlight
        with patch.object(MockFlight, 'advance', side_effect=RuntimeError('injected adapter error')):
            s, d = self.exercise('single_waypoint')
        self.assertFalse(s['passed'])
        self.assertEqual(s['error']['type'], 'RuntimeError')
        self.assertIn('manifest', d)

    def test_live_cannot_start_accidentally_and_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                run_regression('single_waypoint', MISSION, tmp, backend='airsim')
            run_regression('single_waypoint', MISSION, tmp)
            with self.assertRaises(ValueError):
                run_regression('single_waypoint', MISSION, tmp)


class TransportIntegrationTests(unittest.TestCase):
    def test_delayed_competing_claims_converge_to_lower_valid_bid(self):
        now = [0.]
        bus = DegradedMessageBus(['a','b'], lambda: now[0], NetworkConfig(latency_ms_mean=500, latency_ms_jitter=0))
        task = MissionTask('T', TaskType.SEARCH_SECTOR, Geometry((0,0,-3)), 1, {'search'})
        agents = [AllocationAgent(a,[b],bus.endpoint(a),[task],p,lease_s=10) for a,b,p in [('a','b',(0,0,-3)),('b','a',(10,0,-3))]]
        for a in agents:
            a.announce(a.tasks['T'],0,1)
        now[0] = .5
        for a in agents:
            a.receive(.5)  # Bid evidence arrives before competing claims.
        for a in agents:
            bid = a.bids['T'][a.agent_id]
            claim = dict(task_id='T', version=1, owner=a.agent_id, score=bid['score'])
            a.send(MessageType.TASK_AWARD,claim,.5)
            a.adopt(a.tasks['T'],claim,.5)
        self.assertEqual([a.tasks['T'].assigned_agent for a in agents], ['a','b'])
        now[0] = 1.
        for a in agents:
            a.receive(1.)
        self.assertEqual([a.tasks['T'].assigned_agent for a in agents], ['a','a'])
        self.assertTrue(any(e['event']=='losing_claim_released' for e in agents[1].events))
        self.assertTrue(any(e['event']=='claim_corrected' for e in agents[1].events))

    def test_partition_prevents_cross_group_receipt_until_link_restored(self):
        now=[1.]
        ids=['a','b','c','d']
        bus=DegradedMessageBus(ids,lambda:now[0],NetworkConfig(latency_ms_mean=0,latency_ms_jitter=0,
            partitions=[dict(start_s=1,end_s=2,groups=[['a','b'],['c','d']])]))
        for sender in ids:
            peers=[a for a in ids if a!=sender]
            bus.endpoint(sender).send(new_message(MessageType.STATUS_UPDATE,sender,peers,'partition',1,1,{'role':'SCOUT'}))
        inbox={a:[m.sender_id for m in bus.endpoint(a).receive_available()] for a in ids}
        self.assertEqual(inbox,{'a':['b'],'b':['a'],'c':['d'],'d':['c']})
        now[0]=2
        bus.endpoint('a').send(new_message(MessageType.STATUS_UPDATE,'a',['c'],'partition',2,2,{'role':'SCOUT'}))
        self.assertEqual([m.sender_id for m in bus.endpoint('c').receive_available()],['a'])
        # This asserts transport isolation, not general task consensus under partitions.


class DeterminismTests(unittest.TestCase):
    def test_deterministic_execution_repeats_across_process_hash_seeds(self):
        code = '''import hashlib,json,tempfile
from pathlib import Path
from agentic_uav.experiments.regression import run_regression
with tempfile.TemporaryDirectory() as d:
 run_regression('reassignment','configs/phase12/mission.example.json',d)
 names=['summary','events','agent_events','messages','executed_actions','waypoint_arrivals','flight_trace','guardian_audit']
 print(json.dumps({n:hashlib.sha256((Path(d)/(n+'.json')).read_bytes()).hexdigest() for n in names},sort_keys=True))
'''
        values=[]
        for seed in ('1','97'):
            env=dict(os.environ, PYTHONHASHSEED=seed)
            result=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,text=True,timeout=30,check=True)
            values.append(json.loads(result.stdout))
        self.assertEqual(*values)

    def test_configured_targets_and_injected_fault_schedule_repeat(self):
        first=ScenarioManager('configs/missions/search_and_relay.json')
        second=ScenarioManager('configs/missions/search_and_relay.json')
        # Targets currently come from configuration, not a randomized placer.
        coordinates=lambda s:[(t.target_id,t.position.x,t.position.y,t.position.z) for t in s.targets]
        self.assertEqual(coordinates(first),coordinates(second))
        traces=[]
        for _ in range(2):
            schedule=ExperimentSchedule('Drone3',2.)
            fired=[(t,schedule.advance(t)) for t in [0,1.9,2.,2.1,5.]]
            traces.append((fired,schedule.events))
        self.assertEqual(*traces)
        self.assertEqual(traces[0][1],[dict(event='actor_silenced',time_s=2.,agent_id='Drone3')])
