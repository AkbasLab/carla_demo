"""Experiment D: application-heartbeat faults with deterministic OBA landing recovery.

AirSim RPC stays available. Optional LLM commands; no true RF outage or onboard deployment.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentic_uav.control.oba_recovery import RecoveryGuardian
from agentic_uav.comm.llm_commands import LLMCommandWorker, CommandReceiver, validate_target

VERSION = 'experiment-d-llm-hover-v3'


def xyz(vector):
    return (vector.x_val, vector.y_val, vector.z_val)


def load_boundary_config(path, expand=False):
    config = json.loads(Path(path).read_text())
    if expand:
        # Expand each axis to at least [-100, 100] NED meters; never shrink a wider box.
        for axis in 'xyz':
            bounds = config['flight_bounds']
            bounds[axis + '_min'] = min(bounds[axis + '_min'], -100.)
            bounds[axis + '_max'] = max(bounds[axis + '_max'], 100.)
    return config


def run(args):
    import airsim
    import carla
    if args.command_source == 'llm' and args.llm_provider == 'openai' and not os.environ.get('OPENAI_API_KEY'):
        raise ValueError('Set OPENAI_API_KEY for the OpenAI provider')
    replay = []
    if args.command_source == 'replay':
        if not args.replay_file:
            raise ValueError('--replay-file is required for replay')
        replay = json.loads(Path(args.replay_file).read_text())
        for item in replay:
            validate_target({'target': item['target']})
            if (not math.isfinite(item['at_s']) or item['at_s'] < 0 or
                    not math.isfinite(item.get('created_at_s', item['at_s'])) or
                    not 0 <= item.get('created_at_s', item['at_s']) <= item['at_s']):
                raise ValueError('Replay at_s must be finite and nonnegative')
        replay.sort(key=lambda c: c['at_s'])
    config = load_boundary_config(args.boundary_config, args.expand_flight_bounds)
    print(f"[D] Effective AirSim NED flight bounds: {config['flight_bounds']}", flush=True)
    guardian = RecoveryGuardian.from_config(config)
    if args.recovery == 'oba-land' and guardian.site.get('surveyed_clear') is not True:
        raise ValueError('Configure a surveyed-clear landing site before using oba-land')
    cruise_z = guardian.site['ground_z'] - args.cruise_height
    route = [guardian.approach(cruise_z),
             (guardian.site['x'] + args.mission_distance, guardian.site['y'], cruise_z)]
    for a, b in (() if args.communication_only else ((route[0], route[1]), (route[1], route[0]))):
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
    worker = None
    receiver = CommandReceiver()
    command_events = []
    pending = False
    sequence = replay_index = 0
    last_request = -math.inf
    active_target = None

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
        if not ok and not args.communication_only:
            raise ValueError(f'Initial setup route rejected: {reason}; current={initial}; target={route[0]}; bounds={guardian.bounds}')
        air.takeoffAsync(timeout_sec=args.setup_timeout).join()
        air.moveToPositionAsync(*route[0], velocity=args.speed,
                                timeout_sec=args.setup_timeout)
        deadline = time.monotonic() + args.setup_timeout
        ready_since = None
        while time.monotonic() < deadline:
            state = air.getMultirotorState()
            pos = xyz(state.kinematics_estimated.position)
            if guardian.violations(pos) and not args.communication_only:
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
        if args.command_source == 'llm':
            worker = LLMCommandWorker(args.llm_provider, args.llm_model, args.llm_timeout,
                                      args.command_ttl, args.mission_prompt)
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
                    receiver.latched = True
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
            incoming = []
            if worker is not None:
                result = worker.poll()
                if result is not None:
                    pending = False
                    if 'error_type' in result:
                        event('llm_request_failed', elapsed, **result)
                    else:
                        incoming.append(result)
                if phase == 'mission' and not pending and elapsed-last_request >= args.llm_interval:
                    sequence += 1
                    worker.submit(sequence, dict(position=pos, cruise_z=cruise_z,
                        suggested_waypoints=route, elapsed_s=elapsed))
                    pending, last_request = True, elapsed
            while args.command_source == 'replay' and replay_index < len(replay) and replay[replay_index]['at_s'] <= elapsed:
                item = replay[replay_index]
                replay_index += 1
                created = start + item.get('created_at_s', item['at_s'])
                incoming.append(dict(sequence=replay_index, target=validate_target({'target': item['target']}),
                    created_at=created, expires_at=created+args.command_ttl, inference_latency_s=0))
            for command in incoming:
                decision = receiver.receive(command, time.monotonic(), delivered)
                command_events.append(dict(sequence=command['sequence'], target=list(command['target']),
                    at_s=command['created_at']-start, received_at_s=elapsed,
                    inference_latency_s=command['inference_latency_s'], decision=decision))
                event('mission_command_' + decision, elapsed, sequence=command['sequence'])
                if decision == 'accepted':
                    active_target = command['target']
                    # Retain OBA dispatch checks only in the OBA arm.
                    ok, reason = guardian.check_segment(pos, active_target)
                    if args.recovery == 'oba-land' and not ok:
                        phase = 'blocked'
                        receiver.latched = True
                        air.hoverAsync()
                        event('mission_command_blocked', elapsed, reason=reason)
                        command_events[-1]['decision'] = 'oba_rejected'
                        active_target = None
                    else:
                        air.moveToPositionAsync(*active_target, velocity=args.speed, timeout_sec=args.rpc_timeout)
                        event('mission_command_dispatched', elapsed, sequence=command['sequence'])
            if args.command_source == 'shuttle' and phase == 'mission' and elapsed - last_command >= args.command_interval:
                if math.dist(pos, route[waypoint]) <= args.position_tolerance:
                    waypoint = 1 - waypoint
                    mission_legs += 1
                ok, reason = guardian.check_segment(pos, route[waypoint])
                if args.recovery == 'oba-land' and not ok:
                    phase = 'blocked'
                    receiver.latched = True
                    air.hoverAsync()
                    event('mission_command_blocked', elapsed, reason=reason)
                elif delivered:
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
                             and elapsed > detection and speed <= args.safe_speed
                             and (args.communication_only or (not reasons and not collision_seen)))
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
        if worker is not None:
            worker.close()
        # Save experiment outcomes BEFORE cleanup; cleanup landing never counts as recovery.
        summary = dict(script_version=VERSION, status=status, error=error,
                       script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       parameters=vars(args), boundary_config=config, samples=len(rows),
                       command_events=command_events,
                       command_counts={name: sum(c['decision']==name for c in command_events) for name in
                           ('accepted','dropped','expired','suppressed_after_timeout','duplicate_or_out_of_order','oba_rejected')},
                       heartbeat_delivered=sum(r['heartbeat_delivered'] for r in rows),
                       injected_drops=sum(r['injected_drop'] for r in rows),
                       speed_at_first_loss_mps=next((r['speed_mps'] for r in rows if not r['heartbeat_delivered']), None),
                       llm_commands_dispatched_before_first_loss=sum(c['decision']=='accepted' and first_loss is not None and c['received_at_s']<first_loss for c in command_events),
                       first_undelivered_heartbeat_s=first_loss, failsafe_detection_s=detection,
                       detection_loss_streak_start_s=detection_loss_streak,
                       detection_latency_from_loss_streak_s=detection - detection_loss_streak if detection is not None and detection_loss_streak is not None else None,
                       recovery_observed_s=recovery, landing_commanded=landing_commanded,
                       sustained_hover_observed=bool(args.recovery=='hover' and recovery is not None),
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
                                    'Optional live LLM or replay; syntax validation is not semantic safety verification',
                                    'Commands and heartbeats share a per-tick application delivery gate; inference does not stop heartbeats',
                                    'Communication-only hover verifies stopping, not collision-free or boundary-preserving safety'])
        try:
            if rows:
                with (out / 'telemetry.csv').open('w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)
            (out / 'commands.json').write_text(json.dumps(command_events, indent=2) + '\n')
            (out / 'replay_commands.json').write_text(json.dumps([dict(at_s=c['received_at_s'],created_at_s=c['at_s'],target=c['target']) for c in command_events], indent=2) + '\n')
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
    p.add_argument('--expand-flight-bounds', action='store_true',
                   help='Expand each configured NED axis to at least [-100, 100] meters; preserve keepouts and landing checks')
    p.add_argument('--output-dir', required=True)
    p.add_argument('--recovery', choices=['none', 'hover', 'oba-land'], default='hover')
    for name, default in [('loss', 0.5), ('inject-at', 5.), ('duration', 45.), ('timeout', 2.),
                          ('hz', 10.), ('rf-range', 60.), ('safe-speed', 0.25), ('speed', 2.),
                          ('cruise-height', 3.), ('mission-distance', 10.), ('command-interval', 0.5),
                          ('setup-timeout', 60.), ('rpc-timeout', 15.), ('recovery-timeout', 30.),
                          ('stable-seconds', 1.), ('position-tolerance', 0.3), ('ground-tolerance', 0.5)]:
        p.add_argument('--' + name, type=float, default=default)
    p.add_argument('--command-source', choices=['shuttle', 'llm', 'replay'], default='shuttle')
    p.add_argument('--communication-only', action='store_true', help='Hover/none baseline: record geometry but do not gate mission or setup on geofences')
    p.add_argument('--llm-provider', choices=['ollama', 'openai'], default='ollama')
    p.add_argument('--llm-model', default=None)
    p.add_argument('--llm-timeout', type=float, default=15.)
    p.add_argument('--llm-interval', type=float, default=3.)
    p.add_argument('--command-ttl', type=float, default=20.)
    p.add_argument('--mission-prompt', default='Fly between the two suggested waypoints, choosing the one farther from the current position. Keep cruise Z unchanged.')
    p.add_argument('--replay-file')
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--log-every', type=int, default=10)
    p.add_argument('--carla-host', default='localhost')
    p.add_argument('--carla-port', type=int, default=2000)
    a = p.parse_args()
    if a.communication_only and a.recovery == 'oba-land':
        p.error('--communication-only is for hover/none; OBA landing requires boundary checks')
    if a.llm_model is None:
        a.llm_model = 'llama3.1:latest' if a.llm_provider == 'ollama' else 'gpt-4o-mini'
    values = vars(a)
    for key, value in values.items():
        if isinstance(value, float) and (not math.isfinite(value) or (key not in ('loss', 'inject_at') and value <= 0)):
            p.error('Numeric parameters must be finite and positive')
    if not 0 <= a.loss <= 1 or a.inject_at < 0 or a.log_every < 1:
        p.error('Invalid loss, injection time, or logging interval')
    return a


if __name__ == '__main__':
    run(parse_args())
