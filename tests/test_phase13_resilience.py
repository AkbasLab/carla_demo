import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from agentic_uav.experiments.resilience import settings, RetryingEndpoint, ReachablePeerGuardian
from agentic_uav.experiments.comparison import configuration, run_comparison
from agentic_uav.experiments.architectures import ComparisonAgent, RulePolicy
from agentic_uav.policy.mission import load_mission
from agentic_uav.control.runtime_guardian import Action, State, Peer, Outcome, GuardedExecutor
from agentic_uav.comm.protocol import AgentMessage, MessageType as MT, PerfectMessageBus
from agentic_uav.comm.degraded import DegradedMessageBus, NetworkConfig, ObservedEndpoint
from agentic_uav.coordination.contract_net import TaskStatus


class ResilienceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.clock=[0.];self.m,self.gc,self.tasks,self.routes=load_mission('configs/phase12/mission.example.json')
        self.opts=settings(dict(enabled=True));self.guard=ReachablePeerGuardian(self.gc,self.opts)
        self.bus=PerfectMessageBus(list(self.m['vehicles']),lambda:self.clock[0])

    def agent(self):
        v=self.m['vehicles']['Drone1']
        opts=dict(resilience=self.opts,dynamic_roles=True,task_leases=True,persistent_memory=True,
            beacon_interval_s=.5,command_timeout_s=3,state_timeout_s=2,horizon_s=60)
        return ComparisonAgent('Drone1',['Drone2','Drone3','Drone4'],ObservedEndpoint(self.bus.endpoint('Drone1'),'Drone1',lambda:self.clock[0]),self.tasks,v['start_position'],
            role='SCOUT',routes=self.routes,home=v['home'],relay_point=self.m['relay_point'],guardian=self.guard,
            output_dir=self.tmp.name,provider=RulePolicy(),mission=self.m['mission'],architecture='C',settings=opts,
            initial_roles={a:'SCOUT' for a in self.m['vehicles']},lease_s=10,bid_window=.5,progress_timeout=1)

    def message(self,kind,sequence,payload,timestamp=0):
        return AgentMessage(f'test:{sequence}',kind,'Drone2',['Drone1'],'phase8',timestamp,sequence,5,payload)

    def state(self,peer=None):
        return State('Drone1',(0,0,-3),1,80,(0,0,-3),{'Drone2':peer or Peer((0,8,-3),(0,0,0),.5)},('Drone2',))

    def action(self):return Action('move','Drone1','MOVE',1,31,((4,0,-3),),1)

    def test_retry_traverses_partition_and_preserves_original_time_and_ttl(self):
        config=NetworkConfig(latency_ms_mean=0,latency_ms_jitter=0,
            partitions=[dict(start_s=0,end_s=.8,groups=[['Drone1'],['Drone2']])])
        bus=DegradedMessageBus(['Drone1','Drone2'],lambda:self.clock[0],config,42)
        endpoint=RetryingEndpoint(bus.endpoint('Drone2'),lambda:self.clock[0],settings(dict(retry_interval_s=.5)))
        endpoint.send(self.message(MT.TASK_AWARD,1,dict(owner='Drone2')))
        self.assertFalse(bus.endpoint('Drone1').receive_available())
        self.clock[0]=.5;endpoint.tick();self.clock[0]=1;endpoint.tick()
        received=bus.endpoint('Drone1').receive_available()
        self.assertEqual(len(received),1);self.assertEqual(received[0].timestamp,0)
        self.assertEqual(received[0].time_to_live_s,5)
        self.assertEqual([x['status'] for x in bus.logs()],['dropped','dropped','delivered'])
        self.assertEqual(len({x['sequence_number'] for x in bus.logs()}),3)

    def test_retry_is_bounded_and_cannot_resurrect_expired_message(self):
        endpoint=RetryingEndpoint(self.bus.endpoint('Drone2'),lambda:self.clock[0],settings(dict(max_attempts=2,retry_interval_s=.5)))
        m=self.message(MT.TASK_COMPLETE,1,{});m.time_to_live_s=.4
        endpoint.send(m);self.clock[0]=1;endpoint.tick();self.assertEqual(len(self.bus.logs()),1)
        self.assertFalse(self.bus.endpoint('Drone1').receive_available())
        endpoint.send(self.message(MT.TASK_COMPLETE,2,dict(x=1),timestamp=1))
        self.clock[0]=2;endpoint.tick();self.clock[0]=3;endpoint.tick()
        self.assertEqual(len(self.bus.logs()),3)

    def test_short_motion_modification_and_far_stale_peer_are_spatially_checked(self):
        state=self.state(Peer((0,30,-3),(0,0,0),0))
        d=self.guard.evaluate(self.action(),state,1)
        self.assertEqual(d.outcome,Outcome.APPROVE_WITH_MODIFICATION)
        self.assertLessEqual(d.selected_action.waypoints[0][0],1)
        state=replace(state,observed_at=3)
        d=self.guard.evaluate(replace(self.action(),issued_at=3),state,3)
        self.assertIn(d.outcome,(Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION))
        self.assertEqual(state.peers['Drone2'].observed_at,0)

    def test_stale_near_future_missing_and_excess_speed_peers_are_not_ignored(self):
        cases=[self.state(Peer((1,0,-3),(0,0,0),.5)),
            self.state(Peer((0,30,-3),(0,0,0),-5)),self.state(Peer((0,30,-3),(0,0,0),2)),
            replace(self.state(),peers={}),self.state(Peer((0,30,-3),(4,0,0),.5))]
        for state in cases:self.assertEqual(self.guard.evaluate(self.action(),state,1).outcome,Outcome.REJECT_AND_REPLAN)

    def test_collision_and_restricted_zone_cannot_be_executed(self):
        state=self.state(Peer((.3,0,-3),(0,0,0),1))
        gate=GuardedExecutor(self.guard,lambda a: self.fail('Unsafe command executed'),lambda a:True)
        gate.dispatch(self.action(),state,1)
        self.assertFalse(gate.audit[-1]['mission_effect']['executed'])
        config=replace(self.gc,keepouts=[dict(x_min=.1,x_max=2,y_min=-1,y_max=1,z_min=-4,z_max=-2)])
        guardian=ReachablePeerGuardian(config,self.opts)
        self.assertEqual(guardian.evaluate(self.action(),self.state(),1).outcome,Outcome.REJECT_AND_REPLAN)

    def test_award_reconciles_only_embedded_delivered_matching_bid_evidence(self):
        a=self.agent();payload=dict(task_id='SEARCH_SECTOR_A',version=1,owner='Drone2',score=1.)
        self.bus.endpoint('Drone2').send(self.message(MT.TASK_AWARD,1,payload))
        a.receive(0);self.assertIsNone(a.tasks['SEARCH_SECTOR_A'].assigned_agent)
        payload['bid_evidence']=dict(task_id='SEARCH_SECTOR_A',version=1,agent_id='Drone2',score=1.)
        self.bus.endpoint('Drone2').send(self.message(MT.TASK_AWARD,2,payload));a.receive(0)
        self.assertEqual(a.tasks['SEARCH_SECTOR_A'].assigned_agent,'Drone2')
        deadline=a.tasks['SEARCH_SECTOR_A'].lease_expires_at
        self.clock[0]=1;self.bus.endpoint('Drone2').send(self.message(MT.TASK_AWARD,3,payload,timestamp=1));a.receive(1)
        self.assertEqual(a.tasks['SEARCH_SECTOR_A'].lease_expires_at,deadline)

    def test_out_of_order_observations_cannot_regress_state_in_same_inbox_batch(self):
        a=self.agent();self.clock[0]=1
        for seq,stamp in [(1,1),(2,.5)]:
            self.bus.endpoint('Drone2').send(self.message(MT.STATUS_UPDATE,seq,
                dict(position=[0,8,-3],role='SCOUT',battery=80,observed_at=stamp),timestamp=stamp))
        a.receive(1);self.assertEqual(a.peer_beliefs['Drone2']['observed_at'],1)

    def test_completion_fact_requires_delivery_and_original_observation_time(self):
        a=self.agent();task=a.tasks['SEARCH_SECTOR_A'];task.version=2;task.status=TaskStatus.ASSIGNED;task.assigned_agent='Drone3'
        fact=dict(task_id=task.task_id,version=1,owner='Drone2',observed_at=0,completed_waypoints=2)
        self.bus.endpoint('Drone2').send(self.message(MT.STATUS_UPDATE,1,
            dict(position=[0,8,-3],role='SCOUT',battery=80,observed_at=0,completed_tasks=[fact])))
        self.assertEqual(task.status,TaskStatus.ASSIGNED)
        a.receive(0);self.assertEqual(task.status,TaskStatus.COMPLETE)
        self.assertEqual(a.completed_facts[task.task_id]['observed_at'],0)
        self.assertFalse(any(e['event']=='work_completed' for e in a.events))

    def test_transient_rejection_does_not_release_or_reannounce_owned_work(self):
        a=self.agent();task=a.tasks['SEARCH_SECTOR_A'];task.version=1;task.status=TaskStatus.ASSIGNED;task.assigned_agent=a.agent_id
        for now in (0,1,2):a._note_blocked(task,0,['peer_reachable_region_conflict'],now)
        self.assertEqual(a.blocked_approaches[task.task_id]['count'],0)
        self.assertFalse(a._release_blocked(task,2,None));self.assertEqual(task.version,1)

    def test_fresh_evidence_resumes_work_instead_of_releasing_temporary_block(self):
        a=self.agent();task=a.tasks['SEARCH_SECTOR_A'];task.version=1;task.status=TaskStatus.ASSIGNED
        task.assigned_agent=a.agent_id;task.lease_expires_at=10;a.claim_time[task.task_id]=0
        a.acks[task.task_id]=set(a.peers)
        a._note_blocked(task,0,['peer_reachable_region_conflict'],0)
        a.state_time=1
        for peer in a.peers:
            a.peer_beliefs[peer]=dict(position=self.m['vehicles'][peer]['start_position'],velocity=[0,0,0],observed_at=1,role='SCOUT',battery=80)
            a.last_heartbeat[peer]=1
        self.assertIsNone(a._blocked_task()[0])
        self.assertEqual(a.context(1)['decision_format']['example']['selected_tool'],'start_search')

    def test_static_route_calculation_does_not_hide_later_restricted_waypoints(self):
        a=self.agent();a.state_time=1
        for peer in a.peers:
            a.peer_beliefs[peer]=dict(position=self.m['vehicles'][peer]['start_position'],velocity=[0,0,0],observed_at=1,role='SCOUT',battery=80)
            a.last_heartbeat[peer]=1
        a.guardian=ReachablePeerGuardian(replace(self.gc,keepouts=[dict(x_min=6,x_max=9,y_min=-1,y_max=1,z_min=-4,z_max=-2)]),self.opts)
        cost=a._cost(a.tasks['SEARCH_SECTOR_A'],1)
        self.assertTrue(cost['immediate_segment_feasible'])
        self.assertFalse(cost['full_route_static_feasible']);self.assertFalse(cost['route_feasible'])

    def test_role_timeout_has_separate_deterministic_provenance(self):
        a=self.agent();a.role='RESERVE';a.initial_roles['Drone3']='RELAY'
        a.role_recommendation=lambda now: ('RELAY','RELAY_REPLACEMENT') if a.role=='RESERVE' else None
        # Bypass inference submission; this test isolates the bounded role workflow.
        a.needs_decision=lambda now:False
        gate=GuardedExecutor(a.guardian,lambda act:dict(executed=True,completed=True),lambda aid:True)
        a.poll(0,gate);self.clock[0]=1.1;a.poll(1.1,gate)
        self.assertEqual(a.role,'RELAY');self.assertEqual(a.model_decisions,0)
        event=next(e for e in a.events_policy if e['event']=='role_changed')
        self.assertEqual(event['source'],'deterministic_role_fallback')

    def test_legacy_default_is_opt_out_and_invalid_settings_are_rejected(self):
        self.assertFalse(configuration()['resilience']['enabled'])
        for invalid in [dict(max_attempts=0),dict(segment_duration_s=3),dict(unknown=True)]:
            with self.assertRaises(ValueError):configuration(dict(resilience=invalid))


if __name__=='__main__':unittest.main()
