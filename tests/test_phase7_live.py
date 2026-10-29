import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
from agentic_uav.comm import phase7_live as live


class LiveHarnessTests(unittest.TestCase):
    def exercise(self, fail=False):
        class Clock:
            t=0.
            def monotonic(self):return self.t
            def sleep(self,dt):self.t+=max(.001,dt)
        clock=Clock()
        class Future:
            def join(self): pass
        class Client:
            def __init__(self):
                self.positions={f'Drone{i}':[i*10.,0.,28.] for i in range(1,5)}
                self.landed={v:True for v in self.positions}
                self.land_calls=[]
                self.reads=0
            def confirmConnection(self):pass
            def listVehicles(self):return list(self.positions)
            def enableApiControl(self,*a,**kw):pass
            def armDisarm(self,*a,**kw):pass
            def takeoffAsync(self,vehicle_name,**kw):
                self.positions[vehicle_name][2]=25.;self.landed[vehicle_name]=False;return Future()
            def moveToPositionAsync(self,x,y,z,vehicle_name,**kw):
                self.positions[vehicle_name]=[x,y,z];return Future()
            def hoverAsync(self,**kw):return Future()
            def landAsync(self,vehicle_name,**kw):
                self.land_calls.append(vehicle_name);self.landed[vehicle_name]=True;return Future()
            def getMultirotorState(self,vehicle_name):
                self.reads+=1
                if fail and self.positions['Drone1'][0]>10.01:raise RuntimeError('telemetry unavailable')
                p=self.positions[vehicle_name]
                return N(landed_state=0 if self.landed[vehicle_name] else 1,
                    kinematics_estimated=N(position=N(x_val=p[0],y_val=p[1],z_val=p[2]),
                                           linear_velocity=N(x_val=0,y_val=0,z_val=0)))
        client=Client()
        airsim=N(MultirotorClient=lambda **kw:client,LandedState=N(Landed=0))
        with tempfile.TemporaryDirectory() as d:
            args=N(vehicles=list(client.positions),airsim_host='local',rpc_timeout=2.,carla_host=None,
                output_dir=d,flight_height=3.,setup_timeout=5.,ticks=3,dt=.1,flight_distance=2.,flight_speed=.5)
            with patch.dict('sys.modules',{'airsim':airsim}),patch.object(live,'time',clock):
                if fail:
                    with self.assertRaises(RuntimeError):live.run_live_protocol(args)
                else:
                    live.run_live_protocol(args)
            summary=json.loads((Path(d)/'summary.json').read_text())
            beliefs=json.loads((Path(d)/'beliefs.json').read_text())
            messages=json.loads((Path(d)/'messages.json').read_text())
            self.assertEqual(set(client.land_calls),set(args.vehicles))
            return summary,beliefs,messages

    def test_four_airborne_agents_and_addressed_beliefs(self):
        summary,beliefs,messages=self.exercise()
        self.assertTrue(summary['exit_criterion_passed'])
        self.assertEqual(len(beliefs),12)
        for row in beliefs:
            self.assertEqual(len(row['team_beliefs']),3)
            self.assertNotIn(row['agent_id'],row['team_beliefs'])
            self.assertTrue(row['in_air'])
        self.assertTrue(all(r['status']=='delivered' for r in messages))
        self.assertTrue(any(r['influenced_decision'] for r in messages))

    def test_telemetry_failure_never_passes_exit(self):
        summary,_,_=self.exercise(fail=True)
        self.assertFalse(summary['exit_criterion_passed'])
        self.assertFalse(summary['completed'])
