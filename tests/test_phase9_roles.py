import json
import tempfile
import unittest
from pathlib import Path
from agentic_uav.comm.protocol import PerfectMessageBus,MessageType,new_message
from agentic_uav.coordination.contract_net import MissionTask,Geometry,TaskType
from agentic_uav.coordination.dynamic_roles import PeerHealth,Health,Role,DynamicRoleAgent
from scripts.run_phase9_roles import run


class HealthTests(unittest.TestCase):
    def test_silence_never_means_confirmed_failure(self):
        h=PeerHealth(1,3)
        self.assertEqual(h.tick(.5),Health.HEALTHY)
        self.assertEqual(h.tick(1.1),Health.SUSPECTED)
        self.assertEqual(h.tick(3.1),Health.UNREACHABLE)
        self.assertEqual(h.tick(100),Health.UNREACHABLE)

    def test_short_gap_recovers_without_failure(self):
        h=PeerHealth(1,3);h.tick(1.1);h.heartbeat(1.2)
        self.assertEqual(h.state,Health.HEALTHY)

    def test_confirmed_failure_and_recovered_state(self):
        h=PeerHealth(1,3);h.confirmed_failure()
        self.assertEqual(h.tick(10),Health.FAILED)
        h.heartbeat(10)
        self.assertEqual(h.state,Health.RECOVERED)
        for t in [10.2,10.4,10.6,10.8,11.1]:h.heartbeat(t);h.tick(t)
        self.assertEqual(h.state,Health.HEALTHY)


class RoleTests(unittest.TestCase):
    def test_scout_can_become_relay_and_reprioritize(self):
        now=[4.];bus=PerfectMessageBus(['a','b','c'],lambda:now[0])
        task=MissionTask('T',TaskType.SEARCH_SECTOR,Geometry((0,0,-3)),1,{'search'})
        a=DynamicRoleAgent('a',['b','c'],bus.endpoint('a'),[task],(0,0,-3),initial_roles=dict(a='SCOUT',b='RELAY',c='RESERVE'))
        a.peer_status['c']=dict(role='RESERVE',battery=15,position=[0,0,-3])
        a.peer_health['c'].last_seen=4
        a.policy(4)
        self.assertEqual(a.role,Role.RELAY)
        a.peer_health['c'].last_seen=0;now[0]=5;a.policy(5)
        self.assertEqual(a.objective,'CRITICAL_ONLY')

    def test_only_trusted_supervisor_can_confirm_failure(self):
        now=[0.];bus=PerfectMessageBus(['a','b','supervisor'],lambda:now[0])
        a=DynamicRoleAgent('a',['b'],bus.endpoint('a'),[],(0,0,-3),initial_roles={'a':'SCOUT','b':'RELAY'},supervisor_id='supervisor')
        payload=dict(kind='confirmed_failure',agent_id='b')
        bus.endpoint('b').send(new_message(MessageType.MISSION_UPDATE,'b',['a'],'phase8',0,1,payload))
        a.receive(0);self.assertNotEqual(a.peer_health['b'].state,Health.FAILED)
        bus.endpoint('supervisor').send(new_message(MessageType.MISSION_UPDATE,'supervisor',['a'],'phase8',0,1,payload))
        a.receive(0);self.assertEqual(a.peer_health['b'].state,Health.FAILED)

    def exercise(self,**kw):
        with tempfile.TemporaryDirectory() as d:
            s=run(output_dir=d,**kw)
            events=json.loads((Path(d)/'events.json').read_text())
            self.assertTrue(s['mission_complete']);self.assertEqual(s['duplicate_task_completions'],0)
            return s,events

    def test_scout_loss_activates_reserve_and_recovers_task(self):
        s,e=self.exercise(fail_agent='Drone1')
        self.assertEqual(s['final_roles']['Drone4'],'SCOUT')
        self.assertEqual(s['completions_by_agent']['Drone1'],0)
        self.assertGreater(s['lease_expirations'],0)
        self.assertTrue(all(h['Drone1']=='UNREACHABLE' for h in s['final_peer_health'].values()))
        self.assertTrue(any(x['event']=='role_changed' and x['agent_id']=='Drone4' for x in e))

    def test_relay_loss_elects_reserve(self):
        s,_=self.exercise(fail_agent='Drone3')
        self.assertEqual(s['final_roles']['Drone4'],'RELAY')
        self.assertEqual(sum(r=='RELAY' for r in s['final_roles'].values()),1)

    def test_low_battery_releases_and_reserve_activates(self):
        s,e=self.exercise(fail_agent=None,low_battery_agent='Drone1')
        self.assertEqual(s['final_roles']['Drone1'],'RESERVE')
        self.assertEqual(s['final_roles']['Drone4'],'SCOUT')
        self.assertTrue(any(x['event']=='task_released' for x in e))

    def test_delivered_target_discovery_activates_reserve(self):
        s,e=self.exercise(fail_agent=None,critical_task=True)
        self.assertEqual(s['final_roles']['Drone4'],'SCOUT')
        self.assertTrue(any(x['event']=='critical_target_discovered' for x in e))
        self.assertTrue(any(x['event']=='work_completed' and x['task_id']=='INSPECT_TARGET_T1' for x in e))
