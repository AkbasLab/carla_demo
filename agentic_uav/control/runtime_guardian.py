"""Phase 11 deterministic action gate in a shared NED frame.

No planner/network access. Every proposal, modification and fallback is checked
against supplied telemetry and surveyed geometry before the wrapped executor.
This is an abstract safety envelope, not certified flight control.
"""
from dataclasses import dataclass, asdict, replace, field
from enum import Enum
import copy
import json
import math
from .oba_recovery import RecoveryGuardian, segment_hits_box


class Outcome(str, Enum):
    APPROVE='APPROVE'
    APPROVE_WITH_MODIFICATION='APPROVE_WITH_MODIFICATION'
    REJECT_AND_REPLAN='REJECT_AND_REPLAN'
    EXECUTE_SAFE_FALLBACK='EXECUTE_SAFE_FALLBACK'


class Fallback(str, Enum):
    HOLD_POSITION='HOLD_POSITION'
    CLIMB_OR_DESCEND_TO_SAFE_LAYER='CLIMB_OR_DESCEND_TO_SAFE_LAYER'
    RETURN_HOME='RETURN_HOME'
    LAND_AT_SAFE_LOCATION='LAND_AT_SAFE_LOCATION'
    CONTINUE_LAST_VALID_PLAN='CONTINUE_LAST_VALID_PLAN'


def finite(value):
    return not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value)


def point(value):
    return isinstance(value,(tuple,list)) and len(value)==3 and all(finite(v) for v in value)


@dataclass(frozen=True)
class Action:
    command_id: str
    vehicle_id: str
    kind: str
    issued_at: float
    valid_until: float
    waypoints: tuple = ()
    speed_mps: float = 1.
    duration_s: float = 1.
    source: str = 'rule_policy'  # Provenance only; source grants no privilege.


@dataclass(frozen=True)
class Peer:
    position: tuple
    velocity: tuple
    observed_at: float


@dataclass(frozen=True)
class State:
    vehicle_id: str
    position: tuple
    observed_at: float
    battery_percent: float
    home: tuple  # Airborne home/approach point, not implicit authorization to land.
    peers: dict = field(default_factory=dict)
    expected_peers: tuple = ()
    flight_phase: str = 'AIRBORNE'
    communication: str = 'HEALTHY'
    belief_confidence: float = 1.


@dataclass(frozen=True)
class Config:
    flight_bounds: dict
    keepouts: list
    landing_site: dict
    ground_z: float = 0.
    min_height_m: float = 2.
    max_height_m: float = 20.
    max_speed_mps: float = 5.
    min_battery_reserve_percent: float = 20.
    critical_battery_percent: float = 10.
    landing_reserve_percent: float = 2.
    battery_cost_percent_per_m: float = .1
    min_separation_m: float = 2.
    max_state_age_s: float = 1.
    max_peer_age_s: float = 1.
    max_command_age_s: float = 2.
    max_action_duration_s: float = 30.
    minimum_confidence: float = .8
    obstacle_margin_m: float = .5

    def __post_init__(self):
        geometry=RecoveryGuardian.from_config(dict(flight_bounds=self.flight_bounds,keepouts=self.keepouts,
            landing_site=self.landing_site,obstacle_margin_m=self.obstacle_margin_m))
        if self.landing_site['ground_z']!=self.ground_z:raise ValueError('Landing site and reference ground must agree')
        for key,value in asdict(self).items():
            if key not in ('flight_bounds','keepouts','landing_site') and not finite(value):raise ValueError(key)
        if not 0<self.min_height_m<self.max_height_m:raise ValueError('Invalid height interval')
        if not 0<=self.landing_reserve_percent<self.critical_battery_percent<self.min_battery_reserve_percent<=100:raise ValueError('Invalid battery thresholds')
        if not 0<=self.minimum_confidence<=1:raise ValueError('Invalid confidence threshold')
        for key in ('max_speed_mps','min_separation_m','max_state_age_s','max_peer_age_s','max_command_age_s','max_action_duration_s'):
            if getattr(self,key)<=0:raise ValueError(key)
        if self.battery_cost_percent_per_m<0:raise ValueError('Invalid battery cost')


