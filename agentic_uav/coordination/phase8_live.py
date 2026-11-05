"""Four live AirSim executors under local, deterministic contract-net allocation."""
import json
import math
import time
from pathlib import Path
from agentic_uav.comm.protocol import PerfectMessageBus
from agentic_uav.coordination.contract_net import AllocationAgent,MissionTask,Geometry,TaskType,TaskStatus
from agentic_uav.coordination.flight_executor import WaypointExecutor, within_waypoint
from agentic_uav.coordination.mission_view import scale_routes, draw_overview, save_route_map


def load_mission(path,route_scale=1.):
    config=scale_routes(json.loads(Path(path).read_text()),route_scale)
    ids=list(config['vehicles'])
    if len(ids)!=4:raise ValueError('Mission requires four vehicles')
    offsets={a:config['vehicles'][a]['frame_offset_m'] for a in ids}
    routes={}
    def vector(v):return isinstance(v,list) and len(v)==3 and all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in v)
    if not all(vector(v) for v in offsets.values()):raise ValueError('Invalid frame offsets')
    tasks=[]
    for item in config['tasks']:
        route=item['waypoints']
        if not route or not all(vector(p) for p in route) or item['task_id'] in routes:
            raise ValueError('Invalid or duplicate task route')
        routes[item['task_id']]=route
        center=tuple(sum(p[i] for p in route)/len(route) for i in range(3))
        tasks.append(MissionTask(item['task_id'],TaskType.SEARCH_SECTOR,Geometry(center),item.get('priority',1),{'search'},work_units=len(route)))
    if not tasks:raise ValueError('Mission needs tasks')
    return config,ids,offsets,routes,tasks


