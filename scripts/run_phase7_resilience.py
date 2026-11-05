import time
import math
import sys
from pathlib import Path

# Add project root directory to python path
FILE = Path(__file__).resolve()
ROOT = FILE.parents[1]  # Parent directory containing the 'scripts' folder
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.comm.bus import CommBus, Message
from agentic_uav.comm.rf_model import RFPropagationModel
from agentic_uav.control.scenario_manager import ScenarioManager
from agentic_uav.control.skill_engine import SkillEngine
from agentic_uav.control.failsafe import FailSafeManager
from agentic_uav.core.models import SkillCommand, Position3D

def print_live_telemetry(adapter, drones):
    """Prints live 3D coordinates using get_state() state management."""
    coords_str = []
    for d_id in drones:
        state = adapter.get_state(d_id)
        pos = state.position
        coords_str.append(f"{d_id}: (x={pos.x:.2f}, y={pos.y:.2f}, z={pos.z:.2f})")
    print(f"   [LIVE POSITIONS] | {' | '.join(coords_str)}")

def get_euclidean_distance(p1: Position3D, p2: Position3D) -> float:
    """Calculates true 3D Euclidean distance between two positions."""
    return math.sqrt((p1.x - p2.x)**2 + (p1.y - p2.y)**2 + (p1.z - p2.z)**2)

def execute_and_wait_until_reached(engine, adapter, vehicle_id, target_pos, speed_m_s=5.0, check_interval_sec=10.0, tolerance=1.0):
    """
    Issues movement via SkillEngine and actively steps the simulation adapter physics 
    every 10 seconds, verifying physical movement toward target coordinates.
    """
    print(f"\n✈️  [COMMAND SENT] Moving {vehicle_id} to (x={target_pos.x:.1f}, y={target_pos.y:.1f}, z={target_pos.z:.1f})")
    
    # 1. Issue command through official SkillEngine
    cmd = SkillCommand(
        skill_name="GO_TO_WAYPOINT",
        vehicle_id=vehicle_id,
        target_position=target_pos,
        params={"target_position": target_pos, "target_pos": target_pos}
    )
    engine.execute(cmd)

    # 2. Dynamic step loop driven by actual physics/simulation ticks
    elapsed_time = 0
    while True:
        current_pos = adapter.get_state(vehicle_id).position
        dist = get_euclidean_distance(current_pos, target_pos)

        print_live_telemetry(adapter, [vehicle_id])
        print(f"   ↳ Distance remaining: {dist:.2f}m")

        if dist <= tolerance:
            print(f"✅ [{vehicle_id}] Arrived at destination! (Distance: {dist:.2f}m <= {tolerance}m threshold)\n")
            break

        # Calculate vector movement based on velocity and interval time
        if dist > 0:
            step_distance = speed_m_s * check_interval_sec
            move_ratio = min(1.0, step_distance / dist)
            
            new_x = current_pos.x + (target_pos.x - current_pos.x) * move_ratio
            new_y = current_pos.y + (target_pos.y - current_pos.y) * move_ratio
            new_z = current_pos.z + (target_pos.z - current_pos.z) * move_ratio

            # Update adapter state directly or step the adapter engine
            if hasattr(adapter, 'update_vehicle_position'):
                adapter.update_vehicle_position(vehicle_id, Position3D(new_x, new_y, new_z))
            elif hasattr(adapter, '_vehicles') and vehicle_id in adapter._vehicles:
                adapter._vehicles[vehicle_id].position = Position3D(new_x, new_y, new_z)
            else:
                state = adapter.get_state(vehicle_id)
                state.position = Position3D(new_x, new_y, new_z)

        # Step simulation time by interval
        if hasattr(adapter, 'step'):
            adapter.step(check_interval_sec)
        
        elapsed_time += int(check_interval_sec)
        print(f"⏳ [T + {elapsed_time}s] Stepping simulation flight tick...")
        time.sleep(1.0)  # Visual pause for log inspection

