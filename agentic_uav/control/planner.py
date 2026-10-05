import json
import re
from typing import List, Dict, Any, Optional
from agentic_uav.core.models import SkillCommand, Position3D, SearchRegion
from agentic_uav.core.planner_models import HighLevelGoal, PlanStep, MissionPlan
from agentic_uav.control.scenario_manager import ScenarioManager

SYSTEM_PROMPT = """You are an Autonomous UAV Mission Planner.
Your goal is to parse high-level commander directives into executable UAV skill steps.

Available Skills:
1. TAKE_OFF (vehicle_id)
2. GO_TO_WAYPOINT (vehicle_id, target_position: {x, y, z}, velocity)
3. SEARCH_REGION (vehicle_id, sector_id, grid_step)
4. HOLD_POSITION (vehicle_id, target_position: {x,y,z}, duration_seconds)
5. ACT_AS_RELAY (vehicle_id, target_position: {x,y,z}, duration_seconds)
6. RETURN_HOME (vehicle_id)
7. LAND (vehicle_id)

Respond EXCLUSIVELY in valid JSON following this schema:
{
  "goal": "<string>",
  "steps": [
    {
      "step_id": 1,
      "vehicle_id": "Drone1",
      "skill_name": "TAKE_OFF",
      "parameters": {},
      "rationale": "<explanation>"
    }
  ]
}
"""

class LLMTaskPlanner:
    """Decomposes natural language prompts into executable SkillCommand pipelines."""

    def __init__(self, scenario_mgr: ScenarioManager):
        self.scenario_mgr = scenario_mgr

    def generate_plan_mock(self, prompt: str, available_drones: List[str]) -> MissionPlan:
        """Deterministic fallback planner for offline/rule-based execution."""
        prompt_lower = prompt.lower()
        steps: List[PlanStep] = []
        step_idx = 1

        d1 = available_drones[0] if len(available_drones) > 0 else "Drone1"
        d2 = available_drones[1] if len(available_drones) > 1 else "Drone2"

        # 1. Arm and Takeoff
        steps.append(PlanStep(step_idx, d1, "TAKE_OFF", {}, "Arm and ascend search drone")); step_idx += 1
        if "relay" in prompt_lower or len(available_drones) > 1:
            steps.append(PlanStep(step_idx, d2, "TAKE_OFF", {}, "Arm and ascend relay drone")); step_idx += 1

        # 2. Match sectors
        if "sector_ne" in prompt_lower or "ne" in prompt_lower:
            steps.append(PlanStep(step_idx, d1, "SEARCH_REGION", {"sector_id": "Sector_NE", "grid_step": 15.0}, "Search Sector NE")); step_idx += 1
        elif "sector_nw" in prompt_lower or "nw" in prompt_lower:
            steps.append(PlanStep(step_idx, d1, "SEARCH_REGION", {"sector_id": "Sector_NW", "grid_step": 15.0}, "Search Sector NW")); step_idx += 1
        else:
            steps.append(PlanStep(step_idx, d1, "SEARCH_REGION", {"sector_id": "Sector_NE", "grid_step": 15.0}, "Default sector search")); step_idx += 1

        # 3. Relay assignment
        if "relay" in prompt_lower:
            base_pos = self.scenario_mgr.base_station
            steps.append(PlanStep(step_idx, d2, "ACT_AS_RELAY", {
                "target_position": {"x": base_pos.x, "y": base_pos.y, "z": -10.0},
                "duration_seconds": 5.0
            }, "Position relay drone above base station")); step_idx += 1

        # 4. Return and Land
        steps.append(PlanStep(step_idx, d1, "RETURN_HOME", {}, "Return search drone")); step_idx += 1
        steps.append(PlanStep(step_idx, d1, "LAND", {}, "Land search drone")); step_idx += 1

        if "relay" in prompt_lower or len(available_drones) > 1:
            steps.append(PlanStep(step_idx, d2, "RETURN_HOME", {}, "Return relay drone")); step_idx += 1
            steps.append(PlanStep(step_idx, d2, "LAND", {}, "Land relay drone")); step_idx += 1

        return MissionPlan(goal=prompt, steps=steps)

    def convert_plan_to_commands(self, plan: MissionPlan) -> List[SkillCommand]:
        """Converts abstract plan steps into concrete executable SkillCommands."""
        commands = []
        for step in plan.steps:
            params = step.parameters
            target_pos = None
            if "target_position" in params:
                tp = params["target_position"]
                target_pos = Position3D(tp["x"], tp["y"], tp["z"])

            search_reg = None
            if "sector_id" in params and params["sector_id"] in self.scenario_mgr.sectors:
                search_reg = self.scenario_mgr.sectors[params["sector_id"]]

            cmd = SkillCommand(
                skill_name=step.skill_name,
                vehicle_id=step.vehicle_id,
                target_position=target_pos,
                search_region=search_reg,
                duration_seconds=params.get("duration_seconds", 0.0),
                params=params
            )
            commands.append(cmd)
        return commands
