"""Opt-in Phase 13 v2 transport and bounded-horizon safety model.

Every retry traverses the original degraded channel. Unknown peers are never
removed: reachable balls use an explicit, enforced fleet speed bound. These are
mock-model assumptions, not a live flight or collision-avoidance certification.
"""
import copy
from dataclasses import replace
import json
import math
from agentic_uav.comm.protocol import AgentMessage, MessageType as MT
from agentic_uav.control.runtime_guardian import RuntimeGuardian, Outcome, Decision, point, Peer, finite

DEFAULT_RESILIENCE = dict(enabled=False, retry_interval_s=1., max_attempts=6,
    segment_duration_s=1., peer_prediction_limit_s=5.)


def settings(value=None):
    result=dict(DEFAULT_RESILIENCE)
    if value is not None:
        if not isinstance(value,dict) or set(value)-set(result):raise ValueError('Unknown resilience settings')
        result.update(value)
    if type(result['enabled']) is not bool:raise ValueError('Invalid resilience enabled flag')
    if type(result['max_attempts']) is not int or not 1<=result['max_attempts']<=12:raise ValueError('Invalid retry bound')
    for key in ('retry_interval_s','segment_duration_s','peer_prediction_limit_s'):
        if type(result[key]) not in (int,float) or not math.isfinite(result[key]) or result[key]<=0:raise ValueError(key)
    if result['segment_duration_s']>2:raise ValueError('Motion segments must be at most two seconds')
    return result


class RetryingEndpoint:
    """Local bounded repeats; no queue inspection, hidden delivery or freshened TTL.

    Packet sequence/ID differs for each attempt; the semantic transaction payload
    and original creation/expiry times do not. Existing version/owner checks and
    TASK_ACCEPT acknowledgments remain the authority for task execution.
    """
    CRITICAL={MT.TASK_ANNOUNCEMENT,MT.TASK_BID,MT.TASK_AWARD,MT.TASK_ACCEPT,
              MT.TASK_RELEASE,MT.TASK_COMPLETE,MT.ROLE_CHANGE}
    def __init__(self,endpoint,clock,config):
        self.endpoint=endpoint;self.clock=clock;self.config=config
        self.sequence=0;self.pending={};self.events=[]

    def _transmit(self,item):
        m=AgentMessage.from_json(item['message'].to_json())
        self.sequence+=1;item['attempts']+=1
        m.sequence_number=self.sequence
        m.message_id=f'{item["message"].message_id}:tx:{self.sequence}'
        item['last_send']=self.clock();item['last_id']=m.message_id
        self.endpoint.send(m)
        if item['attempts']>1:self.events.append(dict(event='bounded_retry',time_s=self.clock(),
            message_type=m.message_type.value,transaction_id=item['message'].message_id,
            packet_id=m.message_id,attempt=item['attempts'],original_timestamp=m.timestamp,
            original_expiration=m.timestamp+m.time_to_live_s))
        return m.message_id

    def send(self,message):
        m=AgentMessage.from_json(message.to_json())
        key=json.dumps([m.message_type.value,m.recipient_ids,m.payload],sort_keys=True)
        previous=self.pending.get(key)
        # Suppress repeated identical acknowledgments inside one retry interval.
        if m.message_type in self.CRITICAL and previous and self.clock()-previous['last_send']<self.config['retry_interval_s']:
            return previous['last_id']
        item=dict(message=m,attempts=0,last_send=-math.inf)
        result=self._transmit(item)
        if m.message_type in self.CRITICAL:
            self.pending[key]=item
            while len(self.pending)>128:self.pending.pop(next(iter(self.pending)))
        return result

    def tick(self):
        now=self.clock()
        for key,item in list(self.pending.items()):
            m=item['message']
            if now>=m.timestamp+m.time_to_live_s or item['attempts']>=self.config['max_attempts']:
                self.pending.pop(key,None);continue
            if now-item['last_send']>=self.config['retry_interval_s']-1e-8:self._transmit(item)

    def receive_available(self):return self.endpoint.receive_available()
    def estimates(self):return self.endpoint.estimates()


