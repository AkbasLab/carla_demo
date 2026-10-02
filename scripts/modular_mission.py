import argparse
from agentic_uav.simulator.airsim_adapter import AirSimAdapter
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.planners.llama_planner import LlamaMissionPlanner

DRONES = ["Drone1", "Drone2"]

def run_mission(use_airsim: bool = False):
    # Select adapter implementation
    adapter = AirSimAdapter() if use_airsim else MockVehicleAdapter()
    planner = LlamaMissionPlanner()

    print(f"--- Running Mission using {'AirSim' if use_airsim else 'Mock Adapter'} ---")
    adapter.connect()

    for d in DRONES:
        adapter.enable_control(d)
        adapter.takeoff(d)

    instruction = "Move Drone1 to 10, 5, -5 and Drone2 to -5, 10, -8"
    print(f"\nUser Instruction: '{instruction}'")

    # Generate skills using MissionPlanner
    commands = planner.plan(instruction)

    # Execute skills via VehicleAdapter
    for cmd in commands:
        print(f"Executing command for {cmd.vehicle_id} -> Position ({cmd.target_position.x}, {cmd.target_position.y}, {cmd.target_position.z})")
        res = adapter.move_to_position(cmd.vehicle_id, cmd)
        print(f"Result: {res.status} | Final Pos: {res.final_position}")

    for d in DRONES:
        adapter.land(d)

    print("\nMission finished successfully!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--airsim", action="store_true", help="Run with AirSim instead of Mock Adapter")
    args = parser.parse_args()
    
    run_mission(use_airsim=args.airsim)
