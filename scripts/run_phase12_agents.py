"""Four persistent high-level policies sharing one pinned Ollama server, or replay fixtures."""
import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agentic_uav.comm.protocol import PerfectMessageBus, MessageType
from agentic_uav.coordination.contract_net import MissionTask, TaskType, TaskStatus, Geometry
from agentic_uav.control.runtime_guardian import RuntimeGuardian, Config, GuardedExecutor, Action, Outcome
from agentic_uav.policy.structured import OllamaProvider, ReplayProvider, decision_schema
from agentic_uav.policy.persistent import PersistentAgent
from agentic_uav.policy.backends import MockFlight, AirSimFlight
from agentic_uav.policy.evidence import admit_requests, policy_evidence


def load_mission(path):
    m=json.loads(Path(path).read_text());config=Config(**m['guardian'])
    def vector(v):return isinstance(v,list) and len(v)==3 and all(type(x) in (int,float) and math.isfinite(x) for x in v)
    if not isinstance(m['mission'],str) or not 0<len(m['mission'])<=4000:raise ValueError('Mission text required')
    if not isinstance(m['vehicles'],dict) or len(m['vehicles'])!=4:raise ValueError('Exactly four identified vehicles required')
    for a,v in m['vehicles'].items():
        if not re.fullmatch('[A-Za-z0-9_-]{1,64}',a) or v['role'] not in ('SCOUT','RELAY','RESERVE') or not all(vector(v[k]) for k in ['start_position','home','frame_offset_m']):raise ValueError('Invalid vehicle configuration')
    if not vector(m['relay_point']):raise ValueError('Invalid relay point')
    tasks=[];routes={}
    if not 1<=len(m['tasks'])<=32:raise ValueError('Require 1–32 tasks for bounded context')
    for item in m['tasks']:
        tid=item['task_id'];route=item['waypoints']
        if not isinstance(tid,str) or not tid or tid in routes or not route or not all(vector(p) for p in route):raise ValueError('Invalid task route')
        routes[tid]=route
        center=tuple(sum(p[i] for p in route)/len(route) for i in range(3))
        tasks.append(MissionTask(tid,TaskType.SEARCH_SECTOR,Geometry(center),item.get('priority',1),{'search'},work_units=len(route)))
    return m,config,tasks,routes