@dataclass
class Decision:
    outcome: Outcome
    reasons: list
    selected_action: Action | None = None
    fallback: Fallback | None = None
    fallback_rejections: list = field(default_factory=list)


class RuntimeGuardian:
    def __init__(self,config):
        self.config=copy.deepcopy(config)
        c=self.config
        self.geometry=RecoveryGuardian.from_config(dict(flight_bounds=c.flight_bounds,keepouts=c.keepouts,
            landing_site=c.landing_site,obstacle_margin_m=c.obstacle_margin_m))

    def _state_errors(self,state,now):
        c=self.config
        if not finite(now) or now<0:return ['invalid_clock']
        if not isinstance(state,State) or not isinstance(state.vehicle_id,str) or not state.vehicle_id:return ['invalid_state']
        if not point(state.position) or not point(state.home) or not finite(state.observed_at):return ['invalid_state']
        errors=[]
        if not 0<=now-state.observed_at<=c.max_state_age_s:errors.append('stale_or_future_state')
        if not finite(state.battery_percent) or not 0<=state.battery_percent<=100:errors.append('invalid_battery')
        if not finite(state.belief_confidence) or not 0<=state.belief_confidence<=1:errors.append('invalid_confidence')
        if state.flight_phase not in ('GROUNDED','TAKEOFF','AIRBORNE','LANDING'):errors.append('invalid_flight_phase')
        if state.communication not in ('HEALTHY','DEGRADED','LOST'):errors.append('invalid_communication_state')
        if not isinstance(state.peers,dict) or not isinstance(state.expected_peers,(list,tuple)):return errors+['invalid_peer_beliefs']
        if any(not isinstance(p,str) or not p for p in state.expected_peers) or any(not isinstance(p,str) or not p for p in state.peers):return errors+['invalid_peer_identity']
        if set(state.expected_peers)-set(state.peers):errors.append('missing_peer_beliefs')
        for peer in state.peers.values():
            if not isinstance(peer,Peer) or not point(peer.position) or not point(peer.velocity) or not finite(peer.observed_at):errors.append('invalid_peer_belief');continue
            if not 0<=now-peer.observed_at<=c.max_peer_age_s:errors.append('stale_or_future_peer_belief')
        return errors

    def _action_errors(self,a,state,now):
        if not isinstance(a,Action):return ['invalid_action_schema']
        if not isinstance(a.command_id,str) or not a.command_id or a.vehicle_id!=state.vehicle_id:return ['invalid_command_identity']
        if not isinstance(a.source,str) or not a.source:return ['invalid_source']
        if a.kind not in ('MOVE','TAKEOFF','HOLD','RETURN_HOME','LAND'):return ['unsupported_action']
        if not all(finite(v) for v in (a.issued_at,a.valid_until,a.speed_mps,a.duration_s)):return ['nonfinite_action']
        if not isinstance(a.waypoints,(list,tuple)) or not all(point(p) for p in a.waypoints):return ['invalid_waypoint']
        if a.kind in ('MOVE','TAKEOFF') and not a.waypoints:return ['missing_waypoint']
        if a.kind not in ('MOVE','TAKEOFF') and a.waypoints:return ['unexpected_waypoint']
        if a.speed_mps<=0 or a.duration_s<=0:return ['invalid_speed_or_duration']
        if a.issued_at<0 or a.issued_at>now or a.valid_until<=a.issued_at:return ['invalid_command_time']
        if now>=a.valid_until or now-a.issued_at>self.config.max_command_age_s:return ['command_timeout']
        return []

    def _route(self,a,state):
        if a.kind in ('MOVE','TAKEOFF'):return [tuple(p) for p in a.waypoints]
        if a.kind=='RETURN_HOME':return [tuple(state.home)]
        if a.kind=='LAND':return [(state.position[0],state.position[1],self.config.ground_z)]
        return [tuple(state.position)]

    def _route_errors(self,a,state,now,emergency=False,safe_layer=False):
        c=self.config;route=self._route(a,state);points=[tuple(state.position)]+route;errors=[]
        if a.speed_mps>c.max_speed_mps:errors.append('maximum_speed')
        if state.flight_phase=='GROUNDED' and a.kind not in ('HOLD','TAKEOFF'):errors.append('invalid_grounded_action')
        if state.flight_phase not in ('GROUNDED','TAKEOFF') and a.kind=='TAKEOFF':errors.append('takeoff_while_airborne')
        if a.kind=='LAND':
            ok,reason=self.geometry.approve_landing(state.position,min(.25,c.landing_site['radius_m']/2))
            if not ok:errors.append(reason)
        for idx,p in enumerate(points):
            height=c.ground_z-p[2]
            below_allowed=(a.kind=='LAND') or (a.kind=='TAKEOFF' and idx==0) or (state.flight_phase=='GROUNDED' and a.kind=='HOLD')
            if height>c.max_height_m or (height<c.min_height_m and not below_allowed):
                if not (safe_layer and idx==0):errors.append('altitude_bounds')
            if not self.geometry.inside(p):errors.append('geofence')
        elapsed=0.;distance=0.
        for start,end in zip(points,points[1:]):
            if any(segment_hits_box(start,end,b,c.obstacle_margin_m) for b in c.keepouts):errors.append('restricted_zone')
            dist=math.dist(start,end);distance+=dist
            duration=dist/a.speed_mps if dist else a.duration_s
            own_velocity=tuple((end[i]-start[i])/duration for i in range(3))
            for peer in state.peers.values():
                age=now-peer.observed_at
                predicted=tuple(peer.position[i]+peer.velocity[i]*(age+elapsed) for i in range(3))
                relative=tuple(start[i]-predicted[i] for i in range(3));velocity=tuple(own_velocity[i]-peer.velocity[i] for i in range(3))
                vv=sum(v*v for v in velocity)
                t=max(0.,min(duration,-sum(relative[i]*velocity[i] for i in range(3))/vv)) if vv else 0.
                separation=math.sqrt(sum((relative[i]+velocity[i]*t)**2 for i in range(3)))
                # Add bounded state-age uncertainty; future motion assumes constant velocity.
                if separation<c.min_separation_m+c.max_speed_mps*age:errors.append('drone_separation')
            elapsed+=duration
        if elapsed>c.max_action_duration_s or now+elapsed>a.valid_until:errors.append('execution_deadline')
        floor=c.landing_reserve_percent if emergency else c.min_battery_reserve_percent
        if state.battery_percent-distance*c.battery_cost_percent_per_m<floor:errors.append('battery_reserve')
        return sorted(set(errors))

    def _fallback(self,state,now,reasons,last_plan):
        c=self.config;current_height=c.ground_z-state.position[2]
        def action(kind,waypoints=()):
            return Action(f'guardian:{state.vehicle_id}:{now}:{kind}',state.vehicle_id,kind,now,
                          now+c.max_action_duration_s+1,tuple(waypoints),min(1.,c.max_speed_mps),1.,'guardian')
        candidates=[]
        if state.flight_phase=='GROUNDED':candidates=[(Fallback.HOLD_POSITION,action('HOLD'),False)]
        else:
            if state.battery_percent<=c.critical_battery_percent:candidates.append((Fallback.LAND_AT_SAFE_LOCATION,action('LAND'),False))
            if not c.min_height_m<=current_height<=c.max_height_m:
                z=c.ground_z-max(c.min_height_m,min(c.max_height_m,current_height))
                candidates.append((Fallback.CLIMB_OR_DESCEND_TO_SAFE_LAYER,action('MOVE',[(state.position[0],state.position[1],z)]),True))
            if state.battery_percent<c.min_battery_reserve_percent:candidates.append((Fallback.RETURN_HOME,action('RETURN_HOME'),False))
            if state.communication=='DEGRADED' and state.belief_confidence>=c.minimum_confidence and last_plan is not None:
                # Preserve original deadline; a stale plan is never made fresh by recovery.
                candidates.append((Fallback.CONTINUE_LAST_VALID_PLAN,last_plan,False))
            candidates.append((Fallback.HOLD_POSITION,action('HOLD'),False))
        rejected=[]
        for name,a,layer in candidates:
            why=(['insufficient_belief_for_motion'] if state.belief_confidence<c.minimum_confidence and a.kind!='HOLD' else []) or self._action_errors(a,state,now) or self._route_errors(a,state,now,emergency=True,safe_layer=layer)
            if not why:return Decision(Outcome.EXECUTE_SAFE_FALLBACK,reasons,a,name,rejected)
            rejected.append(dict(fallback=name.value,reasons=why))
        return Decision(Outcome.REJECT_AND_REPLAN,reasons+['no_verified_safe_fallback'],fallback_rejections=rejected)

    def evaluate(self,proposal,state,now,active_command=None,last_plan=None):
        state_errors=self._state_errors(state,now)
        if state_errors:return Decision(Outcome.REJECT_AND_REPLAN,state_errors)
        why=self._action_errors(proposal,state,now)
        if why:
            if why==['command_timeout']:return self._fallback(state,now,why,last_plan)
            return Decision(Outcome.REJECT_AND_REPLAN,why)
        if active_command is not None:return Decision(Outcome.REJECT_AND_REPLAN,['conflicting_simultaneous_command'])
        c=self.config
        if state.communication=='LOST' or state.belief_confidence<c.minimum_confidence:
            return self._fallback(state,now,['communication_or_belief_uncertainty'],last_plan)
        corrected=replace(proposal,speed_mps=min(proposal.speed_mps,c.max_speed_mps))
        errors=self._route_errors(corrected,state,now)
        if 'battery_reserve' in errors or 'altitude_bounds' in errors:
            return self._fallback(state,now,errors,last_plan)
        if errors:return Decision(Outcome.REJECT_AND_REPLAN,errors)
        if corrected!=proposal:return Decision(Outcome.APPROVE_WITH_MODIFICATION,['maximum_speed_clamped'],corrected)
        return Decision(Outcome.APPROVE,[],corrected)


