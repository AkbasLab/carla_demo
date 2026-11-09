"""Bounded local approach candidates from delivered telemetry, never ground truth.

This is not trajectory reservation or certified avoidance. Geometry and current
occupancy screen candidates; only the guardian authorizes each short live segment.
Intermediate points never count as mission waypoint work.
"""
from dataclasses import replace
import hashlib
import math
from agentic_uav.control.runtime_guardian import Action, Outcome, RuntimeGuardian, point, finite


def segment_distance(start,end,point):
    delta=tuple(b-a for a,b in zip(start,end));length=sum(x*x for x in delta)
    fraction=max(0.,min(1.,sum((point[i]-start[i])*delta[i] for i in range(3))/length)) if length else 0.
    return math.dist(tuple(start[i]+fraction*delta[i] for i in range(3)),point)


def plan_approach(guardian,state,target,now,speed,arrival_tolerance=0.):
    if (not point(target) or not finite(speed) or speed<=0 or not finite(arrival_tolerance)
            or arrival_tolerance<0 or guardian._state_errors(state,now) or state.communication=='LOST'):return None
    start=tuple(state.position);target=tuple(target);dx=target[0]-start[0];dy=target[1]-start[1]
    distance=math.hypot(dx,dy)
    if distance<.1:return None
    normal=(-dy/distance,dx/distance,0.)
    age=max((now-p.observed_at for p in state.peers.values()),default=0.)
    width=guardian.config.min_separation_m+guardian.config.max_speed_mps*(age+1.)+1.
    # Agent-stable side preference breaks symmetric approach choices without any
    # access to peer policy state. Both sides must independently pass validation.
    sign=1 if hashlib.sha256(state.vehicle_id.encode()).digest()[0]%2 else -1
    arrivals=[target]
    if arrival_tolerance>0:
        # Search inside the existing acceptance disk, never enlarge it. This can
        # avoid aiming at the centre when only an edge is physically admissible.
        radius=.9*arrival_tolerance
        angles=[i*math.pi/4 for i in range(8)]
        if state.peers:
            nearest=min(state.peers.values(),key=lambda p:math.dist(p.position,target))
            angles.insert(0,math.atan2(target[1]-nearest.position[1],target[0]-nearest.position[0]))
        arrivals.extend((target[0]+radius*math.cos(a),target[1]+radius*math.sin(a),target[2]) for a in angles)
    for arrival in arrivals:
        # Try a shorter lateral corridor first. Every leg must still clear the
        # same conservative occupancy screen and every live command the guardian.
        # A large default sidestep needlessly traverses neighbouring task lanes.
        for factor in (.5,1.,1.5):
            for side in (sign,-sign):
                offset=tuple(side*factor*width*x for x in normal)
                points=[tuple(start[i]+offset[i] for i in range(3)),
                        tuple(arrival[i]+offset[i] for i in range(3)),arrival]
                total=sum(math.dist(a,b) for a,b in zip([start]+points,points))
                if state.battery_percent-total*guardian.config.battery_cost_percent_per_m<guardian.config.min_battery_reserve_percent:continue
                valid=True;position=start
                for number,end in enumerate(points):
                    action=Action(f'approach_candidate:{state.vehicle_id}:{now}:{number}',state.vehicle_id,'MOVE',now,now+30,(end,),speed)
                    # Static checks are performed for every leg, not just the shortened
                    # first leg returned by ReachablePeerGuardian.evaluate().
                    static=replace(state,position=position,peers={},expected_peers=())
                    if RuntimeGuardian._route_errors(guardian,action,static,now):valid=False;break
                    if any(segment_distance(position,end,p.position)<guardian.config.min_separation_m+
                           guardian.config.max_speed_mps*(now-p.observed_at)+.1 for p in state.peers.values()):
                        valid=False;break
                    position=end
                if not valid:continue
                first=Action(f'approach_entry:{state.vehicle_id}:{now}',state.vehicle_id,'MOVE',now,now+30,(points[0],),speed)
                decision=guardian.evaluate(first,state,now)
                if decision.outcome in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION):
                    return dict(waypoints=points,distance_m=total,created_at=now,
                                future_segments_require_revalidation=True,required_waypoint=target,arrival_point=arrival)
    return None
