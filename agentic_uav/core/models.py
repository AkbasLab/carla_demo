from dataclasses import dataclass, field
from typing import Literal, Optional, List
import time

@dataclass
class Position3D:
    x: float
    y: float
    z: float

@dataclass
class SearchRegion:
    """Bounding box defined by min and max coordinates (AirSim NED frame)."""
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    altitude: float = -10.0  # Default flight altitude (NED z is negative)

@dataclass
class VehicleState:
    vehicle_id: str
    position: Position3D
    velocity: float = 0.0
    armed: bool = False
    in_air: bool = False
    battery_level: float = 100.0
    home_position: Position3D = field(default_factory=lambda: Position3D(0.0, 0.0, 0.0))
    timestamp: float = field(default_factory=time.time)

# Supported Flight Skill Enums
SkillType = Literal[
    "TAKE_OFF", 
    "GO_TO_WAYPOINT", 
    "SEARCH_REGION", 
    "HOLD_POSITION", 
    "ACT_AS_RELAY", 
    "RETURN_HOME", 
    "LAND"
]

@dataclass
class SkillCommand:
    skill_name: SkillType
    vehicle_id: str
    target_position: Optional[Position3D] = None
    search_region: Optional[SearchRegion] = None
    duration_seconds: float = 0.0  # Used for HOLD_POSITION and ACT_AS_RELAY
    velocity: float = 5.0
    params: dict = field(default_factory=dict)

@dataclass
class SkillResult:
    vehicle_id: str
    skill_name: SkillType
    status: Literal["success", "failed", "aborted", "timeout"]
    started_at: float
    ended_at: float
    final_position: Position3D
    battery_remaining: float = 100.0
    error_code: Optional[str] = None
    details: dict = field(default_factory=dict)
