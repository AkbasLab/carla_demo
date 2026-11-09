"""Regressions for observed seed-11/12 protocol waits and motion failures."""
from dataclasses import replace
import json
import math
import tempfile
import unittest
from unittest.mock import patch
from agentic_uav.comm.protocol import PerfectMessageBus, MessageType as MT, new_message
from agentic_uav.comm.degraded import ObservedEndpoint
from agentic_uav.coordination.contract_net import AllocationAgent, TaskStatus
from agentic_uav.coordination.approach_planner import plan_approach,segment_distance
from agentic_uav.experiments.architectures import ComparisonAgent, RulePolicy
from agentic_uav.experiments.pilot_resilience_v2 import agent_class,settings,StablePeerHealth
from agentic_uav.coordination.dynamic_roles import Health
from agentic_uav.experiments.resilience import ReachablePeerGuardian,settings as resilience_settings
from agentic_uav.policy.mission import load_mission
from agentic_uav.policy.structured import ReplayProvider,decision_example
from agentic_uav.policy.backends import MockFlight
from agentic_uav.control.runtime_guardian import GuardedExecutor,Action,Outcome,Decision,State,Peer


class RecoveryRegressions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.m,self.cfg,self.tasks,self.routes=load_mission('configs/phase12/mission.example.json')
        self.now=[0.];self.bus=PerfectMessageBus(['Drone1','Drone2'],lambda:self.now[0])
        self.guardian=ReachablePeerGuardian(self.cfg,resilience_settings({'enabled':True}),.2)
        self.executed=[]
        self.gate=GuardedExecutor(self.guardian,lambda a:self.executed.append(a) or dict(executed=True,completed=True),lambda a:True)

    def agent(self,provider=None):
        opts=dict(resilience=resilience_settings({'enabled':True}),pilot_resilience_v2=settings({'enabled':True}),
            dynamic_roles=True,task_leases=True,persistent_memory=True,beacon_interval_s=.5,
            command_timeout_s=3,state_timeout_s=2,horizon_s=240)
        cls=agent_class(ComparisonAgent)
        endpoint=ObservedEndpoint(self.bus.endpoint('Drone1'),'Drone1',lambda:self.now[0])
        a=cls('Drone1',['Drone2'],endpoint,self.tasks,[0,0,-3],role='SCOUT',routes=self.routes,
            home=(0,0,-3),relay_point=self.m['relay_point'],guardian=self.guardian,output_dir=self.temp.name,
            provider=provider or RulePolicy(),mission=self.m['mission'],architecture='C',settings=opts,
            initial_roles={'Drone1':'SCOUT','Drone2':'SCOUT'},lease_s=75,bid_window=.5)
        a.battery=80;a.last_heartbeat['Drone2']=0
        a.peer_beliefs['Drone2']=dict(position=[0,8,-3],velocity=[0,0,0],observed_at=0,role='SCOUT',battery=80)
        return a

    def own(self,a,tid='SEARCH_SECTOR_A',now=0):
        t=a.tasks[tid];t.version=1;t.status=TaskStatus.ASSIGNED;t.assigned_agent=a.agent_id;t.lease_expires_at=now+75
        a.claim_time[tid]=now-1;a.acks[tid]={a.agent_id};return t

    def test_two_closing_auctions_cannot_claim_two_tasks(self):
        a=AllocationAgent('Drone1',['Drone2'],self.bus.endpoint('Drone1'),self.tasks[:2],[0,0,-3],lease_s=75)
        for t in a.tasks.values():
            t.status=TaskStatus.BIDDING;t.version=1;a.auction_end[t.task_id]=0
            a.bids[t.task_id]={'Drone1':dict(score=1.,agent_id='Drone1')}
        a.step(0,.1,execute_mock=False)
        self.assertEqual(a.workload(),1)
        self.assertEqual(sum(x['event']=='claim_sent' for x in a.events),1)
        self.assertTrue(any(x['event']=='capacity_bid_withdrawn' for x in a.events))
        remaining=next(t for t in a.tasks.values() if t.status==TaskStatus.BIDDING)
        self.assertFalse(a.adopt(remaining,dict(task_id=remaining.task_id,version=1,owner='Drone1',score=1.),0))

    def test_withdrawn_peer_bid_is_removed(self):
        a=AllocationAgent('Drone1',['Drone2'],self.bus.endpoint('Drone1'),self.tasks[:1],[0,0,-3])
        t=next(iter(a.tasks.values()));t.status=TaskStatus.BIDDING;t.version=1
        a.bids[t.task_id]={'Drone2':dict(score=1.,agent_id='Drone2')}
        msg=new_message(MT.TASK_RELEASE,'Drone2',['Drone1'],'phase8',0,1,dict(task_id=t.task_id,version=1,reason='bid_withdrawn'),ttl=5)
        self.bus.endpoint('Drone2').send(msg);a.receive(0)
        self.assertNotIn('Drone2',a.bids[t.task_id])

    def test_ack_timeout_does_not_remove_physical_peer_or_shorten_task_lease(self):
        a=self.agent();t=self.own(a)
        self.assertIsNone(a.executable_task(2))
        a.state_time=4;a.peer_beliefs['Drone2']['observed_at']=4
        self.assertIs(a.executable_task(4),t)
        self.assertEqual(t.lease_expires_at,75)
        self.assertIn('Drone2',a.safety_state(4).peers)
        a.last_heartbeat['Drone2']=4
        self.assertIsNone(a.executable_task(4.1))  # A returned peer again requires an acknowledgment.
        a.acks[t.task_id].add('Drone2');self.assertIs(a.executable_task(4.1),t)

    def test_silent_telemetry_still_fails_closed(self):
        a=self.agent();self.own(a);a.state_time=20
        self.assertIn('Drone2',a.safety_state(20).peers)
        self.assertIn('stale_or_future_peer_belief',self.guardian._state_errors(a.safety_state(20),20))

    def test_response_for_changed_epoch_refreshes_without_execution_or_fallback(self):
        class Reply(ReplayProvider):
            def generate(self,prompt):return json.dumps(decision_example('start_search',dict(task_id='SEARCH_SECTOR_A',task_version=1)))
        a=self.agent(Reply());t=self.own(a);a.acks[t.task_id].add('Drone2')
        a.request(0);t.version=2
        a.poll(.1,self.gate)
        self.assertFalse(self.executed);self.assertEqual(a.fallback_count,0);self.assertIsNone(a.correction)
        self.assertTrue(any(x['event']=='decision_superseded' for x in a.events_policy))
        self.assertIsNone(a.pending)

    def test_detour_uses_geometry_and_live_guardian_without_changing_waypoints(self):
        a=self.agent();t=self.own(a);a.position=[6,3,-3];a.routes[t.task_id]=[[6,16,-3]]
        a.peer_beliefs['Drone2']['position']=[6,8,-3]
        route=list(a.routes[t.task_id]);target=a._motion_target(t,0,0,1)
        self.assertNotEqual(target,tuple(route[0]));self.assertEqual(a.routes[t.task_id],route)
        proposal=Action('test','Drone1','MOVE',0,30,(target,),1)
        self.assertIn(self.guardian.evaluate(proposal,a.safety_state(0),0).outcome,(Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION))
        self.assertEqual(a.executor.arrivals,[])
        # A later stale observation cannot inherit the candidate's old approval.
        a.state_time=20
        self.assertEqual(self.guardian.evaluate(Action('later','Drone1','MOVE',20,50,(target,),1),a.safety_state(20),20).outcome,Outcome.REJECT_AND_REPLAN)

    def test_no_detour_through_keepout_or_invalid_state(self):
        state=State('Drone1',(6,3,-3),0,80,(0,0,-3),{'Drone2':Peer((6,8,-3),(0,0,0),0)},('Drone2',))
        wall=dict(x_min=-10,x_max=25,y_min=4,y_max=12,z_min=-20,z_max=1)
        guardian=ReachablePeerGuardian(replace(self.cfg,keepouts=[wall]),resilience_settings({'enabled':True}),.2)
        self.assertIsNone(plan_approach(guardian,state,(6,16,-3),0,1))
        self.assertIsNone(plan_approach(self.guardian,replace(state,observed_at=-10),(6,16,-3),0,1))

    def test_physically_blocked_arrival_disk_is_not_declared_reachable(self):
        # Observed A replay: even the far edge of the allowed .4 m disk
        # cannot clear the stopped aircraft plus conservative uncertainty.
        state=State('Drone2',(6,3.5,-3),10,80,(0,8,-3),
            {'Drone1':Peer((4.4,0,-3),(0,0,0),9.8)},('Drone1',))
        self.assertIsNone(plan_approach(self.guardian,state,(6,0,-3),10,1,.4))

    def test_observed_arrival_is_recorded_before_rejecting_next_motion(self):
        a=self.agent();t=self.own(a);a.acks[t.task_id].add('Drone2')
        a.executor.key=(t.task_id,t.version);a.executor.index=0
        a._authorize(t,0,'deterministic_policy','start_search')
        a.position=list(a.routes[t.task_id][0]);a.state_time=20;self.now[0]=20
        # Telemetry is fresh for self, stale for a physical peer. This must
        # prevent the NEXT command, not erase an already observed arrival.
        a.execution_tick(20,self.gate)
        self.assertEqual(len(a.executor.arrivals),1)
        self.assertEqual(a.executor.arrivals[0]['index'],0)
        self.assertEqual(a.checkpoints[t.task_id],1)
        self.assertFalse(self.executed)
        self.assertIn('Drone2',a.safety_state(20).peers)

    def test_stale_own_observation_and_old_epoch_cannot_create_arrival(self):
        for stale in (True,False):
            a=self.agent();t=self.own(a);a.acks[t.task_id].add('Drone2')
            a.executor.key=(t.task_id,t.version if stale else t.version-1);a.executor.index=0
            a.position=list(a.routes[t.task_id][0]);a.state_time=0 if stale else 20
            a.authorized=None;self.now[0]=20
            a.execution_tick(20,self.gate)
            self.assertEqual(a.executor.arrivals,[])

    def test_cached_approach_is_replanned_when_delivered_peer_blocks_it(self):
        a=self.agent();t=self.own(a);a.position=[6,3,-3];a.routes[t.task_id]=[[6,16,-3]]
        a.peer_beliefs['Drone2']['position']=[6,5.7,-3]
        a.approach_plans[(t.task_id,1,0)]=dict(waypoints=[[6,8,-3],[6,16,-3]])
        target=a._motion_target(t,0,0,1)
        self.assertNotEqual(target,(6,8,-3))
        decision=self.guardian.evaluate(Action('replanned','Drone1','MOVE',0,30,(target,),1),a.safety_state(0),0)
        self.assertIn(decision.outcome,(Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION))
        self.assertTrue(any(e['event']=='alternative_approach_invalidated' for e in a.events_policy))

    def test_suspect_health_needs_sustained_evidence_without_changing_timeout(self):
        h=StablePeerHealth();self.assertEqual(h.tick(1.1),Health.SUSPECTED)
        h.heartbeat(1.2);self.assertEqual(h.tick(1.3),Health.SUSPECTED)
        h.heartbeat(1.7);self.assertEqual(h.tick(1.8),Health.SUSPECTED)
        h.heartbeat(2.3);self.assertEqual(h.tick(2.4),Health.HEALTHY)
        h.heartbeat(1.5);self.assertEqual(h.last_seen,2.3)  # Older packet cannot rejuvenate state.
        self.assertEqual(h.tick(5.4),Health.UNREACHABLE)
        h.heartbeat(5.5);self.assertEqual(h.tick(5.6),Health.RECOVERED)
        h.heartbeat(6.6);self.assertEqual(h.tick(6.6),Health.HEALTHY)

    def test_shorter_validated_detour_fits_energy_budget_without_relaxing_clearance(self):
        state=State('Drone1',(6,3,-3),0,
            self.cfg.min_battery_reserve_percent+22*self.cfg.battery_cost_percent_per_m,
            (0,0,-3),{'Drone2':Peer((6,8,-3),(0,0,0),0)},('Drone2',))
        plan=plan_approach(self.guardian,state,(6,16,-3),0,1)
        self.assertIsNotNone(plan)
        self.assertLessEqual(plan['distance_m'],22)
        start=state.position
        for end in plan['waypoints']:
            self.assertGreaterEqual(segment_distance(start,end,(6,8,-3)),self.cfg.min_separation_m+.1)
            start=end

    def test_real_detour_motion_renews_lease_before_straight_line_distance_improves(self):
        a=self.agent();t=self.own(a);a.acks[t.task_id].add('Drone2')
        a.lease_s=6;t.lease_expires_at=6
        a.position=[6,3,-3];a.routes[t.task_id]=[[6,16,-3]]
        a.peer_beliefs['Drone2']['position']=[6,8,-3]
        a._motion_target(t,0,0,1)
        a.executor.update(a,0)
        original=t.lease_expires_at
        # Same selected plan and stationary observations must not renew a lease.
        self.now[0]=2;a.state_time=2
        a.executor.update(a,2);self.assertEqual(t.lease_expires_at,original)
        # Measured lateral movement reduces remaining detour length while
        # increasing straight-line distance to the actual mission waypoint.
        first=a.approach_plans[(t.task_id,1,0)]['waypoints'][0]
        a.position=[6+(first[0]-6)/abs(first[0]-6),3,-3]
        self.now[0]=2.2;a.state_time=2.2
        a.executor.update(a,2.2)
        self.assertGreater(t.lease_expires_at,original)
        self.assertEqual(a.checkpoints[t.task_id],0)
        self.assertEqual(a.executor.arrivals,[])

    def test_replanning_without_movement_does_not_renew_lease(self):
        a=self.agent();t=self.own(a);a.acks[t.task_id].add('Drone2')
        a.lease_s=6;t.lease_expires_at=6;a.position=[6,3,-3];a.routes[t.task_id]=[[6,16,-3]]
        a.peer_beliefs['Drone2']['position']=[6,8,-3]
        a._motion_target(t,0,0,1);a.executor.update(a,0)
        a.approach_plans[(t.task_id,1,0)]['created_at']=2
        self.now[0]=2;a.state_time=2;a.executor.update(a,2)
        self.assertEqual(t.lease_expires_at,6)

    def test_guarded_detour_reaches_real_waypoint_without_counting_staging_points(self):
        a=self.agent();t=self.own(a);a.acks[t.task_id].add('Drone2')
        a.position=[6,3,-3];a.routes[t.task_id]=[[6,16,-3]]
        backend=MockFlight({'Drone1':dict(start_position=a.position)},lambda:self.now[0])
        gate=GuardedExecutor(self.guardian,backend.execute,backend.cancel)
        a._authorize(t,0,'deterministic_policy','start_search')
        for tick in range(350):
            now=tick*.2;self.now[0]=now
            for aid,command in backend.advance(.2):gate.confirm_completion(aid,command)
            sample=backend.sample('Drone1');a.position=sample['position'];a.velocity=sample['velocity'];a.state_time=now
            a.peer_beliefs['Drone2'].update(position=[6,8,-3],velocity=[0,0,0],observed_at=now)
            a.last_heartbeat['Drone2']=now
            gate.watchdog(a.safety_state(now),now)
            a.execution_tick(now,gate)
            if t.status==TaskStatus.COMPLETE:break
        self.assertEqual(t.status,TaskStatus.COMPLETE)
        self.assertEqual(len(a.executor.arrivals),1)
        self.assertEqual(a.executor.arrivals[0]['target'],[6,16,-3])
        self.assertTrue(any(x['event']=='alternative_approach_selected' for x in a.events_policy))

    def test_preview_approvals_do_not_reset_blockage_without_motion(self):
        a=self.agent();t=self.own(a);a.acks[t.task_id].add('Drone2')
        blocked=Decision(Outcome.REJECT_AND_REPLAN,['peer_reachable_region_conflict'])
        approved=Decision(Outcome.APPROVE,[])
        with patch.object(ComparisonAgent,'execution_tick',return_value=None),patch.object(a,'_approach',return_value=(0,(6,0,-3),blocked)):
            a.execution_tick(0,self.gate)
        with patch.object(ComparisonAgent,'execution_tick',return_value=None),patch.object(a,'_approach',return_value=(0,(6,0,-3),approved)):
            self.now[0]=10;a.state_time=10;a.peer_beliefs['Drone2']['observed_at']=10
            a.execution_tick(10,self.gate)
            self.assertEqual(a.blocked_since[(t.task_id,1,0)]['first'],0)
            self.now[0]=16;a.state_time=16;a.peer_beliefs['Drone2']['observed_at']=16
            a.execution_tick(16,self.gate)
        self.assertEqual(a.blocked_since[(t.task_id,1,0)]['blocked_elapsed_s'],0)
        self.assertEqual(t.status,TaskStatus.ASSIGNED)
        with patch.object(ComparisonAgent,'execution_tick',return_value=None),patch.object(a,'_approach',return_value=(0,(6,0,-3),blocked)):
            for now in (17,25,33):
                self.now[0]=now;a.state_time=now;a.peer_beliefs['Drone2']['observed_at']=now
                a.execution_tick(now,self.gate)
        self.assertFalse(t.status==TaskStatus.ASSIGNED and t.assigned_agent==a.agent_id)
        self.assertTrue(any(x['event']=='blocked_task_released' for x in a.events_policy))

    def test_startup_telemetry_wait_does_not_release_task_while_model_is_queued(self):
        a=self.agent();t=self.own(a);a.acks[t.task_id].add('Drone2');a.peer_beliefs={}
        with patch.object(ComparisonAgent,'execution_tick',return_value=None):a.execution_tick(0,self.gate)
        self.assertEqual(a.blocked_since[(t.task_id,1,0)]['kind'],'state_wait')
        for now in (1,16,35):
            self.now[0]=now;a.state_time=now;a.request_waiting_since=1
            a.peer_beliefs['Drone2']=dict(position=[0,8,-3],velocity=[0,0,0],observed_at=now,role='SCOUT',battery=80)
            with patch.object(ComparisonAgent,'execution_tick',return_value=None):a.execution_tick(now,self.gate)
        self.assertEqual(t.status,TaskStatus.ASSIGNED)
        self.assertFalse(any(x['event']=='blocked_task_released' for x in a.events_policy))
        self.assertTrue(any(x['event']=='state_wait_resolved' for x in a.events_policy))

    def test_geometric_timer_does_not_consume_inflight_decision_time(self):
        a=self.agent();t=self.own(a);a.acks[t.task_id].add('Drone2')
        blocked=Decision(Outcome.REJECT_AND_REPLAN,['peer_reachable_region_conflict'])
        with patch.object(ComparisonAgent,'execution_tick',return_value=None),patch.object(a,'_approach',return_value=(0,(6,0,-3),blocked)):
            a.execution_tick(0,self.gate)
            a.pending={'token':'inflight'}
            for now in (1,10,25):
                self.now[0]=now;a.state_time=now;a.peer_beliefs['Drone2']['observed_at']=now
                a.execution_tick(now,self.gate)
        self.assertEqual(t.status,TaskStatus.ASSIGNED)
        self.assertEqual(a.blocked_since[(t.task_id,1,0)]['blocked_elapsed_s'],0)

    def test_idle_correction_does_not_prevent_bounded_geometric_release(self):
        a=self.agent();t=self.own(a);a.acks[t.task_id].add('Drone2')
        blocked=Decision(Outcome.REJECT_AND_REPLAN,['peer_reachable_region_conflict'])
        a.correction={'reason':'unsafe_action'}  # No admitted or in-flight request.
        with patch.object(ComparisonAgent,'execution_tick',return_value=None),patch.object(a,'_approach',return_value=(0,(6,0,-3),blocked)):
            for now in (0,5,10,16):
                self.now[0]=now
                a.state_time=now;a.peer_beliefs['Drone2']['observed_at']=now
                a.execution_tick(now,self.gate)
        self.assertNotEqual(t.status,TaskStatus.ASSIGNED)
        self.assertIn('Drone2',a.safety_state(16).peers)

    def test_repeated_rejected_decisions_release_without_fabricating_work(self):
        a=self.agent();t=self.own(a);a.acks[t.task_id].add('Drone2')
        details=dict(task_id=t.task_id,task_version=1,index=0,reasons=['peer_reachable_region_conflict'])
        with patch.object(ComparisonAgent,'_failure',return_value=None):
            for now in (0,1,2):
                self.now[0]=now;a.state_time=now;a.peer_beliefs['Drone2']['observed_at']=now
                a._failure('unsafe_action:peer_reachable_region_conflict',now,self.gate,True,details)
        self.assertNotEqual(t.status,TaskStatus.ASSIGNED)
        self.assertFalse(any(e['event']=='work_completed' for e in a.events))
        self.assertIn('Drone2',a.safety_state(2).peers)
        self.assertTrue(any(e.get('source')=='v2_repeated_guardian_rejection' for e in a.events_policy))

    def test_arrival_region_is_not_enlarged_to_escape_peer_occupancy(self):
        state=State('Drone1',(6,8,-3),0,80,(0,0,-3),{'Drone2':Peer((3,0,-3),(0,0,0),-.4)},('Drone2',))
        plan=plan_approach(self.guardian,state,(6,0,-3),0,1,arrival_tolerance=.4)
        self.assertIsNotNone(plan)
        self.assertLessEqual(math.dist(plan['arrival_point'],(6,0,-3)),.4)
        self.assertNotEqual(tuple(plan['arrival_point']),(6,0,-3))
        self.assertEqual(tuple(plan['required_waypoint']),(6,0,-3))

    def test_rejection_cache_rebuilt_when_authorization_clears_it_within_log_interval(self):
        a=self.agent();t=self.own(a)
        reasons=['peer_reachable_region_conflict']
        a._note_blocked(t,0,reasons,0)
        a.blocked_approaches.pop(t.task_id)  # Successful start_search clears this cache.
        a._note_blocked(t,0,reasons,.2)
        self.assertEqual(a.blocked_approaches[t.task_id]['key'],(t.task_id,1,0))
        self.assertEqual(a.blocked_since[(t.task_id,1,0)]['first'],0)


if __name__=='__main__':unittest.main()
