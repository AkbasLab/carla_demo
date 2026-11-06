"""Small observed-flight regressions sharing existing mock/AirSim adapters and guardian.

Policies use only the perfect-message endpoints. The regression safety observer reads
all configured vehicle telemetry, including stopped actors; this is not an experiment
in decentralized safety-state estimation or degraded communication.
"""
import hashlib
import json
import math
from pathlib import Path
import time

from agentic_uav.comm.protocol import PerfectMessageBus
from agentic_uav.control.runtime_guardian import Action, State, Peer, RuntimeGuardian, GuardedExecutor, Fallback
from agentic_uav.coordination.contract_net import AllocationAgent, TaskStatus
from agentic_uav.coordination.flight_executor import WaypointExecutor, within_waypoint
from agentic_uav.policy.backends import MockFlight, AirSimFlight
from agentic_uav.policy.mission import load_mission

CASES = ('single_waypoint', 'two_nonconflicting', 'four_search', 'reassignment', 'return_home')


class RegressionAgent(AllocationAgent):
    def send(self, kind, payload, now):
        # A single-vehicle skill regression has no peer traffic to broadcast.
        if self.peers:
            super().send(kind, payload, now)



def run_regression(case, mission_config, output_dir, *, backend='mock', duration=120.,
                   dt=.1, speed=1., lease_seconds=20., fail_at=1., host='127.0.0.1',
                   rpc_timeout=2., setup_timeout=90., execute_live=False):
    if case not in CASES or backend not in ('mock', 'airsim'):
        raise ValueError('Unknown regression case/backend')
    for value in (duration, dt, speed, lease_seconds, rpc_timeout, setup_timeout):
        if not math.isfinite(value) or value <= 0:
            raise ValueError('Timing and speed must be positive and finite')
    if not math.isfinite(fail_at) or fail_at < 0:
        raise ValueError('Invalid failure time')
    if backend == 'airsim' and not execute_live:
        raise ValueError('AirSim regression requires --execute-live and calibrated mission geometry')
    m, cfg, tasks, routes = load_mission(mission_config)
    count = 1 if case in ('single_waypoint', 'return_home') else 2 if case == 'two_nonconflicting' else 4
    ids = list(m['vehicles'])[:count]
    if len(tasks) < count:
        raise ValueError('Not enough configured routes')
    tasks = tasks[:count]
    routes = {t.task_id: routes[t.task_id] for t in tasks}
    if speed > cfg.max_speed_mps:
        raise ValueError('Requested regression speed exceeds guardian maximum')
    out = Path(output_dir)
    if out.exists() and any(out.iterdir()):
        raise ValueError('Use a new result directory')
    out.mkdir(parents=True, exist_ok=True)
    def save(name, data):
        (out / name).write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')
    save('manifest.json', dict(case=case, backend=backend, controlled_vehicles=ids,
         mission=m, mission_sha256=hashlib.sha256(Path(mission_config).read_bytes()).hexdigest(),
         duration_s=duration, dt=dt, speed=speed, lease_seconds=lease_seconds, fail_at_s=fail_at,
         safety_observation='all configured vehicle RPC telemetry, including stopped actors',
         started_at_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), status='started'))
    clock = [0.]
    bus = PerfectMessageBus(ids, lambda: clock[0])
    agents = [RegressionAgent(a, [p for p in ids if p != a], bus.endpoint(a), tasks,
                              m['vehicles'][a]['start_position'], lease_s=lease_seconds, bid_window=.5)
              for a in ids]
    executors = {a: WaypointExecutor(routes, .4, z_tolerance=.6, stall_timeout=10.) for a in ids}
    flight = gate = None
    snapshots = []; events = []; error = None; cleanup = []; failed = None
    fault_tasks = []; return_requested = False; returned = False; complete = False
    observation = {}; sequence = 0; mission_start = None; motion_keys = {}
    try:
        flight = (MockFlight(m['vehicles'], lambda: clock[0]) if backend == 'mock' else
                  AirSimFlight(m['vehicles'], lambda: clock[0], host, rpc_timeout, cfg.ground_z))
        if backend == 'mock':
            for a, s in flight.states.items():
                s.update(home=m['vehicles'][a]['home'], ground_z=cfg.ground_z)
        gate = GuardedExecutor(RuntimeGuardian(cfg), flight.execute, flight.cancel)
        origin = time.monotonic()
        def refresh():
            for a in m['vehicles']:
                started = time.monotonic() - origin if backend == 'airsim' else clock[0]
                observation[a] = dict(flight.sample(a), observed_at=started)
            if backend == 'airsim':
                clock[0] = time.monotonic() - origin
        def state(a, *, battery=None):
            s = observation[a]
            phase = 'TAKEOFF' if a in gate.active and gate.active[a].kind == 'TAKEOFF' else s['phase']
            return State(a, tuple(s['position']), s['observed_at'], s['battery'] if battery is None else battery,
                         tuple(m['vehicles'][a]['home']),
                         peers={p: Peer(tuple(v['position']), tuple(v['velocity']), v['observed_at'])
                                for p, v in observation.items() if p != a},
                         expected_peers=tuple(p for p in m['vehicles'] if p != a), flight_phase=phase)
        def dispatch(a, kind, target=None, battery=None):
            nonlocal sequence
            sequence += 1
            action = Action(f'regression:{sequence}', a, kind, clock[0], clock[0]+min(30., cfg.max_action_duration_s),
                            (tuple(target),) if target is not None else (), speed)
            return gate.dispatch(action, state(a, battery=battery), clock[0])
        def advance():
            if backend == 'airsim':
                time.sleep(dt)
                clock[0] = time.monotonic() - origin
            else:
                clock[0] = round(clock[0] + dt, 9)
            for a, cid in flight.advance(dt):
                gate.confirm_completion(a, cid)
            refresh()
        refresh()
        if backend == 'airsim':
            if any(observation[a]['phase'] != 'GROUNDED' for a in ids):
                raise ValueError('Controlled vehicles must initially be landed')
            # AirSim takeoff can rise to its own intermediate height first.
            if cfg.max_height_m < 5:
                raise ValueError('Configure at least 5 m overhead for AirSim takeoff')
            for a in ids:
                target = m['vehicles'][a]['start_position']
                d = dispatch(a, 'TAKEOFF', target)
                if d.selected_action is None or d.selected_action.kind != 'TAKEOFF':
                    raise RuntimeError('Takeoff rejected: '+','.join(d.reasons))
            while gate.active and clock[0] < setup_timeout:
                advance()
                for a in ids:
                    gate.watchdog(state(a), clock[0])
            if gate.active or any(not within_waypoint(observation[a]['position'], m['vehicles'][a]['start_position'], .4, .6) for a in ids):
                raise TimeoutError('Airborne setup unconfirmed')
        mission_start = clock[0]
        while clock[0] - mission_start < duration:
            now = clock[0]
            elapsed = round(now - mission_start, 9)
            if case == 'reassignment' and failed is None and elapsed >= fail_at:
                failed = ids[0]
                owner = agents[0]
                fault_tasks = [t.task_id for t in owner.tasks.values()
                               if t.status == TaskStatus.ASSIGNED and t.assigned_agent == failed]
                events.append(dict(event='actor_silenced', time_s=elapsed, agent_id=failed, tasks=fault_tasks))
            if failed and failed in gate.active:
                if flight.cancel(failed):
                    gate.active.pop(failed, None)
                    events.append(dict(event='failure_stop_confirmed', time_s=elapsed, agent_id=failed))
            active = [a for a in agents if a.agent_id != failed]
            for a in active:
                a.position = list(observation[a.agent_id]['position'])
                a.receive(now)
            for a in active:
                a.step(now, dt, process_inbox=False, execute_mock=False)
                job = executors[a.agent_id].update(a, now)
                old_key = motion_keys.get(a.agent_id)
                if old_key and a.agent_id in gate.active:
                    task = a.tasks[old_key[0]]
                    revoked = (task.version != old_key[1] or task.assigned_agent != a.agent_id
                               or (task.status != TaskStatus.COMPLETE and
                                   (task.lease_expires_at is None or now >= task.lease_expires_at)))
                    if revoked and flight.cancel(a.agent_id):
                        gate.active.pop(a.agent_id, None)
                        motion_keys.pop(a.agent_id, None)
                        events.append(dict(event='revoked_motion_stop_confirmed', time_s=elapsed, agent_id=a.agent_id))
                if a.agent_id not in gate.active and job['action'] == 'move':
                    d = dispatch(a.agent_id, 'MOVE', job['target'])
                    if d.selected_action and d.selected_action.kind == 'MOVE':
                        motion_keys[a.agent_id] = (job['task_id'], job['version'])
                for mid in a.decisions:
                    bus.record_decision(a.agent_id, mid)
                a.decisions.clear()
            all_done = bool(active) and all(all(t.status == TaskStatus.COMPLETE for t in a.tasks.values()) for a in active)
            if all_done and not gate.active:
                if case == 'return_home' and not return_requested:
                    # Deliberate safety-state injection; never a claim about measured battery.
                    a = ids[0]
                    d = dispatch(a, 'MOVE', routes[tasks[0].task_id][-1], battery=cfg.min_battery_reserve_percent-1)
                    return_requested = d.fallback == Fallback.RETURN_HOME and d.selected_action is not None
                    events.append(dict(event='battery_injected', time_s=elapsed, fallback=str(d.fallback)))
                    if not return_requested:
                        raise RuntimeError('Expected validated RETURN_HOME fallback')
                elif case != 'return_home' or within_waypoint(observation[ids[0]]['position'], m['vehicles'][ids[0]]['home'], .4, .6):
                    returned = case == 'return_home'
                    complete = True
                    break
            snapshots.append(dict(time_s=elapsed, vehicles=json.loads(json.dumps(observation))))
            for a in ids:
                if a != failed:
                    gate.watchdog(state(a), now)
            advance()
    except Exception as exc:
        error = dict(type=type(exc).__name__, message=str(exc))
    finally:
        if flight is not None:
            # Retain API control in hover; do not assume an unsurveyed landing is safe.
            for a in ids:
                try:
                    if not flight.cancel(a):
                        cleanup.append(a+': stop unconfirmed; API control retained')
                except Exception as exc:
                    cleanup.append(a+': '+type(exc).__name__)
        arrivals = [r for e in executors.values() for r in e.arrivals]
        work = [e for a in agents for e in a.events if e['event'] == 'work_completed']
        duplicates = len(work)-len({e['task_id'] for e in work})
        taken = [t for t in fault_tasks if any(e['task_id']==t and e['agent_id']!=failed for e in work)]
        required = {(tid, i) for tid, route in routes.items() for i in range(len(route))}
        observed = {(r['task_id'], r['index']) for r in arrivals}
        passed = complete and error is None and duplicates == 0 and not cleanup and required <= observed
        if case == 'reassignment':
            passed = passed and bool(fault_tasks) and set(taken)==set(fault_tasks)
        if observation:
            snapshots.append(dict(time_s=clock[0]-(mission_start or 0), vehicles=observation))
        manifest = json.loads((out/'manifest.json').read_text())
        manifest.update(status='passed' if passed else 'error' if error else 'incomplete',
                        finished_at_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                        error=error, source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        save('manifest.json', manifest)
        save('summary.json', dict(case=case, backend=backend, passed=passed, mission_complete=complete,
             error=error, duplicate_completions=duplicates, failed_agent=failed, affected_tasks=fault_tasks,
             recovered_tasks=taken, return_home_observed=returned, cleanup_warnings=cleanup,
             limitations=['Kinematic mock is not live evidence', 'Perfect transport and shared safety observer; not decentralized safety estimation',
                          'Live cleanup requests hover and retains API control; no landing verification']))
        for name, value in [('events',events), ('messages',bus.logs()), ('waypoint_arrivals',arrivals),
                            ('agent_events',[e for a in agents for e in a.events]), ('flight_trace',snapshots),
                            ('guardian_audit',gate.audit if gate else []), ('executed_actions',flight.effects if flight else [])]:
            save(name+'.json', value)
    return json.loads((out/'summary.json').read_text())