class ReachablePeerGuardian(RuntimeGuardian):
    """Check short commands against speed-bounded peer reachable balls.

    At future t, a peer is anywhere within vmax*(observation_age+t) of its
    last observed position. No assumption that a stale peer stopped or continued
    at constant velocity. Every peer remains in state and in the audit record.
    """
    def __init__(self,config,resilience,minimum_segment_s=.1):
        super().__init__(config);self.resilience=copy.deepcopy(resilience);self.minimum_segment_s=minimum_segment_s

    def _state_errors(self,state,now):
        errors=super()._state_errors(state,now)
        if 'stale_or_future_peer_belief' in errors:
            # Permit bounded extrapolation only for valid, nonfuture observations.
            if all(isinstance(p,Peer) and finite(p.observed_at) and 0<=now-p.observed_at<=self.resilience['peer_prediction_limit_s'] for p in state.peers.values()):
                errors=[e for e in errors if e!='stale_or_future_peer_belief']
        if isinstance(getattr(state,'peers',None),dict) and any(isinstance(p,Peer) and point(p.velocity) and math.sqrt(sum(v*v for v in p.velocity))>self.config.max_speed_mps+1e-6 for p in state.peers.values()):
            errors.append('peer_speed_bound_exceeded')
        return errors

    def _route_errors(self,a,state,now,emergency=False,safe_layer=False):
        # Retain all original geometry, energy and command checks; replace the
        # constant-velocity separation approximation with a reachable-ball test.
        errors=super()._route_errors(a,replace(state,peers={},expected_peers=()),now,emergency,safe_layer)
        start=tuple(state.position);elapsed=0.;vmax=self.config.max_speed_mps
        for end in self._route(a,state):
            duration=max(self.minimum_segment_s,math.dist(start,end)/a.speed_mps or a.duration_s)
            for peer in state.peers.values():
                if not point(peer.position):continue  # Invalid peers fail _state_errors first.
                delta=tuple(end[i]-start[i] for i in range(3));length2=sum(x*x for x in delta)
                fraction=max(0.,min(1.,sum((peer.position[i]-start[i])*delta[i] for i in range(3))/length2)) if length2 else 0.
                closest=tuple(start[i]+fraction*delta[i] for i in range(3))
                # End-of-segment radius overapproximates the entire swept interval.
                radius=vmax*(now-peer.observed_at+elapsed+duration)
                if math.dist(closest,peer.position)<self.config.min_separation_m+radius:
                    errors.append('peer_reachable_region_conflict')
            elapsed+=duration;start=end
        return sorted(set(errors))

    def evaluate(self,proposal,state,now,active_command=None,last_plan=None):
        errors=self._state_errors(state,now)
        if errors:return Decision(Outcome.REJECT_AND_REPLAN,errors)
        if self._action_errors(proposal,state,now):return super().evaluate(proposal,state,now,active_command,last_plan)
        original=proposal
        horizons=[self.resilience['segment_duration_s']]
        while horizons[-1]>self.minimum_segment_s+1e-8:horizons.append(max(self.minimum_segment_s,horizons[-1]/2))
        decision=None
        for horizon in horizons:
            candidate=original
            if original.kind=='MOVE':
                target=tuple(original.waypoints[0]);distance=math.dist(state.position,target)
                limit=min(original.speed_mps,self.config.max_speed_mps)*horizon
                if distance>limit:
                    target=tuple(state.position[i]+(target[i]-state.position[i])*limit/distance for i in range(3))
                candidate=replace(original,waypoints=(target,))
            elif original.kind=='HOLD':candidate=replace(original,duration_s=min(original.duration_s,horizon))
            decision=super().evaluate(candidate,state,now,active_command,last_plan)
            if decision.outcome in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION):
                if candidate!=original:
                    decision.outcome=Outcome.APPROVE_WITH_MODIFICATION
                    decision.reasons=list(dict.fromkeys(decision.reasons+['bounded_motion_segment']))
                return decision
            if 'peer_reachable_region_conflict' not in decision.reasons:break
        return decision
