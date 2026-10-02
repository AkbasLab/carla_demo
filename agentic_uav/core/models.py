from dataclasses import dataclass, field
from typing import Literal, Optional
import time

@dataclass
class Position3D:
    x: float
    y: float
    z: float

@dataclass
class VehicleState:
    vehicle_id: str
    position: Position3D
    velocity: float = 0.0
    armed: bool = False
    in_air: bool = False
    battery_level: float = 100.0
    timestamp: float = field(default_factory=time.time)

@dataclass
class SkillCommand:
    skill_name: str
    vehicle_id: str
    target_position: Optional[Position3D] = None
    velocity: float = 5.0
    params: dict = field(default_factory=dict)

@dataclass
class SkillResult:
    vehicle_id: str
    status: Literal["success", "failed", "aborted", "timeout"]
    started_at: float
    ended_at: float
    final_position: Position3D
    error_code: Optional[str] = None
