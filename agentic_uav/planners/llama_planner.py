import json
import re
import ollama
from typing import List
from agentic_uav.core.models import SkillCommand, Position3D

class LlamaMissionPlanner:
    def __init__(self, model_name: str = "llama3.1:latest"):
        self.model_name = model_name
        self.system_prompt = (
            "You are a dual-drone flight controller for 'Drone1' and 'Drone2'. "
            "Parse user instructions into target coordinates x, y, and z (meters, AirSim NED frame). "
            "Respond ONLY with a valid JSON array of objects with keys: "
            "\"drone\" (string: 'Drone1' or 'Drone2'), \"x\" (float), \"y\" (float), \"z\" (float)."
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
        parsed_targets = json.loads(cleaned)

        commands = []
        for item in parsed_targets:
            commands.append(
                SkillCommand(
                    skill_name="GO_TO_WAYPOINT",
                    vehicle_id=item["drone"],
                    target_position=Position3D(
                        x=float(item["x"]), y=float(item["y"]), z=float(item["z"])
                    )
                )
            )
        return commands
