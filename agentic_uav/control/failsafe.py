import time
from typing import Dict
from agentic_uav.core.models import Position3D, SkillCommand
from agentic_uav.control.skill_engine import SkillEngine

class FailSafeManager:
    """Monitors asset health, battery levels, geofences, and comm heartbeat timeouts."""

    def __init__(self, engine: SkillEngine, comm_timeout_sec: float = 5.0, min_battery_pct: float = 20.0):
        self.engine = engine
        self.comm_timeout_sec = comm_timeout_sec
        self.min_battery_pct = min_battery_pct
        self.last_heartbeat: Dict[str, float] = {}
        self.battery_levels: Dict[str, float] = {}

    def update_heartbeat(self, vehicle_id: str):
        self.last_heartbeat[vehicle_id] = time.time()

    def set_battery(self, vehicle_id: str, battery_pct: float):
        self.battery_levels[vehicle_id] = battery_pct

    def check_vehicle_health(self, vehicle_id: str) -> bool:
        """Evaluates failsafe triggers. Returns True if vehicle is healthy, False if trigger activated."""
        now = time.time()
        
        # 1. Check Lost Communication
        last_seen = self.last_heartbeat.get(vehicle_id, now)
        if (now - last_seen) > self.comm_timeout_sec:
            print(f"⚠️ [FAILSAFE:{vehicle_id}] Lost Communications detected! (> {self.comm_timeout_sec}s timeout)")
            self.trigger_failsafe_action(vehicle_id, "LOST_COMM")
            return False

        # 2. Check Low Battery
        battery = self.battery_levels.get(vehicle_id, 100.0)
        if battery < self.min_battery_pct:
            print(f"⚠️ [FAILSAFE:{vehicle_id}] Critical Low Battery ({battery:.1f}%)!")
            self.trigger_failsafe_action(vehicle_id, "LOW_BATTERY")
            return False

        return True

    def trigger_failsafe_action(self, vehicle_id: str, reason: str):
        print(f"🚨 [FAILSAFE:{vehicle_id}] Executing Emergency Recovery due to {reason}...")
        
        # Issue autonomous return home skill
        cmd_rtl = SkillCommand(
            skill_name="RETURN_HOME",
            vehicle_id=vehicle_id,
            target_position=Position3D(0.0, 0.0, -5.0)
        )
        self.engine.execute(cmd_rtl)

        cmd_land = SkillCommand(
            skill_name="LAND",
            vehicle_id=vehicle_id
        )
        self.engine.execute(cmd_land)
