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
from agentic_uav.control.orchestrator import AutonomousOrchestrator

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--airsim", action="store_true", help="Run in CARLA/AirSim simulation")
    args = parser.parse_args()

    # Load scenario and adapters
    scenario_mgr = ScenarioManager("configs/missions/search_and_relay.json")
    adapter = AirSimAdapter() if args.airsim else MockVehicleAdapter()
    adapter.connect()

    engine = SkillEngine(adapter, scenario_mgr)
    orchestrator = AutonomousOrchestrator(engine, scenario_mgr)

    # Directive 1: Natural Language Directive
    user_prompt = "Search Sector NE for survivors using Drone1 and position Drone2 as a communication relay"
    drones = ["Drone1", "Drone2"]

    results = orchestrator.execute_directive(user_prompt, drones)

    # Mission Summary Report
    print("\n==================================================")
    print("           MISSION SUMMARY REPORT                 ")
    print("==================================================")
    print(f"Total Directives Executed: 1")
    print(f"Total Commands Triggered:  {len(results)}")
    print(f"Targets Discovered:        {len(scenario_mgr.detection_history)}/{len(scenario_mgr.targets)}")
    for det in scenario_mgr.detection_history:
        print(f" - [{det.target_id}] Spotted by {det.vehicle_id} at dist {det.distance}m")
    print("==================================================")

if __name__ == "__main__":
    main()
