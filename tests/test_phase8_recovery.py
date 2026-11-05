import math
import unittest
from agentic_uav.comm.protocol import PerfectMessageBus, MessageType, new_message
from agentic_uav.coordination.contract_net import AllocationAgent,MissionTask,Geometry,TaskType,TaskStatus
from agentic_uav.coordination.flight_executor import WaypointExecutor,within_waypoint


class RecoveryRegressionTests(unittest.TestCase):
    def test_separate_xy_z_acceptance(self):
        target=[6,45,25];actual=[6.0068,45.0672,25.4782]
        self.assertFalse(within_waypoint(actual,target,.4))
        self.assertTrue(within_waypoint(actual,target,.4,.6))
        self.assertFalse(within_waypoint([6.5,45,25],target,.4,.6))
        self.assertFalse(within_waypoint([6,45,25.7],target,.4,.6))

    def scenario(self,fail=False,stalled=False):
        now=[0.];dt=.1
        ids=['Drone1','Drone2','Drone3','Drone4']
        bus=PerfectMessageBus(ids,lambda:now[0])
        route=[[0,0,25],[0,30,25],[4,30,25]]
        task=MissionTask('A',TaskType.SEARCH_SECTOR,Geometry((0,0,25)),1,{'search'},work_units=len(route))
        agents=[AllocationAgent(a,[p for p in ids if p!=a],bus.endpoint(a),[task],
            [i*8,0,25.5],lease_s=3.,bid_window=.2) for i,a in enumerate(ids)]
        executors={a.agent_id:WaypointExecutor({'A':route},.4,z_tolerance=.6,stall_timeout=.8,max_retries=2) for a in agents}
        active=agents
        for tick in range(1500):
            now[0]=round(tick*dt,6)
            active=[a for a in agents if not (fail and a.agent_id=='Drone1' and now[0]>=8)]
            for a in active:a.receive(now[0])
            for a in active:
                a.step(now[0],dt,process_inbox=False,execute_mock=False)
                cmd=executors[a.agent_id].update(a,now[0])
                if cmd['action']=='move' and not stalled:
                    dx=cmd['target'][0]-a.position[0];dy=cmd['target'][1]-a.position[1]
                    d=math.hypot(dx,dy);ratio=min(1,dt/d) if d else 0
                    a.position[0]+=dx*ratio;a.position[1]+=dy*ratio
                if stalled and tick>80:return agents,executors,False
            if all(a.tasks['A'].status==TaskStatus.COMPLETE for a in active):return agents,executors,True
        return agents,executors,False

    def test_long_leg_and_height_bias_do_not_expire_healthy_owner(self):
        agents,executors,complete=self.scenario()
        self.assertTrue(complete)
        events=[e for a in agents for e in a.events]
        self.assertFalse(any(e['event']=='lease_expired' for e in events))
        self.assertEqual([r['index'] for r in executors['Drone1'].arrivals],[0,1,2])

    def test_failure_during_long_leg_resumes_observed_checkpoint(self):
        agents,executors,complete=self.scenario(fail=True)
        self.assertTrue(complete)
        events=[e for a in agents for e in a.events]
        self.assertTrue(any(e['event']=='lease_expired' for e in events))
        completed=[e for e in events if e['event']=='work_completed']
        self.assertEqual(len(completed),1)
        self.assertNotEqual(completed[0]['agent_id'],'Drone1')
        survivor=executors[completed[0]['agent_id']]
        self.assertEqual([r['index'] for r in survivor.arrivals],[1,2])
        self.assertTrue(any(e['event']=='execution_started' and e['resume_index']==1 for e in events))

    def test_retries_are_bounded_and_do_not_keep_stalled_lease_alive(self):
        agents,executors,complete=self.scenario(stalled=True)
        self.assertFalse(complete)
        events=[e for a in agents for e in a.events]
        retries=[e for e in events if e['event']=='waypoint_command_retry']
        self.assertTrue(retries)
        self.assertLessEqual(max(e['retry'] for e in retries),2)
        self.assertTrue(any(e['event']=='lease_expired' for e in events))
        self.assertFalse(any(e['event']=='work_completed' for e in events))

    def test_stale_owner_cannot_advance_checkpoint(self):
        now=[1.];bus=PerfectMessageBus(['a','b'],lambda:now[0])
        t=MissionTask('A',TaskType.SEARCH_SECTOR,Geometry((0,0,25)),1,{'search'},work_units=4)
        agent=AllocationAgent('a',['b'],bus.endpoint('a'),[t],(0,0,25))
        local=agent.tasks['A'];local.version=2;local.status=TaskStatus.ASSIGNED;local.assigned_agent='a';local.lease_expires_at=4
        bus.endpoint('b').send(new_message(MessageType.INTENT_UPDATE,'b',['a'],'phase8',1,1,
            dict(task_id='A',version=1,intent='task_progress',progress=.75,completed_waypoints=3)))
        agent.receive(1)
        self.assertEqual(agent.checkpoints.get('A',0),0)