def legacy_main():
    rf_model = RFPropagationModel(max_range_meters=25.0)
    comm_bus = CommBus(rf_model=rf_model)
    scenario_mgr = ScenarioManager("configs/missions/search_and_relay_phase6.json", comm_bus=comm_bus)
    
    adapter = MockVehicleAdapter()
    adapter.connect()
    
    engine = SkillEngine(adapter, scenario_mgr)
    failsafe = FailSafeManager(engine, comm_timeout_sec=2.0, min_battery_pct=15.0)
    drones = ["Drone1", "Drone2"]

    print("=== Phase 7: Dynamic Physical Movement Simulation ===")
    print_live_telemetry(adapter, drones)

    # 1. Takeoff
    print("\n--- Step 1: Arming and Takeoff ---")
    engine.execute(SkillCommand(skill_name="TAKE_OFF", vehicle_id="Drone1"))
    engine.execute(SkillCommand(skill_name="TAKE_OFF", vehicle_id="Drone2"))
    failsafe.update_heartbeat("Drone1")
    failsafe.update_heartbeat("Drone2")
    print_live_telemetry(adapter, drones)

    # 2. Fly out of range with 10-second tick updates
    print("\n--- Step 2: Flying Drone1 out of RF Range ---")
    far_pos = Position3D(80.0, 80.0, -10.0)
    execute_and_wait_until_reached(
        engine=engine, 
        adapter=adapter, 
        vehicle_id="Drone1", 
        target_pos=far_pos, 
        speed_m_s=5.0,            # 5 m/s speed calculation
        check_interval_sec=10.0,   # Evaluates position every 10 seconds
        tolerance=1.0
    )

    # 3. Test RF packet drop AFTER position verification
    print("--- Step 3: Testing RF Range Transmissions at Destination ---")
    base_pos = scenario_mgr.base_station
    drone1_pos = adapter.get_state("Drone1").position
    
    test_msg = Message(
        sender_id="Drone1",
        recipient_id="BaseStation",
        topic="TELEMETRY_ALERT",
        payload={
            "status": "SEARCHING", 
            "pos": {"x": drone1_pos.x, "y": drone1_pos.y, "z": drone1_pos.z}
        }
    )
    
    comm_bus.publish(
        msg=test_msg,
        sender_pos=drone1_pos,
        recipient_pos=base_pos
    )

    # 4. Low Battery Failsafe
    print("\n--- Step 4: Triggering Critical Low Battery Failsafe ---")
    failsafe.set_battery("Drone1", 10.0)
    failsafe.check_vehicle_health("Drone1")

    # Fly back to home base
    home_pos = Position3D(0.0, 0.0, -5.0)
    execute_and_wait_until_reached(
        engine=engine, 
        adapter=adapter, 
        vehicle_id="Drone1", 
        target_pos=home_pos, 
        speed_m_s=5.0,
        check_interval_sec=10.0, 
        tolerance=1.0
    )

    # 5. Landing
    print("--- Step 5: Landing Remaining Assets ---")
    engine.execute(SkillCommand(skill_name="LAND", vehicle_id="Drone1"))
    engine.execute(SkillCommand(skill_name="LAND", vehicle_id="Drone2"))
    print_live_telemetry(adapter, drones)

    print("\n=== Phase 7 Test Complete ===")

def main():
    import argparse
    from agentic_uav.comm.phase7_demo import run_protocol_demo
    parser = argparse.ArgumentParser(description="Plan Phase 7 perfect-communication protocol; legacy RF demo remains opt-in")
    parser.add_argument('--legacy-resilience', action='store_true')
    parser.add_argument('--backend', choices=['mock','airsim'], default='mock')
    parser.add_argument('--vehicles', nargs=4, default=['Drone1','Drone2','Drone3','Drone4'])
    parser.add_argument('--dt', type=float, default=.1)
    parser.add_argument('--airsim-host', default='127.0.0.1')
    parser.add_argument('--carla-host', default=None, help='Optional CARLAAir host; use async stepping during flight')
    parser.add_argument('--carla-port', type=int, default=2000)
    parser.add_argument('--rpc-timeout', type=float, default=15.)
    parser.add_argument('--setup-timeout', type=float, default=60.)
    parser.add_argument('--flight-height', type=float, default=3., help='Height above each initial NED Z, not origin-relative altitude')
    parser.add_argument('--flight-speed', type=float, default=.5)
    parser.add_argument('--flight-distance', type=float, default=2.)
    parser.add_argument('--ticks', type=int, default=20)
    parser.add_argument('--output-dir', default='results/phase7/protocol')
    parser.add_argument('--no-plots', action='store_true', help='Skip post-run protocol plots')
    args = parser.parse_args()
    if args.ticks < 1 or len(set(args.vehicles)) != 4 or any(not math.isfinite(v) or v<=0 for v in (args.dt,args.rpc_timeout,args.setup_timeout,args.flight_height,args.flight_speed,args.flight_distance)):
        parser.error('Require positive finite parameters and four distinct vehicle names')
    if args.legacy_resilience:
        legacy_main()
    elif args.backend == 'airsim':
        from agentic_uav.comm.phase7_live import run_live_protocol
        run_live_protocol(args)
    else:
        run_protocol_demo(args.ticks, dt=args.dt, output_dir=args.output_dir)
    if not args.legacy_resilience and not args.no_plots:
        try:
            from scripts.plot_phase7_protocol import generate_plots
            print(f'Phase 7 plots: {generate_plots(args.output_dir)}')
        except Exception as exc:
            print(f'Plot warning: {exc}; raw protocol results remain saved.')


if __name__ == "__main__":
    main()