def run(args,provider=None):
    m,config,tasks,routes=load_mission(args.mission_config)
    out=Path(args.output_dir)
    if out.exists() and any(out.iterdir()):raise ValueError('Use an empty output directory')
    out.mkdir(parents=True,exist_ok=True)
    provider=provider or (ReplayProvider() if args.provider=='replay' else OllamaProvider(args.model,args.model_digest,args.ollama_url,args.inference_timeout,args.seed))
    identity=provider.verify()  # Fail before vehicle control if the model is not pinned.
    if isinstance(provider,OllamaProvider) and not args.no_model_warmup:
        try:identity['warmup']=provider.warmup()
        except Exception as exc:
            failure=dict(stage='model_warmup',error_type=type(exc).__name__,vehicle_control_started=False)
            (out/'preflight_error.json').write_text(json.dumps(failure,indent=2)+'\n')
            (out/'model_manifest.json').write_text(json.dumps(identity,indent=2)+'\n')
            raise
    else:identity['warmup']=dict(performed=False)
    (out/'decision_schema.json').write_text(json.dumps(decision_schema(),indent=2)+'\n')
    (out/'model_manifest.json').write_text(json.dumps(identity,indent=2)+'\n')
    (out/'effective_mission.json').write_text(json.dumps(m,indent=2)+'\n')
    root=Path(__file__).resolve().parents[1]
    sources=list((root/'agentic_uav'/'policy').glob('*.py'))+[Path(__file__).resolve(),root/'agentic_uav/control/runtime_guardian.py',root/'agentic_uav/comm/protocol.py',root/'agentic_uav/coordination/contract_net.py',root/'agentic_uav/coordination/flight_executor.py']
    hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(sources)}
    (out/'run_manifest.json').write_text(json.dumps(dict(backend=args.backend,provider=identity['provider'],seed=args.seed,
        ticks=args.ticks,dt=args.dt,decision_interval=args.decision_interval,inference_timeout=args.inference_timeout,
        lease_seconds=args.lease_seconds,bid_window=args.bid_window,max_context_age=args.max_context_age,
        progress_timeout=args.progress_timeout,max_hold_seconds=args.max_hold_seconds,
        deadline_bidding=args.provider=='ollama',bid_response_margin=args.bid_response_margin,safety_rejection_limit=args.safety_rejection_limit,
        inference_parallelism=args.inference_parallelism if args.provider=='ollama' else 4,model_warmup=identity['warmup']['performed'],python=platform.python_version(),source_hashes=hashes),indent=2)+'\n')
    clock=[0.];bus=PerfectMessageBus(list(m['vehicles']),lambda:clock[0]);guardian=RuntimeGuardian(config)
    backend=(MockFlight(m['vehicles'],lambda:clock[0]) if args.backend=='mock' else
             AirSimFlight(m['vehicles'],lambda:clock[0],args.airsim_host,args.rpc_timeout,config.ground_z))
    if args.backend=='mock':
        for a,s in backend.states.items():s['home']=m['vehicles'][a]['home'];s['ground_z']=config.ground_z
    gate=GuardedExecutor(guardian,backend.execute,backend.cancel);agents=[]
    for a,v in m['vehicles'].items():
        agents.append(PersistentAgent(a,[p for p in m['vehicles'] if p!=a],bus.endpoint(a),tasks,v['start_position'],
            role=v['role'],routes=routes,home=v['home'],relay_point=m['relay_point'],guardian=guardian,
            output_dir=out,provider=provider,mission=m['mission'],lease_s=args.lease_seconds,bid_window=args.bid_window,
            decision_interval=args.decision_interval,inference_timeout=args.inference_timeout,max_context_age=args.max_context_age,progress_timeout=args.progress_timeout,max_hold_seconds=args.max_hold_seconds,
            inference_capacity=args.inference_parallelism,bid_response_margin=args.bid_response_margin,safety_rejection_limit=args.safety_rejection_limit))
    traces=[];error=None;complete=False;world=previous=None;cleanup=[];start=time.monotonic();last_now=0.
    realtime=args.provider=='ollama' or args.backend=='airsim'
    def refresh():
        for a in agents:
            measurement_started=time.monotonic()-start if realtime else clock[0]
            s=backend.sample(a.agent_id)
            if realtime:clock[0]=time.monotonic()-start
            a.position=list(s['position']);a.velocity=tuple(s['velocity']);a.battery=s['battery'];a.phase=s['phase'];a.state_time=measurement_started
            if gate.active.get(a.agent_id) and gate.active[a.agent_id].kind=='TAKEOFF':a.phase='TAKEOFF'
        # Broadcast own telemetry; agents never inspect infrastructure's other states.
        for a in agents:a.send(MessageType.STATUS_UPDATE,
            dict(position=a.position,velocity=list(a.velocity),battery=a.battery,role=a.role,observed_at=a.state_time),clock[0])
        for a in agents:a.receive(clock[0])
    try:
        if args.backend=='airsim' and args.carla_host:
            import carla
            client=carla.Client(args.carla_host,args.carla_port);client.set_timeout(args.rpc_timeout)
            world=client.get_world();previous=world.get_settings();settings=world.get_settings();settings.synchronous_mode=False;world.apply_settings(settings)
        refresh()
        if args.backend=='airsim':
            if any(a.phase!='GROUNDED' for a in agents):raise ValueError('All four vehicles must initially be landed')
            if config.max_height_m<5:raise ValueError('Live takeoff requires at least 5 m configured overhead allowance')
            for a in agents:
                target=(a.position[0],a.position[1],config.ground_z-args.flight_height)
                decision=gate.dispatch(Action(f'takeoff:{a.agent_id}',a.agent_id,'TAKEOFF',clock[0],clock[0]+30,(target,),1),a.safety_state(clock[0]),clock[0])
                if decision.outcome not in (Outcome.APPROVE,Outcome.APPROVE_WITH_MODIFICATION):raise RuntimeError('Takeoff rejected: '+','.join(decision.reasons))
            while time.monotonic()-start<args.setup_timeout:
                clock[0]=time.monotonic()-start
                for a,cid in backend.advance(args.dt):gate.confirm_completion(a,cid)
                refresh()
                for a in agents:gate.watchdog(a.safety_state(clock[0]),clock[0])
                if all(a.phase=='AIRBORNE' and abs(config.ground_z-a.position[2]-args.flight_height)<=.6 for a in agents):break
                time.sleep(args.dt)
            else:raise TimeoutError('Guarded setup did not reach desired airborne states')
        ready=clock[0];start_tick=time.monotonic();last_now=clock[0]
        for tick in range(args.ticks):
            if realtime:
                time.sleep(max(0,start_tick+tick*args.dt-time.monotonic()));clock[0]=ready+time.monotonic()-start_tick
            else:clock[0]=round(ready+tick*args.dt,8)
            delta=max(0,clock[0]-last_now);last_now=clock[0]
            completed_commands=backend.advance(delta)
            for aid,cid in completed_commands:gate.confirm_completion(aid,cid)
            refresh()
            for aid,cid in completed_commands:
                next(a for a in agents if a.agent_id==aid).observe_completion(cid,clock[0])
            for a in agents:
                gate.watchdog(a.safety_state(clock[0]),clock[0])
                a.protocol_tick(clock[0],args.dt)
                a.execution_tick(clock[0],gate)
                a.poll(clock[0],gate)
                if a.identity_fault:raise RuntimeError('Pinned model identity changed; formal run aborted')
                traces.append(dict(time_s=clock[0],agent_id=a.agent_id,position=a.position,role=a.role,
                    flight_phase=a.phase,authorized_task=a.authorized,current_task=next((t.task_id for t in a.tasks.values() if t.assigned_agent==a.agent_id and t.status==TaskStatus.ASSIGNED),None)))
                for mid in a.decisions:bus.record_decision(a.agent_id,mid)
                a.decisions.clear()
            admit_requests(agents,clock[0],args.inference_parallelism if args.provider=='ollama' else len(agents))
            if all(all(t.status==TaskStatus.COMPLETE for t in a.tasks.values()) for a in agents):complete=True;break
    except Exception as exc:
        error=dict(type=type(exc).__name__,message=str(exc)[:200])
    finally:
        # Suppress every pending decision before cleanup. Late workers cannot actuate.
        for a in agents:
            remaining=a.worker.poll() if a.worker else a.pending.get('inline_result') if a.pending else None
            if remaining is not None:
                a._save('responses',dict(simulation_time_s=clock[0],discarded_at_shutdown=True,**remaining))
                a.record('shutdown_response_discarded',clock[0],request_id=remaining['token'])
            elif a.pending:a.record('inference_abandoned_at_shutdown',clock[0],request_id=a.pending['token'])
            a.pending=None
        if args.backend=='airsim':
            try:refresh()
            except Exception as exc:cleanup.append(type(exc).__name__)
            for a in agents:
                active=gate.active.get(a.agent_id)
                if active and gate._cancel(a.agent_id):gate.confirm_completion(a.agent_id,active.command_id)
                if a.agent_id in gate.active:cleanup.append(a.agent_id+': cancellation unconfirmed; API retained');continue
                decision=gate.dispatch(Action(f'cleanup:{a.agent_id}',a.agent_id,'HOLD',clock[0],clock[0]+3,(),1,1,'rule_policy'),a.safety_state(clock[0]),clock[0])
                if decision.selected_action is None:cleanup.append(a.agent_id+': hold not verified; API retained')
            cleanup.append('Unlanded vehicles remain under API control; operator must manage them after the experiment')
        if world is not None:
            try:world.apply_settings(previous)
            except Exception as exc:cleanup.append('CARLA restore: '+type(exc).__name__)
        for a in agents:a.save_memory()
        completions=[e for a in agents for e in a.events if e['event']=='work_completed']
        guarded_ids={e['selected_action']['command_id'] for e in gate.audit if e['selected_action'] is not None}
        all_guarded=all(e['command_id'] in guarded_ids for e in backend.effects)
        evidence=policy_evidence(agents,identity['provider'],all_guarded,error,complete,len(completions)-len({e['task_id'] for e in completions}),args.backend)
        summary=dict(mode='phase12_persistent_high_level_agents',backend=args.backend,provider=identity['provider'],
            llm_inference=identity['provider']=='ollama',mission_complete=complete,error=error,time_s=clock[0],
            completed_task_ids=sorted({e['task_id'] for e in completions}),duplicate_task_completions=len(completions)-len({e['task_id'] for e in completions}),
            decisions_by_agent={a.agent_id:a.model_decisions for a in agents},fallbacks_by_agent={a.agent_id:a.fallback_count for a in agents},
            persistent_contexts=len(agents),all_dispatched_actions_guarded=all_guarded,
            **evidence,
            guardian_decisions=len(gate.audit),cleanup_warnings=cleanup,
            limitations=['Replay fixtures do not establish LLM inference; live adapter requires scene-specific validation',
                'Deadline-protected bids and safety-triggered releases are deterministic support, not LLM decision evidence',
                'Static geometry, constant-velocity peer predictions and abstract battery budgets inherit Phase 11 limits',
                'SimpleFlight may lack battery telemetry; any configured battery assumption is explicit in the mission manifest',
                'Phase 10 degraded-communication recovery weaknesses are not fixed by adding an LLM',
                'One shared local server may serialize requests; timeouts and late responses are explicitly logged',
                'Live setup/cleanup remain client-side; no onboard safety guarantee or automatic unchecked landing'])
        outputs=dict(summary=summary,guardian_audit=gate.audit,flight_trace=traces,executed_actions=backend.effects,
            messages=bus.logs(),protocol_events=[e for a in agents for e in a.events],
            waypoint_arrivals=[e for a in agents for e in a.executor.arrivals])
        for name,data in outputs.items():(out/(name+'.json')).write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    print(json.dumps(summary,indent=2));return summary


