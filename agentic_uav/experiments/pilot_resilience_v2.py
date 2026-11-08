"""Opt-in Phase 17 recovery diagnostics. Never changes the legacy pilot defaults.

The independent telemetry service samples only its own vehicle and uses the same
application network. A policy-process failure is not a whole-vehicle radio failure.
No stale peer is removed or declared physically absent.
"""
from dataclasses import replace
import math
from agentic_uav.comm.protocol import MessageType as MT
from agentic_uav.control.runtime_guardian import Action, RuntimeGuardian, Outcome
from agentic_uav.coordination.contract_net import TaskStatus
from agentic_uav.policy.persistent import PersistentAgent
from agentic_uav.coordination.approach_planner import plan_approach,segment_distance

DEFAULTS=dict(enabled=False,independent_telemetry=True,telemetry_interval_s=.5,
              fault_mode='owned_motion',fault_displacement_m=.6,
              blocked_release_after_s=15.,rejection_log_interval_s=5.,rebid_cooldown_s=15.,
              coordination_timeout_s=3.,approach_detours=True)


def settings(values=None):
    result=dict(DEFAULTS)
    if values is not None:
        if not isinstance(values,dict) or set(values)-set(result):raise ValueError('Unknown pilot_resilience_v2 setting')
        result.update(values)
    for name in ('enabled','independent_telemetry','approach_detours'):
        if type(result[name]) is not bool:raise ValueError('Expected boolean '+name)
    if result['fault_mode'] not in ('fixed_time','owned_motion'):raise ValueError('Invalid V2 fault mode')
    for name in set(result)-{'enabled','independent_telemetry','approach_detours','fault_mode'}:
        if type(result[name]) not in (int,float) or not math.isfinite(result[name]) or result[name]<=0:raise ValueError('Invalid '+name)
    return result


class OwnVehicleTelemetry:
    """Local service, not a fault oracle: no knowledge of which policy is stopped."""
    def __init__(self,publish,recipients,interval_s):
        self.publish=publish;self.recipients=list(recipients);self.interval=interval_s;self.last=-math.inf

    def tick(self,now,*,position,velocity,battery,role,observed_at):
        if now-self.last<self.interval-1e-8:return False
        self.publish(MT.STATUS_UPDATE,dict(position=list(position),velocity=list(velocity),battery=battery,
            role=role,observed_at=observed_at,telemetry_source='independent_own_vehicle_service'),now,self.recipients)
        self.last=now;return True


def owned_motion_trigger(agent,gate,settings,start_position):
    """Scenario-only predicate; agents never receive the scheduler or its state."""
    def ready(now):
        action=gate.active.get(agent.agent_id)
        owns=any(t.status==TaskStatus.ASSIGNED and t.assigned_agent==agent.agent_id for t in agent.tasks.values())
        return (owns and action is not None and action.kind=='MOVE' and
                math.sqrt(sum(v*v for v in agent.velocity))>1e-6 and
                math.dist(agent.position,start_position)>=settings['fault_displacement_m'])
    return ready


