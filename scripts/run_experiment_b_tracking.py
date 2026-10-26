"""Experiment B: live CARLA pedestrian / AirSim drone tracking telemetry.

Requires both simulators. Run one scenario at a time, in a clear test area.
"""
import argparse,csv,json,math,statistics,time,hashlib
from pathlib import Path

SCRIPT_VERSION="experiment-b-height-minus25-v4"

def percentile(values,p):
    v=sorted(values)
    if not v:return None
    i=(len(v)-1)*p/100
    a=math.floor(i);b=math.ceil(i)
    return v[a]+(v[b]-v[a])*(i-a)

def summarize(rows,completed,scenario,speed,guarded,follow_distance=1.0):
    errors=[r["target_error_m"] for r in rows]
    sep=[r["ped_drone_xy_separation_m"] for r in rows]
    return {"scenario":scenario,"pedestrian_speed_mps":speed,"oba_enabled":guarded,
            "samples":len(rows),"completed":completed,"follow_distance_m":follow_distance,
            "tracking_target_rmse_m":math.sqrt(sum(e*e for e in errors)/len(errors)) if errors else None,
            "tracking_target_p95_m":percentile(errors,95),
            "rms_ped_drone_xy_separation_m":math.sqrt(sum(d*d for d in sep)/len(sep)) if sep else None,
            "min_ped_drone_xy_separation_m":min(sep) if sep else None,
            "altitude_violation_samples":sum(r["altitude_violation"] for r in rows),
            "oba_interventions":sum(r["oba_intervention"] for r in rows),
            "mean_guardian_latency_us":statistics.mean(r["guardian_latency_us"] for r in rows) if rows else None,
            "notes":["Target error compares AirSim actual XY to desired offset-follow position, not pedestrian XY",
                     "Pedestrian XY is aligned using initial CARLA and AirSim positions; frames must share axes",
                     "No obstacle clearance or tracking lag inferred from these samples",
                     "CARLA ticks are simulation time; AirSim timing may not be synchronized"]}


def plot_metrics(rows,summary,output):
    """Save diagnostic plots without requiring a graphical display."""
    if not rows:
        return
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    t=[r["carla_sim_time_s"] for r in rows]
    fig,axes=plt.subplots(2,2,figsize=(13,9),constrained_layout=True)
    ax=axes[0,0]
    for prefix,label in (("ped","Pedestrian (mapped)"),("target","Desired follow position"),("drone","Actual drone")):
        ax.plot([r[prefix+"_x"] for r in rows],[r[prefix+"_y"] for r in rows],label=label)
    ax.set(xlabel="X (m)",ylabel="Y (m)",title="XY trajectories")
    ax.set_aspect("equal",adjustable="datalim")
    ax=axes[0,1]
    ax.plot(t,[r["target_error_m"] for r in rows],label="Tracking error")
    ax.axhline(summary["tracking_target_rmse_m"],color="tab:red",linestyle="--",label=f'RMSE {summary["tracking_target_rmse_m"]:.2f} m')
    ax.axhline(summary["tracking_target_p95_m"],color="tab:orange",linestyle=":",label=f'P95 {summary["tracking_target_p95_m"]:.2f} m')
    ax.axhline(summary["acceptance_rmse_m"],color="gray",linestyle="-.",label="RMSE acceptance limit")
    ax.set(ylabel="XY error (m)",title="Distance from desired follow position")
    ax=axes[1,0]
    ax.plot(t,[r["ped_drone_xy_separation_m"] for r in rows],label="Actual XY separation")
    ax.axhline(summary["follow_distance_m"],color="tab:green",linestyle="--",label="Requested follow distance")
    ax.axhline(summary["rms_ped_drone_xy_separation_m"],color="tab:red",linestyle=":",label=f'RMS {summary["rms_ped_drone_xy_separation_m"]:.2f} m')
    ax.set(ylabel="XY separation (m)",title="Drone–pedestrian horizontal separation")
    ax=axes[1,1]
    ax.plot(t,[-r["drone_z"] for r in rows],label="Actual drone height (AirSim origin)")
    ax.plot(t,[-r["command_z"] for r in rows],linestyle="--",label="Commanded height")
    ax.text(0.02,0.95,f'Ceiling: {summary["z_max_m"]:g} m',transform=ax.transAxes,va="top")
    ax.set(ylabel="Height (m)",title=f'Altitude; guardian interventions: {summary["oba_interventions"]}')
    for ax in axes.flat:
        ax.grid(True,alpha=0.3)
        ax.legend(fontsize="small")
    for ax in (axes[0,1],axes[1,0],axes[1,1]):
        ax.set_xlabel("CARLA simulation time (s)")
    status="complete" if summary["completed"] else "partial"
    fig.suptitle(f'Experiment B: {summary["scenario"]} ({status}); {summary["follow_mode"]} offset {summary["follow_distance_m"]:g} m\n{summary["script_version"]}; tracking criteria: {"PASS" if summary["tracking_criteria_passed"] else "FAIL"}; clocks may differ')
    try:
        fig.savefig(Path(output)/"tracking_metrics.png",dpi=160)
    finally:
        plt.close(fig)