def parse_args(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backend',choices=['mock','airsim'],default='mock')
    p.add_argument('--provider',choices=['replay','ollama'],default='replay')
    p.add_argument('--mission-config',default='configs/phase12/mission.example.json')
    p.add_argument('--model');p.add_argument('--model-digest');p.add_argument('--ollama-url',default='http://localhost:11434')
    p.add_argument('--ticks',type=int,default=400);p.add_argument('--dt',type=float,default=.2);p.add_argument('--seed',type=int,default=42)
    p.add_argument('--inference-parallelism',type=int,choices=range(1,5),default=1)
    p.add_argument('--no-model-warmup',action='store_true')
    p.add_argument('--progress-timeout',type=float,default=None)
    p.add_argument('--max-hold-seconds',type=float,default=2.)
    p.add_argument('--bid-response-margin',type=float,default=1.)
    p.add_argument('--safety-rejection-limit',type=int,default=2)
    p.add_argument('--decision-interval',type=float,default=1.);p.add_argument('--inference-timeout',type=float,default=15.)
    p.add_argument('--max-context-age',type=float,default=20.);p.add_argument('--lease-seconds',type=float,default=45.)
    p.add_argument('--bid-window',type=float,default=2.);p.add_argument('--flight-height',type=float,default=3.)
    p.add_argument('--setup-timeout',type=float,default=60.);p.add_argument('--rpc-timeout',type=float,default=2.)
    p.add_argument('--airsim-host',default='127.0.0.1');p.add_argument('--carla-host');p.add_argument('--carla-port',type=int,default=2000)
    p.add_argument('--output-dir',default='results/phase12/replay')
    a=p.parse_args(argv)
    if a.progress_timeout is None:a.progress_timeout=max(30.,2*a.inference_timeout)
    for value in [a.bid_response_margin,a.progress_timeout,a.max_hold_seconds,a.dt,a.decision_interval,a.inference_timeout,a.max_context_age,a.lease_seconds,a.bid_window,a.flight_height,a.setup_timeout,a.rpc_timeout]:
        if not math.isfinite(value) or value<=0:p.error('Timing and height values must be positive and finite')
    if a.ticks<1:p.error('Ticks must be positive')
    if a.safety_rejection_limit<2:p.error('Safety rejection limit must be at least two')
    if a.provider=='ollama' and (not a.model or not a.model_digest):p.error('Ollama requires --model and --model-digest')
    return a

if __name__=='__main__':
    result=run(parse_args())
    if result['error']:raise SystemExit(1)
