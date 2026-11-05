import tempfile
import unittest
from agentic_uav.comm.protocol import PerfectMessageBus, MessageType, new_message
from agentic_uav.coordination.contract_net import MissionTask,TaskType,TaskStatus,Geometry,bid_cost,preferred_claim,AllocationAgent
from scripts.run_phase8_allocation import run

WEIGHTS=dict(distance=1,battery=5,workload=20,communication=5,mismatch=100)


class AllocationTests(unittest.TestCase):
    def task(self):return MissionTask('A',TaskType.SEARCH_SECTOR,Geometry((3,4,0)),1,{'search'})

    def test_task_roundtrip(self):
        t=self.task()
        self.assertEqual(MissionTask.from_dict(t.to_dict()),t)
        self.assertIsNone(t.assigned_agent)

    def test_cost_components_and_ineligibility(self):
        t=self.task()
        bid=bid_cost(t,(0,0,0),50,2,.2,{'search'},WEIGHTS)
        self.assertEqual(bid['score'],48.5)
        self.assertIsNone(bid_cost(t,(0,0,0),50,2,.2,set(),WEIGHTS))
        self.assertEqual(bid_cost(t,(0,0,0),50,2,.2,{'search'},WEIGHTS,role='relay')['score'],148.5)

    def test_claim_order_independent(self):
        a=dict(version=1,score=5,owner='Drone1')
        b=dict(version=1,score=5,owner='Drone2')
        self.assertEqual(preferred_claim(a,b),a)
        self.assertEqual(preferred_claim(b,a),a)
        c=dict(version=2,score=99,owner='Drone2')
        self.assertEqual(preferred_claim(a,c),c)
        with self.assertRaises(ValueError):preferred_claim(a,dict(version=1,score=float('nan'),owner='D'))

    def agent(self):
        now=[0.];bus=PerfectMessageBus(['a','b'],lambda:now[0])
        a=AllocationAgent('a',['b'],bus.endpoint('a'),[self.task()],(0,0,0))
        return a,bus,now

    def test_stale_progress_cannot_renew_new_epoch(self):
        a,bus,now=self.agent();t=a.tasks['A']
        t.version=2;t.status=TaskStatus.ASSIGNED;t.assigned_agent='b';t.lease_expires_at=1
        bus.endpoint('b').send(new_message(MessageType.INTENT_UPDATE,'b',['a'],'phase8',0,1,
            dict(task_id='A',version=1,intent='task_progress'),ttl=5))
        now[0]=.5;a.receive(.5)
        self.assertEqual(t.lease_expires_at,1)

    def test_progress_from_nonowner_ignored(self):
        a,bus,now=self.agent();t=a.tasks['A']
        t.version=1;t.status=TaskStatus.ASSIGNED;t.assigned_agent='a';t.lease_expires_at=1
        bus.endpoint('b').send(new_message(MessageType.INTENT_UPDATE,'b',['a'],'phase8',0,1,
            dict(task_id='A',version=1,intent='task_progress')))
        a.receive(0)
        self.assertEqual(t.lease_expires_at,1)

    def test_expired_lease_not_revived_by_late_progress(self):
        a,bus,now=self.agent();t=a.tasks['A']
        t.version=1;t.status=TaskStatus.ASSIGNED;t.assigned_agent='b';t.lease_expires_at=1
        bus.endpoint('b').send(new_message(MessageType.INTENT_UPDATE,'b',['a'],'phase8',0,1,
            dict(task_id='A',version=1,intent='task_progress')))
        now[0]=1.1;a.step(1.1,.1)
        self.assertEqual(t.version,2)
        self.assertEqual(t.status,TaskStatus.BIDDING)

    def test_voluntary_release_reannounces(self):
        a,_,_=self.agent();t=a.tasks['A'];t.version=1;t.status=TaskStatus.ASSIGNED;t.assigned_agent='a'
        a.release_task('A',0)
        self.assertEqual(t.version,2);self.assertIsNone(t.assigned_agent)
        self.assertEqual(t.status,TaskStatus.BIDDING)

    def test_mock_exit_and_repeatability(self):
        with tempfile.TemporaryDirectory() as d:
            first=run(output_dir=d)
            second=run(output_dir=d)
            self.assertEqual(first,second)
            self.assertTrue(first['mission_complete'])
            self.assertEqual(first['duplicate_task_completions'],0)
            self.assertGreater(first['conflict_corrections'],0)
            self.assertTrue(all(v==1 for v in first['completions_by_agent'].values()))

    def test_silent_owner_reassigned(self):
        with tempfile.TemporaryDirectory() as d:
            s=run(output_dir=d,fail_agent='Drone1',fail_at=1.5)
            self.assertTrue(s['mission_complete'])
            self.assertGreater(s['lease_expirations'],0)
            self.assertEqual(s['completions_by_agent']['Drone1'],0)
            self.assertEqual(s['duplicate_task_completions'],0)
