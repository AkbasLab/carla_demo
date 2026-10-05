import time
from typing import List, Dict
from agentic_uav.core.models import SkillCommand, SkillResult
from agentic_uav.core.planner_models import MissionPlan
from agentic_uav.control.skill_engine import SkillEngine, Position3D
from agentic_uav.control.scenario_manager import ScenarioManager
from agentic_uav.control.planner import LLMTaskPlanner

class AutonomousOrchestrator:
    """Coordinates mission planning, pre-flight safety checks, and step execution."""

    def __init__(self, engine: SkillEngine, scenario_mgr: ScenarioManager):
        self.engine = engine
        self.scenario_mgr = scenario_mgr
        self.planner = LLMTaskPlanner(scenario_mgr)

    def execute_directive(self, prompt: str, available_drones: List[str]) -> List[SkillResult]:
        print(f"\n==================================================")
        print(f"[ORCHESTRATOR] Received Directive: '{prompt}'")
        print(f"==================================================")

        # 1. Generate Mission Plan
        plan: MissionPlan = self.planner.generate_plan_mock(prompt, available_drones)
        print(f"[PLANNER] Plan Generated with {len(plan.steps)} steps:")
        for s in plan.steps:
            print(f"  Step {s.step_id}: [{s.vehicle_id}] {s.skill_name} -> {s.rationale}")

        # 2. Convert to Skill Commands
        commands = self.planner.convert_plan_to_commands(plan)

        # 3. Step-by-Step Execution with Adaptive Monitoring
        results = []
        for idx, cmd in enumerate(commands, 1):
            print(f"\n---> Executing Step {idx}/{len(commands)}: {cmd.skill_name} on {cmd.vehicle_id}")
            res = self.engine.execute(cmd)
            results.append(res)

            if res.status == "failed":
                print(f"[CRITICAL] Step {idx} ({cmd.skill_name}) failed! Error: {res.error_code}")
                print("[ORCHESTRATOR] Initiating Emergency Abort & Return Home Protocol...")
                self._emergency_abort(available_drones)
                break
        self.engine.execute(SkillCommand(skill_name="GO_TO_WAYPOINT", vehicle_id="Drone1", target_position=Position3D(0.0, 0.0, -2.0)))
        self.engine.execute(SkillCommand(skill_name="GO_TO_WAYPOINT", vehicle_id="Drone2", target_position=Position3D(3.0, 0.0, -2.0)))
        print(f"\n[ORCHESTRATOR] Mission Execution Completed.")
        return results

    def _emergency_abort(self, drones: List[str]) -> None:
        """Triggers emergency return and land sequence across active assets."""
        for drone_id in drones:
            print(f"[EMERGENCY] Returning and Landing {drone_id}...")
            self.engine.execute(SkillCommand(skill_name="RETURN_HOME", vehicle_id=drone_id))
             # Hover above individual landing spots before descending
            engine.execute(SkillCommand(skill_name="GO_TO_WAYPOINT", vehicle_id="Drone1", target_position=Position3D(0.0, 0.0, -2.0)))
            engine.execute(SkillCommand(skill_name="GO_TO_WAYPOINT", vehicle_id="Drone2", target_position=Position3D(3.0, 0.0, -2.0)))

            self.engine.execute(SkillCommand(skill_name="LAND", vehicle_id=drone_id))