def run_live(args):
    import airsim
    config,ids,offsets,routes,tasks=load_mission(args.mission_config,getattr(args,"route_scale",1.))
    if args.fail_agent is not None and args.fail_agent not in ids:raise ValueError('Failed agent not in mission')
    client=airsim.MultirotorClient(ip=args.airsim_host,timeout_value=args.rpc_timeout)
    client.confirmConnection()
    missing=set(ids)-set(client.listVehicles())
    if missing:raise ValueError(f'Missing vehicles: {sorted(missing)}')
    stamp=[None]
    bus=PerfectMessageBus(ids,lambda:0. if stamp[0] is None else time.monotonic()-stamp[0])
    agents=[];executors={};controlled=[];trace=[];commands=[];failure=None;complete=False
    cleanup_errors=[];world=previous=None;failed=set();ticks_run=0
    spectator_previous=None;camera_location=None
    last_commands={};targets={}
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    def position(a):
        state=client.getMultirotorState(vehicle_name=a)
        p=state.kinematics_estimated.position
        return state,[v+o for v,o in zip((p.x_val,p.y_val,p.z_val),offsets[a])]
    for task_id,route in routes.items():
        print(f'[Phase8] {task_id}: shared NED targets (meters)',flush=True)
        for index,point in enumerate(route,1):
            print(f'  WP{index}: X={point[0]:.1f}, Y={point[1]:.1f}, Z={point[2]:.1f}',flush=True)
    (out/'effective_mission.json').write_text(json.dumps(config,indent=2)+'\n')
    try:
        if args.carla_host:
            import carla
            cc=carla.Client(args.carla_host,args.carla_port);cc.set_timeout(args.rpc_timeout)
            world=cc.get_world();previous=world.get_settings()
            settings=world.get_settings();settings.synchronous_mode=False;world.apply_settings(settings)
        for a in ids:
            state,p=position(a)
            if state.landed_state!=airsim.LandedState.Landed:
                raise ValueError(f'{a} must initially be landed')
            targets[a]=[p[0],p[1],p[2]-args.flight_height]
            client.enableApiControl(True,vehicle_name=a);controlled.append(a)
            client.armDisarm(True,vehicle_name=a)
        try:
            save_route_map(routes,targets,out/'mission_routes.png')
        except Exception as exc:
            print(f'[Phase8] Route-map warning: {exc}',flush=True)
        if getattr(args,'overview_camera',False):
            spectator_previous=world.get_spectator().get_transform()
            camera_location=draw_overview(world,carla,routes,targets,args.carla_frame_origin,
                args.camera_height,args.ticks*args.dt+args.setup_timeout+60)
            print(f'[Phase8] Overhead CARLA spectator at {camera_location}; routes and all four starts framed.',flush=True)
        futures=[client.takeoffAsync(timeout_sec=args.setup_timeout,vehicle_name=a) for a in ids]
        for f in futures:f.join()
        for a in ids:
            local=[v-o for v,o in zip(targets[a],offsets[a])]
            client.moveToPositionAsync(*local,velocity=args.speed,timeout_sec=args.setup_timeout,vehicle_name=a)
        deadline=time.monotonic()+args.setup_timeout;ready_since=None
        while time.monotonic()<deadline:
            ready=True
            for a in ids:
                state,p=position(a)
                v=state.kinematics_estimated.linear_velocity
                ready &= (state.landed_state!=airsim.LandedState.Landed and within_waypoint(p,targets[a],args.arrival_tolerance,getattr(args,"altitude_tolerance",.6)) and math.sqrt(v.x_val**2+v.y_val**2+v.z_val**2)<.3)
            ready_since=(time.monotonic() if ready_since is None else ready_since) if ready else None
            if ready_since is not None and time.monotonic()-ready_since>=1:break
            time.sleep(args.dt)
        else:raise TimeoutError('Four vehicles did not settle; inspect starting references/telemetry')
        for a in ids:
            _,p=position(a)
            agents.append(AllocationAgent(a,[peer for peer in ids if peer!=a],bus.endpoint(a),tasks,p,
                lease_s=args.lease_seconds,bid_window=args.bid_window,inject_conflict=not args.no_conflict_injection))
            executors[a]=WaypointExecutor(routes,args.arrival_tolerance,
                z_tolerance=getattr(args,'altitude_tolerance',.6),
                stall_timeout=getattr(args,'stall_timeout',4.),max_retries=getattr(args,'max_waypoint_retries',2))
        stamp[0]=time.monotonic()
        for tick in range(args.ticks):
            time.sleep(max(0,stamp[0]+tick*args.dt-time.monotonic()))
            now=time.monotonic()-stamp[0];ticks_run=tick+1
            if args.fail_agent and now>=args.fail_at and args.fail_agent not in failed:
                # Infrastructure neutralizes the vehicle; peers learn only through missing messages.
                client.hoverAsync(vehicle_name=args.fail_agent);failed.add(args.fail_agent)
                commands.append(dict(time_s=now,agent_id=args.fail_agent,action='injected_failure_hold'))
            active=[a for a in agents if a.agent_id not in failed]
            for a in active:
                state,p=position(a.agent_id);a.position=p
                if state.landed_state==airsim.LandedState.Landed:
                    raise RuntimeError(f'{a.agent_id} unexpectedly landed during sector execution')
                a.receive(now)
            for a in active:
                a.step(now,args.dt,process_inbox=False,execute_mock=False)
                action=executors[a.agent_id].update(a,now)
                command_key=(action['action'],action.get('task_id'),action.get('version'),action.get('index'),action.get('retry',0))
                if command_key!=last_commands.get(a.agent_id):
                    # Stop the previous command before dispatch on task/version changes.
                    if action['action']=='hold' or last_commands.get(a.agent_id,(None,None,None))[1:3]!=(action.get('task_id'),action.get('version')):
                        client.hoverAsync(vehicle_name=a.agent_id)
                    if action['action']=='move':
                        local=[v-o for v,o in zip(action['target'],offsets[a.agent_id])]
                        client.moveToPositionAsync(*local,velocity=args.speed,timeout_sec=args.waypoint_timeout,vehicle_name=a.agent_id)
                    last_commands[a.agent_id]=command_key
                    commands.append(dict(time_s=now,agent_id=a.agent_id,**action))
                    print(f'[Phase8] {now:.1f}s {a.agent_id}: {action}',flush=True)
                for mid in a.decisions:bus.record_decision(a.agent_id,mid)
                a.decisions.clear()
                trace.append(dict(time_s=now,agent_id=a.agent_id,position=a.position[:],
                    execution=action,verified_checkpoints=dict(a.checkpoints),tasks=[t.to_dict() for t in a.tasks.values()]))
            if active and all(all(t.status==TaskStatus.COMPLETE for t in a.tasks.values()) for a in active):
                complete=True;break
    except Exception as exc:
        failure=repr(exc);raise
    finally:
        for a in controlled:
            try:
                client.landAsync(timeout_sec=args.setup_timeout,vehicle_name=a).join()
                deadline=time.monotonic()+args.landing_confirm_timeout
                while time.monotonic()<deadline:
                    if client.getMultirotorState(vehicle_name=a).landed_state==airsim.LandedState.Landed:
                        client.armDisarm(False,vehicle_name=a);client.enableApiControl(False,vehicle_name=a);break
                    time.sleep(.2)
                else:
                    client.hoverAsync(vehicle_name=a);cleanup_errors.append(f'{a}: landing not confirmed; API retained')
            except Exception as exc:cleanup_errors.append(f'{a}: {exc!r}')
        if world is not None and previous is not None:
            if spectator_previous is not None:
                try:world.get_spectator().set_transform(spectator_previous)
                except Exception as exc:cleanup_errors.append(f'Spectator restore: {exc!r}')
            try:world.apply_settings(previous)
            except Exception as exc:cleanup_errors.append(f'CARLA restore: {exc!r}')
        events=sorted([e for a in agents for e in a.events],key=lambda e:(e['time_s'],e['agent_id']))
        finishes=[e for e in events if e['event']=='work_completed']
        summary=dict(mode='phase8_decentralized_contract_net_airsim',llm=False,mission_complete=complete,error=failure,
            ticks=ticks_run,time_s=max((r['time_s'] for r in trace),default=0.),completed_task_ids=sorted({e['task_id'] for e in finishes}),
            completions_by_agent={a:sum(e['agent_id']==a for e in finishes) for a in ids},
            duplicate_task_completions=len(finishes)-len({e['task_id'] for e in finishes}),
            conflict_corrections=sum(e['event']=='claim_corrected' for e in events),
            lease_expirations=len({(e['task_id'],e['version']) for e in events if e['event']=='lease_expired'}),
            waypoint_command_retries=sum(e['event']=='waypoint_command_retry' for e in events),
            xy_arrival_tolerance_m=args.arrival_tolerance,z_arrival_tolerance_m=getattr(args,'altitude_tolerance',.6),
            failed_agents=sorted(failed),cleanup_errors=cleanup_errors,mission_config=config,
            route_scale=getattr(args,'route_scale',1.),overview_camera_location=camera_location,
            verified_checkpoints={a.agent_id:dict(a.checkpoints) for a in agents},
            stall_timeout_s=getattr(args,'stall_timeout',4.),max_waypoint_retries=getattr(args,'max_waypoint_retries',2),
            limitations=['Observed ordered waypoint visits, not sensor-confirmed search coverage',
                'No collision avoidance; scene and frame-offset calibration required',
                'Silent-agent injection commands physical hover; peers infer failure only from missing messages',
                'No network partition/rejoin fencing; perfect communication among surviving agents'])
        payloads=dict(summary=summary,events=events,beliefs=trace,messages=bus.logs(),commands=commands,
                      waypoint_arrivals=[row for e in executors.values() for row in e.arrivals])
        for name,data in payloads.items():(out/(name+'.json')).write_text(json.dumps(data,indent=2)+'\n')
        print(json.dumps(summary,indent=2))
    return summary
