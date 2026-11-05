"""Four authority/coordination choices; one guarded motion and message implementation."""
import copy
import json
import math
from agentic_uav.comm.protocol import AgentMessage,MessageType as MT
from agentic_uav.coordination.contract_net import TaskStatus,bid_cost
from agentic_uav.coordination.dynamic_roles import PeerHealth,Health
from agentic_uav.policy.persistent import PersistentAgent
from agentic_uav.policy.structured import ReplayProvider,PolicyError,decision_example
from agentic_uav.control.runtime_guardian import Action
from dataclasses import replace

CONTROLLER='FleetController'
BID_WEIGHTS=dict(distance=1.,battery=5.,workload=20.,communication=5.,mismatch=100.)


class RulePolicy(ReplayProvider):
    """Same structured tools/calculations as D; deterministic selection, no inference."""
    def verify(self):return dict(provider='deterministic',model=None,digest=None,options={},llm_inference=False)
    def generate(self,prompt):
        c=json.loads(prompt)
        return json.dumps(c['decision_format']['example'])


class ComparisonAgent(PersistentAgent):
    def __init__(self,*args,architecture,settings,initial_roles,**kwargs):
        super().__init__(*args,**kwargs)
        self.architecture=architecture;self.settings=settings;self.initial_roles=copy.deepcopy(initial_roles)
        self.peer_health={p:PeerHealth() for p in self.peers};self.health_seen={p:-math.inf for p in self.peers}
        self.last_beacon={};self.last_communication_fallback=-math.inf;self.completed_facts={}
        if isinstance(self.provider,RulePolicy):self.policy_source='deterministic_policy'

    def emit(self,kind,payload,now,recipients):
        self.sequence+=1
        self.endpoint.send(AgentMessage(f'phase13:{self.agent_id}:{self.sequence}',kind,self.agent_id,
            list(recipients),'phase8',now,self.sequence,max(5.,self.lease_s*2),payload))

    def send(self,kind,payload,now):
        if kind in (MT.HEARTBEAT,MT.STATUS_UPDATE):
            if now-self.last_beacon.get(kind,-math.inf)<self.settings['beacon_interval_s']-1e-8:return
            self.last_beacon[kind]=now
        if self.settings.get('resilience',{}).get('enabled') and kind==MT.TASK_AWARD:
            payload=dict(payload,bid_evidence=copy.deepcopy(self.bids.get(payload['task_id'],{}).get(self.agent_id)))
        if self.settings.get('resilience',{}).get('enabled') and kind==MT.STATUS_UPDATE:
            payload=dict(payload,completed_tasks=list(self.completed_facts.values()))
        super().send(kind,payload,now)
        if self.architecture=='A' and kind==MT.STATUS_UPDATE:
            reports=[dict(task_id=t.task_id,version=t.version,status=t.status.value,completed_waypoints=self.checkpoints.get(t.task_id,0))
                for t in self.tasks.values() if t.assigned_agent==self.agent_id or t.status==TaskStatus.COMPLETE]
            self.emit(kind,dict(**payload,work_reports=reports),now,[CONTROLLER])

    def communication_inputs(self,now):
        estimates=self.endpoint.estimates()
        for peer,h in self.peer_health.items():
            previous=h.state
            timestamp=self.last_heartbeat.get(peer,-math.inf)
            if timestamp>self.health_seen[peer]:
                h.heartbeat(timestamp);self.health_seen[peer]=timestamp
            h.tick(now)
            if h.state!=previous:self.record('peer_health_changed',now,peer=peer,previous=previous.value,state=h.state.value)
        # Same locally observed health inputs for C and D; never configured loss probability.
        risks=[min(1.,max(0.,now-self.last_heartbeat.get(p,0))/3) for p in self.peers]
        self.communication_risk=max(risks,default=0.)
        return estimates

    def role_recommendation(self,now):
        if self.architecture not in ('C','D') or not self.settings['dynamic_roles']:return None
        if self.battery<self.guardian.config.min_battery_reserve_percent:
            return ('RESERVE','LOW_BATTERY') if self.role!='RESERVE' else None
        unavailable={p for p,h in self.peer_health.items() if h.state in (Health.UNREACHABLE,Health.FAILED,Health.RECOVERED)}
        relay_required='RELAY' in self.initial_roles.values()
        if relay_required:
            # Initial role briefing is known, but missing early telemetry is not evidence of relay loss.
            if any(self.initial_roles[p]=='RELAY' and p not in self.peer_beliefs and p not in unavailable for p in self.peers):return None
            candidates=[]
            for aid in [self.agent_id]+self.peers:
                if aid in unavailable:continue
                state=dict(role=self.role,battery=self.battery,position=self.position) if aid==self.agent_id else self.peer_beliefs.get(aid)
                if not state or state.get('battery',0)<self.guardian.config.min_battery_reserve_percent:continue
                rank={'RELAY':0,'RESERVE':1,'SCOUT':2}[state['role']]
                candidates.append((rank,math.dist(state['position'],self.relay_point),aid))
            relay=min(candidates)[2] if candidates else None
            if relay==self.agent_id and self.role!='RELAY':return 'RELAY','RELAY_REPLACEMENT'
            if relay!=self.agent_id and self.role=='RELAY':return 'SCOUT','RELAY_ALREADY_COVERED'
        if self.role=='RESERVE' and unavailable:return 'SCOUT','PEER_UNREACHABLE'
        return None

    def protocol_tick(self,now,dt):
        self.communication_inputs(now)
        self.freeze_lease_expiry()
        super().protocol_tick(now,dt)
        self.freeze_lease_expiry()

    def freeze_lease_expiry(self):
        if self.architecture=='D' and not self.settings['task_leases']:
            for task in self.tasks.values():
                if task.status==TaskStatus.ASSIGNED:task.lease_expires_at=self.settings['horizon_s']+1

    def _monotonic_observations(self,messages,now):
        newest={p:v['observed_at'] for p,v in self.peer_beliefs.items()}
        heartbeat=dict(self.last_heartbeat);result=[]
        for m in messages:
            if m.sender_id in self.peers and m.mission_id=='phase8':
                if m.message_type==MT.STATUS_UPDATE:
                    observed=m.payload.get('observed_at',m.timestamp)
                    vectors=[m.payload.get('position'),m.payload.get('velocity',[0,0,0])]
                    valid=(type(observed) in (int,float) and math.isfinite(observed) and 0<=observed<=m.timestamp and
                        all(isinstance(v,list) and len(v)==3 and all(type(x) in (int,float) and math.isfinite(x) for x in v) for v in vectors) and
                        m.payload.get('role') in ('SCOUT','RELAY','RESERVE'))
                    if not valid:continue
                    if observed<newest.get(m.sender_id,-math.inf):
                        self.record('older_status_ignored',now,peer=m.sender_id,observed_at=observed);continue
                    newest[m.sender_id]=observed
                elif m.message_type==MT.HEARTBEAT:
                    if m.timestamp<heartbeat.get(m.sender_id,-math.inf):continue
                    heartbeat[m.sender_id]=m.timestamp
            result.append(m)
        return result

    def receive(self,now):
        if not self.settings.get('resilience',{}).get('enabled'):
            super().receive(now);self.freeze_lease_expiry();return
        endpoint=self.endpoint;delivered=[]
        for message in self._monotonic_observations(endpoint.receive_available(),now):
            if message.sender_id not in self.peers or message.mission_id!='phase8':
                delivered.append(message);continue
            p=message.payload
            if message.message_type==MT.STATUS_UPDATE:
                observed=p.get('observed_at',message.timestamp)
                if type(observed) not in (int,float) or not math.isfinite(observed):continue
                for fact in p.get('completed_tasks',[]):
                    self.accept_completion_fact(fact,message,now)
                if observed<self.peer_beliefs.get(message.sender_id,{}).get('observed_at',-math.inf):
                    self.record('older_status_ignored',now,peer=message.sender_id,observed_at=observed);continue
            if message.message_type==MT.HEARTBEAT and message.timestamp<self.last_heartbeat.get(message.sender_id,-math.inf):continue
            if message.message_type==MT.TASK_AWARD and p.get('owner')==message.sender_id:
                task=self.tasks.get(p.get('task_id'));bid=p.get('bid_evidence');version=p.get('version')
                valid=(task is not None and task.status!=TaskStatus.COMPLETE and type(version) is int and
                    isinstance(bid,dict) and bid.get('agent_id')==message.sender_id and
                    bid.get('task_id')==task.task_id and bid.get('version')==version and
                    type(bid.get('score')) in (int,float) and math.isfinite(bid['score']) and
                    bid['score']>=0 and bid['score']==p.get('score'))
                if valid and version>=task.version:
                    if version>task.version:
                        task.version=version;task.status=TaskStatus.BIDDING;task.assigned_agent=None;task.lease_expires_at=None
                        self.bids[task.task_id]={};self.claims.pop(task.task_id,None)
                        self.auction_end[task.task_id]=message.timestamp
                    self.bids.setdefault(task.task_id,{})[message.sender_id]=copy.deepcopy(bid)
                    self.record('delivered_bid_evidence_reconciled',now,task_id=task.task_id,version=version,
                        message_id=message.message_id)
            delivered.append(message)
        class Inbox:
            def receive_available(inner):return delivered
            def send(inner,m):return endpoint.send(m)
        self.endpoint=Inbox()
        try:super().receive(now)
        finally:self.endpoint=endpoint
        self.freeze_lease_expiry()

    def safety_state(self,now):
        state=super().safety_state(now)
        if not self.settings.get('resilience',{}).get('enabled'):return state
        # Fresh status is also a contact observation; never replace its source time
        # with receive time, or let a missed heartbeat override delivered telemetry.
        ages=[now-max(self.last_heartbeat.get(p,0),self.peer_beliefs.get(p,{}).get('observed_at',0)) for p in self.peers]
        oldest=max(ages,default=0)
        return replace(state,communication='LOST' if oldest>3 else 'DEGRADED' if oldest>1 else 'HEALTHY')

    def poll(self,now,gate):
        self._gate_busy=self.agent_id in gate.active
        if self.settings.get('resilience',{}).get('enabled'):
            recommendation=self.role_recommendation(now)
            if recommendation!=getattr(self,'_role_waiting_for',None):
                self._role_waiting_for=recommendation;self._role_wait_started=now
            if recommendation and now-self._role_wait_started>=self.progress_timeout:
                source=self.policy_source
                try:
                    self.policy_source='deterministic_role_fallback'
                    self.apply(decision_example('change_role',dict(new_role=recommendation[0],reason_code=recommendation[1])),now,gate)
                    self.record('role_deadline_fallback',now,new_role=recommendation[0],source=self.policy_source)
                except PolicyError as error:self.record('role_fallback_deferred',now,reason_code=str(error))
                finally:self.policy_source=source
                self._role_wait_started=now
        return super().poll(now,gate)

    def adopt(self,task,claim,now):
        result=super().adopt(task,claim,now);self.freeze_lease_expiry();return result

    def report_execution(self,*args,**kwargs):
        result=super().report_execution(*args,**kwargs)
        if result and kwargs.get('complete') and self.settings.get('resilience',{}).get('enabled'):
            task_id,version,now=args[:3]
            self.completed_facts[task_id]=dict(task_id=task_id,version=version,owner=self.agent_id,
                observed_at=now,completed_waypoints=len(self.routes[task_id]))
        self.freeze_lease_expiry();return result

    def accept_completion_fact(self,fact,message,now):
        # Trusted-team, delivered completion certificates are terminal work facts,
        # even if local lease knowledge has advanced. They do not fabricate local
        # work_completed events or grant another actor execution authority.
        if not isinstance(fact,dict):return
        task=self.tasks.get(fact.get('task_id'))
        if task is None or task.task_id in self.completed_facts:return
        if fact.get('owner') not in self.peers or type(fact.get('version')) is not int or fact['version']<1:return
        observed=fact.get('observed_at')
        if type(observed) not in (int,float) or not math.isfinite(observed) or not 0<=observed<=message.timestamp:return
        if type(fact.get('completed_waypoints')) is not int or fact['completed_waypoints']!=len(self.routes[task.task_id]):return
        self.completed_facts[task.task_id]=copy.deepcopy(fact)
        task.status=TaskStatus.COMPLETE;task.lease_expires_at=None
        self.checkpoints[task.task_id]=len(self.routes[task.task_id])
        self.log('delivered_completion_reconciled',now,task_id=task.task_id,owner=fact['owner'],
            original_version=fact['version'],original_observation_time=observed)
        self.decisions.append(message.message_id)

    def _tool_candidates(self,now):
        candidates=super()._tool_candidates(now)
        candidates.pop('change_role',None)
        recommendation=self.role_recommendation(now)
        if recommendation:candidates['change_role']=[dict(new_role=recommendation[0],reason_code=recommendation[1])]
        return candidates

    TEMPORARY_SAFETY_REASONS={'peer_reachable_region_conflict','stale_or_future_peer_belief',
        'communication_or_belief_uncertainty','missing_peer_beliefs','no_verified_safe_fallback'}

    def _temporary_rejection(self,reasons):
        return self.settings.get('resilience',{}).get('enabled') and bool(reasons) and set(reasons)<=self.TEMPORARY_SAFETY_REASONS

    def _note_blocked(self,task,index,reasons,now):
        if self._temporary_rejection(reasons):
            self.blocked_approaches[task.task_id]=dict(key=(task.task_id,task.version,index),
                reasons=tuple(sorted(set(reasons))),count=0,observed_at=now)
            self.record('temporary_approach_wait',now,task_id=task.task_id,version=task.version,reasons=reasons)
            return
        return super()._note_blocked(task,index,reasons,now)

    def _blocked_task(self):
        if not self.settings.get('resilience',{}).get('enabled'):return super()._blocked_task()
        for tid,blocked in self.blocked_approaches.items():
            task=self.tasks[tid]
            if self._temporary_rejection(blocked.get('reasons',[])):continue
            if task.status==TaskStatus.ASSIGNED and task.assigned_agent==self.agent_id and blocked['key'][1]==task.version:
                return task,blocked
        return None,None

    def _cost(self,task,now):
        result=super()._cost(task,now)
        if self.settings.get('resilience',{}).get('enabled'):
            # Full-route geometry/energy is a deterministic calculation; only the
            # immediately executable segment can be assessed against live peers.
            route=self.routes[task.task_id][self.checkpoints.get(task.task_id,0):]
            action=Action(f'static_cost:{self.agent_id}:{now}',self.agent_id,'MOVE',now,now+30,
                tuple(tuple(p) for p in route),min(1.,self.guardian.config.max_speed_mps))
            state=replace(self.safety_state(now),peers={},expected_peers=())
            errors=self.guardian._route_errors(action,state,now)
            result['full_route_static_feasible']=not errors
            result['immediate_segment_feasible']=result['route_feasible']
            result['route_feasible']=result['route_feasible'] and not errors
            result['guardian_reasons']=sorted(set(result['guardian_reasons']+errors))
            result['separation_risk']='peer_reachable_region_conflict' in result['guardian_reasons']
            result['future_segments_require_revalidation']=True
        return result

    def _release_blocked(self,task,now,gate,source='deterministic_safety_recovery'):
        blocked=self.blocked_approaches.get(task.task_id,{})
        if self._temporary_rejection(blocked.get('reasons',[])):
            self.record('transient_release_deferred',now,task_id=task.task_id);return False
        return super()._release_blocked(task,now,gate,source)

    def _example(self,now,candidates):
        if 'change_role' in candidates:return decision_example('change_role',candidates['change_role'][0])
        task=self.executable_task(now)
        if task is not None and self.settings.get('resilience',{}).get('enabled'):
            _,_,preview=self._approach(task,now)
            if self._temporary_rejection(preview.reasons):return decision_example('hold',candidates['hold'][0])
        return super()._example(now,candidates)

    def needs_decision(self,now):
        if self.settings.get('resilience',{}).get('enabled') and getattr(self,'_gate_busy',False):return False
        # Acquire initial safety beacons before spending inference on a known-incomplete context.
        if len(self.peer_beliefs)<len(self.peers) and now<self.guardian.config.max_peer_age_s:return False
        return self.role_recommendation(now) is not None or super().needs_decision(now)

    def context(self,now):
        c=super().context(now)
        c['communication_estimate']=self.communication_inputs(now)
        c['peer_health']={p:h.state.value for p,h in self.peer_health.items()}
        c['architecture']=self.architecture
        if self.settings.get('resilience',{}).get('enabled'):
            recommendation=self.role_recommendation(now)
            if recommendation:
                c['role_recovery_requirement']=dict(new_role=recommendation[0],reason_code=recommendation[1],
                    instruction='Resolve the observed missing role with change_role; subsequent positioning still requires runtime assurance.',
                    deterministic_fallback_after_s=self.progress_timeout)
                c['unresolved_decisions'].insert(0,dict(goal='RESOLVE_MISSING_ROLE',new_role=recommendation[0],reason_code=recommendation[1]))
        if not self.settings['persistent_memory']:c['memory']=[]
        return c

    def apply(self,decision,now,gate):
        if self.settings.get('resilience',{}).get('enabled') and decision['selected_tool']=='hold' and self.agent_id in gate.active:
            return dict(status='existing_guarded_command_in_progress')
        if decision['selected_tool']=='change_role':
            recommended=self.role_recommendation(now);p=decision['parameters']
            if not recommended or p['new_role']!=recommended[0]:raise PolicyError('role_change_not_locally_justified')
            if p['new_role']!='SCOUT':
                self._stop_motion(gate)
                for task in list(self.tasks.values()):
                    if task.status==TaskStatus.ASSIGNED and task.assigned_agent==self.agent_id:self.release_task(task.task_id,now)
                    elif self.agent_id in self.bids.get(task.task_id,{}):
                        self.bids[task.task_id].pop(self.agent_id,None)
                        self.send(MT.TASK_RELEASE,dict(task_id=task.task_id,version=task.version,reason='bid_withdrawn'),now)
            previous=self.role;self.role=p['new_role']
            self.send(MT.ROLE_CHANGE,dict(role=self.role,reason_code=p['reason_code']),now)
            self.record('role_changed',now,previous=previous,role=self.role,source=self.policy_source)
            return dict(status='role_changed',role=self.role)
        return super().apply(decision,now,gate)

