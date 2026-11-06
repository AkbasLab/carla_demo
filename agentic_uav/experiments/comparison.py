"""One configurable A/B/C/D route benchmark with shared infrastructure.

Physical execution is the Phase 12 kinematic backend. This initial comparison
harness does not claim AirSim flight or calibrated radio performance.
"""
from collections import Counter
import copy
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import time
from agentic_uav.comm.degraded import DegradedMessageBus,ObservedEndpoint,NetworkConfig,preset
from agentic_uav.control.runtime_guardian import RuntimeGuardian,GuardedExecutor,Action
from agentic_uav.control.scenario_manager import ExperimentSchedule
from agentic_uav.policy.backends import MockFlight
from agentic_uav.policy.mission import load_mission
from agentic_uav.policy.structured import OllamaProvider,ReplayProvider
from agentic_uav.policy.evidence import admit_requests,policy_evidence
from .resilience import settings as resilience_settings, RetryingEndpoint, ReachablePeerGuardian
from .architectures import ComparisonAgent,FixedTaskAgent,FleetController,RulePolicy,CONTROLLER,BID_WEIGHTS

DEFAULTS=dict(schema_version=1,architecture='C',backend='mock',mission_config='configs/phase12/mission.example.json',
    condition='nominal',network={},seed=42,ticks=3000,dt=.1,clock_mode='auto',
    lease_seconds=180.,bid_window=30.,decision_interval=.5,inference_timeout=30.,max_context_age=35.,
    inference_parallelism=1,progress_timeout=60.,beacon_interval_s=.5,command_timeout_s=3.,state_timeout_s=2.,
    policy=dict(provider='replay',model=None,model_digest=None,ollama_url='http://localhost:11434'),
    resilience=resilience_settings(),
    scenario=dict(fail_agent=None,fail_at_s=8.),
    initial_assignments=dict(Drone1=['SEARCH_SECTOR_A'],Drone2=['SEARCH_SECTOR_B'],Drone3=['SEARCH_SECTOR_C'],Drone4=['SEARCH_SECTOR_D']),
    ablations=dict(persistent_memory=True,task_leases=True,dynamic_roles=True,perfect_communication=False,fallback_policy=False),
    output_dir='results/phase13/comparison')


def configuration(values=None):
    values=values or {}
    if set(values)-set(DEFAULTS):raise ValueError('Unknown comparison settings: '+str(sorted(set(values)-set(DEFAULTS))))
    c=copy.deepcopy(DEFAULTS)
    for key,value in values.items():
        if key=='resilience':c[key]=resilience_settings(value)
        elif key in ('policy','scenario','ablations'):
            if not isinstance(value,dict) or set(value)-set(DEFAULTS[key]):raise ValueError('Invalid '+key+' settings')
            c[key].update(value)
        else:c[key]=copy.deepcopy(value)
    if c['schema_version']!=1 or c['architecture'] not in ('A','B','C','D'):raise ValueError('Choose architecture A, B, C or D')
    if c['backend']!='mock':raise ValueError('Phase 13 initial comparison supports mock flight only; live comparison is not validated')
    if c['condition'] not in ('nominal','moderate','severe','partitioned'):raise ValueError('Unknown network condition')
    for key in ('dt','lease_seconds','bid_window','decision_interval','inference_timeout','max_context_age','progress_timeout','beacon_interval_s','command_timeout_s','state_timeout_s'):
        if type(c[key]) not in (int,float) or not math.isfinite(c[key]) or c[key]<=0:raise ValueError('Invalid '+key)
    if type(c['ticks']) is not int or c['ticks']<1 or type(c['seed']) is not int or c['seed']<0:raise ValueError('Invalid ticks or seed')
    if type(c['inference_parallelism']) is not int or not 1<=c['inference_parallelism']<=4:raise ValueError('Invalid inference parallelism')
    if c['resilience']['enabled'] and c['dt']>c['resilience']['segment_duration_s']:raise ValueError('dt exceeds bounded segment horizon')
    if c['clock_mode'] not in ('auto','simulated','wall'):raise ValueError('Unknown clock mode')
    if c['policy']['provider'] not in ('replay','ollama'):raise ValueError('Choose replay fixture or pinned Ollama')
    if any(type(v) is not bool for v in c['ablations'].values()):raise ValueError('Ablations must be boolean')
    if c['architecture']!='D' and any(c['ablations'][k]!=DEFAULTS['ablations'][k] for k in ('persistent_memory','task_leases','dynamic_roles','fallback_policy')):
        raise ValueError('Agentic ablations apply to D; C already uses the same communication-health inputs')
    if not isinstance(c['network'],dict) or not isinstance(c['initial_assignments'],dict):raise ValueError('Network and initial assignments must be objects')
    return c


