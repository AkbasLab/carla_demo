"""Experiment D: live CARLA + AirSim with injected heartbeat loss.

Packet loss is emulated at the application heartbeat layer, NOT on AirSim RPC.
The drone executes a bounded hover recovery; no LLM is used.
"""
import argparse,csv,json,random,time,math
from pathlib import Path

def run(args):
    import carla,airsim
    from agentic_uav.comm.rf_model import RFPropagationModel
    from agentic_uav.core.models import Position3D
    if not (0<=args.loss<=1) or args.duration<=0 or args.hz<=0 or args.timeout<=0:
        raise ValueError("Invalid loss, duration, hz, or timeout")
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    rng=random.Random(args.seed)
    carla_client=carla.Client(args.carla_host,args.carla_port)
    carla_client.set_timeout(10)
    world=carla_client.get_world()
    previous=world.get_settings()
    air=None
    records=[];events=[]
    status="failed";failure=None
    last_heartbeat=None;first_loss=None;detection=None;recovery=None
    recovery_commanded=False
    try:
        settings=world.get_settings()
        settings.synchronous_mode=True
        settings.fixed_delta_seconds=1/args.hz
        world.apply_settings(settings)
        air=airsim.MultirotorClient()
        air.confirmConnection();air.enableApiControl(True);air.armDisarm(True)
        print("[D] Taking off...",flush=True)
        air.takeoffAsync().join()
        print("[D] Connected to CARLA and AirSim",flush=True)
        rf=RFPropagationModel(max_range_meters=args.rf_range)
        base=Position3D(0,0,0)
        period=1/args.hz
        next_tick=time.monotonic()
        start=next_tick
        ticks=math.ceil(args.duration*args.hz)
        for tick in range(ticks):
            # Wall-clock pacing avoids outrunning the independently timed AirSim backend.
            next_tick+=period
            time.sleep(max(0,next_tick-time.monotonic()))
            world.tick()
            state=air.getMultirotorState().kinematics_estimated.position
            pos=Position3D(state.x_val,state.y_val,state.z_val)
            elapsed=time.monotonic()-start
            injection_active=elapsed>=args.inject_at
            in_range=rf.is_connected(pos,base)
            dropped=injection_active and rng.random()<args.loss
            delivered=in_range and not dropped
            if delivered:
                last_heartbeat=elapsed
                first_loss=None
            elif first_loss is None:
                first_loss=elapsed
            heartbeat_age=elapsed-(last_heartbeat if last_heartbeat is not None else 0)
            trigger=args.recovery=="hover" and not recovery_commanded and heartbeat_age>args.timeout
            if trigger:
                detection=elapsed
                print(f"[D] Heartbeat timeout at {elapsed:.3f}s; hover recovery",flush=True)
                air.hoverAsync()
                recovery_commanded=True
                events.append({"event":"timeout_hover_command","elapsed_s":elapsed})
            if recovery_commanded and recovery is None:
                # A command being issued is not proof of a safe recovered state.
                vel=air.getMultirotorState().kinematics_estimated.linear_velocity
                speed=math.sqrt(vel.x_val**2+vel.y_val**2+vel.z_val**2)
                if speed<=args.safe_speed:
                    recovery=elapsed
                    events.append({"event":"low_speed_observed","elapsed_s":elapsed})
            violation=int(-pos.z>args.ceiling or -pos.z<0)
            records.append({"tick":tick,"wall_elapsed_s":elapsed,"carla_sim_elapsed_s":(tick+1)*period,
                            "x":pos.x,"y":pos.y,"z":pos.z,"rf_in_range":int(in_range),
                            "injected_drop":int(dropped),"heartbeat_delivered":int(delivered),
                            "heartbeat_age_s":heartbeat_age,"failsafe_active":int(recovery_commanded),
                            "altitude_violation":violation})
            if tick%args.log_every==0:
                print(f"[D] {tick}/{ticks} t={elapsed:.1f}s heartbeat={int(delivered)} recovery={recovery_commanded}",flush=True)
        status="completed"
    except Exception as e:
        failure=repr(e)
        raise
    finally:
        if records:
            with (out/"telemetry.csv").open("w",newline="") as f:
                w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
        summary={"status":status,"error":failure,"scenario":"live_carla_airsim_heartbeat_fault",
                 "seed":args.seed,"configured_loss_probability":args.loss,
                 "recovery_mode":args.recovery,"samples":len(records),
                 "heartbeat_delivered":sum(r["heartbeat_delivered"] for r in records),
                 "injected_drops":sum(r["injected_drop"] for r in records),
                 "altitude_violation_samples":sum(r["altitude_violation"] for r in records),
                 "first_undelivered_heartbeat_s":next((r["wall_elapsed_s"] for r in records if not r["heartbeat_delivered"]),None),
                 "failsafe_detection_s":detection,"recovery_observed_s":recovery,
                 "recovery_time_from_detection_s":recovery-detection if recovery is not None and detection is not None else None,
                 "events":events,
                 "limitations":["Injected loss affects application-level heartbeat only; CARLA and AirSim RPC remain available",
                                "Hover command is not the existing FailSafeManager RETURN_HOME/LAND policy",
                                "Low speed is only a partial recovery criterion, not full safety verification",
                                "No LLM planning or real RF packet injection",
                                "CARLA and AirSim clocks are not synchronized"]}
        (out/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
        if air is not None:
            try:
                print("[D] Landing...",flush=True)
                air.hoverAsync().join()
                air.landAsync().join()
                air.armDisarm(False);air.enableApiControl(False)
            except Exception as e:print("[D] Cleanup warning:",repr(e),flush=True)
        try:world.apply_settings(previous)
        except Exception as e:print("[D] CARLA restore warning:",repr(e),flush=True)
    print(json.dumps(summary,indent=2))

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--output-dir",required=True)
    p.add_argument("--loss",type=float,default=0.5,help="Heartbeat drop probability after injection")
    p.add_argument("--inject-at",type=float,default=3.)
    p.add_argument("--duration",type=float,default=15.)
    p.add_argument("--timeout",type=float,default=2.)
    p.add_argument("--hz",type=float,default=10.)
    p.add_argument("--rf-range",type=float,default=60.)
    p.add_argument("--ceiling",type=float,default=30.)
    p.add_argument("--safe-speed",type=float,default=0.25)
    p.add_argument("--seed",type=int,default=42)
    p.add_argument("--log-every",type=int,default=10)
    p.add_argument("--recovery",choices=["hover","none"],default="hover")
    p.add_argument("--carla-host",default="localhost")
    p.add_argument("--carla-port",type=int,default=2000)
    a=p.parse_args()
    if a.inject_at<0 or a.log_every<1 or a.rf_range<=0:p.error("Invalid parameter")
    run(a)
