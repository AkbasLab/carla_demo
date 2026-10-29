import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
from agentic_uav.comm.protocol import PerfectMessageBus
from agentic_uav.coordination.contract_net import AllocationAgent,MissionTask,TaskType,TaskStatus,Geometry
from agentic_uav.coordination.flight_executor import WaypointExecutor
from agentic_uav.coordination import phase8_live as live


class ExecutorTests(unittest.TestCase):
    def agent(self):
        bus=PerfectMessageBus(['a','b'],lambda:3.)
        a=AllocationAgent('a',['b'],bus.endpoint('a'),[MissionTask('A',TaskType.SEARCH_SECTOR,Geometry((1,0,25)),1,{'search'})],(0,0,25),lease_s=10)
        t=a.tasks['A'];t.version=1;t.status=TaskStatus.ASSIGNED;t.assigned_agent='a';t.lease_expires_at=10
        a.claim_time['A']=-1;a.acks['A']={'a','b'}
        return a

    def test_stalled_vehicle_does_not_complete_or_renew(self):
        a=self.agent();e=WaypointExecutor({'A':[[1,0,25],[2,0,25]]},.1)
        e.update(a,0)
        for now in [1,2,3,4,5]:e.update(a,now)
        self.assertEqual(a.tasks['A'].status,TaskStatus.ASSIGNED)
        self.assertEqual(a.tasks['A'].lease_expires_at,10)
        self.assertEqual(e.arrivals,[])

    def test_observed_arrivals_and_revocation(self):
        a=self.agent();e=WaypointExecutor({'A':[[1,0,25],[2,0,25]]},.1)
        self.assertEqual(e.update(a,0)['action'],'move')
        a.position=[1,0,25];e.update(a,1)
        self.assertEqual(len(e.arrivals),1)
        a.tasks['A'].assigned_agent='b'
        self.assertTrue(e.update(a,2)['revoked'])
        self.assertNotEqual(a.tasks['A'].status,TaskStatus.COMPLETE)

    def test_complete_requires_every_waypoint(self):
        a=self.agent();e=WaypointExecutor({'A':[[1,0,25],[2,0,25]]},.1)
        e.update(a,0);a.position=[2,0,25];e.update(a,1)
        self.assertEqual(len(e.arrivals),0)
        a.position=[1,0,25];e.update(a,2)
        a.position=[2,0,25];e.update(a,3)
        self.assertEqual(a.tasks['A'].status,TaskStatus.COMPLETE)


class LiveIntegrationTests(unittest.TestCase):
    def exercise(self,failed):
        class Clock:
            t=0.
            def monotonic(self):return self.t
            def sleep(self,dt):self.t+=max(dt,.001)
        clock=Clock()
        class Future:
            def join(self):pass
        class Air:
            def __init__(self):
                self.pos={f'Drone{i}':[0.,0.,28.] for i in range(1,5)}
                self.landed={a:True for a in self.pos};self.holds=[]
            def confirmConnection(self):pass
            def listVehicles(self):return list(self.pos)
            def enableApiControl(self,*a,**kw):pass
            def armDisarm(self,*a,**kw):pass
            def takeoffAsync(self,vehicle_name,**kw):self.landed[vehicle_name]=False;self.pos[vehicle_name][2]=25.;return Future()
            def moveToPositionAsync(self,x,y,z,vehicle_name,**kw):self.pos[vehicle_name]=[x,y,z];return Future()
            def hoverAsync(self,vehicle_name):self.holds.append(vehicle_name);return Future()
            def landAsync(self,vehicle_name,**kw):self.landed[vehicle_name]=True;return Future()
            def getMultirotorState(self,vehicle_name):
                p=self.pos[vehicle_name]
                return N(landed_state=0 if self.landed[vehicle_name] else 1,kinematics_estimated=N(
                    position=N(x_val=p[0],y_val=p[1],z_val=p[2]),linear_velocity=N(x_val=0,y_val=0,z_val=0)))
        air=Air();api=N(MultirotorClient=lambda **kw:air,LandedState=N(Landed=0))
        with tempfile.TemporaryDirectory() as d:
            args=N(mission_config='configs/phase8/carlaair.example.json',fail_agent='Drone1' if failed else None,
                fail_at=.8,airsim_host='local',rpc_timeout=2,output_dir=d,carla_host=None,
                flight_height=3,speed=1,setup_timeout=5,dt=.1,arrival_tolerance=.1,lease_seconds=1.5,
                bid_window=.2,no_conflict_injection=False,ticks=300,waypoint_timeout=10,landing_confirm_timeout=1)
            with patch.dict('sys.modules',{'airsim':api}),patch.object(live,'time',clock):s=live.run_live(args)
            arrivals=json.loads((Path(d)/'waypoint_arrivals.json').read_text())
            self.assertTrue(s['mission_complete'])
            self.assertEqual(s['duplicate_task_completions'],0)
            self.assertGreaterEqual(len(arrivals),16)
            self.assertEqual(s['cleanup_errors'],[])
            if failed:
                self.assertEqual(s['failed_agents'],['Drone1'])
                self.assertIn('Drone1',air.holds)
            return s

    def test_live_dispatch_and_completion(self):self.exercise(False)
    def test_failed_agent_holds_and_survivors_finish(self):self.exercise(True)