class FixedTaskAgent(ComparisonAgent):
    """A's vehicle or B's independent policy: no peer allocation/negotiation API."""
    LOCAL_TOOLS={'compute_task_cost','accept_task','start_search','go_to_waypoint','hold','return_home','release_task','decline_task'}
    def __init__(self,*args,initial_task_ids=(),horizon=100,**kwargs):
        super().__init__(*args,**kwargs)
        self.control_until=-math.inf;self.refused_epochs=set();self.timeout_latched=False;self.controller_timestamps={}
        for tid in initial_task_ids:
            task=self.tasks[tid];task.status=TaskStatus.ASSIGNED;task.assigned_agent=self.agent_id
            task.version=1;task.lease_expires_at=horizon+1
            self.claim_time[tid]=-self.bid_window;self.acks[tid]=set(self.peers)
        self.initial_task_ids=set(initial_task_ids)

    def receive(self,now):
        delivered=self.endpoint.receive_available();beacons=[]
        for message in delivered:
            if message.mission_id!='phase8':continue
            p=message.payload
            if message.sender_id in self.peers and message.message_type in (MT.HEARTBEAT,MT.STATUS_UPDATE):beacons.append(message)
            elif self.architecture=='A' and message.sender_id==CONTROLLER and message.message_type==MT.TASK_AWARD:
                task=self.tasks.get(p.get('task_id'));version=p.get('version');deadline=p.get('lease_expires_at')
                if task is None or type(version) is not int or version<task.version or p.get('owner')!=self.agent_id:continue
                if type(deadline) not in (int,float) or not math.isfinite(deadline) or deadline<=now:continue
                if now>=message.timestamp+self.settings['command_timeout_s'] or (task.task_id,version) in self.refused_epochs:continue
                if self.settings.get('resilience',{}).get('enabled'):
                    key=(task.task_id,version)
                    if message.timestamp<self.controller_timestamps.get(key,-math.inf):continue
                    self.controller_timestamps[key]=message.timestamp
                if task.status==TaskStatus.COMPLETE and version==task.version:
                    self.emit(MT.TASK_COMPLETE,dict(task_id=task.task_id,version=task.version,owner=self.agent_id),now,[CONTROLLER]);continue
                if any(t.status==TaskStatus.ASSIGNED and t.assigned_agent==self.agent_id and t.task_id!=task.task_id for t in self.tasks.values()):continue
                if version>task.version:
                    task.version=version;self.claim_time[task.task_id]=now-self.bid_window
                    self.checkpoints[task.task_id]=max(self.checkpoints.get(task.task_id,0),p.get('completed_waypoints',0))
                task.status=TaskStatus.ASSIGNED;task.assigned_agent=self.agent_id;task.lease_expires_at=deadline
                self.control_until=message.timestamp+self.settings['command_timeout_s'];self.acks[task.task_id]=set(self.peers)
                self.emit(MT.TASK_ACCEPT,dict(task_id=task.task_id,version=version,owner=self.agent_id),now,[CONTROLLER])
                self.decisions.append(message.message_id)
        if self.settings.get('resilience',{}).get('enabled'):beacons=self._monotonic_observations(beacons,now)
        endpoint=self.endpoint
        class Inbox:
            def receive_available(inner):return beacons
            def send(inner,m):return endpoint.send(m)
        self.endpoint=Inbox()
        try:PersistentAgent.receive(self,now)
        finally:self.endpoint=endpoint

    def send(self,kind,payload,now):
        if kind in (MT.HEARTBEAT,MT.STATUS_UPDATE):return super().send(kind,payload,now)
        if self.architecture=='A' and kind in (MT.TASK_COMPLETE,MT.INTENT_UPDATE,MT.TASK_RELEASE):
            self.emit(kind,payload,now,[CONTROLLER])
        # B never sends coordination messages; completion remains local/evaluator evidence.

    def protocol_tick(self,now,dt):
        self.communication_inputs(now)
        self.send(MT.HEARTBEAT,dict(alive=True),now)
        self.send(MT.STATUS_UPDATE,dict(role=self.role,position=list(self.position),velocity=list(self.velocity),battery=self.battery,observed_at=self.state_time),now)
        self._update_opportunity(now)

    def _opportunity(self,now):
        task=self.executable_task(now)
        if task is not None and not self.authorized:return 'EXECUTE_OWNED_TASK',task.task_id,task.version
        return None

    def executable_task(self,now):
        if self.architecture=='A' and now>=self.control_until:return None
        # Fixed assignment does not require peer agreement or a task auction.
        return next((t for t in self.tasks.values() if t.assigned_agent==self.agent_id and t.status==TaskStatus.ASSIGNED and now<t.lease_expires_at),None)

    def _tool_candidates(self,now):
        return {k:v for k,v in super()._tool_candidates(now).items() if k in self.LOCAL_TOOLS}

    def apply(self,decision,now,gate):
        if decision['selected_tool'] not in self.LOCAL_TOOLS:raise PolicyError('coordination_disabled_for_architecture')
        return super().apply(decision,now,gate)

    def release_task(self,task_id,now):
        task=self.tasks[task_id]
        if task.assigned_agent!=self.agent_id or task.status!=TaskStatus.ASSIGNED:raise ValueError('Not owned')
        self.refused_epochs.add((task_id,task.version))
        self.send(MT.TASK_RELEASE,dict(task_id=task_id,version=task.version,owner=self.agent_id,reason='local_route_blocked'),now)
        task.status=TaskStatus.UNASSIGNED;task.assigned_agent=None;task.lease_expires_at=None
        self.log('task_released',now,task_id=task_id,version=task.version)

    def report_execution(self,*args,**kwargs):
        ok=super().report_execution(*args,**kwargs)
        if ok and self.architecture=='B':
            task=self.tasks[args[0]]
            if task.status!=TaskStatus.COMPLETE:task.lease_expires_at=self.settings['horizon_s']+1
        return ok

    def _fallback(self,now,gate,reason):
        # Parent fallback could bid; fixed architectures must never enter that path.
        self.fallback_count+=1;self.record('deterministic_fallback',now,reason_code=reason)
        if self.agent_id not in gate.active:
            gate.dispatch(Action(f'fixed_fallback:{self.agent_id}:{now}',self.agent_id,'HOLD',now,now+3,(),1,1,'rule_policy'),self.safety_state(now),now)

    def execution_tick(self,now,gate):
        if self.architecture=='A' and now>=self.control_until and now>=self.settings['command_timeout_s']:
            if not self.timeout_latched:
                self.record('controller_command_timeout',now)
                try:self._stop_motion(gate)
                except PolicyError:
                    self.record('controller_timeout_cancellation_unconfirmed',now);return
                self._fallback(now,gate,'controller_command_timeout');self.timeout_latched=True
            return
        self.timeout_latched=False
        super().execution_tick(now,gate)