def effective_network(c,ids):
    values=asdict(preset(c['condition']))
    if c['condition']=='partitioned':
        # The same station is present in every experiment; group 2 cannot reach it during the outage.
        values['partitions'][0]['groups'][0].append(CONTROLLER)
    values.update(c['network'])
    if c['ablations']['perfect_communication']:
        values=asdict(NetworkConfig(latency_ms_mean=0,latency_ms_jitter=0))
    return NetworkConfig(**values)


def run_comparison(values,provider=None):
    c=configuration(values);m,guard_config,tasks,routes=load_mission(c['mission_config'],allowed_team_sizes=(2,4))
    ids=list(m['vehicles']);architecture=c['architecture'];horizon=c['ticks']*c['dt']
    if CONTROLLER in ids:raise ValueError('Reserved controller identity')
    fail=c['scenario']['fail_agent']
    if fail is not None and fail not in ids:raise ValueError('Unknown failure agent')
    if set(c['initial_assignments'])!=set(ids):raise ValueError('Provide initial assignments for the mission vehicle IDs')
    assigned=[tid for tids in c['initial_assignments'].values() for tid in tids]
    if any(not isinstance(v,list) or not v for v in c['initial_assignments'].values()) or len(assigned)!=len(set(assigned)) or set(assigned)!=set(routes):
        raise ValueError('Initial assignments must cover every task once without duplicates')
    out=Path(c['output_dir'])
    if out.exists() and any(out.iterdir()):raise ValueError('Use an empty output directory')
    out.mkdir(parents=True,exist_ok=True)
    use_policy=architecture in ('B','D') and not c['ablations']['fallback_policy']
    if not use_policy:provider=RulePolicy()
    elif provider is None:
        p=c['policy'];provider=ReplayProvider() if p['provider']=='replay' else OllamaProvider(p['model'],p['model_digest'],p['ollama_url'],c['inference_timeout'],c['seed'])
    try:
        identity=provider.verify()
        if isinstance(provider,OllamaProvider):identity['warmup']=provider.warmup()
    except Exception as exc:
        (out/'preflight_error.json').write_text(json.dumps(dict(stage='model_verification_or_warmup',error_type=type(exc).__name__,vehicle_control_started=False),indent=2)+'\n')
        raise
    actual_llm=identity['provider']=='ollama'
    if actual_llm and c['clock_mode']=='simulated':raise ValueError('Ollama requires wall/auto clock so latency counts toward mission time')
    wall=c['clock_mode']=='wall' or (c['clock_mode']=='auto' and actual_llm)
    clock=[0.];network_config=effective_network(c,ids)
    scenario=ExperimentSchedule(fail,c['scenario']['fail_at_s'])
    backend=MockFlight(m['vehicles'],lambda:clock[0])
    for aid,v in m['vehicles'].items():backend.states[aid].update(home=v['home'],ground_z=guard_config.ground_z)
    bus=DegradedMessageBus(ids+[CONTROLLER],lambda:clock[0],network_config,c['seed'],
        positions=lambda aid:tuple(m['guardian']['landing_site'][k] for k in ('x','y','ground_z')) if aid==CONTROLLER else backend.sample(aid)['position'])
    endpoints={aid:ObservedEndpoint(bus.endpoint(aid),aid,lambda:clock[0],mission_lifetime_s=horizon+1) for aid in ids+[CONTROLLER]}
    if c['resilience']['enabled']:
        endpoints={aid:RetryingEndpoint(ep,lambda:clock[0],c['resilience']) for aid,ep in endpoints.items()}
    guardian=ReachablePeerGuardian(guard_config,c['resilience'],c['dt']) if c['resilience']['enabled'] else RuntimeGuardian(guard_config);gate=GuardedExecutor(guardian,backend.execute,backend.cancel)
    settings=dict(persistent_memory=c['ablations']['persistent_memory'],dynamic_roles=c['ablations']['dynamic_roles'],task_leases=c['ablations']['task_leases'],
        beacon_interval_s=c['beacon_interval_s'],command_timeout_s=c['command_timeout_s'],state_timeout_s=c['state_timeout_s'],
        resilience=c['resilience'],horizon_s=horizon,lease_seconds=c['lease_seconds'],bid_window=c['bid_window'],minimum_battery_percent=guard_config.min_battery_reserve_percent)
    lease=c['lease_seconds']  # Ablation changes expiry, never heartbeat eligibility or packet TTL.
    initial_roles={a:v['role'] for a,v in m['vehicles'].items()};agents=[]
    for aid,v in m['vehicles'].items():
        cls=FixedTaskAgent if architecture in ('A','B') else ComparisonAgent
        extra=dict(initial_task_ids=c['initial_assignments'][aid] if architecture=='B' else (),horizon=horizon) if cls==FixedTaskAgent else {}
        agent=cls(aid,[p for p in ids if p!=aid],endpoints[aid],tasks,v['start_position'],role=v['role'],routes=routes,
            home=v['home'],relay_point=m['relay_point'],guardian=guardian,output_dir=out,provider=provider,mission=m['mission'],
            architecture=architecture,settings=settings,initial_roles=initial_roles,lease_s=lease,bid_window=c['bid_window'],weights=BID_WEIGHTS,
            decision_interval=c['decision_interval'],inference_timeout=c['inference_timeout'],max_context_age=c['max_context_age'],
            progress_timeout=c['progress_timeout'],deadline_bidding=architecture in ('C','D'),inference_capacity=c['inference_parallelism'],**extra)
        agents.append(agent)
    controller=FleetController(endpoints[CONTROLLER],tasks,ids,settings) if architecture=='A' else None
    shared=dict(mission=m,network=asdict(network_config),scenario=c['scenario'],seed=c['seed'],dt=c['dt'],ticks=c['ticks'],
        lease_seconds=c['lease_seconds'],bid_window=c['bid_window'],beacon_interval_s=c['beacon_interval_s'],
        command_timeout_s=c['command_timeout_s'],state_timeout_s=c['state_timeout_s'],backend=c['backend'],bid_weights=BID_WEIGHTS,
        decision_interval=c['decision_interval'],inference_timeout=c['inference_timeout'],max_context_age=c['max_context_age'],
        progress_timeout=c['progress_timeout'],inference_parallelism=c['inference_parallelism'],clock_mode=c['clock_mode'],
        resilience=c['resilience'],primary_policy_configuration=c['policy'],initial_assignments=c['initial_assignments'])
    sources=list(Path('agentic_uav/experiments').glob('*.py'))+list(Path('agentic_uav/policy').glob('*.py'))+[
        Path('agentic_uav/comm/degraded.py'),Path('agentic_uav/comm/protocol.py'),Path('agentic_uav/control/runtime_guardian.py'),
        Path('agentic_uav/control/scenario_manager.py'),Path('agentic_uav/coordination/contract_net.py'),Path('agentic_uav/coordination/flight_executor.py'),
        Path('agentic_uav/coordination/dynamic_roles.py'),Path('scripts/run_phase13_comparison.py')]
    expiry_disabled=architecture=='B' or not c['ablations']['task_leases']
    manifest=dict(effective_configuration=c,shared_inputs=shared,shared_inputs_sha256=hashlib.sha256(json.dumps(shared,sort_keys=True).encode()).hexdigest(),
        effective_clock='wall' if wall else 'simulated',effective_provider=identity,effective_task_lease_seconds=None if expiry_disabled else lease,
        task_lease_expiry_disabled=expiry_disabled,lease_deadline_when_disabled_s=horizon+1 if expiry_disabled else None,
        agent_class=type(agents[0]).__name__,skills='Phase12 WaypointExecutor + MockFlight',guardian=('ReachablePeerGuardian' if c['resilience']['enabled'] else 'Phase11 RuntimeGuardian')+' + GuardedExecutor',
        benchmark_version='resilience_v2' if c['resilience']['enabled'] else 'pilot_v1',
        uncertainty_assumptions='Every peer speed <= guardian maximum speed; reachable balls include observation age and segment horizon' if c['resilience']['enabled'] else 'legacy constant-velocity peer prediction',
        allocation_authority='FleetController delivered inbox' if controller else 'operator fixed initial assignments' if architecture=='B' else 'local delivered-message contract net',
        communication_health_inputs='ObservedEndpoint heartbeat/sequence/ack/RTT + local staged peer health',
        source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(sources)})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n')
    error=None;complete=False;trace=[];start=time.monotonic();last_now=0.
    try:
        for tick in range(c['ticks']):
            if wall:
                time.sleep(max(0,start+tick*c['dt']-time.monotonic()));clock[0]=time.monotonic()-start
            else:clock[0]=round(tick*c['dt'],8)
            now=clock[0]
            for aid,cid in backend.advance(now-last_now):
                gate.confirm_completion(aid,cid)
                agent=next(a for a in agents if a.agent_id==aid)
                state=backend.sample(aid);agent.position=list(state['position']);agent.state_time=now
                agent.observe_completion(cid,now)
            last_now=now
            for a in agents:
                state=backend.sample(a.agent_id);a.position=list(state['position']);a.velocity=tuple(state['velocity'])
                a.battery=state['battery'];a.phase=state['phase'];a.state_time=now
            if c['resilience']['enabled']:
                for aid,endpoint in endpoints.items():
                    if aid not in scenario.stopped:endpoint.tick()
            for a in agents:
                if a.agent_id not in scenario.stopped:a.receive(now)
            for aid in scenario.advance(now):
                cancelled=gate._cancel(aid)
                active=gate.active.get(aid)
                if cancelled and active:gate.confirm_completion(aid,active.command_id)
                scenario.events.append(dict(event='injection_cancel_ack',time_s=now,agent_id=aid,confirmed=cancelled))
                if cancelled:
                    a=next(a for a in agents if a.agent_id==aid)
                    gate.dispatch(Action('scenario_hold:'+aid,aid,'HOLD',now,now+3,(),1,1,'scenario'),a.safety_state(now),now)
            active_agents=[a for a in agents if a.agent_id not in scenario.stopped]
            for a in active_agents:
                gate.watchdog(a.safety_state(now),now);a.protocol_tick(now,c['dt'])
            if controller:
                controller.receive(now);controller.step(now)
                for mid in controller.decisions:bus.record_decision(CONTROLLER,mid)
                controller.decisions.clear()
            for a in active_agents:
                a.execution_tick(now,gate);a.poll(now,gate)
                if a.identity_fault:raise RuntimeError('Pinned model identity changed')
                for mid in a.decisions:bus.record_decision(a.agent_id,mid)
                a.decisions.clear()
            admit_requests(active_agents,now,c['inference_parallelism'] if actual_llm else 4)
            for a in agents:
                trace.append(dict(time_s=now,agent_id=a.agent_id,position=list(a.position),velocity=list(a.velocity),
                    active=a.agent_id not in scenario.stopped,role=a.role,communication_estimate=endpoints[a.agent_id].estimates(),
                    owned_tasks=[dict(task_id=t.task_id,version=t.version,lease_expires_at=t.lease_expires_at)
                                 for t in a.tasks.values() if t.status.value=='assigned' and t.assigned_agent==a.agent_id],
                    execution_task_id=a.executor.key[0] if a.executor.key else None,
                    active_command_kind=gate.active[a.agent_id].kind if a.agent_id in gate.active else None,
                    peer_health={p:h.state.value for p,h in a.peer_health.items()}))
            completed={e['task_id'] for a in agents for e in a.events if e['event']=='work_completed'}
            if set(routes)<=completed:complete=True;break
    except Exception as exc:error=dict(type=type(exc).__name__,message=str(exc)[:240])
    finally:
        for a in agents:
            if a.pending:a.record('inference_abandoned_at_shutdown',clock[0],request_id=a.pending['token'])
            a.pending=None;a.save_memory()
        # Kinematic benchmark only: stop ongoing simulated jobs without claiming a physical landing.
        for aid in list(backend.active):
            if gate._cancel(aid):
                action=gate.active.get(aid)
                if action:gate.confirm_completion(aid,action.command_id)
    completion_events=[e for a in agents for e in a.events if e['event']=='work_completed']
    duplicates=len(completion_events)-len({e['task_id'] for e in completion_events})
    guarded={e['selected_action']['command_id'] for e in gate.audit if e.get('selected_action') and e.get('mission_effect',{}).get('executed')}
    coverage=all(e['command_id'] in guarded for e in backend.effects)
    evidence=policy_evidence(agents,identity['provider'],coverage,error,complete,duplicates,'mock')
    # Independent LLM execution must not be labelled evidence of coordinated allocation.
    evidence['llm_supported_execution_success']=evidence.pop('cooperative_mission_success')
    summary=dict(mode='phase13_shared_architecture_comparison',architecture=architecture,backend='mock',seed=c['seed'],condition=c['condition'],
        provider=identity['provider'],llm_inference=actual_llm,mission_complete=complete,time_s=clock[0],error=error,
        mission_execution_success=complete and duplicates==0 and coverage and error is None,decentralized_coordination_enabled=architecture in ('C','D'),
        completed_task_ids=sorted({e['task_id'] for e in completion_events}),duplicate_task_completions=duplicates,
        completions_by_agent={a.agent_id:sum(e['agent_id']==a.agent_id for e in completion_events) for a in agents},
        decisions_by_agent={a.agent_id:a.model_decisions for a in agents},fallbacks_by_agent={a.agent_id:a.fallback_count for a in agents},
        final_roles={a.agent_id:a.role for a in agents if a.agent_id not in scenario.stopped},
        role_changes=sum(e['event']=='role_changed' for a in agents for e in a.events_policy),
        lease_expirations=sum(e['event']=='lease_expired' for a in agents for e in a.events)+(sum(e['event']=='central_lease_expired' for e in controller.events) if controller else 0),
        all_dispatched_actions_guarded=coverage,guardian_outcomes=dict(Counter(e['outcome'] for e in gate.audit)),
        network_outcomes=dict(Counter(e['status'] for e in bus.logs())),network_drop_reasons=dict(Counter(e['drop_reason'] for e in bus.logs() if e.get('drop_reason'))),
        architecture_selected_from_configuration=True,ablations=c['ablations'],shared_inputs_sha256=manifest['shared_inputs_sha256'],**evidence,
        limitations=['Kinematic mock flight and application-level network; no live AirSim comparison or calibrated RF evidence',
            'C and D retain fail-closed guardian checks on stale peer state; reassignment does not guarantee executable recovery under a partition',
            'B initial assignments are reliable pre-mission briefing; B never negotiates or reassigns them',
            'Deadline bids and rule-policy replacement are deterministic support, not LLM coordination evidence',
            'Nominal replay fixtures verify architecture wiring; actual pinned-model and repeated matched trials remain necessary',
            'Physical route completion is the common stop criterion; undelivered completion reports and pending packets at stop are censored',
            'Persistent-memory ablation removes episodic prompt memory, not required identity, local beliefs, inboxes or audit history',
            'Relay changes are role/position rules; no RF reachability benefit is claimed'])
    outputs=dict(summary=summary,scenario_events=scenario.events,guardian_audit=gate.audit,messages=bus.logs(),
        executed_actions=backend.effects,flight_trace=trace,protocol_events=[e for a in agents for e in a.events],
        waypoint_arrivals=[e for a in agents for e in a.executor.arrivals],controller_events=controller.events if controller else [],
        retry_events=[dict(agent_id=aid,**event) for aid,endpoint in endpoints.items() for event in getattr(endpoint,'events',[])])
    for name,data in outputs.items():(out/(name+'.json')).write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    return summary
