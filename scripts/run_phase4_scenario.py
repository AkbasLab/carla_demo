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
from agentic_uav.control.scenario_manager import ScenarioManager
from agentic_uav.control.skill_engine import SkillEngine
from agentic_uav.core.models import SkillCommand, Position3D

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--airsim", action="store_true", help="Run in CARLA/AirSim simulation")
    args = parser.parse_args()

    # Load Phase 4 scenario config
    scenario_mgr = ScenarioManager("configs/missions/search_and_relay.json")
    adapter = AirSimAdapter() if args.airsim else MockVehicleAdapter()
    adapter.connect()
    
    engine = SkillEngine(adapter, scenario_mgr)

    print("=== Launching Phase 4 Search-and-Relay Mission ===")

    # 1. Takeoff both drones
    engine.execute(SkillCommand(skill_name="TAKE_OFF", vehicle_id="Drone1"))
    engine.execute(SkillCommand(skill_name="TAKE_OFF", vehicle_id="Drone2"))

    # 2. Drone1 searches Sector NE (Contains Survivor_Alpha at 35, 25)
    sector_ne = scenario_mgr.sectors["Sector_NE"]
    print("\n--- Drone1 Executing SEARCH_REGION in Sector_NE ---")
    res1 = engine.execute(
        SkillCommand(
            skill_name="SEARCH_REGION",
            vehicle_id="Drone1",
            search_region=sector_ne,
            params={"grid_step": 15.0}
        )
    )

    # 3. Drone2 establishes relay position for search ops
    print("\n--- Drone2 Positioned as Comm Relay ---")
    res2 = engine.execute(
        SkillCommand(
            skill_name="ACT_AS_RELAY",
            vehicle_id="Drone2",
            target_position=scenario_mgr.base_station,
            duration_seconds=2.0
        )
    )

    # 4. Return & Land
    engine.execute(SkillCommand(skill_name="RETURN_HOME", vehicle_id="Drone1"))
    engine.execute(SkillCommand(skill_name="RETURN_HOME", vehicle_id="Drone2"))
    # Hover above individual landing spots before descending
    engine.execute(SkillCommand(skill_name="LAND", vehicle_id="Drone1"))
    engine.execute(SkillCommand(skill_name="LAND", vehicle_id="Drone2"))

    # Report results
    print("\n=== Scenario Mission Results ===")
    print(f"Total Targets Acquired: {len(scenario_mgr.detection_history)}/{len(scenario_mgr.targets)}")
    for event in scenario_mgr.detection_history:
        print(f" -> Target '{event.target_id}' acquired by '{event.vehicle_id}' at distance {event.distance}m")

if __name__ == "__main__":
    main()
