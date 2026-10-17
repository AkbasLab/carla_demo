"""OpenAI-planned Phase 3 UAV skills. Default is mock + plan-only.

pip install openai
export OPENAI_API_KEY='...'
python scripts/run_phase3_skills_openai.py
python scripts/run_phase3_skills_openai.py --execute
python scripts/run_phase3_skills_openai.py --airsim --execute
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openai import OpenAI
from agentic_uav.simulator.airsim_adapter import AirSimAdapter
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.control.skill_engine import SkillEngine
from agentic_uav.core.models import SkillCommand, Position3D, SearchRegion

ALLOWED = {"TAKE_OFF", "GO_TO_WAYPOINT", "SEARCH_REGION", "HOLD_POSITION", "ACT_AS_RELAY", "RETURN_HOME", "LAND"}
DEFAULT_MISSION = ("Take off, fly to (10, 10, -10), search the region x=10..30 and "
                   "y=10..30 at altitude -10 using a grid step of 10, hold for 2 seconds, "
                   "act as a relay at (20, 20, -15) for 3 seconds, return home, and land.")

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"steps": {"type": "array", "minItems": 1, "maxItems": 20,
        "items": {"type": "object", "additionalProperties": False,
            "properties": {
                "skill_name": {"type": "string", "enum": sorted(ALLOWED)},
                "target_position": {"anyOf": [
                    {"type": "object", "additionalProperties": False,
                     "properties": {k: {"type": "number"} for k in ("x", "y", "z")},
                     "required": ["x", "y", "z"]}, {"type": "null"}]},
                "search_region": {"anyOf": [
                    {"type": "object", "additionalProperties": False,
                     "properties": {k: {"type": "number"} for k in ("min_x", "max_x", "min_y", "max_y", "altitude")},
                     "required": ["min_x", "max_x", "min_y", "max_y", "altitude"]}, {"type": "null"}]},
                "duration_seconds": {"type": "number"},
                "velocity": {"type": "number"},
                "grid_step": {"type": "number"}
            },
            "required": ["skill_name", "target_position", "search_region", "duration_seconds", "velocity", "grid_step"]
        }}}, "required": ["steps"]
}

def plan(client, model, mission):
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": (
                "Translate the user's simulated UAV mission into an ordered list of supported skills. "
                "Do not invent coordinates, regions, durations or capabilities. "
                "Coordinates use AirSim NED (negative z is above ground). "
                "Use null for unused position/region, 0 for unused duration, "
                "5 for default velocity, 10 for default grid_step. "
                "Include TAKE_OFF before flight, and RETURN_HOME then LAND when requested. "
                "Only return steps that are explicitly supported by the request.")},
            {"role": "user", "content": mission}
        ],
        response_format={"type": "json_schema", "json_schema": {"name": "uav_skill_plan", "strict": True, "schema": SCHEMA}},
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("OpenAI returned an empty plan")
    return json.loads(content)["steps"]

def to_commands(steps, vehicle_id):
    commands = []
    for i, step in enumerate(steps, 1):
        name = step["skill_name"]
        if name not in ALLOWED:
            raise ValueError(f"Step {i}: unsupported skill {name}")
        pos, region = step["target_position"], step["search_region"]
        duration, velocity, grid_step = step["duration_seconds"], step["velocity"], step["grid_step"]
        if name in {"GO_TO_WAYPOINT", "ACT_AS_RELAY"} and pos is None:
            raise ValueError(f"Step {i}: {name} requires target_position")
        if name == "SEARCH_REGION":
            if region is None or region["min_x"] > region["max_x"] or region["min_y"] > region["max_y"]:
                raise ValueError(f"Step {i}: invalid search region")
            if grid_step <= 0:
                raise ValueError(f"Step {i}: grid_step must be positive")
        if velocity <= 0 or duration < 0 or duration > 300:
            raise ValueError(f"Step {i}: invalid velocity/duration")
        if name in {"HOLD_POSITION", "ACT_AS_RELAY"} and duration <= 0:
            raise ValueError(f"Step {i}: duration must be positive")
        commands.append(SkillCommand(
            skill_name=name, vehicle_id=vehicle_id,
            target_position=Position3D(**pos) if pos else None,
            search_region=SearchRegion(**region) if region else None,
            duration_seconds=duration, velocity=velocity,
            params={"grid_step": grid_step} if name == "SEARCH_REGION" else {}
        ))
    return commands

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--airsim", action="store_true", help="Use live AirSim/CARLA instead of mock")
    parser.add_argument("--execute", action="store_true", help="Execute plan; otherwise preview only")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--vehicle-id", default="Drone1")
    parser.add_argument("--mission", default=DEFAULT_MISSION)
    args = parser.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("Set OPENAI_API_KEY in your environment")
    client = OpenAI()
    commands = to_commands(plan(client, args.model, args.mission), args.vehicle_id)
    print(f"OpenAI planned {len(commands)} skills for {args.vehicle_id}:")
    for i, cmd in enumerate(commands, 1):
        print(f"  {i}. {cmd}")
    if not args.execute:
        print("Plan only. Add --execute to run (and --airsim for live simulation).")
        return
    adapter = AirSimAdapter() if args.airsim else MockVehicleAdapter()
    adapter.connect()
    engine = SkillEngine(adapter)
    for cmd in commands:
        print(f"\n[Executing] {cmd.skill_name}")
        result = engine.execute(cmd)
        p = result.final_position
        print(f"Status={result.status} | Time={result.ended_at-result.started_at:.2f}s | Pos=({p.x:.1f}, {p.y:.1f}, {p.z:.1f})")
        if result.status != "success":
            print(f"Stopping after failure: {result.error_code}")
            break

if __name__ == "__main__":
    main()