class GuardedExecutor:
    """Only this gateway dispatches in the Phase 11 harness. Independent audit log."""
    def __init__(self,guardian,execute,cancel):
        self.guardian=guardian;self.execute_action=execute;self.cancel_action=cancel
        self.active={};self.active_started={};self.active_state={};self.last_plan={};self.audit=[];self.seen=set()

    def _reservation_conflict(self,action,state,now):
        # Cross-check known concurrent plans, not just last observed peer velocity.
        def segments(a,s,start_time):
            start=tuple(s.position);time=start_time;result=[]
            for end in self.guardian._route(a,s):
                duration=math.dist(start,end)/a.speed_mps or a.duration_s
                velocity=tuple((end[i]-start[i])/duration for i in range(3))
                result.append((time,time+duration,start,velocity))
                time+=duration;start=end
            # Reserve the final occupied position through the command's validity.
            if time<a.valid_until:result.append((time,a.valid_until,start,(0.,0.,0.)))
            return result
        own=segments(action,state,now)
        for vehicle,other in self.active.items():
            if vehicle==state.vehicle_id:continue
            for a0,a1,p,v in own:
                for b0,b1,q,w in segments(other,self.active_state[vehicle],self.active_started[vehicle]):
                    begin=max(a0,b0);end=min(a1,b1)
                    if begin>end:continue
                    r=tuple(p[i]+v[i]*(begin-a0)-q[i]-w[i]*(begin-b0) for i in range(3))
                    delta=tuple(v[i]-w[i] for i in range(3));vv=sum(x*x for x in delta)
                    t=max(0.,min(end-begin,-sum(r[i]*delta[i] for i in range(3))/vv)) if vv else 0.
                    if math.sqrt(sum((r[i]+delta[i]*t)**2 for i in range(3)))<self.guardian.config.min_separation_m:return True
        return False

    def _cancel(self,vehicle_id):
        try:return self.cancel_action(vehicle_id) is True
        except Exception:return False

    def _execute(self,action):
        try:
            effect=self.execute_action(action)
            if not isinstance(effect,dict):raise ValueError('Executor must return a result dictionary')
            return effect
        except Exception as error:
            # A transport failure cannot establish whether the action started.
            return dict(executed=False,completed=False,possibly_active=True,status='execution_unconfirmed',error=type(error).__name__)

    def confirm_completion(self,vehicle_id,command_id):
        active=self.active.get(vehicle_id)
        if active is not None and active.command_id==command_id:
            self.active.pop(vehicle_id);self.active_started.pop(vehicle_id,None)
            return True
        return False

    def _record(self,proposal,state,now,decision,effect):
        # repr safely preserves malformed/nonfinite inputs; audit JSON itself is finite.
        try:
            proposed=asdict(proposal) if isinstance(proposal,Action) else copy.deepcopy(proposal)
            json.dumps(proposed,allow_nan=False)
        except (TypeError,ValueError):proposed={'invalid_proposal_repr':repr(proposal)}
        try:
            observed=asdict(state)
            json.dumps(observed,allow_nan=False)
        except (TypeError,ValueError):observed={'invalid_state_repr':repr(state)}
        self.audit.append(dict(time_s=now if finite(now) else None,vehicle_id=state.vehicle_id,observed_state=observed,proposed_action=proposed,
            outcome=decision.outcome.value,reasons=decision.reasons,
            selected_action=asdict(decision.selected_action) if decision.selected_action else None,
            fallback=decision.fallback.value if decision.fallback else None,
            fallback_rejections=decision.fallback_rejections,mission_effect=effect))

    def dispatch(self,proposal,state,now):
        d=self.guardian.evaluate(proposal,state,now,self.active.get(state.vehicle_id),self.last_plan.get(state.vehicle_id))
        if isinstance(proposal,Action) and (state.vehicle_id,proposal.command_id) in self.seen:
            d=Decision(Outcome.REJECT_AND_REPLAN,['replayed_command'])
        if d.selected_action and self._reservation_conflict(d.selected_action,state,now):
            d=Decision(Outcome.REJECT_AND_REPLAN,d.reasons+['conflicting_reserved_trajectory'])
        effect={'executed':False,'status':'replan_required'}
        if d.selected_action:
            # Existing execution must be canceled before a timeout fallback can start.
            if state.vehicle_id in self.active:
                if not self._cancel(state.vehicle_id):
                    d=Decision(Outcome.REJECT_AND_REPLAN,d.reasons+['cancellation_unconfirmed'])
                else:self.active.pop(state.vehicle_id)
            if d.selected_action:
                effect=self._execute(d.selected_action)
                if effect.get('executed') or effect.get('possibly_active'):
                    if isinstance(proposal,Action):self.seen.add((state.vehicle_id,proposal.command_id))
                    if not effect.get('completed',False):
                        self.active[state.vehicle_id]=d.selected_action;self.active_started[state.vehicle_id]=now;self.active_state[state.vehicle_id]=copy.deepcopy(state)
                    if effect.get('executed') and d.outcome in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION):self.last_plan[state.vehicle_id]=d.selected_action
        self._record(proposal,state,now,d,effect)
        return d

    def watchdog(self,state,now):
        active=self.active.get(state.vehicle_id)
        if active is None:return None
        errors=self.guardian._state_errors(state,now)
        uncertain=bool(errors) or state.communication=='LOST' or state.belief_confidence<self.guardian.config.minimum_confidence
        timed_out=not finite(now) or now-self.active_started[state.vehicle_id]>=self.guardian.config.max_action_duration_s
        if not errors and not uncertain and not timed_out and now<active.valid_until and not self.guardian._route_errors(active,state,now):return None
        if not self._cancel(state.vehicle_id):
            d=Decision(Outcome.REJECT_AND_REPLAN,['watchdog','cancellation_unconfirmed'])
            self._record(active,state,now,d,dict(executed=False,status='cancellation_unconfirmed'));return d
        self.active.pop(state.vehicle_id)
        # Fresh fallback candidates are checked only after confirmed cancellation.
        d=Decision(Outcome.REJECT_AND_REPLAN,errors) if errors else self.guardian._fallback(state,now,['runtime_timeout_or_state_violation'],None)
        if d.selected_action and self._reservation_conflict(d.selected_action,state,now):
            d=Decision(Outcome.REJECT_AND_REPLAN,d.reasons+['conflicting_reserved_trajectory'])
        effect=self._execute(d.selected_action) if d.selected_action else dict(executed=False,status='no_verified_safe_fallback')
        if d.selected_action and (effect.get('executed') or effect.get('possibly_active')) and not effect.get('completed',False):
            self.active[state.vehicle_id]=d.selected_action;self.active_started[state.vehicle_id]=now;self.active_state[state.vehicle_id]=copy.deepcopy(state)
        self._record(active,state,now,d,effect);return d
