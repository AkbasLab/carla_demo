"""Experiment B: live CARLA pedestrian / AirSim drone tracking telemetry.

Requires both simulators. Run one scenario at a time, in a clear test area.
"""
import argparse,csv,json,math,statistics,time,hashlib,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

SCRIPT_VERSION="experiment-b-boundary-monitor-v6"

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
    ax.axhline(summary["minimum_separation_m"],color="black",linestyle="-.",label="Minimum horizontal separation")
    ax.set(ylabel="XY separation (m)",title="Drone–pedestrian horizontal separation")
    ax=axes[1,1]
    ax.plot(t,[-r["drone_z"] for r in rows],label="Actual drone height (AirSim origin)")
    ax.plot(t,[-r["command_z"] for r in rows],linestyle="--",label="Commanded height")
    ax.axhline(summary["height_min_m"],color="gray",linestyle=":",label="Configured height floor")
    ax.axhline(summary["z_max_m"],color="black",linestyle="-.",label="Configured height ceiling")
    ax.text(0.02,0.95,f'Ceiling: {summary["z_max_m"]:g} m',transform=ax.transAxes,va="top")
    ax.set(ylabel="Height (m)",title=f'Altitude; guardian intervention samples: {summary["oba_interventions"]}')
    for ax in axes.flat:
        ax.grid(True,alpha=0.3)
        ax.legend(fontsize="small")
    for ax in (axes[0,1],axes[1,0],axes[1,1]):
        ax.set_xlabel("CARLA simulation time (s)")
        lower,upper=ax.get_ylim()
        span=upper-lower
        if ax is axes[1,1]:
            midpoint=(lower+upper)/2
            ax.set_ylim(midpoint-1.5*span,midpoint+1.5*span)
        else:
            # Distances are nonnegative: anchor at zero rather than showing negative meters.
            ax.set_ylim(0,max(3*span,upper))
    status="complete" if summary["completed"] else "partial"
    fig.suptitle(f'Experiment B: {summary["scenario"]} ({status}); {summary["follow_mode"]} offset {summary["follow_distance_m"]:g} m\n{summary["script_version"]}; tracking criteria: {"PASS" if summary["tracking_criteria_passed"] else "FAIL"}; timing: {"VALID" if summary["timing_valid"] else "INVALID"}; sampled boundaries: {"PASS" if summary["sampled_boundary_compliance"] else "FAIL/UNVERIFIED"}\nMetric-panel Y ranges expanded 3×')
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

def wait_until_settled(drone,target,timeout,settle_seconds,tolerance,height_only=False):
    """Require position and low speed continuously; refuse to score an unready start."""
    deadline=time.monotonic()+timeout
    settled_since=None
    while time.monotonic()<deadline:
        state=drone.getMultirotorState()
        pos=state.kinematics_estimated.position
        vel=state.kinematics_estimated.linear_velocity
        error=abs(pos.z_val-target[2]) if height_only else math.dist((pos.x_val,pos.y_val,pos.z_val),target)
        speed=abs(vel.z_val) if height_only else math.sqrt(vel.x_val**2+vel.y_val**2+vel.z_val**2)
        if error<=tolerance and speed<=0.3:
            if settled_since is None: settled_since=time.monotonic()
            if time.monotonic()-settled_since>=settle_seconds:
                return
        else:
            settled_since=None
        time.sleep(0.05)
    raise TimeoutError("Drone did not satisfy the setup gate; tracking was not started")

