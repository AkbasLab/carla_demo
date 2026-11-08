"""Isolated persistent policy state over the deterministic Phase 8 protocol."""
from collections import deque
import copy
from dataclasses import asdict
import json
import math
from pathlib import Path
import time
from agentic_uav.comm.protocol import MessageType as MT, AgentMessage
from agentic_uav.coordination.contract_net import AllocationAgent, TaskStatus, TaskType, MissionTask, Geometry, bid_cost
from agentic_uav.coordination.flight_executor import WaypointExecutor
from agentic_uav.control.runtime_guardian import Action, Outcome, Peer, State
from .structured import TOOLS, PolicyError, AsyncWorker, ReplayProvider, validate_decision, decision_example, OllamaProvider


class PersistentAgent(AllocationAgent):
    def __init__(self,*args,role,routes,home,relay_point,guardian,output_dir,provider,
                 mission,decision_interval=1.,inference_timeout=15.,max_context_age=20.,progress_timeout=None,max_hold_seconds=2.,
                 deadline_bidding=None,inference_capacity=1,bid_response_margin=1.,safety_rejection_limit=2,**kwargs):
        super().__init__(*args,**kwargs)
        self.role=role;self.routes=copy.deepcopy(routes);self.home=tuple(home);self.relay_point=tuple(relay_point)
        self.guardian=guardian;self.mission=mission;self.provider=provider
        self.worker=None if isinstance(provider,ReplayProvider) else AsyncWorker(provider)
        self.out=Path(output_dir)/self.agent_id;self.out.mkdir(parents=True,exist_ok=True)
        self.memory=deque(maxlen=12);self.recent_messages=deque(maxlen=5);self.peer_beliefs={};self.observations={}
        self.executor=WaypointExecutor(self.routes,.4,z_tolerance=.6,stall_timeout=5.)
        self.authorized=None;self.single_index=None;self.motion_key=None;self._allow_bid=False
        self.velocity=(0.,0.,0.);self.phase='AIRBORNE';self.state_time=0.;self.last_skill_result=None
        self.decision_interval=decision_interval;self.inference_timeout=inference_timeout;self.max_context_age=max_context_age
        self.last_request=-math.inf;self.request_number=0;self.pending=None;self.correction=None;self.correction_attempt=0
        self.progress_timeout=progress_timeout if progress_timeout is not None else max(30.,2*inference_timeout)
        self.max_hold_seconds=max_hold_seconds
        self.request_waiting_since=None;self.opportunity_key=None;self.opportunity_since=0.;self.opportunity_deferrals=0
        self.authorization=None;self.calculations={};self.accepted_tasks=set();self.pending_policy_motion={}
        self.policy_source='llm' if isinstance(provider,OllamaProvider) else 'replay_fixture' if isinstance(provider,ReplayProvider) else 'test_fixture'
        self.identity_fault=False;self.model_decisions=0;self.fallback_count=0;self.events_policy=[];self.completed_requests=set()
        self.received_counts={};self.status_times={};self.last_measurement=None;self.last_distance=None
        self.deadline_bidding=isinstance(provider,OllamaProvider) if deadline_bidding is None else deadline_bidding
        self.inference_estimate=inference_timeout;self.inference_admission_delay_s=max(0,len(self.peers)//inference_capacity)*inference_timeout
        self.bid_response_margin=bid_response_margin;self.safety_rejection_limit=safety_rejection_limit
        self.blocked_approaches={};self.bid_blocked_until={};self.declined_task_epochs=set()

    def record(self,kind,now,**data):
        event=dict(time_s=now,agent_id=self.agent_id,event=kind,**data)
        self.events_policy.append(event)
        with (self.out/'decision_history.jsonl').open('a') as f:f.write(json.dumps(event,allow_nan=False)+'\n')

    def _save(self,name,data):
        with (self.out/(name+'.jsonl')).open('a') as f:f.write(json.dumps(data,allow_nan=False)+'\n')

    def offer(self,task,now):
        if not self._allow_bid or self.role!='SCOUT' or self.battery<self.guardian.config.min_battery_reserve_percent:return
        saved=self.role;self.role='inspector' if task.task_type==TaskType.INSPECT_TARGET else 'searcher'
        try:super().offer(task,now)
        finally:self.role=saved

    def _bid_available(self,task,now):
        if (task.task_id,task.version) in self.declined_task_epochs:return
        if self.agent_id in self.bids.get(task.task_id,{}):return
        if now>=self.auction_end.get(task.task_id,-math.inf) or now<self.bid_blocked_until.get(task.task_id,-math.inf):return
        if task.status!=TaskStatus.BIDDING or self.workload() or self.role!='SCOUT':return
        # Bids promise executable work, not just a low geometric cost.
        if self.guardian._state_errors(self.safety_state(now),now):return
        calculation=self._cost(task,now)
        return calculation['route_feasible'] and calculation['battery_sufficient']

    def _bid(self,task,now):
        if not self._bid_available(task,now):return
        self._allow_bid=True
        try:self.offer(task,now)
        finally:self._allow_bid=False

    def receive(self,now):
        messages=self.endpoint.receive_available();allocation=[]
        for m in messages:
            if m.mission_id!='phase8' or m.sender_id not in self.peers:continue
            self.received_counts[m.sender_id]=self.received_counts.get(m.sender_id,0)+1
            if m.message_type not in (MT.HEARTBEAT,MT.STATUS_UPDATE):
                self.recent_messages.append(dict(sender=m.sender_id,type=m.message_type.value,time_s=m.timestamp,
                    task_id=m.payload.get('task_id'),role=m.payload.get('role'),reason_code=str(m.payload.get('reason_code',''))[:48]))
            if m.message_type==MT.STATUS_UPDATE:
                p=m.payload
                def vector(v):return isinstance(v,list) and len(v)==3 and all(type(x) in (int,float) and math.isfinite(x) for x in v)
                observed=p.get('observed_at',m.timestamp)
                if vector(p.get('position')) and vector(p.get('velocity',[0,0,0])) and type(observed) in (int,float) and math.isfinite(observed) and 0<=observed<=m.timestamp and p.get('role') in ('SCOUT','RELAY','RESERVE'):
                    self.peer_beliefs[m.sender_id]=dict(position=p['position'],velocity=p.get('velocity',[0,0,0]),
                        observed_at=p.get('observed_at',m.timestamp),role=p.get('role'),battery=p.get('battery'))
                    self.status_times[m.sender_id]=now
                self.decisions.append(m.message_id)
            elif m.message_type==MT.TASK_RELEASE and m.payload.get('reason')=='bid_withdrawn':
                self.bids.get(m.payload.get('task_id'),{}).pop(m.sender_id,None)
            elif m.message_type==MT.TARGET_FOUND:
                task=MissionTask.from_dict(m.payload['task'])
                if task.task_id not in self.tasks and task.task_type==TaskType.INSPECT_TARGET:
                    self.tasks[task.task_id]=task;self.routes[task.task_id]=[list(task.location_or_region.center)]
                    self.executor.routes=self.routes
                self.decisions.append(m.message_id)
            else:allocation.append(m)
        endpoint=self.endpoint
        class Inbox:
            def receive_available(inner):return allocation
            def send(inner,msg):return endpoint.send(msg)
        self.endpoint=Inbox()
        try:super().receive(now)
        finally:self.endpoint=endpoint

    def protocol_tick(self,now,dt):
        self.send(MT.STATUS_UPDATE,dict(role=self.role,position=list(self.position),velocity=list(self.velocity),battery=self.battery,observed_at=self.state_time),now)
        self._deadline_bids(now)
        super().step(now,dt,process_inbox=False,execute_mock=False)
        self._update_opportunity(now)

    def _deadline_bids(self,now):
        if not self.deadline_bidding or self.workload() or self.role!='SCOUT':return
        for task in self.tasks.values():
            if task.status!=TaskStatus.BIDDING or self.agent_id in self.bids.get(task.task_id,{}):continue
            slack=self.auction_end.get(task.task_id,-math.inf)-now
            required=self.inference_admission_delay_s+self.inference_estimate+self.bid_response_margin
            if not 0<slack<=required:continue
            self._bid(task,now)
            if self.agent_id in self.bids.get(task.task_id,{}):
                self.record('deadline_bid_submitted',now,task_id=task.task_id,version=task.version,
                    deadline=self.auction_end[task.task_id],remaining_s=slack,
                    estimated_admission_s=self.inference_admission_delay_s,estimated_inference_s=self.inference_estimate,
                    source='deterministic_deadline_guard')

    def _approach(self,task,now,speed=None):
        if speed is None:speed=min(1.,self.guardian.config.max_speed_mps)
        index=self.executor.index if self.executor.key==(task.task_id,task.version) else self.checkpoints.get(task.task_id,0)
        if index>=len(self.routes[task.task_id]):raise PolicyError('waypoint_out_of_order')
        target=self._motion_target(task,index,now,speed)
        action=Action(f'approach:{self.agent_id}:{now}',self.agent_id,'MOVE',now,now+30,(target,),speed)
        check=self.guardian.evaluate(action,self.safety_state(now),now)
        return index,target,check

    def _motion_target(self,task,index,now,speed):
        return tuple(self.routes[task.task_id][index])

    def _note_blocked(self,task,index,reasons,now):
        key=(task.task_id,task.version,index);reasons=tuple(sorted(set(reasons)))
        previous=self.blocked_approaches.get(task.task_id,{})
        count=previous.get('count',0)+1 if previous.get('key')==key and previous.get('reasons')==reasons else 1
        self.blocked_approaches[task.task_id]=dict(key=key,reasons=reasons,count=count,observed_at=now)
        self.record('approach_blocked',now,task_id=task.task_id,version=task.version,index=index,reasons=list(reasons),consecutive_rejections=count)

    def _blocked_task(self):
        for tid,blocked in self.blocked_approaches.items():
            task=self.tasks[tid]
            if task.status==TaskStatus.ASSIGNED and task.assigned_agent==self.agent_id and blocked['key'][1]==task.version:return task,blocked
        return None,None

    def _release_blocked(self,task,now,gate,source='deterministic_safety_recovery'):
        try:self._stop_motion(gate)
        except PolicyError:
            self.record('blocked_task_release_deferred',now,task_id=task.task_id,reason_code='cancellation_unconfirmed')
            return False
        version=task.version
        self.bid_blocked_until[task.task_id]=now+self.bid_window
        self.release_task(task.task_id,now)
        self.record('blocked_task_released',now,task_id=task.task_id,previous_version=version,new_version=task.version,
            reason_code='SAFETY_ROUTE_BLOCKED',source=source)
        self.correction=None;self.correction_attempt=0
        return True

    def safety_state(self,now):
        peers={p:Peer(tuple(v['position']),tuple(v['velocity']),v['observed_at']) for p,v in self.peer_beliefs.items()}
        oldest=max((now-self.last_heartbeat.get(p,0) for p in self.peers),default=0)
        communication='LOST' if oldest>3 else 'DEGRADED' if oldest>1 else 'HEALTHY'
        return State(self.agent_id,tuple(self.position),self.state_time,self.battery,self.home,
            peers,tuple(self.peers),self.phase,communication,1.)

    def _opportunity(self,now):
        ready=self.executable_task(now)
        if not self.authorized and ready is not None and self.role=='SCOUT':
            return ('EXECUTE_OWNED_TASK',ready.task_id,ready.version)
        if not self.workload() and self.role=='SCOUT' and self.battery>=self.guardian.config.min_battery_reserve_percent:
            for t in sorted(self.tasks.values(),key=lambda t:(-t.priority,t.task_id)):
                if self._bid_available(t,now):
                    return ('BID_FOR_AVAILABLE_TASK',t.task_id,t.version)
        return None

    def _update_opportunity(self,now):
        opportunity=self._opportunity(now)
        if opportunity!=self.opportunity_key:
            self.opportunity_key=opportunity;self.opportunity_since=now;self.opportunity_deferrals=0
        return opportunity

    def needs_decision(self,now):
        if self.correction:return True
        if self._opportunity(now):return True
        if self.battery<self.guardian.config.min_battery_reserve_percent or self.safety_state(now).communication!='HEALTHY':return True
        if self.role=='RELAY' and math.dist(self.position,self.relay_point)>.4:return True
        if any('INSPECT_'+oid not in self.tasks for oid in self.observations):return True
        if self.role=='RESERVE' and any(t.priority>=10 and t.status!=TaskStatus.COMPLETE for t in self.tasks.values()):return True
        # Await protocol acknowledgment/auction resolution without spending a model slot on HOLD.
        return False

    def _tool_candidates(self,now):
        owned=next((t for t in self.tasks.values() if t.assigned_agent==self.agent_id and t.status==TaskStatus.ASSIGNED and t.lease_expires_at is not None and now<t.lease_expires_at),None)
        ready=self.executable_task(now)
        result={'hold':[dict(duration_s=min(1.,self.max_hold_seconds))],
                'request_help':[dict(reason_code='REPLAN_REQUIRED')]}
        if math.dist(self.position,self.home)>.4:result['return_home']=[{}]
        unfinished=[t for t in self.tasks.values() if t.status!=TaskStatus.COMPLETE]
        if unfinished:result['compute_task_cost']=[dict(task_id=t.task_id) for t in unfinished]
        if owned:
            key=dict(task_id=owned.task_id,task_version=owned.version)
            if (owned.task_id,owned.version) not in self.accepted_tasks:result['accept_task']=[key]
            result['release_task']=[dict(**key,reason_code='TASK_UNSUITABLE')]
            result['decline_task']=[dict(**key,reason_code='TASK_UNSUITABLE')]
        if ready and self.role=='SCOUT':
            index,target,check=self._approach(ready,now)
            if check.outcome in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION):
                key=dict(task_id=ready.task_id,task_version=ready.version)
                result['start_search']=[key]
                result['go_to_waypoint']=[dict(**key,waypoint_index=index,speed_mps=min(1.,self.guardian.config.max_speed_mps))]
            elif not self.guardian._state_errors(self.safety_state(now),now):
                result['release_task']=[dict(task_id=ready.task_id,task_version=ready.version,reason_code='SAFETY_ROUTE_BLOCKED')]
        if not owned and self.role=='SCOUT' and self.battery>=self.guardian.config.min_battery_reserve_percent:
            bids=[dict(task_id=t.task_id,task_version=t.version) for t in unfinished if self._bid_available(t,now)]
            if bids:result['send_bid']=bids
            claims=[]
            for t in unfinished:
                offers=self.bids.get(t.task_id,{})
                if t.status==TaskStatus.BIDDING and now>=self.auction_end.get(t.task_id,math.inf) and offers and min(offers.values(),key=lambda b:(b['score'],b['agent_id']))['agent_id']==self.agent_id:
                    claims.append(dict(task_id=t.task_id,task_version=t.version))
            if claims:result['claim_task']=claims
        if not any(t.status==TaskStatus.BIDDING for t in self.tasks.values()):
            unassigned=[dict(task_id=t.task_id) for t in unfinished if t.status==TaskStatus.UNASSIGNED]
            if unassigned:result['announce_task']=unassigned
        if self.role=='RELAY':result['act_as_relay']=[{}]
        roles=[]
        if self.role!='SCOUT' and self.battery>=self.guardian.config.min_battery_reserve_percent:roles.append('SCOUT')
        if self.role!='RESERVE' and (self.battery<self.guardian.config.min_battery_reserve_percent or not unfinished):roles.append('RESERVE')
        recent={a:b for a,b in self.peer_beliefs.items() if now-b['observed_at']<=self.guardian.config.max_peer_age_s}
        if self.role!='RELAY' and self.safety_state(now).communication!='HEALTHY' and not any(b['role']=='RELAY' for b in recent.values()):
            eligible=[self.agent_id]+[a for a,b in recent.items() if b.get('battery',0)>=self.guardian.config.min_battery_reserve_percent]
            if min(eligible)==self.agent_id:roles.append('RELAY')
        if roles:result['change_role']=[dict(new_role=role,reason_code='ROLE_NEEDED') for role in roles]
        if self.observations:result['report_target']=[dict(observation_id=oid) for oid in list(self.observations)[:16]]
        return result

    def _example(self,now,candidates):
        opportunity=self._opportunity(now)
        blocked_task,_=self._blocked_task()
        if blocked_task is not None and 'release_task' in candidates and not self.guardian._state_errors(self.safety_state(now),now):
            return decision_example('release_task',dict(task_id=blocked_task.task_id,task_version=blocked_task.version,reason_code='SAFETY_ROUTE_BLOCKED'))
        if opportunity and opportunity[0]=='EXECUTE_OWNED_TASK' and 'start_search' not in candidates:
            # Unknown telemetry calls for waiting; a known blocked route calls for reallocation.
            tool='release_task' if not self.guardian._state_errors(self.safety_state(now),now) and 'release_task' in candidates else 'hold'
            return decision_example(tool,copy.deepcopy(candidates[tool][0]))
        tool=('start_search' if opportunity and opportunity[0]=='EXECUTE_OWNED_TASK' else
              'send_bid' if opportunity else 'act_as_relay' if self.role=='RELAY' else 'hold')
        if tool not in candidates:tool='hold'
        return decision_example(tool,copy.deepcopy(candidates[tool][0]))

    def _check_progress(self,decision,now,gate):
        opportunity=self._update_opportunity(now)
        if not opportunity or decision['selected_tool'] not in ('hold','compute_task_cost','accept_task','request_help'):return
        if now-self.opportunity_since<self.progress_timeout or self.opportunity_deferrals<2:return
        # Liveness must never pressure motion through unknown or unsafe state.
        state=self.safety_state(now)
        if self.guardian._state_errors(state,now) or state.communication!='HEALTHY' or self.agent_id in gate.active:return
        if opportunity[0]=='EXECUTE_OWNED_TASK':
            task=self.tasks[opportunity[1]]
            index=self.executor.index if self.executor.key==(task.task_id,task.version) else self.checkpoints.get(task.task_id,0)
            if index>=len(self.routes[task.task_id]):return
            check=Action(f'preview:{self.agent_id}:{now}',self.agent_id,'MOVE',now,now+30,(tuple(self.routes[task.task_id][index]),),1.)
            if self.guardian.evaluate(check,state,now).outcome not in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION):return
        raise PolicyError('mission_progress_stall',dict(opportunity=opportunity[0],task_id=opportunity[1],task_version=opportunity[2],
            waiting_s=now-self.opportunity_since,instruction='Choose an applicable mission-progress tool or explicitly release/request help; holding is not progress.'))

    def _authorize(self,task,now,source,tool,request_id=None):
        authorization=dict(source=source,tool=tool,request_id=request_id,authorized_at=now,start_position=list(self.position))
        self.record('search_authorized',now,task_id=task.task_id,version=task.version,**authorization)
        self.authorized=(task.task_id,task.version);self.authorization=authorization

    def _observe_arrivals(self,start,now):
        for arrival in self.executor.arrivals[start:]:
            auth=self.authorization or dict(source='unknown',request_id=None,start_position=list(self.position))
            arrival['authorization_source']=auth['source'];arrival['policy_request_id']=auth['request_id']
            moved=math.dist(auth['start_position'],self.position)>.1
            self.record('policy_progress_observed',now,task_id=arrival['task_id'],version=arrival['version'],
                index=arrival['index'],source=auth['source'],request_id=auth['request_id'] if moved else None)

    def observe_completion(self,command_id,now):
        motion=self.pending_policy_motion.pop(command_id,None)
        if motion is None:return
        if math.dist(motion['start_position'],self.position)<=.1:return
        self.record('policy_progress_observed',now,source=motion['source'],request_id=motion['request_id'],
            selected_tool=motion['tool'],command_id=command_id)

    def context(self,now):
        active=next((t for t in self.tasks.values() if t.assigned_agent==self.agent_id and t.status==TaskStatus.ASSIGNED),None)
        executable=self.executable_task(now)
        candidates=self._tool_candidates(now);example=self._example(now,candidates);opportunity=self._update_opportunity(now)
        approach=None
        if executable is not None:
            index,target,check=self._approach(executable,now)
            approach=dict(task_id=executable.task_id,version=executable.version,index=index,target=list(target),
                checked_at=now,feasible=check.outcome in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION),reasons=check.reasons)
        tasks=[dict(task_id=t.task_id,version=t.version,status=t.status.value,owner=t.assigned_agent,priority=t.priority,
                    bidding_remaining_s=max(0,self.auction_end.get(t.task_id,now)-now) if t.status==TaskStatus.BIDDING else None,
                    own_bid=self.agent_id in self.bids.get(t.task_id,{}),center=list(t.location_or_region.center))
               for t in sorted(self.tasks.values(),key=lambda t:t.task_id)]
        return dict(agent_id=self.agent_id,team_mission=self.mission,current_role=self.role,
            current_task=dict(task_id=active.task_id,version=active.version,executable=executable is not None,lease_remaining_s=max(0,active.lease_expires_at-now)) if active else None,
            own_state=dict(position=self.position,velocity=self.velocity,battery=self.battery,flight_phase=self.phase,time_s=now,observed_at=self.state_time),
            tasks=tasks[:32],decision_format=dict(required_fields=list(example),example=example),non_negotiable_constraints=asdict(self.guardian.config),
            summarized_beliefs=copy.deepcopy(self.peer_beliefs),recent_important_messages=list(self.recent_messages),
            memory=[m for m in self.memory if m.get('selected_tool')!='hold'][-8:],available_tools={tool:TOOLS[tool] for tool in candidates},
            tool_candidates=candidates,policy_limits=dict(max_hold_seconds=self.max_hold_seconds,progress_timeout_s=self.progress_timeout),
            mission_progress_requirement=dict(opportunity=opportunity,waiting_s=now-self.opportunity_since,
                instruction='Complete owned executable work. Use deterministic calculations if needed; do not repeatedly hold when progress is feasible.'),
            approach_validation=approach,bidding_budget=dict(estimated_admission_s=self.inference_admission_delay_s,
                estimated_inference_s=self.inference_estimate,response_margin_s=self.bid_response_margin,deadline_guard_enabled=self.deadline_bidding),
            deterministic_calculations=list(self.calculations.values())[-4:],communication_estimate={p:dict(
                heartbeat_age_s=max(0,now-self.last_heartbeat.get(p,0)),received_messages=self.received_counts.get(p,0)) for p in self.peers},
            current_skill_result=self.last_skill_result,unresolved_decisions=([dict(goal=opportunity[0],task_id=opportunity[1],task_version=opportunity[2])] if opportunity else ['wait for acknowledgments, a suitable task, or role-specific work; obey safety']),
            locally_observed_targets=list(self.observations)[:16],correction=self.correction)

    def request(self,now):
        if self.identity_fault or self.pending is not None or (self.worker and self.worker.busy) or now-self.last_request<self.decision_interval:return
        context=self.context(now);prompt=json.dumps(context,allow_nan=False,sort_keys=True)
        self.request_number+=1;token=f'{self.agent_id}:{self.request_number}';self.last_request=now
        self.pending=dict(token=token,offered_tools=list(context['available_tools']),context_time=now,wall_start=time.monotonic(),correction_attempt=self.correction_attempt)
        self.pending['task_snapshot']={t['task_id']:(t['version'],t['status'],t['owner']) for t in context['tasks']}
        self.pending['tool_candidates']=copy.deepcopy(context['tool_candidates'])
        self._save('prompts',dict(request_id=token,simulation_time_s=now,prompt=prompt,correction_attempt=self.correction_attempt,admission_wait_s=0. if self.request_waiting_since is None else now-self.request_waiting_since))
        self.request_waiting_since=None
        if isinstance(self.provider,OllamaProvider):
            self._save('request_specs',dict(request_id=token,model_digest=self.provider.digest,request=self.provider.request_spec(prompt)))
        if self.worker:self.worker.submit(token,prompt)
        else:
            raw=self.provider.generate(prompt)
            self.pending['inline_result']=dict(token=token,raw=raw,latency_s=0.)

    def _fallback(self,now,gate,reason):
        self.fallback_count+=1;self.record('deterministic_fallback',now,reason_code=reason)
        self.last_skill_result=dict(status='deterministic_fallback',reason_code=reason)
        self.memory.append(dict(time_s=now,selected_tool='deterministic_fallback',result=self.last_skill_result))
        # Calculations and bidding continue deterministically; no unguarded motion.
        if self.role=='SCOUT':
            for task in self.tasks.values():
                if task.status==TaskStatus.BIDDING:self._bid(task,now)
            task=self.executable_task(now)
            if task is not None and self.authorized!=(task.task_id,task.version):
                index,target,check=self._approach(task,now)
                if check.outcome in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION):
                    self._authorize(task,now,'deterministic_fallback','start_search')
                else:
                    self._note_blocked(task,index,check.reasons,now)
                    if self.blocked_approaches[task.task_id]['count']>=self.safety_rejection_limit:self._release_blocked(task,now,gate)
        if self.agent_id not in gate.active:
            action=Action(f'fallback:{self.agent_id}:{now}',self.agent_id,'HOLD',now,now+3,(),1,1,'rule_policy')
            gate.dispatch(action,self.safety_state(now),now)

    def _failure(self,reason,now,gate,correctable,details=None):
        self.record('policy_error',now,reason_code=reason,correction_attempt=self.correction_attempt,validation_details=details)
        task,blocked=self._blocked_task()
        if task is not None and blocked['count']>=self.safety_rejection_limit:
            self._release_blocked(task,now,gate)
            return
        if correctable and self.correction_attempt==0:
            example=self._example(now,self._tool_candidates(now))
            instruction=('Release the blocked task so a peer can rebid; do not repeat the rejected start_search or waypoint. Hold if cancellation or telemetry is uncertain. '
                if task is not None else 'Use the current task version and bidding deadline; a closed auction cannot accept a late bid. ' if reason=='not_eligible_to_bid' else '')
            self.correction_attempt=1;self.correction=dict(error=reason,validation_details=details,required_fields=list(decision_example()),example=example,instruction=instruction+'Return ALL FIVE top-level fields in exactly one corrected decision: situation_assessment, selected_tool, parameters, outgoing_messages, confidence. Supply your own assessment and confidence; do not invent coordinates or task ownership.')
            self.last_request=-math.inf
            self.record('structured_correction_requested',now,reason_code=reason)
        else:
            self.correction=None;self.correction_attempt=0;self._fallback(now,gate,reason)

    def poll(self,now,gate):
        result=self.worker.poll() if self.worker else self.pending.get('inline_result') if self.pending else None
        if result is not None:
            self._save('responses',dict(simulation_time_s=now,**result))
            if self.pending is None or result['token']!=self.pending['token']:
                self.record('late_response_discarded',now,request_id=result['token']);return
            pending=self.pending;self.pending=None
            if result.get('error_type')=='ModelIdentityError':self.identity_fault=True
            if result.get('latency_s',0)>=self.inference_timeout:
                self._failure('inference_timeout',now,gate,False);return
            if 'error_type' in result:
                self._failure(result['error_type'],now,gate,False);return
            if now-pending['context_time']>self.max_context_age:
                self._failure('stale_decision_context',now,gate,False);return
            latency=result.get('latency_s',0.)
            if latency>0:self.inference_estimate=min(self.inference_timeout,max(latency,.75*self.inference_estimate+.25*latency))
            try:
                decision=validate_decision(result['raw'],self.peers)
                if decision['confidence']<.5:raise PolicyError('low_policy_confidence')
                if decision['selected_tool'] not in pending['offered_tools']:raise PolicyError('tool_not_offered_in_request')
                params=decision['parameters'];tid=params.get('task_id');task=self.tasks.get(tid)
                snapshot=pending.get('task_snapshot',{}).get(tid)
                current=(task.version,task.status.value,task.assigned_agent) if task is not None else None
                if snapshot is not None and (current!=snapshot or
                        (task.lease_expires_at is not None and now>=task.lease_expires_at)):
                    # A valid response can become obsolete while the model runs.
                    # Start a fresh decision, never rewrite its version or execute it.
                    self.record('policy_error',now,request_id=result['token'],reason_code='task_context_changed',
                                correction_attempt=pending['correction_attempt'],disposition='refresh_without_execution')
                    self.record('decision_superseded',now,request_id=result['token'],task_id=tid,
                                previous=snapshot,current=current)
                    self.correction=None;self.correction_attempt=0;self.last_request=-math.inf
                    return
                if tid is not None and 'task_version' in params:
                    offered=pending.get('tool_candidates',{}).get(decision['selected_tool'],[])
                    if offered and not any(p.get('task_id')==tid and p.get('task_version')==params['task_version'] for p in offered):
                        raise PolicyError('task_parameters_not_offered')
                self._check_progress(decision,now,gate)
                tool_result=self.apply(decision,now,gate)
            except (PolicyError,ValueError,KeyError,TypeError) as error:
                reason=str(error)[:160] if isinstance(error,PolicyError) else type(error).__name__
                self._failure(reason,now,gate,True,details=getattr(error,'details',None));return
            if self._opportunity(now) and decision['selected_tool'] in ('hold','compute_task_cost','accept_task','request_help'):self.opportunity_deferrals+=1
            self.model_decisions+=1
            self.memory.append(dict(time_s=now,selected_tool=decision['selected_tool'],parameters=decision['parameters'],result=tool_result))
            self.last_skill_result=tool_result
            self.record('policy_decision_applied',now,request_id=result['token'],decision=decision,tool_result=tool_result,
                source=self.policy_source,flight_phase=self.phase)
            self.correction=None;self.correction_attempt=0
        if self.pending and time.monotonic()-self.pending['wall_start']>=self.inference_timeout:
            expired=self.pending;self.pending=None
            self.record('inference_timeout',now,request_id=expired['token'])
            self._failure('inference_timeout',now,gate,False)

    def _task(self,params,now,owned=False):
        task=self.tasks.get(params['task_id'])
        if task is None:raise PolicyError('unknown_task')
        if 'task_version' in params and params['task_version']!=task.version:raise PolicyError('stale_task_version')
        if task.status==TaskStatus.COMPLETE:raise PolicyError('task_already_complete')
        if owned and (task.assigned_agent!=self.agent_id or task.status!=TaskStatus.ASSIGNED or task.lease_expires_at is None or now>=task.lease_expires_at):raise PolicyError('task_not_owned_or_lease_expired')
        return task

    def _cost(self,task,now):
        route=self.routes[task.task_id][self.checkpoints.get(task.task_id,0):]
        if not route:raise PolicyError('task_route_already_traversed')
        target=route[0];entry_distance=math.dist(self.position,target)
        distance=sum(math.dist(a,b) for a,b in zip([self.position]+route,route));speed=min(1.,self.guardian.config.max_speed_mps)
        score=bid_cost(task,self.position,self.battery,self.workload(),self.communication_risk,self.capabilities,self.weights,'searcher')
        proposed=Action(f'calculation:{self.agent_id}:{now}',self.agent_id,'MOVE',now,now+30,tuple(tuple(p) for p in route),speed)
        checked=self.guardian.evaluate(proposed,self.safety_state(now),now)
        result=dict(task_id=task.task_id,task_version=task.version,computed_at=now,distance_m=distance,distance_to_entry_m=entry_distance,travel_time_s=distance/speed,bid=score,
            battery_sufficient=self.battery-distance*self.guardian.config.battery_cost_percent_per_m>=self.guardian.config.min_battery_reserve_percent,
            communication_reachability={p:('recent_contact' if now-self.status_times.get(p,-math.inf)<=1 else 'unknown') for p in self.peers},
            route_feasible=checked.outcome in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION),separation_risk='drone_separation' in checked.reasons,
            guardian_reasons=checked.reasons)
        self.calculations[task.task_id]=result
        return result

    def _stop_motion(self,gate):
        active=gate.active.get(self.agent_id)
        if active:
            if not gate._cancel(self.agent_id):raise PolicyError('cancellation_unconfirmed')
            gate.confirm_completion(self.agent_id,active.command_id)
        self.authorized=None;self.motion_key=None

    def _send_selected(self,kind,payload,now,decision):
        outgoing=decision['outgoing_messages']
        if not outgoing:self.send(kind,payload,now);return
        self.sequence+=1
        message=AgentMessage(f'phase8:{self.agent_id}:{self.sequence}',kind,self.agent_id,
            outgoing[0]['recipients'],'phase8',now,self.sequence,5.,payload)
        self.endpoint.send(message)

    def apply(self,d,now,gate):
        tool=d['selected_tool'];p=d['parameters'];state=self.safety_state(now)
        if tool=='compute_task_cost':return self._cost(self._task(p,now),now)
        if tool=='announce_task':
            task=self._task(p,now)
            if task.status!=TaskStatus.UNASSIGNED:raise PolicyError('task_not_unassigned')
            if any(t.status==TaskStatus.BIDDING for t in self.tasks.values()):raise PolicyError('auction_already_open')
            self.announce(task,now,task.version+1);return dict(status='announced',task_id=task.task_id)
        if tool=='send_bid':
            task=self._task(p,now)
            if task.status!=TaskStatus.BIDDING or self.workload() or self.role!='SCOUT':raise PolicyError('not_eligible_to_bid')
            self._bid(task,now)
            if self.agent_id not in self.bids.get(task.task_id,{}):raise PolicyError('bid_not_feasible_or_deadline_passed')
            return self._cost(task,now)
        if tool=='claim_task':
            task=self._task(p,now);offers=self.bids.get(task.task_id,{})
            if not self.can_claim(task) or self.role!='SCOUT' or self.battery<self.guardian.config.min_battery_reserve_percent:raise PolicyError('not_eligible_to_claim')
            if task.status!=TaskStatus.BIDDING or now<self.auction_end.get(task.task_id,math.inf) or not offers:raise PolicyError('auction_not_ready')
            winner=min(offers.values(),key=lambda b:(b['score'],b['agent_id']))
            if winner['agent_id']!=self.agent_id:raise PolicyError('not_best_valid_bid')
            claim=dict(task_id=task.task_id,version=task.version,owner=self.agent_id,score=winner['score'])
            self.send(MT.TASK_AWARD,claim,now);self.adopt(task,claim,now);return dict(status='claim_sent')
        if tool in ('accept_task','start_search','go_to_waypoint','release_task','decline_task'):
            task=self._task(p,now,owned=tool!='decline_task')
            if tool=='accept_task':
                self.accepted_tasks.add((task.task_id,task.version))
                self.send(MT.TASK_ACCEPT,dict(task_id=task.task_id,version=task.version,owner=self.agent_id),now)
                return dict(status='ownership_confirmed',task_id=task.task_id)
            if tool in ('release_task','decline_task'):
                if task.assigned_agent==self.agent_id:
                    if task.task_id in self.blocked_approaches or p['reason_code']=='SAFETY_ROUTE_BLOCKED':
                        if not self._release_blocked(task,now,gate,source=self.policy_source):raise PolicyError('cancellation_unconfirmed')
                    else:self._stop_motion(gate);self.release_task(task.task_id,now)
                else:
                    self.declined_task_epochs.add((task.task_id,task.version))
                    self.bids.get(task.task_id,{}).pop(self.agent_id,None)
                    self.send(MT.TASK_RELEASE,dict(task_id=task.task_id,version=task.version,reason='bid_withdrawn'),now)
                return dict(status='released_or_declined')
            ready=self.executable_task(now)
            if self.role!='SCOUT' or ready is None or ready.task_id!=task.task_id:raise PolicyError('task_not_executable')
            if tool=='go_to_waypoint':
                expected=self.executor.index if self.executor.key==(task.task_id,task.version) else self.checkpoints.get(task.task_id,0)
                if p['waypoint_index']!=expected or expected>=len(self.routes[task.task_id]):raise PolicyError('waypoint_out_of_order')
                speed=p['speed_mps'];self.single_index=expected
            else:speed=min(1.,self.guardian.config.max_speed_mps);self.single_index=None
            index=self.executor.index if self.executor.key==(task.task_id,task.version) else self.checkpoints.get(task.task_id,0)
            target=self.routes[task.task_id][index]
            index,target,preview=self._approach(task,now,speed)
            self.record('approach_revalidated',now,task_id=task.task_id,version=task.version,index=index,
                target=list(target),reasons=preview.reasons,outcome=preview.outcome.value)
            if preview.outcome not in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION):
                self._note_blocked(task,index,preview.reasons,now)
                raise PolicyError('unsafe_action:'+','.join(preview.reasons),dict(task_id=task.task_id,task_version=task.version,index=index,reasons=preview.reasons,recovery_tool='release_task'))
            action=Action(f'policy:{self.agent_id}:{self.request_number}:{now}',self.agent_id,'MOVE',now,now+30,(tuple(target),),speed,source='llm' if self.worker else 'rule_policy')
            if self.agent_id not in gate.active:
                checked=gate.dispatch(action,state,now)
                if checked.outcome not in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION):
                    self._note_blocked(task,index,checked.reasons,now)
                    raise PolicyError('unsafe_action:'+','.join(checked.reasons))
                self.motion_key=(task.task_id,task.version,index)
            self.blocked_approaches.pop(task.task_id,None)
            self.accepted_tasks.add((task.task_id,task.version))
            self._authorize(task,now,self.policy_source,tool,f'{self.agent_id}:{self.request_number}')
            return dict(status='search_authorized',task_id=task.task_id,version=task.version)
        if tool=='change_role':
            if p['new_role']==self.role:raise PolicyError('role_unchanged')
            if p['new_role']=='RESERVE' and self.battery>=self.guardian.config.min_battery_reserve_percent and any(t.status!=TaskStatus.COMPLETE for t in self.tasks.values()):raise PolicyError('reserve_requires_low_battery_or_completed_mission')
            if p['new_role']=='RELAY' and self.role!='RELAY':
                recent={a:b for a,b in self.peer_beliefs.items() if now-b['observed_at']<=self.guardian.config.max_peer_age_s}
                if any(b['role']=='RELAY' for b in recent.values()):raise PolicyError('healthy_relay_already_known')
                candidates=[self.agent_id]+[a for a,b in recent.items() if b.get('battery',0)>=self.guardian.config.min_battery_reserve_percent]
                if min(candidates)!=self.agent_id:raise PolicyError('not_deterministic_relay_candidate')
            if p['new_role']=='SCOUT' and self.battery<self.guardian.config.min_battery_reserve_percent:raise PolicyError('insufficient_reserve_for_scout')
            if p['new_role']!='SCOUT':
                self._stop_motion(gate)
                for task in self.tasks.values():
                    if self.agent_id in self.bids.get(task.task_id,{}):
                        self.bids[task.task_id].pop(self.agent_id,None)
                        self.send(MT.TASK_RELEASE,dict(task_id=task.task_id,version=task.version,reason='bid_withdrawn'),now)
                for task in list(self.tasks.values()):
                    if task.assigned_agent==self.agent_id and task.status==TaskStatus.ASSIGNED:self.release_task(task.task_id,now)
                self.authorized=None
            self.role=p['new_role']
            self._send_selected(MT.ROLE_CHANGE,dict(role=self.role,reason_code=p['reason_code']),now,d)
            return dict(status='role_changed',role=self.role)
        if tool=='request_help':
            self._send_selected(MT.HELP_REQUEST,dict(reason_code=p['reason_code']),now,d);return dict(status='help_requested')
        if tool=='report_target':
            observation=self.observations.get(p['observation_id'])
            if observation is None:raise PolicyError('unobserved_target')
            tid='INSPECT_'+p['observation_id']
            if tid in self.tasks:return dict(status='already_reported')
            task=MissionTask(tid,TaskType.INSPECT_TARGET,Geometry(tuple(observation['position'])),10,{'inspect'},work_units=1)
            self.tasks[tid]=task;self.routes[tid]=[list(observation['position'])];self.executor.routes=self.routes
            self.send(MT.TARGET_FOUND,dict(task=task.to_dict()),now);return dict(status='target_reported',task_id=tid)
        if tool in ('hold','return_home','act_as_relay'):
            if tool=='hold' and p['duration_s']>self.max_hold_seconds:raise PolicyError('hold_duration_exceeds_policy_limit')
            kind='HOLD' if tool=='hold' else 'RETURN_HOME' if tool=='return_home' else 'MOVE'
            if tool=='act_as_relay' and self.role!='RELAY':raise PolicyError('relay_role_required')
            if self.agent_id in gate.active:raise PolicyError('active_command_requires_completion')
            action=Action(f'policy:{self.agent_id}:{self.request_number}:{now}',self.agent_id,kind,now,now+30,
                (self.relay_point,) if kind=='MOVE' else (),1,p.get('duration_s',1.),'llm' if self.worker else 'rule_policy')
            checked=gate.dispatch(action,state,now)
            if checked.outcome not in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION):raise PolicyError('unsafe_action:'+','.join(checked.reasons))
            if kind!='HOLD':self.pending_policy_motion[action.command_id]=dict(source=self.policy_source,request_id=f'{self.agent_id}:{self.request_number}',tool=tool,start_position=list(self.position))
            return dict(status='guarded_skill_dispatched',kind=kind)
        raise PolicyError('unsupported_tool')

    def execution_tick(self,now,gate):
        task=self.executable_task(now)
        if self.authorized and (task is None or self.authorized!=(task.task_id,task.version)):
            # Revoke old epochs before any new action; cancellation must be confirmed.
            active=gate.active.get(self.agent_id)
            if active:
                if gate._cancel(self.agent_id):gate.confirm_completion(self.agent_id,active.command_id)
                else:self.record('revocation_cancellation_unconfirmed',now,command_id=active.command_id)
            self.authorized=None;self.motion_key=None
            self._fallback(now,gate,'task_authorization_revoked');return
        if not self.authorized:return
        if self.agent_id not in gate.active:
            index,target,preview=self._approach(task,now)
            if preview.outcome not in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION):
                self.authorized=None
                self.record('execution_guardian_intervention',now,reasons=preview.reasons)
                self._note_blocked(task,index,preview.reasons,now)
                if self.blocked_approaches[task.task_id]['count']>=self.safety_rejection_limit:self._release_blocked(task,now,gate)
                return
        arrival_start=len(self.executor.arrivals)
        action=self.executor.update(self,now)
        self._observe_arrivals(arrival_start,now)
        if action['action']=='hold':
            self.last_skill_result=dict(status='observed_search_completed' if action.get('complete') else 'holding',task_id=task.task_id,version=task.version)
            self.authorized=None;self.motion_key=None;return
        if self.single_index is not None and action['index']>self.single_index:
            self.authorized=None;self.single_index=None;self.motion_key=None;return
        key=(action['task_id'],action['version'],action['index'])
        if self.agent_id in gate.active:return
        target=self._motion_target(task,action['index'],now,min(1.,self.guardian.config.max_speed_mps))
        proposed=Action(f'executor:{self.agent_id}:{now}',self.agent_id,'MOVE',now,now+30,(target,),min(1.,self.guardian.config.max_speed_mps),source='rule_policy')
        decision=gate.dispatch(proposed,self.safety_state(now),now)
        self.motion_key=key
        if decision.outcome not in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION):
            self.authorized=None;self.record('execution_guardian_intervention',now,reasons=decision.reasons)
            self._note_blocked(task,action['index'],decision.reasons,now)
            if self.blocked_approaches[task.task_id]['count']>=self.safety_rejection_limit:self._release_blocked(task,now,gate)

    def save_memory(self):
        (self.out/'memory.json').write_text(json.dumps(dict(agent_id=self.agent_id,memory=list(self.memory)),indent=2)+'\n')
