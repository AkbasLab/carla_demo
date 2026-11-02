import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from agentic_uav.control.runtime_guardian import (Action,Config,State,Peer,RuntimeGuardian,
    GuardedExecutor,Outcome,Fallback)
from run_phase11_guardian import run


class GuardianTests(unittest.TestCase):
    def setUp(self):
        self.config=Config(**json.loads(Path('configs/phase11/guardian.example.json').read_text()))
        self.guardian=RuntimeGuardian(self.config)
        self.state=State('Drone1',(0,0,-5),0,80,(-4,0,-5))
        self.action=Action('one','Drone1','MOVE',0,30,((8,0,-5),),1)
        self.executed=[]
        self.gate=GuardedExecutor(self.guardian,lambda a:self.executed.append(a) or dict(executed=True,completed=True),lambda v:True)

    def test_valid_and_modified_commands(self):
        self.assertEqual(self.guardian.evaluate(self.action,self.state,0).outcome,Outcome.APPROVE)
        d=self.guardian.evaluate(replace(self.action,speed_mps=9),self.state,0)
        self.assertEqual(d.outcome,Outcome.APPROVE_WITH_MODIFICATION)
        self.assertEqual(d.selected_action.speed_mps,5)

    def test_all_waypoints_and_segments(self):
        for route,reason in [(((8,8,-5),),'restricted_zone'),(((21,0,-5),),'geofence'),
                              (((1,0,-5),(3,3,-5)),'restricted_zone')]:
            d=self.guardian.evaluate(replace(self.action,waypoints=route),self.state,0)
            self.assertIn(reason,d.reasons);self.assertIsNone(d.selected_action)

    def test_malformed_and_identity_inputs(self):
        for a in [dict(kind='MOVE'),replace(self.action,vehicle_id='Drone2'),replace(self.action,waypoints=((float('nan'),0,0),)),
                  replace(self.action,speed_mps=0),replace(self.action,kind='UNKNOWN'),replace(self.action,issued_at=1),
                  replace(self.action,issued_at=-1)]:
            d=self.gate.dispatch(a,self.state,0)
            self.assertEqual(d.outcome,Outcome.REJECT_AND_REPLAN)
        self.assertFalse(self.executed)
        json.dumps(self.gate.audit,allow_nan=False)

    def test_battery_fallbacks_and_energy_budget(self):
        d=self.guardian.evaluate(self.action,replace(self.state,battery_percent=15),0)
        self.assertEqual(d.fallback,Fallback.RETURN_HOME)
        d=self.guardian.evaluate(self.action,replace(self.state,battery_percent=8),0)
        self.assertEqual(d.fallback,Fallback.LAND_AT_SAFE_LOCATION)
        d=self.guardian.evaluate(self.action,replace(self.state,battery_percent=1),0)
        self.assertIsNone(d.selected_action)
        self.assertIn('no_verified_safe_fallback',d.reasons)

    def test_safe_layer_reentry(self):
        d=self.guardian.evaluate(self.action,replace(self.state,position=(0,0,-22)),0)
        self.assertEqual(d.fallback,Fallback.CLIMB_OR_DESCEND_TO_SAFE_LAYER)
        self.assertEqual(d.selected_action.waypoints,((0,0,-20),))
        # Reentry must not bypass the geofence or restricted volumes.
        d=self.guardian.evaluate(self.action,replace(self.state,position=(30,0,-22)),0)
        self.assertIsNone(d.selected_action)

    def test_peer_separation_including_crossing_motion(self):
        for peer in [Peer((4,0,-5),(0,0,0),0),Peer((4,-4,-5),(0,1,0),0)]:
            state=replace(self.state,peers={'Drone2':peer},expected_peers=('Drone2',))
            d=self.guardian.evaluate(self.action,state,0)
            self.assertIn('drone_separation',d.reasons)
            self.assertIsNone(d.selected_action)

    def test_no_blind_hold_with_unsafe_local_hazard(self):
        state=replace(self.state,communication='LOST',peers={'Drone2':Peer((1,0,-5),(0,0,0),0)})
        d=self.guardian.evaluate(self.action,state,0)
        self.assertIsNone(d.selected_action)
        self.assertEqual(d.fallback_rejections[0]['reasons'],['drone_separation'])

    def test_stale_missing_beliefs_and_low_confidence(self):
        for state in [replace(self.state,observed_at=-2),replace(self.state,expected_peers=('Drone2',)),
                      replace(self.state,peers={'Drone2':Peer((10,0,-5),(0,0,0),-2)})]:
            self.assertIsNone(self.guardian.evaluate(self.action,state,0).selected_action)
        d=self.guardian.evaluate(self.action,replace(self.state,belief_confidence=.1,battery_percent=15),0)
        self.assertEqual(d.fallback,Fallback.HOLD_POSITION)

    def test_landing_location_and_descent_corridor(self):
        land=replace(self.action,kind='LAND',waypoints=())
        self.assertEqual(self.guardian.evaluate(land,self.state,0).outcome,Outcome.APPROVE)
        self.assertIsNone(self.guardian.evaluate(land,replace(self.state,position=(5,0,-5)),0).selected_action)
        cfg=replace(self.config,landing_site={**self.config.landing_site,'surveyed_clear':False})
        self.assertIn('landing_site_not_surveyed_clear',RuntimeGuardian(cfg).evaluate(land,self.state,0).reasons)
        cfg=replace(self.config,keepouts=[dict(x_min=-.2,x_max=.2,y_min=-.2,y_max=.2,z_min=-2,z_max=-1)])
        self.assertIsNone(RuntimeGuardian(cfg).evaluate(land,self.state,0).selected_action)

    def test_last_plan_revalidated_and_original_deadline_preserved(self):
        expired=replace(self.action,command_id='expired',valid_until=.5)
        d=self.guardian.evaluate(expired,replace(self.state,communication='DEGRADED'),1,last_plan=self.action)
        self.assertEqual(d.fallback,Fallback.CONTINUE_LAST_VALID_PLAN)
        d=self.guardian.evaluate(expired,replace(self.state,communication='DEGRADED',observed_at=3),3,last_plan=self.action)
        self.assertEqual(d.fallback,Fallback.HOLD_POSITION)  # Last plan creation time is too old.

    def test_conflict_replay_and_watchdog_cancellation(self):
        canceled=[];executed=[]
        gate=GuardedExecutor(self.guardian,lambda a:executed.append(a) or dict(executed=True,completed=False),lambda v:canceled.append(v) or True)
        gate.dispatch(self.action,self.state,0)
        d=gate.dispatch(replace(self.action,command_id='two'),self.state,0)
        self.assertEqual(d.reasons,['conflicting_simultaneous_command'])
        self.assertEqual(len(executed),1)
        d=gate.watchdog(replace(self.state,observed_at=31),31)
        self.assertEqual(canceled,['Drone1']);self.assertEqual(d.fallback,Fallback.HOLD_POSITION)
        self.gate.dispatch(self.action,self.state,0)
        self.assertEqual(self.gate.dispatch(self.action,self.state,0).reasons,['replayed_command'])

    def test_runtime_comm_loss_and_failed_cancellation(self):
        gate=GuardedExecutor(self.guardian,lambda a:dict(executed=True,completed=False),lambda v:False)
        gate.dispatch(self.action,self.state,0)
        d=gate.watchdog(replace(self.state,communication='LOST'),0)
        self.assertIn('cancellation_unconfirmed',d.reasons)
        self.assertIsNone(d.selected_action)
        self.assertIn('Drone1',gate.active)

    def test_grounded_phase_and_no_implicit_takeoff(self):
        state=replace(self.state,position=(0,0,0),flight_phase='GROUNDED')
        d=self.guardian.evaluate(self.action,state,0)
        self.assertEqual(d.fallback,Fallback.HOLD_POSITION)
        takeoff=replace(self.action,kind='TAKEOFF',waypoints=((0,0,-5),))
        self.assertEqual(self.guardian.evaluate(takeoff,state,0).outcome,Outcome.APPROVE)

    def test_simultaneous_crossing_reservations(self):
        gate=GuardedExecutor(self.guardian,lambda a:dict(executed=True,completed=False),lambda v:True)
        # Each move would be safe against a stationary peer, but together they cross.
        first=replace(self.action,waypoints=((6,0,-5),))
        s1=replace(self.state,peers={'Drone2':Peer((10,0,-5),(0,0,0),0)})
        self.assertEqual(gate.dispatch(first,s1,0).outcome,Outcome.APPROVE)
        second=replace(self.action,vehicle_id='Drone2',command_id='two',waypoints=((4,0,-5),))
        s2=replace(self.state,vehicle_id='Drone2',position=(10,0,-5),peers={'Drone1':Peer((0,0,-5),(0,0,0),0)})
        d=gate.dispatch(second,s2,0)
        self.assertIn('conflicting_reserved_trajectory',d.reasons)
        self.assertIsNone(d.selected_action)

    def test_executor_failure_blocks_concurrent_dispatch(self):
        def fail(action):raise TimeoutError('unknown transport result')
        gate=GuardedExecutor(self.guardian,fail,lambda v:False)
        gate.dispatch(self.action,self.state,0)
        self.assertEqual(gate.audit[-1]['mission_effect']['status'],'execution_unconfirmed')
        self.assertIn('Drone1',gate.active)
        self.assertEqual(gate.dispatch(replace(self.action,command_id='other'),self.state,0).reasons,['conflicting_simultaneous_command'])

    def test_watchdog_hard_duration_and_completion_identity(self):
        gate=GuardedExecutor(self.guardian,lambda a:dict(executed=True,completed=False),lambda v:True)
        gate.dispatch(replace(self.action,valid_until=1000),self.state,0)
        self.assertFalse(gate.confirm_completion('Drone1','wrong-id'))
        d=gate.watchdog(replace(self.state,observed_at=31),31)
        self.assertEqual(d.fallback,Fallback.HOLD_POSITION)
        active=gate.active['Drone1']
        self.assertTrue(gate.confirm_completion('Drone1',active.command_id))
        self.assertIsNone(gate.watchdog(replace(self.state,observed_at=32),32))

    def test_injection_harness_and_separate_finite_audit(self):
        with tempfile.TemporaryDirectory() as tmp,redirect_stdout(io.StringIO()):
            summary=run(tmp,self.config)
            self.assertTrue(summary['exit_criterion_passed'])
            self.assertEqual(summary['unsafe_original_actions_executed'],0)
            self.assertEqual(summary['valid_controls_approved'],4)
            self.assertTrue(summary['all_five_fallbacks_exercised'])
            self.assertGreater(summary['unsafe_proposals'],30)
            audit=json.loads((Path(tmp)/'guardian_audit.json').read_text())
            self.assertEqual(set(summary['outcomes']),{o.value for o in Outcome})
            for row in audit:
                self.assertIn('mission_effect',row)
                if row['outcome']==Outcome.REJECT_AND_REPLAN.value:self.assertFalse(row['mission_effect']['executed'])
