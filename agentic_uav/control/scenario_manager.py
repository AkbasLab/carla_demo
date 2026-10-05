import json
import math
import time
from typing import List, Optional
from agentic_uav.core.models import (
    Position3D, SearchRegion, TargetInfo, DetectionEvent, VehicleState
)

class ScenarioManager:
    """Manages ground-truth scenario assets, keep-out zones, and target acquisition."""

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.base_station: Position3D = Position3D(0, 0, 0)
        self.sectors: dict[str, SearchRegion] = {}
        self.restricted_zones: List[dict] = []
        self.targets: List[TargetInfo] = []
        self.detection_history: List[DetectionEvent] = []
        
        self.load_scenario()

    def load_scenario(self) -> None:
        with open(self.config_path, "r") as f:
            data = json.load(f)

        base = data["base_station"]["position"]
        self.base_station = Position3D(x=base["x"], y=base["y"], z=base["z"])

        for sec in data["search_sectors"]:
            self.sectors[sec["sector_id"]] = SearchRegion(
                min_x=sec["min_x"], max_x=sec["max_x"],
                min_y=sec["min_y"], max_y=sec["max_y"],
                altitude=sec["altitude"]
            )

        self.restricted_zones = data.get("restricted_zones", [])

        self.targets = []
        for tgt in data["simulated_targets"]:
            pos = tgt["position"]
            self.targets.append(
                TargetInfo(
                    target_id=tgt["target_id"],
                    type=tgt["type"],
                    position=Position3D(x=pos["x"], y=pos["y"], z=pos["z"]),
                    detection_radius=tgt["detection_radius_meters"],
                    detected=tgt.get("detected", False)
                )
            )

    def check_geofence_violation(self, pos: Position3D) -> Optional[str]:
        """Verify if a 3D coordinate collides with any restricted fly zone."""
        for zone in self.restricted_zones:
            if (zone["min_x"] <= pos.x <= zone["max_x"] and
                zone["min_y"] <= pos.y <= zone["max_y"] and
                zone["min_z"] <= pos.z <= zone["max_z"]):
                return zone["zone_id"]
        return None

    def check_target_detections(self, vehicle_id: str, uav_pos: Position3D) -> List[DetectionEvent]:
        """Evaluates bounding box/radial proximity against ground-truth targets."""
        new_detections = []

        for target in self.targets:
            if target.detected:
                continue

            # Calculate 2D horizontal distance to ground target
            dist_2d = math.sqrt(
                (uav_pos.x - target.position.x) ** 2 + 
                (uav_pos.y - target.position.y) ** 2
            )

            if dist_2d <= target.detection_radius:
                target.detected = True
                target.detected_by = vehicle_id
                target.detected_at = time.time()

                event = DetectionEvent(
                    target_id=target.target_id,
                    vehicle_id=vehicle_id,
                    target_position=target.position,
                    uav_position=uav_pos,
                    distance=round(dist_2d, 2)
                )
                self.detection_history.append(event)
                new_detections.append(event)

        return new_detections
