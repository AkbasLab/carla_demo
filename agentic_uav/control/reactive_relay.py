import math
from agentic_uav.comm.bus import CommBus, Message
from agentic_uav.core.models import Position3D, SkillCommand
from agentic_uav.control.skill_engine import SkillEngine

class ReactiveRelayAgent:
    """Decentralized controller running on relay drones to respond to ad-hoc worker events."""

    def __init__(self, vehicle_id: str, comm_bus: CommBus, engine: SkillEngine, base_station_pos: Position3D):
        self.vehicle_id = vehicle_id
        self.comm_bus = comm_bus
        self.engine = engine
        self.base_station_pos = base_station_pos
        self.is_relaying = False

        # Subscribe to inter-drone target discovery topics
        self.comm_bus.subscribe("TARGET_DISCOVERED", self.on_target_discovered)

    def on_target_discovered(self, msg: Message) -> None:
        """Triggered automatically when another drone detects a target."""
        if msg.sender_id == self.vehicle_id:
            return  # Ignore self-messages

        print(f"\n[REACTIVE_AGENT:{self.vehicle_id}] Intercepted alert from '{msg.sender_id}'!")
        target_pos_dict = msg.payload.get("target_position")
        uav_pos_dict = msg.payload.get("uav_position")

        if not uav_pos_dict:
            return

        uav_pos = Position3D(uav_pos_dict["x"], uav_pos_dict["y"], uav_pos_dict["z"])

        # Compute mid-point relay vector between Base Station and worker drone
        relay_midpoint = Position3D(
            x=round((self.base_station_pos.x + uav_pos.x) / 2.0, 2),
            y=round((self.base_station_pos.y + uav_pos.y) / 2.0, 2),
            z=-15.0  # Maintain stable relay altitude
        )

        print(f"[REACTIVE_AGENT:{self.vehicle_id}] Autonomous decision: Repositioning to midpoint {relay_midpoint} to bridge signal.")

        # Dispatch autonomous flight skill directly without central orchestrator intervention
        cmd = SkillCommand(
            skill_name="ACT_AS_RELAY",
            vehicle_id=self.vehicle_id,
            target_position=relay_midpoint,
            duration_seconds=3.0
        )
        self.engine.execute(cmd)
        self.is_relaying = True
