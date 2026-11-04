"""Deadline and separation regressions derived from the real easy_run3 failure."""
import json
from contextlib import redirect_stdout
from dataclasses import replace
import io
import tempfile
from unittest.mock import patch
import unittest
import test_phase12_agents as fixtures
from agentic_uav.coordination.contract_net import TaskStatus
from agentic_uav.policy.evidence import admit_requests,policy_evidence
from agentic_uav.policy.structured import PolicyError,ReplayProvider
from agentic_uav.control.runtime_guardian import Action
from agentic_uav.policy.persistent import PersistentAgent
from run_phase12_agents import run,parse_args


class RecoveryTests(unittest.TestCase):
    setUp=fixtures.AgentTests.setUp

    def fresh(self,now):
        self.clock[0]=now
        for a in self.agents:
            a.state_time=now
            for p in a.peers:
                peer=next(b for b in self.agents if b.agent_id==p)
                a.last_heartbeat[p]=now
                a.peer_beliefs[p].update(position=list(peer.position),velocity=[0,0,0],observed_at=now)

    def owned(self,tid='SEARCH_SECTOR_A',now=3):
        t=self.a.tasks[tid];t.status=TaskStatus.ASSIGNED;t.assigned_agent=self.a.agent_id
        t.version=1;t.lease_expires_at=1000
        self.a.claim_time[tid]=0;self.a.acks[tid]=set(self.a.peers)
        self.fresh(now)
        return t

    def open_d(self):
        for a in self.agents:
            a.bid_window=30
            for t in a.tasks.values():
                if t.task_id!='SEARCH_SECTOR_D':t.status=TaskStatus.COMPLETE
        self.a.position=[8,0,-3];self.fresh(90)
        for a in self.agents:a.announce(a.tasks['SEARCH_SECTOR_D'],90,1)

    def test_late_queued_nearby_bid_is_submitted_before_deadline_and_wins(self):
        self.open_d();self.fresh(103)
        self.a._bid(self.a.tasks['SEARCH_SECTOR_D'],103)
        drone4=self.agents[3];drone4.deadline_bidding=True
        drone4.inference_estimate=10;drone4.inference_admission_delay_s=22.2
        self.fresh(113);drone4._deadline_bids(113)
        bid=drone4.bids['SEARCH_SECTOR_D']['Drone4']
        self.assertLess(bid['score'],self.a.bids['SEARCH_SECTOR_D']['Drone1']['score'])
        log=next(e for e in drone4.events_policy if e['event']=='deadline_bid_submitted')
        self.assertEqual(log['deadline'],120);self.assertEqual(log['remaining_s'],7)
        self.assertEqual(log['source'],'deterministic_deadline_guard')
        for a in self.agents:a.receive(113)
        self.fresh(120)
        for a in self.agents:a.protocol_tick(120,.2)
        for a in self.agents:a.receive(120)
        self.assertTrue(all(a.tasks['SEARCH_SECTOR_D'].assigned_agent=='Drone4' for a in self.agents))
        self.assertEqual(drone4.model_decisions,0)  # No fabricated LLM credit.

    def test_deadline_guard_leaves_time_for_llm_when_budget_is_sufficient(self):
        self.open_d();a=self.agents[3];a.deadline_bidding=True
        a.inference_estimate=5;a.inference_admission_delay_s=2
        self.fresh(100);a._deadline_bids(100)
        self.assertNotIn(a.agent_id,a.bids['SEARCH_SECTOR_D'])
        self.fresh(113);a._deadline_bids(113)
        self.assertIn(a.agent_id,a.bids['SEARCH_SECTOR_D'])
        a._deadline_bids(113)
        self.assertEqual(sum(e['event']=='deadline_bid_submitted' for e in a.events_policy),1)

    def test_deadline_guard_does_not_bid_after_close_or_with_stale_telemetry(self):
        self.open_d();a=self.agents[3];a.deadline_bidding=True
        a._deadline_bids(113)  # Own/peer measurements are still at t=90.
        self.assertNotIn(a.agent_id,a.bids['SEARCH_SECTOR_D'])
        self.fresh(121);a._deadline_bids(121)
        self.assertNotIn(a.agent_id,a.bids['SEARCH_SECTOR_D'])

    def test_admission_hint_accounts_for_jobs_ahead_without_reading_beliefs(self):
        class Waiting:
            def __init__(self,name):
                self.agent_id=name;self.authorized=None;self.identity_fault=False;self.pending=None
                self.worker=None;self.last_request=-float('inf');self.decision_interval=1
                self.request_waiting_since=None;self.inference_estimate=10
            def request(self,now):self.pending={'context_time':now};self.last_request=now
        aa=[Waiting('Drone'+str(i)) for i in range(1,5)]
        admit_requests(aa,0,1)
        self.assertEqual([a.inference_admission_delay_s for a in aa],[0,10,20,30])
        self.assertEqual(sum(a.pending is not None for a in aa),1)

    def test_explicit_decline_is_not_undone_by_deadline_guard(self):
        self.open_d();a=self.agents[3];a.deadline_bidding=True
        a.apply(fixtures.decision('decline_task',dict(task_id='SEARCH_SECTOR_D',task_version=1,reason_code='TASK_UNSUITABLE')),90,self.gate)
        self.fresh(113);a._deadline_bids(113)
        self.assertNotIn(a.agent_id,a.bids['SEARCH_SECTOR_D'])
        self.assertNotIn('send_bid',a.context(113)['available_tools'])
        a.announce(a.tasks['SEARCH_SECTOR_D'],113,2)
        a._deadline_bids(113)
        self.assertIn(a.agent_id,a.bids['SEARCH_SECTOR_D'])  # A new epoch permits reevaluation.

    def test_feasibility_is_rechecked_when_peer_moves_after_cost_was_computed(self):
        t=self.owned()
        self.assertTrue(self.a._cost(t,3)['route_feasible'])
        self.agents[1].position=[2,0,-3];self.fresh(4)
        with self.assertRaises(PolicyError) as error:
            self.a.apply(fixtures.decision('start_search',dict(task_id=t.task_id,task_version=1)),4,self.gate)
        self.assertIn('drone_separation',str(error.exception));self.assertFalse(self.executed)
        self.assertIsNone(self.a.authorized)
        self.assertEqual(self.a.blocked_approaches[t.task_id]['count'],1)
        context=self.a.context(4)
        self.assertFalse(context['approach_validation']['feasible'])
        self.assertNotIn('start_search',context['available_tools'])
        self.assertEqual(context['decision_format']['example']['selected_tool'],'release_task')

    def test_approach_preview_respects_configured_speed_below_one(self):
        t=self.owned();self.guardian.config=replace(self.cfg,max_speed_mps=.5)
        self.assertTrue(self.a.context(3)['approach_validation']['feasible'])
        self.a.apply(fixtures.decision('start_search',dict(task_id=t.task_id,task_version=1)),3,self.gate)
        self.assertEqual(self.executed[-1].speed_mps,.5)

    def test_correction_example_releases_blocked_work_instead_of_repeating_motion(self):
        t=self.owned();self.agents[1].position=[2,0,-3];self.fresh(3)
        with self.assertRaises(PolicyError) as error:
            self.a.apply(fixtures.decision('start_search',dict(task_id=t.task_id,task_version=1)),3,self.gate)
        self.a._failure(str(error.exception),3,self.gate,True,details=error.exception.details)
        c=self.a.correction
        self.assertEqual(c['example']['selected_tool'],'release_task')
        self.assertEqual(c['example']['parameters']['reason_code'],'SAFETY_ROUTE_BLOCKED')
        self.assertIn('do not repeat',c['instruction'])
        self.assertEqual(c['validation_details']['recovery_tool'],'release_task')

    def test_repeated_identical_rejection_releases_and_reannounces_new_epoch(self):
        t=self.owned();self.agents[1].position=[2,0,-3];self.fresh(3)
        for n in range(2):
            with self.assertRaises(PolicyError) as error:
                self.a.apply(fixtures.decision('start_search',dict(task_id=t.task_id,task_version=1)),3,self.gate)
            self.a._failure(str(error.exception),3,self.gate,True)
        self.assertEqual(t.version,2);self.assertEqual(t.status,TaskStatus.BIDDING)
        self.assertIsNone(t.assigned_agent);self.assertFalse(self.executed)
        self.assertIsNone(self.a.correction)
        self.assertEqual(sum(e['event']=='blocked_task_released' for e in self.a.events_policy),1)
        self.a._bid(t,3)
        self.assertNotIn(self.a.agent_id,self.a.bids[t.task_id])  # Owner cooldown.
        with self.assertRaises(PolicyError):
            self.a.apply(fixtures.decision('start_search',dict(task_id=t.task_id,task_version=1)),3,self.gate)

    def test_ignoring_corrected_tool_catalog_also_triggers_bounded_recovery(self):
        t=self.owned();self.agents[1].position=[2,0,-3];self.fresh(3)
        class Stubborn(ReplayProvider):
            def generate(self,prompt):return json.dumps(fixtures.decision('start_search',dict(task_id=t.task_id,task_version=1)))
        self.a.provider=Stubborn()
        # First request was made before the hazard appeared, so search had been offered.
        self.agents[1].position=[0,8,-3];self.fresh(3);self.a.request(3)
        self.agents[1].position=[2,0,-3];self.fresh(3);self.a.poll(3,self.gate)
        self.a.request(3);self.a.poll(3,self.gate)
        self.assertEqual(t.status,TaskStatus.BIDDING);self.assertEqual(t.version,2)
        self.assertFalse(any(a.kind=='MOVE' for a in self.executed))

    def test_release_waits_for_cancellation_acknowledgment(self):
        t=self.owned()
        active=Action('possibly_active','Drone1','MOVE',3,30,((4,0,-3),),1)
        self.gate.active['Drone1']=active;self.gate.cancel_action=lambda vehicle:False
        self.assertFalse(self.a._release_blocked(t,3,self.gate))
        self.assertEqual(t.status,TaskStatus.ASSIGNED);self.assertEqual(t.version,1)
        self.assertFalse(any(e['event']=='blocked_task_released' for e in self.a.events_policy))

    def test_peer_can_take_over_and_finish_released_task_using_delivered_messages(self):
        # Mirror Sector D recovery with other drones already holding their final positions.
        self.a.position=[8,0,-3];self.agents[1].position=[8,8,-3];self.agents[2].position=[8,16,-3]
        t=self.owned('SEARCH_SECTOR_D')
        for a in self.agents[1:]:
            peer_task=a.tasks[t.task_id];peer_task.status=TaskStatus.ASSIGNED;peer_task.assigned_agent='Drone1'
            peer_task.version=1;peer_task.lease_expires_at=1000
            for other in a.tasks.values():
                if other.task_id!=t.task_id:other.status=TaskStatus.COMPLETE
        for _ in range(2):
            with self.assertRaises(PolicyError) as error:
                self.a.apply(fixtures.decision('start_search',dict(task_id=t.task_id,task_version=1)),3,self.gate)
            self.a._failure(str(error.exception),3,self.gate,True)
        drone4=self.agents[3]
        self.assertEqual(drone4.tasks[t.task_id].version,1)  # No hidden global update.
        drone4.receive(3)
        self.assertEqual(drone4.tasks[t.task_id].version,2)
        drone4._bid(drone4.tasks[t.task_id],3)
        for a in self.agents:a.receive(3)
        self.fresh(5)
        for a in self.agents:a.protocol_tick(5,.2)
        for a in self.agents:a.receive(5)
        self.assertTrue(all(a.tasks[t.task_id].assigned_agent=='Drone4' for a in self.agents))
        self.fresh(7.2);drone4.request_number=1
        result=drone4.apply(fixtures.decision('start_search',dict(task_id=t.task_id,task_version=2)),7.2,self.gate)
        self.assertEqual(result['status'],'search_authorized')
        for now,position in [(8,[4,24,-3]),(9,[8,24,-3])]:
            drone4.position=position;self.fresh(now);drone4.execution_tick(now,self.gate)
        self.assertEqual(drone4.tasks[t.task_id].status,TaskStatus.COMPLETE)
        self.assertEqual(len(drone4.executor.arrivals),2)
        self.assertTrue(all(a['authorization_source']=='replay_fixture' for a in drone4.executor.arrivals))

    def test_single_slow_model_queue_still_completes_all_four_lanes(self):
        class ContextReplay(ReplayProvider):
            def generate(self,prompt):return json.dumps(json.loads(prompt)['decision_format']['example'])
        class DelayedAgent(PersistentAgent):
            def __init__(self,*args,**kwargs):
                kwargs['deadline_bidding']=True
                super().__init__(*args,**kwargs)
            def poll(self,now,gate):
                if self.pending and now-self.pending['context_time']<9:return
                if self.pending:self.pending['inline_result']['latency_s']=9
                super().poll(now,gate)
        with tempfile.TemporaryDirectory() as tmp,redirect_stdout(io.StringIO()):
            args=parse_args(['--ticks','1500','--inference-timeout','30','--max-context-age','35',
                '--lease-seconds','180','--bid-window','30','--output-dir',tmp+'/run'])
            with patch('run_phase12_agents.PersistentAgent',DelayedAgent),patch('run_phase12_agents.admit_requests',lambda agents,now,capacity:admit_requests(agents,now,1)):
                summary=run(args,provider=ContextReplay())
        self.assertTrue(summary['mission_complete']);self.assertIsNone(summary['error'])
        self.assertEqual(summary['duplicate_task_completions'],0)
        self.assertTrue(all(n>0 for n in summary['productive_decisions_by_agent'].values()))
        self.assertEqual(sum(summary['fallbacks_by_agent'].values()),0)
        self.assertGreater(sum(summary['deadline_bids_by_agent'].values()),0)
        self.assertTrue(summary['all_dispatched_actions_guarded'])
        self.assertFalse(summary['llm_exit_criterion_observed'])  # Synthetic timing, not actual inference.


if __name__=='__main__':unittest.main()