def run(args):
    import carla, airsim
    from agentic_uav.control.tracking_safety import (
        SafetyEnvelope, map_xy, closest_separation, tracking_velocity)

    envelope = SafetyEnvelope(args.minimum_separation, args.safety_margin,
                              args.height_min, args.z_max, args.prediction_horizon,
                              args.max_acceleration)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    if any((output/name).exists() for name in ("telemetry.csv", "summary.json", "tracking_metrics.png")):
        raise FileExistsError("Choose a new output directory; existing experiment artifacts will not be overwritten")
    client = carla.Client(args.carla_host, args.carla_port)
    client.set_timeout(args.rpc_timeout)
    world = client.get_world()
    original = world.get_settings()
    walker = drone = None
    rows = []
    completed = setup_completed = False
    abort_reason = None
    setup_duration_s = measurement_start_height = None
    leg_ticks = math.ceil(100*math.sqrt(args.rectangle_area_scale))
    walking_speed = args.speed*100*math.sqrt(args.rectangle_area_scale)/leg_ticks
    calibrated = args.frame_offset_x is not None and args.frame_offset_y is not None
    print(f"[Experiment B] {SCRIPT_VERSION}; guarded={args.oba}; calibrated={calibrated}", flush=True)
    try:
        settings = world.get_settings()
        settings.synchronous_mode = False
        settings.fixed_delta_seconds = 0.05
        world.apply_settings(settings)
        spectator = world.get_spectator().get_transform()
        forward, right = spectator.get_forward_vector(), spectator.get_right_vector()
        def normalize(x, y):
            length = math.hypot(x, y)
            if length < 1e-6:
                raise ValueError("Spectator must have a nonvertical horizontal heading")
            return x/length, y/length
        fx, fy = normalize(forward.x, forward.y)
        rx, ry = normalize(right.x, right.y)
        spawn = spectator.location+forward*8.
        spawn.z += 1.
        walker = world.try_spawn_actor(world.get_blueprint_library().filter("walker.pedestrian.*")[0], carla.Transform(spawn))
        if walker is None:
            raise RuntimeError("Pedestrian spawn failed")
        world.wait_for_tick(args.rpc_timeout)
        drone = airsim.MultirotorClient(timeout_value=args.rpc_timeout)
        drone.confirmConnection()
        initial = drone.getMultirotorState().kinematics_estimated.position
        ped0 = walker.get_location()
        if not all(math.isfinite(v) for v in (initial.x_val,initial.y_val,initial.z_val,ped0.x,ped0.y)):
            raise RuntimeError("Non-finite setup coordinates; refusing to arm")
        offset_x = args.frame_offset_x if calibrated else initial.x_val-ped0.x
        offset_y = args.frame_offset_y if calibrated else initial.y_val-ped0.y
        def mapped(x, y):
            return map_xy(x, y, args.frame_yaw_deg, offset_x, offset_y)
        heading = map_xy(fx, fy, args.frame_yaw_deg, 0., 0.)
        pedestrian_start = mapped(ped0.x, ped0.y)
        start_xy = tuple(p-d*args.follow_distance for p, d in zip(pedestrian_start, heading))
        if args.oba:
            # The pedestrian is stationary during setup. Reject a straight setup
            # segment that would cross its protected horizontal disk, before arming.
            relative = (initial.x_val-pedestrian_start[0], initial.y_val-pedestrian_start[1])
            displacement = (start_xy[0]-initial.x_val, start_xy[1]-initial.y_val)
            if closest_separation(relative, displacement, 1.) < args.minimum_separation+args.safety_margin:
                raise RuntimeError("Unsafe setup path: reposition the scene before arming")
        setup_start = time.monotonic()
        drone.enableApiControl(True)
        drone.armDisarm(True)
        drone.takeoffAsync(timeout_sec=args.setup_timeout).join()
        command_height = min(args.z_max-args.safety_margin,
                             max(args.height_min+args.safety_margin, args.target_height)) if args.oba else args.target_height
        start_target = (*start_xy, -command_height)
        drone.moveToPositionAsync(*start_target, velocity=args.drone_speed, timeout_sec=args.setup_timeout)
        wait_until_settled(drone, start_target, args.setup_timeout,
                           args.settle_seconds, args.start_tolerance)
        setup_duration_s = time.monotonic()-setup_start
        setup_completed = True
        baseline_state = drone.getMultirotorState()
        measurement_start_height = -baseline_state.kinematics_estimated.position.z_val
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05
        world.apply_settings(settings)
        carla_start = world.get_snapshot().timestamp.elapsed_seconds
        airsim_start = baseline_state.timestamp
        tracking_start = time.monotonic()
        path = [start_xy, pedestrian_start]
        previous_ped = pedestrian_start
        previous_sim_time = carla_start
        previous_air_stamp = airsim_start
        for tick in range(args.ticks):
            remaining = tracking_start+(tick+1)*0.05-time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            if args.scenario == "rectangle":
                dx, dy = ((fx, fy), (rx, ry), (-fx, -fy), (-rx, -ry))[(tick//leg_ticks)%4]
            else:
                bias = 1.2*math.sin(tick*0.08)
                dx, dy = normalize(fx+rx*bias, fy+ry*bias)
            ctrl = carla.WalkerControl()
            ctrl.speed = walking_speed if args.scenario == "rectangle" else args.speed
            ctrl.direction = carla.Vector3D(dx, dy, 0.)
            walker.apply_control(ctrl)
            read_start = time.monotonic()
            world.tick()
            snapshot = world.get_snapshot()
            actor_snapshot = snapshot.find(walker.id)
            if actor_snapshot is None:
                raise RuntimeError("Pedestrian missing from CARLA snapshot")
            ped = actor_snapshot.get_transform().location
            ped_xy = mapped(ped.x, ped.y)
            sim_time = snapshot.timestamp.elapsed_seconds
            dt = sim_time-previous_sim_time
            if dt <= 0:
                raise RuntimeError("CARLA simulation timestamp did not advance")
            pedestrian_velocity = tuple((p-q)/dt for p, q in zip(ped_xy, previous_ped))
            path.append(ped_xy)
            if args.follow_mode == "path":
                target = trailing_position(path, args.follow_distance)
            else:
                hx, hy = map_xy(dx, dy, args.frame_yaw_deg, 0., 0.)
                target = (ped_xy[0]-hx*args.follow_distance, ped_xy[1]-hy*args.follow_distance)
            # Path distance can imply smaller Euclidean clearance at a corner.
            radial = (target[0]-ped_xy[0], target[1]-ped_xy[1])
            radius = math.hypot(*radial)
            projected = False
            if args.oba and radius < args.minimum_separation+args.safety_margin:
                direction = tuple(v/radius for v in radial) if radius else tuple(-v for v in heading)
                target = tuple(p+v*(args.minimum_separation+args.safety_margin) for p, v in zip(ped_xy, direction))
                projected = True
            state = drone.getMultirotorState()
            read_duration = time.monotonic()-read_start
            pos, vel = state.kinematics_estimated.position, state.kinematics_estimated.linear_velocity
            if not all(math.isfinite(v) for v in (pos.x_val,pos.y_val,pos.z_val,
                    vel.x_val,vel.y_val,vel.z_val,state.timestamp,sim_time,*ped_xy)):
                raise RuntimeError("Non-finite simulator telemetry")
            position, velocity = (pos.x_val, pos.y_val), (vel.x_val, vel.y_val)
            carla_elapsed = sim_time-carla_start
            air_elapsed = (state.timestamp-airsim_start)/1e9
            skew = abs(air_elapsed-carla_elapsed)
            timing_valid = (state.timestamp > previous_air_stamp and
                            skew <= args.max_clock_skew and read_duration <= args.max_telemetry_latency)
            start_ns = time.perf_counter_ns()
            command_velocity = tracking_velocity(position, target, pedestrian_velocity, velocity,
                args.position_gain, args.drone_speed, args.max_acceleration, dt)
            vz = max(-args.vertical_speed, min(args.vertical_speed,
                     args.height_gain*(-command_height-pos.z_val)))
            reasons = envelope.reasons(position, velocity, command_velocity, ped_xy,
                pedestrian_velocity, -pos.z_val, vel.z_val) if args.oba else []
            if args.oba and not timing_valid:
                reasons.append("invalid_timing")
            if args.oba and not args.height_min+args.safety_margin <= -pos.z_val-vz*args.prediction_horizon <= args.z_max-args.safety_margin:
                reasons.append("command_height_risk")
            guardian_us = (time.perf_counter_ns()-start_ns)/1000.
            height = -pos.z_val
            separation = math.dist(position, ped_xy)
            rows.append({"tick":tick,"carla_sim_time_s":carla_elapsed,"sample_interval_s":dt,
                "wall_elapsed_s":time.monotonic()-tracking_start,"airsim_elapsed_s":air_elapsed,
                "clock_skew_s":skew,"telemetry_latency_s":read_duration,"timing_valid":int(timing_valid),
                "ped_x":ped_xy[0],"ped_y":ped_xy[1],"target_x":target[0],"target_y":target[1],
                "command_z":-command_height,"drone_x":pos.x_val,"drone_y":pos.y_val,"drone_z":pos.z_val,
                "command_vx":command_velocity[0],"command_vy":command_velocity[1],"command_vz":vz,
                "target_error_m":math.dist(position,target),"ped_drone_xy_separation_m":separation,
                "altitude_violation":int(not args.height_min <= height <= args.z_max),
                "separation_violation":int(separation < args.minimum_separation),
                "oba_intervention":int(projected or bool(reasons) or command_height != args.target_height),
                "guardian_latency_us":guardian_us,"guardian_reason":";".join(reasons)})
            if reasons:
                abort_reason = ";".join(reasons)
                break
            # Refresh short-lived velocity commands every sample; no deadband or
            # repeated asynchronous position goals. Feedforward uses measured target velocity.
            drone.moveByVelocityAsync(*command_velocity, vz, duration=args.command_duration)
            previous_ped, previous_sim_time = ped_xy, sim_time
            previous_air_stamp = state.timestamp
        else:
            completed = True
    except Exception as exc:
        abort_reason = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        # Stop the target before cancelling flight commands. These are best-effort
        # simulator recovery actions; never label them a proven safe controller.
        try:
            if walker is not None:
                stop = carla.WalkerControl()
                stop.speed = 0.
                walker.apply_control(stop)
            settings = world.get_settings()
            settings.synchronous_mode = False
            world.apply_settings(settings)
            if drone is not None:
                drone.cancelLastTask()
                drone.hoverAsync().join()
        except Exception as exc:
            abort_reason = abort_reason or f"Recovery failed: {exc}"
        try:
            if rows:
                with (output/"telemetry.csv").open("w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)
            summary = summarize(rows, completed, args.scenario, args.speed, args.oba, args.follow_distance)
            summary.update(script_version=SCRIPT_VERSION, script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                guardian_sha256=hashlib.sha256((Path(__file__).resolve().parents[1]/"agentic_uav/control/tracking_safety.py").read_bytes()).hexdigest(),
                configuration=vars(args),
                follow_mode=args.follow_mode,setup_gate="full_position_and_speed",setup_completed=setup_completed,
                setup_duration_s=setup_duration_s,measurement_start_height_m=measurement_start_height,
                target_height_m=args.target_height,z_max_m=args.z_max,height_min_m=args.height_min,
                minimum_separation_m=args.minimum_separation,safety_margin_m=args.safety_margin,
                frame_calibrated=calibrated,frame_verified=args.frame_verified,
                frame_yaw_deg=args.frame_yaw_deg,frame_offset_x=args.frame_offset_x,frame_offset_y=args.frame_offset_y,
                abort_reason=abort_reason,rectangle_area_scale=args.rectangle_area_scale,rectangle_leg_ticks=leg_ticks,
                commanded_walking_speed_mps=walking_speed if args.scenario=="rectangle" else args.speed,
                acceptance_rmse_m=args.acceptance_rmse,acceptance_p95_m=args.acceptance_p95,
                timing_valid=bool(rows and all(r["timing_valid"] for r in rows)),
                separation_violation_samples=sum(r["separation_violation"] for r in rows),
                sampled_violation_duration_s=sum(r["sample_interval_s"] for r in rows if r["separation_violation"] or r["altitude_violation"]),
                max_clock_skew_s=max((r["clock_skew_s"] for r in rows), default=None),
                max_telemetry_latency_s=max((r["telemetry_latency_s"] for r in rows), default=None),
                min_measured_height_m=min((-r["drone_z"] for r in rows), default=None),
                max_measured_height_m=max((-r["drone_z"] for r in rows), default=None),
                height_convention="-AirSim NED Z; configured origin-relative bounds, not terrain clearance",
                controller=dict(position_gain=args.position_gain,height_gain=args.height_gain,
                    max_speed=args.drone_speed,max_acceleration=args.max_acceleration,
                    command_duration=args.command_duration,prediction_horizon=args.prediction_horizon))
            summary["tracking_criteria_passed"] = bool(completed and setup_completed and rows and summary["timing_valid"] and calibrated and args.frame_verified and
                summary["tracking_target_rmse_m"] <= args.acceptance_rmse and summary["tracking_target_p95_m"] <= args.acceptance_p95)
            summary["sampled_boundary_compliance"] = bool(completed and setup_completed and not abort_reason and rows and calibrated and args.frame_verified and summary["timing_valid"] and
                summary["altitude_violation_samples"] == 0 and summary["separation_violation_samples"] == 0)
            summary["notes"] = ["Clock drift and acquisition latency checked, not hardware synchronization",
                "Boundary result covers sampled calibrated XY separation and origin-relative height only",
                "No terrain, obstacle, between-sample collision, or formal safety guarantee"]
            (output/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
            try:
                plot_metrics(rows, summary, output)
            except Exception as exc:
                print("Plot generation warning:", exc, flush=True)
        finally:
            try:
                if walker is not None:
                    walker.destroy()
                # Do not land blindly on a pedestrian/unknown terrain: leave the
                # simulator drone hovering under API control for operator recovery.
            finally:
                world.apply_settings(original)
    print((output/"summary.json").read_text())
    return completed and not abort_reason


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scenario", choices=["rectangle", "zigzag"], required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--oba", action="store_true")
    p.add_argument("--carla-host", default="localhost")
    p.add_argument("--carla-port", type=int, default=2000)
    p.add_argument("--ticks", type=int)
    p.add_argument("--rectangle-area-scale", type=float, default=5.)
    p.add_argument("--log-every", type=int, default=10)
    p.add_argument("--speed", type=float, default=1.4)
    p.add_argument("--drone-speed", type=float, default=3.)
    p.add_argument("--follow-distance", type=float, default=5.)
    p.add_argument("--target-height", type=float, default=25., help="Height=-AirSim NED Z, relative to origin")
    p.add_argument("--height-min", type=float, default=0., help="Origin-relative floor; not terrain clearance")
    p.add_argument("--z-max", type=float, default=30.)
    p.add_argument("--minimum-separation", type=float, default=3., help="Conservative horizontal safety distance, distinct from tracking error")
    p.add_argument("--safety-margin", type=float, default=0.5)
    p.add_argument("--max-acceleration", type=float, default=2., help="XY command slew limit and assumed braking acceleration, m/s^2")
    p.add_argument("--prediction-horizon", type=float, default=0.5)
    p.add_argument("--position-gain", type=float, default=0.8)
    p.add_argument("--height-gain", type=float, default=0.8)
    p.add_argument("--vertical-speed", type=float, default=1.)
    p.add_argument("--command-duration", type=float, default=0.15)
    p.add_argument("--max-clock-skew", type=float, default=0.1)
    p.add_argument("--max-telemetry-latency", type=float, default=0.1)
    p.add_argument("--frame-yaw-deg", type=float, default=0.)
    p.add_argument("--frame-offset-x", type=float)
    p.add_argument("--frame-offset-y", type=float)
    p.add_argument("--frame-verified", action="store_true", help="Operator has independently verified static frame registration")
    p.add_argument("--follow-mode", choices=["path", "heading"], default="path")
    p.add_argument("--acceptance-rmse", type=float, default=1.)
    p.add_argument("--acceptance-p95", type=float, default=2.)
    p.add_argument("--setup-timeout", type=float, default=60.)
    p.add_argument("--rpc-timeout", type=float, default=2.)
    p.add_argument("--settle-seconds", type=float, default=1.)
    p.add_argument("--start-tolerance", type=float, default=0.3)
    a = p.parse_args(argv)
    numeric = [v for v in vars(a).values() if isinstance(v, float)]
    if not all(math.isfinite(v) for v in numeric):
        p.error("All numeric settings must be finite")
    positive = (a.rectangle_area_scale,a.speed,a.drone_speed,a.follow_distance,a.safety_margin,
        a.max_acceleration,a.prediction_horizon,a.position_gain,a.height_gain,a.vertical_speed,
        a.command_duration,a.max_clock_skew,a.max_telemetry_latency,a.acceptance_rmse,a.acceptance_p95,
        a.setup_timeout,a.rpc_timeout,a.settle_seconds,a.start_tolerance)
    if min(positive) <= 0 or a.log_every < 1 or (a.ticks is not None and a.ticks < 1):
        p.error("Durations, limits, speeds, gains, and counts must be positive")
    if a.minimum_separation <= 0 or a.height_min+2*a.safety_margin >= a.z_max:
        p.error("Invalid safety envelope")
    if (a.frame_offset_x is None) != (a.frame_offset_y is None):
        p.error("Supply both frame offsets")
    if a.oba and (not a.frame_verified or a.frame_offset_x is None):
        p.error("Guarded runs require calibrated --frame-offset-x/--frame-offset-y and --frame-verified")
    if a.oba and a.follow_distance < a.minimum_separation+a.safety_margin:
        p.error("Follow distance must include minimum horizontal separation plus safety margin")
    if a.oba and not a.height_min+a.safety_margin <= a.target_height <= a.z_max-a.safety_margin:
        p.error("Target height must be inside the configured floor/ceiling with margin")
    if a.command_duration < 0.05 or a.prediction_horizon < a.command_duration+a.max_telemetry_latency:
        p.error("Prediction horizon must cover command duration plus telemetry latency; commands must cover a 20Hz tick")
    if a.ticks is None:
        a.ticks = 4*math.ceil(100*math.sqrt(a.rectangle_area_scale)) if a.scenario == "rectangle" else 400
    return a


if __name__ == "__main__":
    raise SystemExit(0 if run(parse_args()) else 1)
