from typing import Protocol, List
from agentic_uav.core.models import SkillCommand

class MissionPlanner(Protocol):
    def plan(self, user_instruction: str) -> List[SkillCommand]:
        ...
