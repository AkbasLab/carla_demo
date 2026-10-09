import argparse
import sys
from pathlib import Path

# Add project root directory to python path
FILE = Path(__file__).resolve()
ROOT = FILE.parents[1]  # Parent directory containing the 'scripts' folder
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))


from agentic_uav.simulator.airsim_adapter import AirSimAdapter
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.comm.bus import CommBus
from agentic_uav.control.scenario_manager import ScenarioManager
from agentic_uav.control.skill_engine import SkillEngine
from agentic_uav.control.reactive_relay import ReactiveRelayAgent
from agentic_uav.core.models import SkillCommand, Position3D

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--airsim", action="store_true", help="Run in CARLA/AirSim simulation")
    args = parser.parse_args()

    # Setup Inter-Drone Network
    comm_bus = CommBus()
    scenario_mgr = ScenarioManager("configs/missions/search_and_relay_phase6.json", comm_bus=comm_bus)
    adapter = AirSimAdapter() if args.airsim else MockVehicleAdapter()
    adapter.connect()

    engine = SkillEngine(adapter, scenario_mgr)
    drones = ["Drone1", "Drone2"] # vehicle tracking list

    # Initialize Reactive Agent on Drone2
    relay_agent = ReactiveRelayAgent(
        vehicle_id="Drone2",
        comm_bus=comm_bus,
        engine=engine,
        base_station_pos=scenario_mgr.base_station
    )

    print("=== Phase 6: Decentralized Multi-Agent Mesh Simulation ===")

    # 1. Takeoff both drones
    engine.execute(SkillCommand(skill_name="TAKE_OFF", vehicle_id="Drone1"))
    engine.execute(SkillCommand(skill_name="TAKE_OFF", vehicle_id="Drone2"))
    print_live_telemetry(adapter,drones) # print coordinates after takeoff

    # Drone2 initially sits on standby near Base Station
    engine.execute(SkillCommand(
        skill_name="HOLD_POSITION", 
        vehicle_id="Drone2", 
        target_position=Position3D(0.0, 0.0, -10.0), 
        duration_seconds=1.0
    ))

    # 2. Drone1 begins search in Sector NE
    print("\n--- Drone1 sweeping Sector NE ---")
    sector_ne = scenario_mgr.sectors["Sector_NE"]
    engine.execute(SkillCommand(
        skill_name="SEARCH_REGION",
        vehicle_id="Drone1",
        search_region=sector_ne,
        params={"grid_step": 15.0}
    ))

    # 3. Clean Landings
    print("\n--- Mission Complete: Landing Assets ---")
    engine.execute(SkillCommand(skill_name="GO_TO_WAYPOINT", vehicle_id="Drone1", target_position=Position3D(0.0, 0.0, -2.0)))
    print_live_telemetry(adapter, drones) # print Drone1 waypoint position
    engine.execute(SkillCommand(skill_name="GO_TO_WAYPOINT", vehicle_id="Drone2", target_position=Position3D(3.0, 0.0, -2.0)))
    print_live_telemetry(adapter, drones) # print Drone2 waypoint position
    engine.execute(SkillCommand(skill_name="LAND", vehicle_id="Drone1"))
    engine.execute(SkillCommand(skill_name="LAND", vehicle_id="Drone2"))

    print_live_telemetry(adapter, drones) # final ground position

    print(f"\nTotal Inter-Drone Network Packets: {len(comm_bus.message_history)}")
    print(f"Reactive Relay Autonomous Repositioning Executed: {relay_agent.is_relaying}")


def print_live_telemetry(adapter, drones):
    """Helper function to print live 3D coordinates of all active drones."""
    coords_str = []
    for d_id in drones:
        state = adapter.get_state(d_id)
        pos = state.position
        coords_str.append(f"{d_id}: (x={pos.x:.2f}, y={pos.y:.2f}, z={pos.z:.2f}")
    print(f"[LIVE POSITIONS] | {'|'.join(coords_str)}")

if __name__ == "__main__":
    main()
