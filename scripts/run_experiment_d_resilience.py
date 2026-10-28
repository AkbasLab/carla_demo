"""Experiment D: application-heartbeat faults with deterministic OBA landing recovery.

AirSim RPC stays available. No LLM, true RF outage, terrain perception, or onboard deployment.
"""
import argparse
import csv
import hashlib
import json
import math
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentic_uav.control.oba_recovery import RecoveryGuardian

VERSION = 'experiment-d-oba-landing-v2'


def xyz(vector):
    return (vector.x_val, vector.y_val, vector.z_val)


def run(args):
    import airsim
    import carla
    config = json.loads(Path(args.boundary_config).read_text())
    guardian = RecoveryGuardian.from_config(config)
    if args.recovery == 'oba-land' and guardian.site.get('surveyed_clear') is not True:
        raise ValueError('Configure a surveyed-clear landing site before using oba-land')
    cruise_z = guardian.site['ground_z'] - args.cruise_height
    route = [guardian.approach(cruise_z),
             (guardian.site['x'] + args.mission_distance, guardian.site['y'], cruise_z)]
    for a, b in ((route[0], route[1]), (route[1], route[0])):
        approved, reason = guardian.check_segment(a, b)
        if not approved:
            raise ValueError('Mission route rejected: ' + reason)
    approved, reason = guardian.approve_landing(route[0], args.position_tolerance)
    if args.recovery == 'oba-land' and not approved:
        raise ValueError('Landing configuration rejected: ' + reason)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    client = carla.Client(args.carla_host, args.carla_port)
    client.set_timeout(args.rpc_timeout)
    world = client.get_world()
    previous = world.get_settings()
    air = None
    rows, events = [], []
    status, error = 'failed', None
    phase = 'setup'
    detection = recovery = first_loss = detection_loss_streak = None
    stable_since = None
    collision_seen = False
    violations_during_recovery = 0
    landing_commanded = False
    mission_legs = 0
    last_heartbeat = 0.0
    last_command = -math.inf
    recovery_target = None
    start = None

    def event(name, elapsed, **fields):
        events.append(dict(event=name, elapsed_s=elapsed, **fields))
        print(f'[D] {elapsed:.2f}s {name} {fields}', flush=True)

    try:
        # Async physics continues during takeoff, setup, and all recovery RPCs.
        settings = world.get_settings()
        settings.synchronous_mode = False
        world.apply_settings(settings)
        air = airsim.MultirotorClient(timeout_value=args.rpc_timeout)
        air.confirmConnection()
        air.enableApiControl(True)
        air.armDisarm(True)
        initial = xyz(air.getMultirotorState().kinematics_estimated.position)
        ok, reason = guardian.check_segment(initial, route[0])
        if not ok:
            raise ValueError('Initial setup route rejected: ' + reason)
        air.takeoffAsync(timeout_sec=args.setup_timeout).join()
        air.moveToPositionAsync(*route[0], velocity=args.speed,
                                timeout_sec=args.setup_timeout)
        deadline = time.monotonic() + args.setup_timeout
        ready_since = None
        while time.monotonic() < deadline:
            state = air.getMultirotorState()
            pos = xyz(state.kinematics_estimated.position)
            if guardian.violations(pos):
                raise RuntimeError('Boundary violation during setup')
            if math.dist(pos, route[0]) <= args.position_tolerance and math.dist(xyz(state.kinematics_estimated.linear_velocity), (0, 0, 0)) <= args.safe_speed:
                ready_since = ready_since if ready_since is not None else time.monotonic()
                if time.monotonic() - ready_since >= args.stable_seconds:
                    break
            else:
                ready_since = None
            time.sleep(1 / args.hz)
        else:
            raise TimeoutError('Vehicle did not settle before measurement')
        phase, waypoint = 'mission', 1
        start = time.monotonic()
        collision_timestamp = air.simGetCollisionInfo().time_stamp
        first_loss_streak = None
        for tick in range(math.ceil(args.duration * args.hz)):
            time.sleep(max(0, start + (tick + 1) / args.hz - time.monotonic()))
            state = air.getMultirotorState()
            pos, vel = xyz(state.kinematics_estimated.position), xyz(state.kinematics_estimated.linear_velocity)
            elapsed = time.monotonic() - start
            speed = math.dist(vel, (0, 0, 0))
            collision = air.simGetCollisionInfo()
            if collision.has_collided and collision.time_stamp != collision_timestamp:
                collision_seen = True
            reasons = guardian.violations(pos)  # Evaluation independent of recovery decision.
            in_range = math.dist(pos, (guardian.site['x'], guardian.site['y'], guardian.site['ground_z'])) <= args.rf_range
            dropped = elapsed >= args.inject_at and rng.random() < args.loss
            delivered = in_range and not dropped
            if delivered:
                last_heartbeat, first_loss_streak = elapsed, None
            else:
                first_loss = elapsed if first_loss is None else first_loss
                first_loss_streak = elapsed if first_loss_streak is None else first_loss_streak
            age = elapsed - last_heartbeat
            if detection is None and age > args.timeout:
                detection = elapsed
                detection_loss_streak = first_loss_streak
                event('heartbeat_timeout', elapsed, loss_streak_start_s=first_loss_streak,
                      delay_from_last_heartbeat_s=age)
                if args.recovery != 'none':
                    phase = 'braking'
                    air.hoverAsync()
                    event('hover_command', elapsed)
            # Recovery is latched; restored heartbeats cannot silently resume the mission.
            if phase not in ('mission', 'setup'):
                violations_during_recovery += bool(reasons)
            if args.recovery == 'oba-land' and detection is not None and phase not in ('blocked', 'failed', 'landed'):
                if elapsed - detection > args.recovery_timeout:
                    phase = 'failed'
                    air.hoverAsync()
                    event('recovery_timeout', elapsed)
                elif reasons or collision_seen:
                    phase = 'blocked'
                    air.hoverAsync()
                    event('recovery_blocked', elapsed, reasons=reasons or ['collision'])
                elif phase == 'braking' and speed <= args.safe_speed and elapsed > detection:
                    recovery_target = guardian.approach(pos[2])
                    ok, reason = guardian.check_segment(pos, recovery_target)
                    if ok:
                        phase = 'returning'
                        air.moveToPositionAsync(*recovery_target, velocity=args.speed,
                                                timeout_sec=args.recovery_timeout)
                        event('approved_return_command', elapsed, target=recovery_target)
                    else:
                        phase = 'blocked'
                        event('recovery_blocked', elapsed, reason=reason)
                elif phase == 'returning':
                    ok, reason = guardian.check_segment(pos, recovery_target)
                    if not ok:
                        phase = 'blocked'
                        air.hoverAsync()
                        event('recovery_blocked', elapsed, reason=reason)
                    elif math.dist(pos, recovery_target) <= args.position_tolerance and speed <= args.safe_speed:
                        ok, reason = guardian.approve_landing(pos, args.position_tolerance)
                        if ok:
                            air.landAsync(timeout_sec=args.recovery_timeout)
                            landing_commanded, phase = True, 'landing'
                            event('approved_land_command', elapsed)
                        else:
                            phase = 'blocked'
                            air.hoverAsync()
                            event('recovery_blocked', elapsed, reason=reason)
                elif phase == 'landing':
                    ok, reason = guardian.approve_landing(pos, guardian.site['radius_m'] - 1e-6)
                    if not ok:
                        phase = 'blocked'
                        air.hoverAsync()
                        event('descent_aborted', elapsed, reason=reason)
            if phase == 'mission' and elapsed - last_command >= args.command_interval:
                if math.dist(pos, route[waypoint]) <= args.position_tolerance:
                    waypoint = 1 - waypoint
                    mission_legs += 1
                # OBA also checks actual-to-proposed segments before mission dispatch.
                ok, reason = guardian.check_segment(pos, route[waypoint])
                if args.recovery == 'oba-land' and not ok:
                    phase = 'blocked'
                    air.hoverAsync()
                    event('mission_command_blocked', elapsed, reason=reason)
                else:
                    air.moveToPositionAsync(*route[waypoint], velocity=args.speed,
                                            timeout_sec=args.rpc_timeout)
                last_command = elapsed
            landed = state.landed_state == airsim.LandedState.Landed
            if args.recovery == 'oba-land':
                candidate = (phase == 'landing' and landed and speed <= args.safe_speed
                             and not reasons and not collision_seen
                             and math.hypot(pos[0] - guardian.site['x'], pos[1] - guardian.site['y']) <= args.position_tolerance
                             and abs(pos[2] - guardian.site['ground_z']) <= args.ground_tolerance)
            else:
                candidate = (args.recovery == 'hover' and phase == 'braking' and detection is not None
                             and elapsed > detection and speed <= args.safe_speed and not reasons and not collision_seen)
            stable_since = (stable_since if stable_since is not None else elapsed) if candidate else None
            if recovery is None and stable_since is not None and elapsed - stable_since >= args.stable_seconds:
                recovery = elapsed
                if args.recovery == 'oba-land':
                    phase = 'landed'
                event('landing_observed' if args.recovery == 'oba-land' else 'stable_hover_observed', elapsed)
            rows.append(dict(tick=tick, wall_elapsed_s=elapsed, airsim_timestamp_ns=state.timestamp,
                             carla_timestamp_s=world.get_snapshot().timestamp.elapsed_seconds,
                             x=pos[0], y=pos[1], z=pos[2], speed_mps=speed,
                             height_above_configured_ground_m=guardian.site['ground_z'] - pos[2],
                             rf_in_range=int(in_range), injected_drop=int(dropped),
                             heartbeat_delivered=int(delivered), heartbeat_age_s=age,
                             phase=phase, boundary_violation=int(bool(reasons)),
                             boundary_reasons=';'.join(reasons), collision_seen=int(collision_seen),
                             landed=int(landed)))
            if tick % args.log_every == 0:
                print(f'[D] {elapsed:.1f}s phase={phase} heartbeat={delivered}', flush=True)
        status = 'completed'
    except Exception as exc:
        error = repr(exc)
        raise
    finally:
        # Save experiment outcomes BEFORE cleanup; cleanup landing never counts as recovery.
        summary = dict(script_version=VERSION, status=status, error=error,
                       script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       parameters=vars(args), boundary_config=config, samples=len(rows),
                       heartbeat_delivered=sum(r['heartbeat_delivered'] for r in rows),
                       injected_drops=sum(r['injected_drop'] for r in rows),
                       first_undelivered_heartbeat_s=first_loss, failsafe_detection_s=detection,
                       detection_loss_streak_start_s=detection_loss_streak,
                       detection_latency_from_loss_streak_s=detection - detection_loss_streak if detection is not None and detection_loss_streak is not None else None,
                       recovery_observed_s=recovery, landing_commanded=landing_commanded,
                       recovery_time_from_detection_s=recovery - detection if recovery is not None else None,
                       boundary_violation_samples=sum(r['boundary_violation'] for r in rows),
                       boundary_violation_samples_during_recovery=violations_during_recovery,
                       collision_seen=collision_seen, recovery_success=bool(recovery is not None and not collision_seen and not violations_during_recovery),
                       mission_legs_completed=mission_legs, mission_completion=None,
                       false_failsafe_activation=None, events=events,
                       limitations=['Heartbeat injection only; RPC remains available; watchdog runs in Python client, not onboard',
                                    'Static configured geometry and surveyed landing-site assumption; no terrain perception',
                                    'Estimated vehicle state; sampled violations can miss between-sample excursions',
                                    'Asynchronous CARLA and AirSim clocks are not synchronized',
                                    'Mission completion and false activation require a separately defined mission and expected-outage oracle',
                                    'No LLM; recovery geometry extends OBA rather than using legacy midpoint guardian'])
        try:
            if rows:
                with (out / 'telemetry.csv').open('w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)
            (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        finally:
            try:
                if air is not None:
                    if phase != 'landed':
                        air.hoverAsync()
                    # No unchecked cleanup landing: preserve blocked/failed recovery for inspection.
                    if phase == 'landed':
                        air.armDisarm(False)
                        air.enableApiControl(False)
                    print('[D] Cleanup excluded from metrics; landed vehicle disarmed.' if phase == 'landed' else '[D] Unlanded vehicle hovering under API control; manage it after the test.', flush=True)
            finally:
                world.apply_settings(previous)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--boundary-config', required=True)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--recovery', choices=['none', 'hover', 'oba-land'], default='hover')
    for name, default in [('loss', 0.5), ('inject-at', 5.), ('duration', 45.), ('timeout', 2.),
                          ('hz', 10.), ('rf-range', 60.), ('safe-speed', 0.25), ('speed', 2.),
                          ('cruise-height', 3.), ('mission-distance', 10.), ('command-interval', 0.5),
                          ('setup-timeout', 60.), ('rpc-timeout', 15.), ('recovery-timeout', 30.),
                          ('stable-seconds', 1.), ('position-tolerance', 0.3), ('ground-tolerance', 0.5)]:
        p.add_argument('--' + name, type=float, default=default)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--log-every', type=int, default=10)
    p.add_argument('--carla-host', default='localhost')
    p.add_argument('--carla-port', type=int, default=2000)
    a = p.parse_args()
    values = vars(a)
    for key, value in values.items():
        if isinstance(value, float) and (not math.isfinite(value) or (key not in ('loss', 'inject_at') and value <= 0)):
            p.error('Numeric parameters must be finite and positive')
    if not 0 <= a.loss <= 1 or a.inject_at < 0 or a.log_every < 1:
        p.error('Invalid loss, injection time, or logging interval')
    return a


if __name__ == '__main__':
    run(parse_args())
