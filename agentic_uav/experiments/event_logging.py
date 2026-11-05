"""Scoped, streaming experiment instrumentation; never installed by Phase 13."""
from collections import Counter
from contextlib import ExitStack, contextmanager
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import patch
from agentic_uav.comm.protocol import MessageType as MT

EVENT_TYPES = ('MISSION_STARTED','OBSERVATION_RECEIVED','BELIEF_UPDATED','MESSAGE_SENT',
    'MESSAGE_DROPPED','MESSAGE_RECEIVED','TASK_ANNOUNCED','TASK_BID','TASK_ASSIGNED',
    'TASK_RELEASED','ROLE_CHANGED','LLM_CALLED','DECISION_PROPOSED','GUARDIAN_INTERVENED',
    'SKILL_STARTED','SKILL_COMPLETED','TARGET_FOUND','FAULT_INJECTED','MISSION_COMPLETED')


def utc_now():return datetime.now(timezone.utc).isoformat()


class EventLog:
    def __init__(self,path,experiment_id,attempt_id):
        self.path=Path(path);self.experiment_id=experiment_id;self.attempt_id=attempt_id
        self.counts=Counter();self.sequence=0

    def emit(self,event_type,simulation_time_s=None,agent_id=None,**data):
        self.sequence+=1;self.counts[event_type]+=1
        record=dict(schema_version=1,event_id=f'{self.attempt_id}:{self.sequence}',
            experiment_id=self.experiment_id,attempt_id=self.attempt_id,event_type=event_type,
            wall_time_utc=utc_now(),simulation_time_s=simulation_time_s,agent_id=agent_id,data=data)
        # Each record is closed/flushed immediately, including during a failed run.
        with self.path.open('a') as stream:stream.write(json.dumps(record,allow_nan=False,sort_keys=True)+'\n')


