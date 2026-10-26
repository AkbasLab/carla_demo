"""Experiment B: live CARLA pedestrian / AirSim drone tracking telemetry.

Requires both simulators. Run one scenario at a time, in a clear test area.
"""
import argparse,csv,json,math,statistics,time
from pathlib import Path

def percentile(values,p):
    v=sorted(values)
    if not v:return None
    i=(len(v)-1)*p/100
    a=math.floor(i);b=math.ceil(i)
    return v[a]+(v[b]-v[a])*(i-a)

def summarize(rows,completed,scenario,speed,guarded,follow_distance=2.0):
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
    ax.set(ylabel="XY error (m)",title="Distance from desired follow position")
    ax=axes[1,0]
    ax.plot(t,[r["ped_drone_xy_separation_m"] for r in rows],label="Actual XY separation")
    ax.axhline(summary["follow_distance_m"],color="tab:green",linestyle="--",label="Requested follow distance")
    ax.axhline(summary["rms_ped_drone_xy_separation_m"],color="tab:red",linestyle=":",label=f'RMS {summary["rms_ped_drone_xy_separation_m"]:.2f} m')
    ax.set(ylabel="XY separation (m)",title="Drone–pedestrian horizontal separation")
    ax=axes[1,1]
    ax.plot(t,[-r["drone_z"] for r in rows],label="Actual drone height (AirSim origin)")
    ax.plot(t,[-r["command_z"] for r in rows],linestyle="--",label="Commanded height")
    ax.axhline(summary["z_max_m"],color="tab:red",linestyle=":",label="Altitude ceiling")
    ax.set(ylabel="Height (m)",title=f'Altitude; guardian interventions: {summary["oba_interventions"]}')
    for ax in axes.flat:
        ax.grid(True,alpha=0.3)
        ax.legend(fontsize="small")
    for ax in (axes[0,1],axes[1,0],axes[1,1]):
        ax.set_xlabel("CARLA simulation time (s)")
    status="complete" if summary["completed"] else "partial"
    fig.suptitle(f'Experiment B: {summary["scenario"]} ({status}); CARLA and AirSim time may differ')
    try:
        fig.savefig(Path(output)/"tracking_metrics.png",dpi=160)
    finally:
        plt.close(fig)

def run(args):
    import carla,airsim
    output=Path(args.output_dir);output.mkdir(parents=True,exist_ok=True)
    client=carla.Client(args.carla_host,args.carla_port);client.set_timeout(10.)
    world=client.get_world()
    original=world.get_settings()
    walker=None;drone=None;rows=[];completed=False
    try:
        settings=world.get_settings()
        settings.synchronous_mode=True;settings.fixed_delta_seconds=0.05
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
        world.tick()
        drone=airsim.MultirotorClient();drone.confirmConnection()
        drone.enableApiControl(True);drone.armDisarm(True);drone.takeoffAsync().join()
        ped0=walker.get_location()
        p0=drone.getMultirotorState().kinematics_estimated.position
        origin=(p0.x_val,p0.y_val)
        last_cmd=None
        last_command_time=0.0
        print("[Experiment B] Tracking started", flush=True)
        for tick in range(args.ticks):
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
            target_x=origin[0]+ped.x-ped0.x-dx*args.follow_distance
            target_y=origin[1]+ped.y-ped0.y-dy*args.follow_distance
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
                drone.moveToPositionAsync(*command,velocity=args.drone_speed)
                last_cmd=command
                last_command_time=now
            if tick % args.log_every == 0:
                print(f"[Experiment B] tick={tick} before AirSim telemetry", flush=True)
            pos=drone.getMultirotorState().kinematics_estimated.position
            if tick % args.log_every == 0:
                print(f"[Experiment B] tick={tick} telemetry received", flush=True)
            err=math.hypot(pos.x_val-target_x,pos.y_val-target_y)
            ped_x=origin[0]+ped.x-ped0.x;ped_y=origin[1]+ped.y-ped0.y
            rows.append({"tick":tick,"carla_sim_time_s":(tick+1)*0.05,
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
        summary["z_max_m"]=args.z_max
        summary["target_height_m"]=args.target_height
        (output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
        try:
            plot_metrics(rows,summary,output)
        except Exception as e:
            print("Plot generation warning (telemetry and summary saved):",e,flush=True)
        if walker is not None:walker.destroy()
        if drone is not None:
            try:drone.hoverAsync().join();drone.landAsync().join();drone.armDisarm(False);drone.enableApiControl(False)
            except Exception as e:print("AirSim cleanup warning:",e)
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
    p.add_argument("--command-interval",type=float,default=0.5,help="Minimum wall-clock seconds between AirSim move commands")
    p.add_argument("--speed",type=float,default=1.4)
    p.add_argument("--drone-speed",type=float,default=2.5)
    p.add_argument("--follow-distance",type=float,default=2.0,help="Horizontal follow offset in meters (default: 2)")
    p.add_argument("--target-height",type=float,default=3.)
    p.add_argument("--z-max",type=float,default=30.)
    a=p.parse_args()
    if a.ticks<1 or a.speed<=0 or a.target_height<=0 or a.z_max<=0 or a.log_every<1 or a.command_interval<0 or a.follow_distance<=0: p.error("Invalid parameters")
    run(a)
