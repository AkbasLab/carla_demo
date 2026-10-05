from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from agentic_uav.core.models import SkillCommand

@dataclass
class HighLevelGoal:
    user_prompt: str
    available_drones: List[str]
    context_sectors: List[str]

@dataclass
class PlanStep:
    step_id: int
    vehicle_id: str
    skill_name: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    rationale: str = ""

@dataclass
class MissionPlan:
    goal: str
    steps: List[PlanStep] = field(default_factory=list)
    estimated_duration_s: float = 0.0
    valid: bool = True
    validation_error: Optional[str] = None