@contextmanager
def instrument(comparison,log):
    """Install observers in this process only; always restore original classes.

    Serial runner only. Infrastructure observes transport outcomes; agents still
    see only their delivered inboxes. No events are synthesized for absent paths.
    """
    class LoggedBus(comparison.DegradedMessageBus):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);self.recorded_drops=set()
        def log_drops(self,records):
            for r in records:
                key=(r['message_id'],r['recipient_id'])
                if r['status'] in ('dropped','expired') and key not in self.recorded_drops:
                    self.recorded_drops.add(key)
                    log.emit('MESSAGE_DROPPED',self._clock(),sender=r['sender_id'],recipient=r['recipient_id'],
                        message_id=r['message_id'],message_type=r['message_type'],status=r['status'],
                        reason=r.get('drop_reason'),created_at=r['creation_time'],expires_at=r['expires_at'])
        def _send(self,agent_id,message):
            start=len(self._log)
            result=super()._send(agent_id,message)
            log.emit('MESSAGE_SENT',self._clock(),agent_id,message_id=message.message_id,
                message_type=message.message_type.value,recipients=message.recipient_ids,
                created_at=message.timestamp,expires_at=message.timestamp+message.time_to_live_s,
                envelope=json.loads(message.to_json()))
            self.log_drops(self._log[start:]);return result
        def _receive(self,agent_id):
            records=[r for _,r in self._queues[agent_id]]
            messages=super()._receive(agent_id)
            for m in messages:
                log.emit('MESSAGE_RECEIVED',self._clock(),agent_id,message_id=m.message_id,
                    message_type=m.message_type.value,sender=m.sender_id,created_at=m.timestamp,envelope=json.loads(m.to_json()))
                if m.message_type==MT.STATUS_UPDATE:
                    log.emit('OBSERVATION_RECEIVED',self._clock(),agent_id,source='delivered_status',
                        message_id=m.message_id,sender=m.sender_id,observation=m.payload)
                if m.message_type==MT.TARGET_FOUND:
                    log.emit('TARGET_FOUND',self._clock(),agent_id,source='delivered_report',
                        message_id=m.message_id,sender=m.sender_id,payload=m.payload)
            self.log_drops(records);return messages

    def agent_class(base):
        class LoggedAgent(base):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs)
                for task in self.tasks.values():
                    if task.assigned_agent==self.agent_id:
                        log.emit('TASK_ASSIGNED',0.,self.agent_id,task_id=task.task_id,owner=self.agent_id,
                            version=task.version,authority='initial operator briefing')
            def log(self,name,now,**data):
                super().log(name,now,**data)
                event={'task_announced':'TASK_ANNOUNCED','bid_computed':'TASK_BID',
                    'task_released':'TASK_RELEASED','losing_claim_released':'TASK_RELEASED'}.get(name)
                if event:log.emit(event,now,self.agent_id,source_event=name,details=data)
            def record(self,name,now,**data):
                super().record(name,now,**data)
                if name=='role_changed':log.emit('ROLE_CHANGED',now,self.agent_id,**data)
                elif name in ('policy_error','structured_correction_requested','inference_timeout','late_response_discarded','inference_abandoned_at_shutdown'):
                    log.emit('POLICY_EVENT',now,self.agent_id,source_event=name,details=data)
            def adopt(self,task,claim,now):
                before=(task.status,task.assigned_agent,task.version)
                result=super().adopt(task,claim,now)
                if result and before!=(task.status,task.assigned_agent,task.version):
                    log.emit('TASK_ASSIGNED',now,self.agent_id,task_id=task.task_id,
                        owner=task.assigned_agent,version=task.version,authority='delivered-message contract net')
                return result
            def receive(self,now):
                before=copy.deepcopy(self.peer_beliefs)
                assignments={t.task_id:(t.status,t.assigned_agent,t.version) for t in self.tasks.values()}
                super().receive(now)
                for peer,belief in self.peer_beliefs.items():
                    if before.get(peer)!=belief:log.emit('BELIEF_UPDATED',now,self.agent_id,
                        peer=peer,previous=before.get(peer),current=belief,source='delivered_inbox')
                if self.architecture=='A':
                    for t in self.tasks.values():
                        if assignments[t.task_id]!=(t.status,t.assigned_agent,t.version) and t.assigned_agent==self.agent_id:
                            log.emit('TASK_ASSIGNED',now,self.agent_id,task_id=t.task_id,
                                owner=t.assigned_agent,version=t.version,authority='delivered controller command')
            def request(self,now):
                before=self.request_number
                try:return super().request(now)
                finally:
                    if self.request_number!=before:
                        kind='LLM_CALLED' if self.policy_source=='llm' else 'POLICY_CALLED'
                        log.emit(kind,now,self.agent_id,request_id=f'{self.agent_id}:{self.request_number}',
                            provider=self.policy_source,prompt_path=f'run/{self.agent_id}/prompts.jsonl')
            def apply(self,decision,now,gate):
                log.emit('DECISION_PROPOSED',now,self.agent_id,decision=decision,source=self.policy_source,
                    request_id=f'{self.agent_id}:{self.request_number}' if self.policy_source=='llm' else None)
                return super().apply(decision,now,gate)
        return LoggedAgent

    class LoggedController(comparison.FleetController):
        def receive(self,now):
            before=copy.deepcopy(self.states);super().receive(now)
            for peer,state in self.states.items():
                if before.get(peer)!=state:log.emit('BELIEF_UPDATED',now,'FleetController',
                    peer=peer,previous=before.get(peer),current=state,source='delivered_inbox')
        def step(self,now):
            start=len(self.events);super().step(now)
            for event in self.events[start:]:
                kind={'central_assignment':'TASK_ASSIGNED','central_lease_expired':'TASK_RELEASED'}.get(event['event'])
                if kind:log.emit(kind,now,'FleetController',authority='central_controller_ledger',details=event)

    class LoggedGate(comparison.GuardedExecutor):
        def _record(self,proposal,state,now,decision,effect):
            super()._record(proposal,state,now,decision,effect)
            if decision.outcome.value!='APPROVE':
                log.emit('GUARDIAN_INTERVENED',now,state.vehicle_id,audit=self.audit[-1])

    class LoggedFlight(comparison.MockFlight):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            log.emit('MISSION_STARTED',self.clock(),vehicles=list(self.states),backend='mock')
            for aid,state in self.states.items():
                log.emit('OBSERVATION_RECEIVED',self.clock(),aid,source='own_telemetry',observation=state)
        def execute(self,action):
            result=super().execute(action)
            if result.get('executed'):log.emit('SKILL_STARTED',self.clock(),action.vehicle_id,
                command_id=action.command_id,kind=action.kind,source=action.source)
            return result
        def advance(self,dt):
            done=super().advance(dt)
            for aid,cid in done:log.emit('SKILL_COMPLETED',self.clock(),aid,command_id=cid,source='mock_observed_completion')
            return done
        def cancel(self,aid):
            active=self.active.get(aid);result=super().cancel(aid)
            if active and result:log.emit('SKILL_CANCELLED',self.clock(),aid,command_id=active['action'].command_id)
            return result

    class LoggedSchedule(comparison.ExperimentSchedule):
        def advance(self,now):
            result=super().advance(now)
            for aid in result:log.emit('FAULT_INJECTED',now,aid,fault='actor_silenced')
            return result

    classes=dict(DegradedMessageBus=LoggedBus,ComparisonAgent=agent_class(comparison.ComparisonAgent),
        FixedTaskAgent=agent_class(comparison.FixedTaskAgent),FleetController=LoggedController,GuardedExecutor=LoggedGate,
        MockFlight=LoggedFlight,ExperimentSchedule=LoggedSchedule)
    with ExitStack() as stack:
        for name,cls in classes.items():stack.enter_context(patch.object(comparison,name,cls))
        yield
