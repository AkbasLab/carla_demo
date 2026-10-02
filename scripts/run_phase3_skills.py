import argparse
from agentic_uav.simulator.airsim_adapter import AirSimAdapter
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.control.skill_engine import SkillEngine
from agentic_uav.core.models import SkillCommand, Position3D, SearchRegion

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--airsim", action="store_true", help="Run in AirSim/CARLA")
    args = parser.parse_args()

    adapter = AirSimAdapter() if args.airsim else MockVehicleAdapter()
    adapter.connect()
    engine = SkillEngine(adapter)

    vehicle_id = "Drone1"
    print(f"--- Running Phase 3 Skill Suite on [{vehicle_id}] ---")

    skills_to_test = [
        SkillCommand(skill_name="TAKE_OFF", vehicle_id=vehicle_id),
        SkillCommand(skill_name="GO_TO_WAYPOINT", vehicle_id=vehicle_id, target_position=Position3D(10, 10, -10)),
        SkillCommand(
            skill_name="SEARCH_REGION", 
            vehicle_id=vehicle_id, 
            search_region=SearchRegion(min_x=10, max_x=30, min_y=10, max_y=30, altitude=-10),
            params={"grid_step": 10.0}
        ),
        SkillCommand(skill_name="HOLD_POSITION", vehicle_id=vehicle_id, duration_seconds=2.0),
        SkillCommand(skill_name="ACT_AS_RELAY", vehicle_id=vehicle_id, target_position=Position3D(20, 20, -15), duration_seconds=3.0),
        SkillCommand(skill_name="RETURN_HOME", vehicle_id=vehicle_id),
        SkillCommand(skill_name="LAND", vehicle_id=vehicle_id)
    ]

    for cmd in skills_to_test:
        print(f"\n[Executing]: {cmd.skill_name}")
        result = engine.execute(cmd)
        print(f" Contract Return: Status='{result.status}' | Time={round(result.ended_at - result.started_at, 2)}s | Pos=({result.final_position.x:.1f}, {result.final_position.y:.1f}, {result.final_position.z:.1f})")
        if result.error_code:
            print(f" Error: {result.error_code}")

if __name__ == "__main__":
    main()
