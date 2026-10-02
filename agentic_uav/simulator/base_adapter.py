from typing import Protocol
from agentic_uav.core.models import VehicleState, SkillCommand, SkillResult

class VehicleAdapter(Protocol):
    """Abstract interface hiding specific simulator/hardware API calls."""
    
    def connect(self) -> None:
        ...

    def enable_control(self, vehicle_id: str) -> None:
        ...

    def get_state(self, vehicle_id: str) -> VehicleState:
        ...

    def takeoff(self, vehicle_id: str) -> SkillResult:
        ...

    def land(self, vehicle_id: str) -> SkillResult:
        ...

    def move_to_position(self, vehicle_id: str, command: SkillCommand) -> SkillResult:
        ...

    def stop(self, vehicle_id: str) -> None:
        ...
