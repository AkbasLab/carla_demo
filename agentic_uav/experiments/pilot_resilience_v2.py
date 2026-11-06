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

DEFAULTS=dict(enabled=False,independent_telemetry=True,telemetry_interval_s=.5,
              fault_mode='owned_motion',fault_displacement_m=.6,
              blocked_release_after_s=15.,rejection_log_interval_s=5.,rebid_cooldown_s=15.)


def settings(values=None):
    result=dict(DEFAULTS)
    if values is not None:
        if not isinstance(values,dict) or set(values)-set(result):raise ValueError('Unknown pilot_resilience_v2 setting')
        result.update(values)
    for name in ('enabled','independent_telemetry'):
        if type(result[name]) is not bool:raise ValueError('Expected boolean '+name)
    if result['fault_mode'] not in ('fixed_time','owned_motion'):raise ValueError('Invalid V2 fault mode')
    for name in set(result)-{'enabled','independent_telemetry','fault_mode'}:
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
            if previous is None:self.blocked_since[key]=dict(first=now,last_log=-math.inf,reasons=tuple(sorted(reasons)))
            elif previous['reasons']!=tuple(sorted(reasons)):
                self.blocked_since[key]=dict(first=now,last_log=-math.inf,reasons=tuple(sorted(reasons)))
            record=self.blocked_since[key]
            if now-record['last_log']>=self.v2['rejection_log_interval_s']:
                super()._note_blocked(task,index,reasons,now);record['last_log']=now

        def execution_tick(self,now,gate):
            task=self.executable_task(now)
            if task is not None:
                index,_,check=self._approach(task,now);key=(task.task_id,task.version,index)
                if check.outcome in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION):self.blocked_since.pop(key,None)
                else:
                    self._note_blocked(task,index,check.reasons,now)
                    if now-self.blocked_since[key]['first']>=self.v2['blocked_release_after_s']:
                        # Base helper requires confirmed cancellation before release.
                        if PersistentAgent._release_blocked(self,task,now,gate,'v2_bounded_safety_wait'):
                            self.bid_blocked_until[task.task_id]=now+self.v2['rebid_cooldown_s']
                            self.blocked_since.pop(key,None)
            return super().execution_tick(now,gate)

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