class FleetController:
    """Centralized allocation using only its delivered inbox, never backend/agent objects."""
    def __init__(self,endpoint,tasks,vehicle_ids,settings):
        self.endpoint=endpoint;self.tasks={t.task_id:copy.deepcopy(t) for t in tasks}
        self.vehicle_ids=list(vehicle_ids);self.settings=settings;self.states={};self.sequence=0
        self.checkpoints={};self.last_send={};self.events=[];self.cooldowns={};self.decisions=[];self.bootstrap_ready=False

    def send_assignment(self,task,now):
        self.sequence+=1
        payload=dict(task_id=task.task_id,version=task.version,owner=task.assigned_agent,
            lease_expires_at=task.lease_expires_at,completed_waypoints=self.checkpoints.get(task.task_id,0))
        self.endpoint.send(AgentMessage(f'phase13:controller:{self.sequence}',MT.TASK_AWARD,CONTROLLER,
            [task.assigned_agent],'phase8',now,self.sequence,self.settings['command_timeout_s'],payload))
        self.last_send[task.task_id]=now
        self.events.append(dict(event='central_command_sent',time_s=now,**payload))

    def receive(self,now):
        for message in self.endpoint.receive_available():
            if message.sender_id not in self.vehicle_ids or message.mission_id!='phase8':continue
            p=message.payload;used=False
            if message.message_type==MT.STATUS_UPDATE:
                v=p.get('position');observed=p.get('observed_at',message.timestamp)
                if not isinstance(v,list) or len(v)!=3 or not all(type(x) in (int,float) and math.isfinite(x) for x in v):continue
                if type(observed) not in (int,float) or not math.isfinite(observed) or not 0<=observed<=message.timestamp:continue
                if observed<self.states.get(message.sender_id,{}).get('observed_at',-math.inf):continue
                self.states[message.sender_id]=dict(position=v,battery=p.get('battery',0),role=p.get('role'),observed_at=observed)
                for report in p.get('work_reports',[]):self.progress(message.sender_id,report,now)
                used=True
            elif message.message_type in (MT.TASK_COMPLETE,MT.INTENT_UPDATE,MT.TASK_RELEASE):
                used=self.progress(message.sender_id,dict(p,status='complete' if message.message_type==MT.TASK_COMPLETE else 'released' if message.message_type==MT.TASK_RELEASE else 'assigned'),now)
            elif message.message_type==MT.TASK_ACCEPT:used=True
            if used:self.decisions.append(message.message_id)

    def progress(self,sender,p,now):
        task=self.tasks.get(p.get('task_id'))
        if task is None or task.assigned_agent!=sender or p.get('version')!=task.version or task.status!=TaskStatus.ASSIGNED:return False
        index=p.get('completed_waypoints',self.checkpoints.get(task.task_id,0))
        if type(index) is not int or not 0<=index<=task.work_units:return False
        if index>self.checkpoints.get(task.task_id,0):
            self.checkpoints[task.task_id]=index;task.lease_expires_at=now+self.settings['lease_seconds']
        if p.get('status')=='complete':task.status=TaskStatus.COMPLETE;task.lease_expires_at=None
        elif p.get('status')=='released':
            self.cooldowns[(sender,task.task_id)]=now+self.settings['bid_window']
            task.status=TaskStatus.UNASSIGNED;task.assigned_agent=None;task.lease_expires_at=None
        return True

    def step(self,now):
        if self.settings.get('resilience',{}).get('enabled') and not self.bootstrap_ready:
            fresh={a for a,v in self.states.items() if now-v['observed_at']<=self.settings['state_timeout_s']}
            if fresh!=set(self.vehicle_ids) and now<2*self.settings['state_timeout_s']:return
            self.bootstrap_ready=True
            self.events.append(dict(event='central_delivered_state_bootstrap',time_s=now,known_vehicle_ids=sorted(fresh)))
        for task in self.tasks.values():
            if task.status==TaskStatus.ASSIGNED and now>=task.lease_expires_at:
                self.events.append(dict(event='central_lease_expired',time_s=now,task_id=task.task_id,owner=task.assigned_agent,version=task.version))
                task.status=TaskStatus.UNASSIGNED;task.assigned_agent=None
        for task in sorted(self.tasks.values(),key=lambda t:(-t.priority,t.task_id)):
            if task.status==TaskStatus.UNASSIGNED:
                busy={t.assigned_agent for t in self.tasks.values() if t.status==TaskStatus.ASSIGNED}
                candidates=[]
                for aid,state in self.states.items():
                    if aid in busy or state['role']!='SCOUT' or now-state['observed_at']>self.settings['state_timeout_s'] or now<self.cooldowns.get((aid,task.task_id),0):continue
                    if state['battery']<self.settings.get('minimum_battery_percent',20):continue
                    risk=min(1.,max(0.,now-state['observed_at'])/3)
                    score=bid_cost(task,state['position'],state['battery'],0,risk,{'search','inspect'},BID_WEIGHTS,'searcher')
                    if score:candidates.append((score['score'],aid))
                if not candidates:continue
                task.assigned_agent=min(candidates)[1];task.status=TaskStatus.ASSIGNED;task.version+=1
                task.lease_expires_at=now+self.settings['lease_seconds']
                self.events.append(dict(event='central_assignment',time_s=now,task_id=task.task_id,owner=task.assigned_agent,version=task.version))
            if task.status==TaskStatus.ASSIGNED and now-self.last_send.get(task.task_id,-math.inf)>=self.settings['beacon_interval_s']:
                self.send_assignment(task,now)