def trailing_position(path,distance):
    """Interpolate a point distance meters back along the pedestrian path."""
    remaining=distance
    for i in range(len(path)-1,0,-1):
        end=path[i];start=path[i-1]
        length=math.dist(start,end)
        if length==0:
            continue
        if remaining<=length:
            fraction=remaining/length
            return (end[0]+fraction*(start[0]-end[0]),end[1]+fraction*(start[1]-end[1]))
        remaining-=length
    return path[0]

def wait_until_settled(drone,target,timeout,settle_seconds,tolerance):
    """Require position and low speed continuously; refuse to score an unready start."""
    deadline=time.monotonic()+timeout
    settled_since=None
    while time.monotonic()<deadline:
        state=drone.getMultirotorState()
        pos=state.kinematics_estimated.position
        vel=state.kinematics_estimated.linear_velocity
        error=math.dist((pos.x_val,pos.y_val,pos.z_val),target)
        speed=math.sqrt(vel.x_val**2+vel.y_val**2+vel.z_val**2)
        if error<=tolerance and speed<=0.3:
            if settled_since is None: settled_since=time.monotonic()
            if time.monotonic()-settled_since>=settle_seconds:
                return
        else:
            settled_since=None
        time.sleep(0.05)
    raise TimeoutError("Drone did not settle at the starting follow position; tracking was not started")

