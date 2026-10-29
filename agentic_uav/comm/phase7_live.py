"""Perfect message protocol while four configured AirSim multirotors fly.

Agents receive their own telemetry and addressed messages only. Vehicle/simulator
access is confined to the experiment harness, never used to populate peer beliefs.
"""
import json
import math
import time
from pathlib import Path
from agentic_uav.comm.protocol import MessageType, PerfectMessageBus
from agentic_uav.comm.phase7_demo import ProtocolAgent


def run_live_protocol(args):
    import airsim
    ids = args.vehicles
    client = airsim.MultirotorClient(ip=args.airsim_host, timeout_value=args.rpc_timeout)
    client.confirmConnection()
    missing = set(ids) - set(client.listVehicles())
    if missing:
        raise ValueError(f'Configure four AirSim multirotors first; missing {sorted(missing)}')
    now = [0.]
    bus = PerfectMessageBus(ids, lambda: now[0])
    agents = [ProtocolAgent(agent, [p for p in ids if p != agent], bus.endpoint(agent)) for agent in ids]
    trace, cleanup_errors, controlled = [], [], []
    world = previous = None
    completed = False
    failure = None
    initial = {}
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        if args.carla_host:
            import carla
            carla_client = carla.Client(args.carla_host, args.carla_port)
            carla_client.set_timeout(args.rpc_timeout)
            world = carla_client.get_world()
            previous = world.get_settings()
            settings = world.get_settings()
            settings.synchronous_mode = False
            world.apply_settings(settings)
        # A valid scene must already provide separated spawn locations and a clear short route.
        for agent in ids:
            p = client.getMultirotorState(vehicle_name=agent).kinematics_estimated.position
            initial[agent] = (p.x_val, p.y_val, p.z_val - args.flight_height)
            client.enableApiControl(True, vehicle_name=agent)
            controlled.append(agent)
            client.armDisarm(True, vehicle_name=agent)
        futures = [client.takeoffAsync(timeout_sec=args.setup_timeout, vehicle_name=agent) for agent in ids]
        for future in futures:
            future.join()
        for agent in ids:
            client.moveToPositionAsync(*initial[agent], velocity=1., timeout_sec=args.setup_timeout, vehicle_name=agent)
        deadline = time.monotonic() + args.setup_timeout
        ready_since = None
        while time.monotonic() < deadline:
            ready = True
            for agent in ids:
                state = client.getMultirotorState(vehicle_name=agent)
                p = state.kinematics_estimated.position
                v = state.kinematics_estimated.linear_velocity
                ready &= (state.landed_state != airsim.LandedState.Landed and
                          math.dist((p.x_val,p.y_val,p.z_val), initial[agent]) < .3 and
                          math.sqrt(v.x_val**2+v.y_val**2+v.z_val**2) < .3)
            ready_since = (time.monotonic() if ready_since is None else ready_since) if ready else None
            if ready_since is not None and time.monotonic()-ready_since >= 1.:
                break
            time.sleep(.1)
        else:
            raise TimeoutError('Four vehicles did not reach airborne starting positions')
        start = time.monotonic()
        # Exercise all envelopes; only heartbeat/status currently have decision consumers.
        for kind in MessageType:
            agents[0].send(kind, {'protocol_probe': True}, 0.)
        for tick in range(args.ticks):
            time.sleep(max(0, start + tick*args.dt-time.monotonic()))
            now[0] = time.monotonic()-start
            for agent in agents:
                state = client.getMultirotorState(vehicle_name=agent.agent_id)
                p = state.kinematics_estimated.position
                agent.position = [p.x_val,p.y_val,p.z_val]
                airborne = state.landed_state != airsim.LandedState.Landed
                agent.send(MessageType.HEARTBEAT, {'alive': True}, now[0])
                agent.send(MessageType.STATUS_UPDATE, {'position':list(agent.position), 'in_air':airborne, 'role':'searcher'}, now[0])
                trace.append(dict(tick=tick, time_s=now[0], agent_id=agent.agent_id,
                                  own_position=list(agent.position), in_air=airborne))
            for agent in agents:
                agent.receive()
                for decision in agent.decision_trace:
                    bus.record_decision(agent.agent_id, decision['message_id'])
                agent.decision_trace.clear()
                record = next(r for r in reversed(trace) if r['agent_id']==agent.agent_id)
                record.update(action=agent.action, team_beliefs=json.loads(json.dumps(agent.team_beliefs)))
                # Each vehicle follows a short forward segment, keeping its own initial height.
                if agent.action == 'continue_flight':
                    origin = initial[agent.agent_id]
                    offset = min(args.flight_distance, args.flight_speed*now[0])
                    client.moveToPositionAsync(origin[0]+offset, origin[1], origin[2],
                        velocity=args.flight_speed, timeout_sec=args.rpc_timeout, vehicle_name=agent.agent_id)
                else:
                    client.hoverAsync(vehicle_name=agent.agent_id)
        completed = True
    except Exception as exc:
        failure = repr(exc)
        raise
    finally:
        # Cleanup is infrastructure, not peer communication or mission reasoning.
        for agent in controlled:
            try:
                client.landAsync(timeout_sec=args.setup_timeout, vehicle_name=agent).join()
                if client.getMultirotorState(vehicle_name=agent).landed_state == airsim.LandedState.Landed:
                    client.armDisarm(False, vehicle_name=agent)
                    client.enableApiControl(False, vehicle_name=agent)
                else:
                    client.hoverAsync(vehicle_name=agent)
                    cleanup_errors.append(f'{agent}: landing unconfirmed; API control retained')
            except Exception as exc:
                cleanup_errors.append(f'{agent}: {exc!r}')
        if world is not None and previous is not None:
            try:
                world.apply_settings(previous)
            except Exception as exc:
                cleanup_errors.append(f'CARLA restore: {exc!r}')
        logs = bus.logs()
        exit_passed = bool(completed and trace and all(r['in_air'] for r in trace) and
            all(set(a.team_beliefs)==set(a.peers) for a in agents) and
            all(r['status']=='delivered' for r in logs))
        summary = dict(mode='perfect_communication_airsim_protocol', completed=completed,
            error=failure, agents=ids, ticks=args.ticks, exit_criterion_passed=exit_passed,
            message_types=[t.value for t in MessageType], recipient_deliveries=len(logs),
            delivered=sum(r['status']=='delivered' for r in logs), cleanup_errors=cleanup_errors,
            limitations=['Configured separated spawns/clear route required; no collision avoidance is provided',
                         'Agent isolation is an API convention, not a security sandbox',
                         'Task/role message probes do not implement auctions or negotiation',
                         'AirSim integration requires live validation; passing mock tests is not flight evidence'])
        (out/'messages.json').write_text(json.dumps(logs,indent=2)+'\n')
        (out/'beliefs.json').write_text(json.dumps(trace,indent=2)+'\n')
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(json.dumps(summary,indent=2))
    return summary
