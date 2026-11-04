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
from .structured import TOOLS, PolicyError, AsyncWorker, ReplayProvider, validate_decision


class PersistentAgent(AllocationAgent):
    def __init__(self,*args,role,routes,home,relay_point,guardian,output_dir,provider,
                 mission,decision_interval=1.,inference_timeout=15.,max_context_age=20.,**kwargs):
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
        self.identity_fault=False;self.model_decisions=0;self.fallback_count=0;self.events_policy=[];self.completed_requests=set()
        self.received_counts={};self.status_times={};self.last_measurement=None;self.last_distance=None

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

    def _bid(self,task,now):
        self._allow_bid=True
        try:self.offer(task,now)
        finally:self._allow_bid=False

    def receive(self,now):
        messages=self.endpoint.receive_available();allocation=[]
        for m in messages:
            if m.mission_id!='phase8' or m.sender_id not in self.peers:continue
            self.received_counts[m.sender_id]=self.received_counts.get(m.sender_id,0)+1
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
        super().step(now,dt,process_inbox=False,execute_mock=False)

    def safety_state(self,now):
        peers={p:Peer(tuple(v['position']),tuple(v['velocity']),v['observed_at']) for p,v in self.peer_beliefs.items()}
        oldest=max((now-self.last_heartbeat.get(p,0) for p in self.peers),default=0)
        communication='LOST' if oldest>3 else 'DEGRADED' if oldest>1 else 'HEALTHY'
        return State(self.agent_id,tuple(self.position),self.state_time,self.battery,self.home,
            peers,tuple(self.peers),self.phase,communication,1.)

    def context(self,now):
        active=next((t for t in self.tasks.values() if t.assigned_agent==self.agent_id and t.status==TaskStatus.ASSIGNED),None)
        executable=self.executable_task(now)
        tasks=[dict(task_id=t.task_id,version=t.version,status=t.status.value,owner=t.assigned_agent,priority=t.priority,
                    own_bid=self.agent_id in self.bids.get(t.task_id,{}),center=list(t.location_or_region.center))
               for t in sorted(self.tasks.values(),key=lambda t:t.task_id)]
        return dict(agent_id=self.agent_id,team_mission=self.mission,current_role=self.role,
            current_task=dict(task_id=active.task_id,version=active.version,executable=executable is not None) if active else None,
            own_state=dict(position=self.position,velocity=self.velocity,battery=self.battery,flight_phase=self.phase,time_s=now,observed_at=self.state_time),
            tasks=tasks[:32],non_negotiable_constraints=asdict(self.guardian.config),
            summarized_beliefs=copy.deepcopy(self.peer_beliefs),recent_important_messages=list(self.recent_messages),
            memory=list(self.memory),available_tools=TOOLS,communication_estimate={p:dict(
                heartbeat_age_s=max(0,now-self.last_heartbeat.get(p,0)),received_messages=self.received_counts.get(p,0)) for p in self.peers},
            current_skill_result=self.last_skill_result,unresolved_decisions=['choose one valid tool; task ownership and safety checks are mandatory'],
            locally_observed_targets=list(self.observations)[:16],correction=self.correction)

    def request(self,now):
        if self.identity_fault or self.pending is not None or (self.worker and self.worker.busy) or now-self.last_request<self.decision_interval:return
        context=self.context(now);prompt=json.dumps(context,allow_nan=False,sort_keys=True)
        self.request_number+=1;token=f'{self.agent_id}:{self.request_number}';self.last_request=now
        self.pending=dict(token=token,context_time=now,wall_start=time.monotonic(),correction_attempt=self.correction_attempt)
        self._save('prompts',dict(request_id=token,simulation_time_s=now,prompt=prompt,correction_attempt=self.correction_attempt))
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
            if task is not None:self.authorized=(task.task_id,task.version)
        if self.agent_id not in gate.active:
            action=Action(f'fallback:{self.agent_id}:{now}',self.agent_id,'HOLD',now,now+3,(),1,1,'rule_policy')
            gate.dispatch(action,self.safety_state(now),now)

    def _failure(self,reason,now,gate,correctable):
        self.record('policy_error',now,reason_code=reason,correction_attempt=self.correction_attempt)
        if correctable and self.correction_attempt==0:
            self.correction_attempt=1;self.correction=dict(error=reason,instruction='Return exactly one corrected schema-valid decision. Do not invent coordinates or task ownership.')
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
            try:
                decision=validate_decision(result['raw'],self.peers)
                if decision['confidence']<.5:raise PolicyError('low_policy_confidence')
                tool_result=self.apply(decision,now,gate)
            except (PolicyError,ValueError,KeyError,TypeError) as error:
                reason=str(error)[:160] if isinstance(error,PolicyError) else type(error).__name__
                self._failure(reason,now,gate,True);return
            self.model_decisions+=1
            self.memory.append(dict(time_s=now,selected_tool=decision['selected_tool'],parameters=decision['parameters'],result=tool_result))
            self.last_skill_result=tool_result
            self.record('policy_decision_applied',now,request_id=result['token'],decision=decision,tool_result=tool_result,
                source='replay_fixture' if isinstance(self.provider,ReplayProvider) else 'llm',flight_phase=self.phase)
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
        route=self.routes[task.task_id];target=route[0];entry_distance=math.dist(self.position,target)
        distance=sum(math.dist(a,b) for a,b in zip([self.position]+route,route));speed=min(1.,self.guardian.config.max_speed_mps)
        score=bid_cost(task,self.position,self.battery,self.workload(),self.communication_risk,self.capabilities,self.weights,'searcher')
        proposed=Action(f'calculation:{self.agent_id}:{now}',self.agent_id,'MOVE',now,now+30,tuple(tuple(p) for p in route),speed)
        checked=self.guardian.evaluate(proposed,self.safety_state(now),now)
        return dict(task_id=task.task_id,task_version=task.version,computed_at=now,distance_m=distance,distance_to_entry_m=entry_distance,travel_time_s=distance/speed,bid=score,
            battery_sufficient=self.battery-distance*self.guardian.config.battery_cost_percent_per_m>=self.guardian.config.min_battery_reserve_percent,
            communication_reachability={p:('recent_contact' if now-self.status_times.get(p,-math.inf)<=1 else 'unknown') for p in self.peers},
            route_feasible=checked.outcome in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION),separation_risk='drone_separation' in checked.reasons,
            guardian_reasons=checked.reasons)

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
            if self.agent_id not in self.bids.get(task.task_id,{}):raise PolicyError('capability_or_battery_ineligible')
            return self._cost(task,now)
        if tool=='claim_task':
            task=self._task(p,now);offers=self.bids.get(task.task_id,{})
            if self.workload() or self.role!='SCOUT' or self.battery<self.guardian.config.min_battery_reserve_percent:raise PolicyError('not_eligible_to_claim')
            if task.status!=TaskStatus.BIDDING or now<self.auction_end.get(task.task_id,math.inf) or not offers:raise PolicyError('auction_not_ready')
            winner=min(offers.values(),key=lambda b:(b['score'],b['agent_id']))
            if winner['agent_id']!=self.agent_id:raise PolicyError('not_best_valid_bid')
            claim=dict(task_id=task.task_id,version=task.version,owner=self.agent_id,score=winner['score'])
            self.send(MT.TASK_AWARD,claim,now);self.adopt(task,claim,now);return dict(status='claim_sent')
        if tool in ('accept_task','start_search','go_to_waypoint','release_task','decline_task'):
            task=self._task(p,now,owned=tool!='decline_task')
            if tool=='accept_task':
                self.send(MT.TASK_ACCEPT,dict(task_id=task.task_id,version=task.version,owner=self.agent_id),now)
                return dict(status='ownership_confirmed',task_id=task.task_id)
            if tool in ('release_task','decline_task'):
                if task.assigned_agent==self.agent_id:
                    self._stop_motion(gate);self.release_task(task.task_id,now)
                else:
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
            action=Action(f'policy:{self.agent_id}:{self.request_number}:{now}',self.agent_id,'MOVE',now,now+30,(tuple(target),),speed,source='llm' if self.worker else 'rule_policy')
            if self.agent_id not in gate.active:
                checked=gate.dispatch(action,state,now)
                if checked.outcome not in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION):raise PolicyError('unsafe_action:'+','.join(checked.reasons))
                self.motion_key=(task.task_id,task.version,index)
            self.authorized=(task.task_id,task.version);return dict(status='search_authorized',task_id=task.task_id,version=task.version)
        if tool=='change_role':
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
            kind='HOLD' if tool=='hold' else 'RETURN_HOME' if tool=='return_home' else 'MOVE'
            if tool=='act_as_relay' and self.role!='RELAY':raise PolicyError('relay_role_required')
            if self.agent_id in gate.active:raise PolicyError('active_command_requires_completion')
            action=Action(f'policy:{self.agent_id}:{self.request_number}:{now}',self.agent_id,kind,now,now+30,
                (self.relay_point,) if kind=='MOVE' else (),1,p.get('duration_s',1.),'llm' if self.worker else 'rule_policy')
            checked=gate.dispatch(action,state,now)
            if checked.outcome not in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION):raise PolicyError('unsafe_action:'+','.join(checked.reasons))
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
        action=self.executor.update(self,now)
        if action['action']=='hold':
            self.last_skill_result=dict(status='observed_search_completed' if action.get('complete') else 'holding',task_id=task.task_id,version=task.version)
            self.authorized=None;self.motion_key=None;return
        if self.single_index is not None and action['index']>self.single_index:
            self.authorized=None;self.single_index=None;self.motion_key=None;return
        key=(action['task_id'],action['version'],action['index'])
        if self.agent_id in gate.active:return
        target=tuple(action['target'])
        proposed=Action(f'executor:{self.agent_id}:{now}',self.agent_id,'MOVE',now,now+30,(target,),1,source='rule_policy')
        decision=gate.dispatch(proposed,self.safety_state(now),now)
        self.motion_key=key
        if decision.outcome not in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION):
            self.authorized=None;self.record('execution_guardian_intervention',now,reasons=decision.reasons)

    def save_memory(self):
        (self.out/'memory.json').write_text(json.dumps(dict(agent_id=self.agent_id,memory=list(self.memory)),indent=2)+'\n')