def run(args):
    import carla,airsim
    print(f"[Experiment B] {SCRIPT_VERSION}; follow={args.follow_distance} m; mode={args.follow_mode}; speed={args.drone_speed} m/s",flush=True)
    output=Path(args.output_dir);output.mkdir(parents=True,exist_ok=True)
    client=carla.Client(args.carla_host,args.carla_port);client.set_timeout(10.)
    world=client.get_world()
    original=world.get_settings()
    walker=None;drone=None;rows=[];completed=False
    setup_completed=False;setup_duration_s=None;tracking_start=None;measurement_start_height=None
    try:
        settings=world.get_settings()
        settings.synchronous_mode=False;settings.fixed_delta_seconds=0.05
        world.apply_settings(settings)
        bp=world.get_blueprint_library().filter("walker.pedestrian.*")
        if not bp:raise RuntimeError("No pedestrian blueprints found")
        spectator=world.get_spectator().get_transform()
        forward=spectator.get_forward_vector();right=spectator.get_right_vector()
        norm=lambda x,y:(x/math.hypot(x,y),y/math.hypot(x,y))
        fx,fy=norm(forward.x,forward.y)
        rx,ry=norm(right.x,right.y)
        spawn=spectator.location+forward*8.;spawn.z+=1.
        walker=world.try_spawn_actor(bp[0],carla.Transform(spawn))
        if walker is None:raise RuntimeError("Pedestrian spawn failed")
        world.wait_for_tick(10.)
        setup_start=time.monotonic()
        print("[Experiment B] Setup: takeoff (excluded from tracking metrics)",flush=True)
        drone=airsim.MultirotorClient(timeout_value=args.rpc_timeout);drone.confirmConnection()
        drone.enableApiControl(True);drone.armDisarm(True);drone.takeoffAsync(timeout_sec=args.setup_timeout).join()
        ped0=walker.get_location()
        p0=drone.getMultirotorState().kinematics_estimated.position
        origin=(p0.x_val,p0.y_val)
        requested_z=-args.target_height
        setup_z=max(-args.z_max,requested_z) if args.oba else requested_z
        start_target=(origin[0]-fx*args.follow_distance,origin[1]-fy*args.follow_distance,setup_z)
        print(f"[Experiment B] Setup: positioning at {start_target}",flush=True)
        drone.moveToPositionAsync(*start_target,velocity=args.drone_speed,timeout_sec=args.setup_timeout)
        wait_until_settled(drone,start_target,args.setup_timeout,args.settle_seconds,args.start_tolerance)
        measurement_start_height=-drone.getMultirotorState().kinematics_estimated.position.z_val
        print(f"[Experiment B] Height ready: {measurement_start_height:.2f} m; commanded {args.target_height:.2f} m (height = -AirSim Z)",flush=True)
        setup_duration_s=time.monotonic()-setup_start
        setup_completed=True
        # Keep the original mapping fixed; moving the origin after positioning would shift the target.
        settings=world.get_settings()
        settings.synchronous_mode=True;settings.fixed_delta_seconds=0.05
        world.apply_settings(settings)
        tracking_start=time.monotonic()
        airsim_start=drone.getMultirotorState().timestamp
        path=[start_target[:2],origin]
        last_cmd=None
        last_command_time=0.0
        print("[Experiment B] Tracking started", flush=True)
        for tick in range(args.ticks):
            # Pace CARLA ticks against wall time; this does not synchronize simulator clocks.
            remaining=tracking_start+(tick+1)*0.05-time.monotonic()
            if remaining>0:
                time.sleep(remaining)
            if args.scenario=="rectangle":
                leg=(tick//100)%4
                dx,dy=((fx,fy),(rx,ry),(-fx,-fy),(-rx,-ry))[leg]
            else:
                bias=1.2*math.sin(tick*0.08)
                dx,dy=norm(fx+rx*bias,fy+ry*bias)
            ctrl=carla.WalkerControl()
            ctrl.speed=args.speed;ctrl.direction=carla.Vector3D(dx,dy,0.)
            walker.apply_control(ctrl)
            if tick % args.log_every == 0:
                print(f"[Experiment B] tick={tick}/{args.ticks} before CARLA tick", flush=True)
            world.tick()
            ped=walker.get_location()
            ped_x=origin[0]+ped.x-ped0.x;ped_y=origin[1]+ped.y-ped0.y
            path.append((ped_x,ped_y))
            if args.follow_mode=="path":
                target_x,target_y=trailing_position(path,args.follow_distance)
            else:
                target_x=ped_x-dx*args.follow_distance
                target_y=ped_y-dy*args.follow_distance
            requested_z=-args.target_height
            start_ns=time.perf_counter_ns()
            cmd_z=max(-args.z_max,requested_z) if args.oba else requested_z
            intervened=int(cmd_z!=requested_z)
            guardian_us=(time.perf_counter_ns()-start_ns)/1000.
            command=(target_x,target_y,cmd_z)
            now=time.monotonic()
            if (last_cmd is None or math.dist(command,last_cmd)>0.20) and (last_cmd is None or now-last_command_time>=args.command_interval):
                if tick % args.log_every == 0:
                    print(f"[Experiment B] tick={tick} before AirSim command", flush=True)
                drone.moveToPositionAsync(*command,velocity=args.drone_speed,timeout_sec=args.rpc_timeout)
                last_cmd=command
                last_command_time=now
            if tick % args.log_every == 0:
                print(f"[Experiment B] tick={tick} before AirSim telemetry", flush=True)
            state=drone.getMultirotorState()
            pos=state.kinematics_estimated.position
            if tick % args.log_every == 0:
                print(f"[Experiment B] tick={tick} telemetry received", flush=True)
            err=math.hypot(pos.x_val-target_x,pos.y_val-target_y)
            ped_x=origin[0]+ped.x-ped0.x;ped_y=origin[1]+ped.y-ped0.y
            rows.append({"tick":tick,"carla_sim_time_s":(tick+1)*0.05,
                         "wall_elapsed_s":time.monotonic()-tracking_start,
                         "airsim_elapsed_s":(state.timestamp-airsim_start)/1e9,
                         "ped_x":ped_x,"ped_y":ped_y,
                         "target_x":target_x,"target_y":target_y,"command_z":cmd_z,
                         "drone_x":pos.x_val,"drone_y":pos.y_val,"drone_z":pos.z_val,
                         "target_error_m":err,
                         "ped_drone_xy_separation_m":math.hypot(pos.x_val-ped_x,pos.y_val-ped_y),
                         "altitude_violation":int(-pos.z_val>args.z_max),
                         "oba_intervention":intervened,"guardian_latency_us":guardian_us})
        completed=True
    finally:
        if rows:
            with (output/"telemetry.csv").open("w",newline="") as f:
                writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        summary=summarize(rows,completed,args.scenario,args.speed,args.oba,args.follow_distance)
        summary["script_version"]=SCRIPT_VERSION
        summary["script_sha256"]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        summary["follow_mode"]=args.follow_mode
        summary["acceptance_rmse_m"]=args.acceptance_rmse
        summary["acceptance_p95_m"]=args.acceptance_p95
        summary["tracking_criteria_passed"]=bool(completed and setup_completed and rows and
            summary["tracking_target_rmse_m"]<=args.acceptance_rmse and
            summary["tracking_target_p95_m"]<=args.acceptance_p95)
        summary["z_max_m"]=args.z_max
        summary["target_height_m"]=args.target_height
        summary["measurement_start_height_m"]=measurement_start_height
        summary["height_convention"]="height = -AirSim NED Z, relative to AirSim origin; not ground clearance"
        summary.update(setup_completed=setup_completed,setup_duration_s=setup_duration_s,
                       drone_speed_mps=args.drone_speed,command_interval_s=args.command_interval,
                       wall_elapsed_s=rows[-1]["wall_elapsed_s"] if rows else None,
                       airsim_elapsed_s=rows[-1]["airsim_elapsed_s"] if rows else None)
        (output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
        try:
            plot_metrics(rows,summary,output)
        except Exception as e:
            print("Plot generation warning (telemetry and summary saved):",e,flush=True)
        try:
            # Landing must be allowed to advance physics without Python issuing CARLA ticks.
            settings=world.get_settings();settings.synchronous_mode=False
            world.apply_settings(settings)
            if walker is not None:walker.destroy()
            if drone is not None:
                try:
                    drone.landAsync(timeout_sec=args.setup_timeout).join()
                    drone.armDisarm(False);drone.enableApiControl(False)
                except Exception as e:print("AirSim cleanup warning:",e)
        finally:
            world.apply_settings(original)
    print((output/"summary.json").read_text())

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--scenario",choices=["rectangle","zigzag"],required=True)
    p.add_argument("--output-dir",required=True)
    p.add_argument("--oba",action="store_true")
    p.add_argument("--carla-host",default="localhost");p.add_argument("--carla-port",type=int,default=2000)
    p.add_argument("--ticks",type=int,default=400)
    p.add_argument("--log-every",type=int,default=10)
    p.add_argument("--command-interval",type=float,default=0.1,help="Minimum wall-clock seconds between AirSim move commands")
    p.add_argument("--speed",type=float,default=1.4)
    p.add_argument("--drone-speed",type=float,default=4.0)
    p.add_argument("--follow-distance",type=float,default=1.0,help="Horizontal follow offset in meters (default: 1)")
    p.add_argument("--target-height",type=float,default=-25.,help="Signed height relative to AirSim origin, equal to -NED Z (default: -25 m, commands Z=+25 m)")
    p.add_argument("--z-max",type=float,default=30.)
    p.add_argument("--follow-mode",choices=["path","heading"],default="path",help="Follow prior pedestrian path (continuous target) or instantaneous heading (legacy)")
    p.add_argument("--acceptance-rmse",type=float,default=1.,help="Provisional tracking RMSE limit in meters")
    p.add_argument("--acceptance-p95",type=float,default=2.,help="Provisional tracking P95 limit in meters")
    p.add_argument("--setup-timeout",type=float,default=60.,help="Timeout per setup operation in seconds")
    p.add_argument("--rpc-timeout",type=float,default=15.,help="AirSim RPC timeout in seconds")
    p.add_argument("--settle-seconds",type=float,default=1.,help="Required continuous settled time before measuring")
    p.add_argument("--start-tolerance",type=float,default=0.3,help="Starting 3D position tolerance in meters")
    a=p.parse_args()
    if a.ticks<1 or a.speed<=0 or a.z_max<=0 or a.log_every<1 or a.command_interval<0 or a.follow_distance<=0 or a.drone_speed<=0 or a.setup_timeout<=0 or a.rpc_timeout<=0 or a.settle_seconds<=0 or a.start_tolerance<=0 or a.acceptance_rmse<=0 or a.acceptance_p95<=0 or not all(math.isfinite(v) for v in (a.acceptance_rmse,a.acceptance_p95,a.speed,a.drone_speed,a.follow_distance,a.target_height,a.z_max,a.command_interval,a.setup_timeout,a.rpc_timeout,a.settle_seconds,a.start_tolerance)): p.error("Invalid parameters")
    run(a)