def agent_class(base):
    """Compose with the Phase 14 instrumented class so all audits remain active."""
    class PilotResilienceAgent(base):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self.v2=self.settings['pilot_resilience_v2'];self.blocked_since={};self.wait_logged_at=-math.inf
            self.approach_plans={};self._coordination_members=None
            self.rejected_decisions={}

        def coordination_peers(self,now):
            timeout=min(self.lease_s,self.v2['coordination_timeout_s'])
            members={p for p in self.peers if now-self.last_heartbeat.get(p,0)<=timeout}
            if members!=self._coordination_members:
                self.record('coordination_membership_observed',now,eligible_peers=sorted(members),
                    timeout_s=timeout,physical_peers_retained=sorted(self.peers),
                    assumption='local_timeout_not_partition_consensus')
                self._coordination_members=members
            return members

        def _motion_target(self,task,index,now,speed):
            goal=tuple(self.routes[task.task_id][index]);key=(task.task_id,task.version,index)
            if not self.v2['approach_detours']:return goal
            self.approach_plans={k:v for k,v in self.approach_plans.items() if k==key}
            plan=self.approach_plans.get(key)
            if plan is not None:
                while plan['waypoints'] and math.dist(self.position,plan['waypoints'][0])<=.4:
                    plan['waypoints'].pop(0)
                if plan['waypoints']:return tuple(plan['waypoints'][0])
                self.approach_plans.pop(key,None)
                return goal
            state=self.safety_state(now)
            check=self.guardian.evaluate(Action(f'v2_direct:{self.agent_id}:{now}',self.agent_id,
                'MOVE',now,now+30,(goal,),speed),state,now)
            obstructed=any(segment_distance(self.position,goal,p.position)<self.guardian.config.min_separation_m+
                self.guardian.config.max_speed_mps*(now-p.observed_at)+.1 for p in state.peers.values())
            if 'peer_reachable_region_conflict' not in check.reasons and not obstructed:return goal
            plan=plan_approach(self.guardian,state,goal,now,speed,self.executor.tolerance)
            if plan is not None:
                self.approach_plans[key]=plan
                self.record('alternative_approach_selected',now,task_id=task.task_id,version=task.version,
                    index=index,mission_target=list(goal),**plan)
                return tuple(plan['waypoints'][0])
            return goal

        def send(self,kind,payload,now):
            # Physical beacons do not replace semantic completion gossip from
            # a still-running task policy. Keep previously verified facts visible.
            if kind==MT.STATUS_UPDATE and self.v2['independent_telemetry'] and not self.completed_facts:return
            return super().send(kind,payload,now)

        def _cost(self,task,now):
            # Runtime checks still validate every dispatched segment. Do not treat
            # a whole mission route as one command with a 30-second deadline.
            result=PersistentAgent._cost(self,task,now)
            route=self.routes[task.task_id][self.checkpoints.get(task.task_id,0):]
            state=replace(self.safety_state(now),peers={},expected_peers=())
            errors=[]
            for target in route:
                action=Action(f'v2_static:{self.agent_id}:{now}',self.agent_id,'MOVE',now,now+30,
                              (tuple(target),),min(1.,self.guardian.config.max_speed_mps))
                errors.extend(RuntimeGuardian._route_errors(self.guardian,action,state,now))
                state=replace(state,position=tuple(target))
            if not result['battery_sufficient']:errors.append('battery_reserve')
            result.update(full_route_static_feasible=not errors,immediate_segment_feasible=result['route_feasible'],
                          route_feasible=result['route_feasible'] and not errors,
                          guardian_reasons=sorted(set(result['guardian_reasons']+errors)),
                          future_segments_require_revalidation=True,route_deadline_model='separate_guarded_waypoint_commands')
            self.calculations[task.task_id]=result
            return result

        def _note_blocked(self,task,index,reasons,now):
            key=(task.task_id,task.version,index);previous=self.blocked_since.get(key)
            state_wait=bool(self.guardian._state_errors(self.safety_state(now),now)) or bool(
                set(reasons)&{'communication_or_belief_uncertainty','missing_peer_beliefs',
                              'stale_or_future_peer_belief','stale_or_future_state'})
            kind='state_wait' if state_wait else 'geometry'
            if previous is not None and previous.get('kind','geometry')!=kind:previous=None
            if previous is None:self.blocked_since[key]=dict(first=now,last_log=-math.inf,
                reasons=tuple(sorted(reasons)),position=tuple(self.position),kind=kind,
                blocked_elapsed_s=0.,last_checked=now,last_blocked=not state_wait)
            record=self.blocked_since[key]
            record['reasons']=tuple(sorted(reasons))
            # Authorization clears the base rejection cache. Log throttling must
            # never suppress rebuilding bookkeeping used by execution_tick().
            cached=self.blocked_approaches.get(task.task_id)
            if (cached is None or cached.get('key')!=key or
                    now-record['last_log']>=self.v2['rejection_log_interval_s']):
                super()._note_blocked(task,index,reasons,now);record['last_log']=now
                if self.architecture=='A':
                    self.send(MT.INTENT_UPDATE,dict(task_id=task.task_id,version=task.version,
                        owner=self.agent_id,execution_status='approach_blocked',index=index,
                        reasons=list(reasons),target=list(self.routes[task.task_id][index])),now)

        def execution_tick(self,now,gate):
            task=self.executable_task(now)
            if task is not None:
                index,_,check=self._approach(task,now);key=(task.task_id,task.version,index)
                record=self.blocked_since.get(key)
                # An approval or a new LLM authorization is not observed motion.
                if record and math.dist(self.position,record['position'])>=.2:
                    self.blocked_since.pop(key,None)
                rejected=check.outcome not in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION)
                if rejected:
                    self._note_blocked(task,index,check.reasons,now)
                record=self.blocked_since.get(key)
                if record and not rejected and record.get('kind')=='state_wait':
                    # Missing startup telemetry is not a permanently blocked route.
                    self.record('state_wait_resolved',now,task_id=task.task_id,version=task.version,
                                waited_s=now-record['first'])
                    self.blocked_since.pop(key,None);self.blocked_approaches.pop(task.task_id,None)
                    record=None
                decision_wait=bool(self.pending or (self.worker and self.worker.busy)
                                   or self.request_waiting_since is not None)
                if record:
                    geometry_blocked=rejected and record.get('kind','geometry')=='geometry'
                    # Charge sampled geometric blockage, not startup, shared-model
                    # admission/inference, or intervals in which the route is clear.
                    if geometry_blocked and record.get('last_blocked') and not decision_wait:
                        record['blocked_elapsed_s']+=max(0.,now-record['last_checked'])
                    record['last_checked']=now
                    record['last_blocked']=geometry_blocked and not decision_wait
                if (record and rejected and record.get('kind','geometry')=='geometry' and not decision_wait
                        and record['blocked_elapsed_s']+1e-8>=self.v2['blocked_release_after_s']):
                    # Base helper requires confirmed cancellation before release.
                    if PersistentAgent._release_blocked(self,task,now,gate,'v2_bounded_safety_wait'):
                        self.bid_blocked_until[task.task_id]=now+self.v2['rebid_cooldown_s']
                        self.blocked_since.pop(key,None);self.approach_plans.pop(key,None)
            return super().execution_tick(now,gate)

        def _failure(self,reason,now,gate,correctable,details=None):
            # Count actual rejected decisions, not previews or time waiting for
            # inference. Intermittent short-segment approvals must not permit an
            # endless correction loop against the same unchanged obstruction.
            task=self.executable_task(now)
            if (task is not None and reason.startswith('unsafe_action:') and
                    not self.guardian._state_errors(self.safety_state(now),now) and
                    isinstance(details,dict) and details.get('task_id')==task.task_id and
                    details.get('task_version')==task.version):
                key=(task.task_id,task.version,details.get('index'),reason)
                old=self.rejected_decisions.get(key,{})
                count=old.get('count',0)+1 if old and math.dist(self.position,old['position'])<.2 else 1
                self.rejected_decisions={key:dict(count=count,position=tuple(self.position))}
                if count>=self.safety_rejection_limit:
                    self.record('policy_error',now,reason_code=reason,validation_details=details,
                        correction_attempt=self.correction_attempt,disposition='release_after_repeated_rejection')
                    if PersistentAgent._release_blocked(self,task,now,gate,'v2_repeated_guardian_rejection'):
                        self.bid_blocked_until[task.task_id]=now+self.v2['rebid_cooldown_s']
                        self.rejected_decisions.clear()
                        return
            return super()._failure(reason,now,gate,correctable,details)

        def needs_decision(self,now):
            # Do not spend repeated inference on a currently unverifiable motion
            # context. Protocol/telemetry, watchdogs and bounded release keep ticking.
            errors=self.guardian._state_errors(self.safety_state(now),now)
            task=self.executable_task(now)
            if not errors and task is not None:
                _,_,check=self._approach(task,now)
                if check.outcome not in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION):errors=check.reasons
            if errors:
                if now-self.wait_logged_at>=self.v2['rejection_log_interval_s']:
                    self.record('v2_policy_waiting_for_safe_context',now,reasons=errors);self.wait_logged_at=now
                return False
            return super().needs_decision(now)
    return PilotResilienceAgent
