import json
import re
import ollama
from typing import List
from agentic_uav.core.models import SkillCommand, Position3D, SearchRegion

class LlamaMissionPlanner:
    def __init__(self, model_name: str = "llama3.1:latest"):
        self.model_name = model_name
        self.system_prompt = (
            "You are an autonomous UAV mission planner. Translate instructions into a JSON list of skill commands.\n"
            "Supported skills:\n"
            "- TAKE_OFF (vehicle_id)\n"
            "- GO_TO_WAYPOINT (vehicle_id, target: [x, y, z])\n"
            "- SEARCH_REGION (vehicle_id, region: [min_x, max_x, min_y, max_y, altitude])\n"
            "- HOLD_POSITION (vehicle_id, duration_seconds)\n"
            "- ACT_AS_RELAY (vehicle_id, target: [x, y, z], duration_seconds)\n"
            "- RETURN_HOME (vehicle_id)\n"
            "- LAND (vehicle_id)\n\n"
            "Output JSON format strictly:\n"
            "[\n"
            "  {\"skill_name\": \"SEARCH_REGION\", \"vehicle_id\": \"Drone1\", \"region\": [0, 20, 0, 20, -10]},\n"
            "  {\"skill_name\": \"ACT_AS_RELAY\", \"vehicle_id\": \"Drone2\", \"target\": [10, 10, -15], \"duration_seconds\": 10}\n"
            "]"
        )

    def plan(self, user_instruction: str) -> List[SkillCommand]:
        response = ollama.chat(
            model=self.model_name,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_instruction},
            ],
        )
        raw_output = response["message"]["content"].strip()
        cleaned = re.sub(r'```(?:json)?\s*(.*?)\s*```', r'\1', raw_output, flags=re.DOTALL).strip()
        parsed_skills = json.loads(cleaned)

        commands = []
        for item in parsed_skills:
            skill_name = item["skill_name"]
            vehicle_id = item["vehicle_id"]
            
            target_pos = None
            if "target" in item and item["target"]:
                t = item["target"]
                target_pos = Position3D(x=float(t[0]), y=float(t[1]), z=float(t[2]))

            search_reg = None
            if "region" in item and item["region"]:
                r = item["region"]
                search_reg = SearchRegion(
                    min_x=float(r[0]), max_x=float(r[1]),
                    min_y=float(r[2]), max_y=float(r[3]),
                    altitude=float(r[4]) if len(r) > 4 else -10.0
                )

            duration = float(item.get("duration_seconds", 0.0))

            commands.append(
                SkillCommand(
                    skill_name=skill_name,
                    vehicle_id=vehicle_id,
                    target_position=target_pos,
                    search_region=search_reg,
                    duration_seconds=duration
                )
            )
        return commands
