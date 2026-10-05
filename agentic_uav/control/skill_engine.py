import time
from typing import List, Optional
from agentic_uav.core.models import SkillCommand, SkillResult, Position3D, SearchRegion
from agentic_uav.simulator.base_adapter import VehicleAdapter
from agentic_uav.control.scenario_manager import ScenarioManager

class SkillEngine:
    def __init__(self, adapter: VehicleAdapter, scenario_mgr: Optional[ScenarioManager] = None):
        self.adapter = adapter
        self.scenario_mgr = scenario_mgr

    def execute(self, command: SkillCommand) -> SkillResult:
        method_map = {
            "TAKE_OFF": self.take_off,
            "GO_TO_WAYPOINT": self.go_to_waypoint,
            "SEARCH_REGION": self.search_region,
            "HOLD_POSITION": self.hold_position,
            "ACT_AS_RELAY": self.act_as_relay,
            "RETURN_HOME": self.return_home,
            "LAND": self.land,
        }

        handler = method_map.get(command.skill_name)
        if not handler:
            start_t = time.time()
            curr_pos = self.adapter.get_state(command.vehicle_id).position
            return SkillResult(
                vehicle_id=command.vehicle_id,
                skill_name=command.skill_name,
                status="failed",
                started_at=start_t,
                ended_at=time.time(),
                final_position=curr_pos,
                error_code="INVALID_SKILL_NAME"
            )

        return handler(command)

    def _inspect_position(self, vehicle_id: str) -> List[dict]:
        """Check geofences and ground-truth target proximity."""
        if not self.scenario_mgr:
            return []

        state = self.adapter.get_state(vehicle_id)
        
        # Check geofence
        violation = self.scenario_mgr.check_geofence_violation(state.position)
        if violation:
            print(f"[WARNING] Vehicle {vehicle_id} violated Keep-Out Zone: {violation}")

        # Check target proximity
        detections = self.scenario_mgr.check_target_detections(vehicle_id, state.position)
        for det in detections:
            print(f"[TARGET ACQUIRED] Vehicle '{det.vehicle_id}' spotted '{det.target_id}' at dist {det.distance}m!")

        return detections

    def take_off(self, command: SkillCommand) -> SkillResult:
        start_t = time.time()
        try:
            self.adapter.enable_control(command.vehicle_id)
            res = self.adapter.takeoff(command.vehicle_id)
            state = self.adapter.get_state(command.vehicle_id)
            self._inspect_position(command.vehicle_id)
            return SkillResult(
                vehicle_id=command.vehicle_id,
                skill_name="TAKE_OFF",
                status="success",
                started_at=start_t,
                ended_at=time.time(),
                final_position=state.position,
                battery_remaining=state.battery_level
            )
        except Exception as e:
            state = self.adapter.get_state(command.vehicle_id)
            return SkillResult(
                vehicle_id=command.vehicle_id,
                skill_name="TAKE_OFF",
                status="failed",
                started_at=start_t,
                ended_at=time.time(),
                final_position=state.position,
                error_code=str(e)
            )

    def go_to_waypoint(self, command: SkillCommand) -> SkillResult:
        start_t = time.time()
        if not command.target_position:
            state = self.adapter.get_state(command.vehicle_id)
            return SkillResult(
                vehicle_id=command.vehicle_id,
                skill_name="GO_TO_WAYPOINT",
                status="failed",
                started_at=start_t,
                ended_at=time.time(),
                final_position=state.position,
                error_code="MISSING_TARGET_POSITION"
            )
        try:
            res = self.adapter.move_to_position(command.vehicle_id, command)
            state = self.adapter.get_state(command.vehicle_id)
            self._inspect_position(command.vehicle_id)
            return SkillResult(
                vehicle_id=command.vehicle_id,
                skill_name="GO_TO_WAYPOINT",
                status="success",
                started_at=start_t,
                ended_at=time.time(),
                final_position=state.position,
                battery_remaining=state.battery_level
            )
        except Exception as e:
            state = self.adapter.get_state(command.vehicle_id)
            return SkillResult(
                vehicle_id=command.vehicle_id,
                skill_name="GO_TO_WAYPOINT",
                status="failed",
                started_at=start_t,
                ended_at=time.time(),
                final_position=state.position,
                error_code=str(e)
            )

    def search_region(self, command: SkillCommand) -> SkillResult:
        start_t = time.time()
        region = command.search_region
        if not region:
            state = self.adapter.get_state(command.vehicle_id)
            return SkillResult(
                vehicle_id=command.vehicle_id,
                skill_name="SEARCH_REGION",
                status="failed",
                started_at=start_t,
                ended_at=time.time(),
                final_position=state.position,
                error_code="MISSING_SEARCH_REGION"
            )

        grid_step = command.params.get("grid_step", 10.0)
        waypoints = []
        curr_y = region.min_y
        sweep_east = True

        while curr_y <= region.max_y:
            if sweep_east:
                waypoints.append(Position3D(region.min_x, curr_y, region.altitude))
                waypoints.append(Position3D(region.max_x, curr_y, region.altitude))
            else:
                waypoints.append(Position3D(region.max_x, curr_y, region.altitude))
                waypoints.append(Position3D(region.min_x, curr_y, region.altitude))
            curr_y += grid_step
            sweep_east = not sweep_east

        try:
            waypoints_visited = 0
            all_detections = []
            for wp in waypoints:
                sub_cmd = SkillCommand(
                    skill_name="GO_TO_WAYPOINT",
                    vehicle_id=command.vehicle_id,
                    target_position=wp,
                    velocity=command.velocity
                )
                self.adapter.move_to_position(command.vehicle_id, sub_cmd)
                dets = self._inspect_position(command.vehicle_id)
                all_detections.extend(dets)
                waypoints_visited += 1

            state = self.adapter.get_state(command.vehicle_id)
            return SkillResult(
                vehicle_id=command.vehicle_id,
                skill_name="SEARCH_REGION",
                status="success",
                started_at=start_t,
                ended_at=time.time(),
                final_position=state.position,
                battery_remaining=state.battery_level,
                details={
                    "waypoints_visited": waypoints_visited, 
                    "detections_count": len(all_detections)
                }
            )
        except Exception as e:
            state = self.adapter.get_state(command.vehicle_id)
            return SkillResult(
                vehicle_id=command.vehicle_id,
                skill_name="SEARCH_REGION",
                status="failed",
                started_at=start_t,
                ended_at=time.time(),
                final_position=state.position,
                error_code=str(e)
            )

    def hold_position(self, command: SkillCommand) -> SkillResult:
        start_t = time.time()
        vehicle_id = command.vehicle_id
        duration = command.duration_seconds if command.duration_seconds > 0 else 5.0

        try:
            if command.target_position:
                self.adapter.move_to_position(vehicle_id, command)
            
            self.adapter.stop(vehicle_id)
            time.sleep(duration)

            state = self.adapter.get_state(vehicle_id)
            self._inspect_position(vehicle_id)
            return SkillResult(
                vehicle_id=vehicle_id,
                skill_name="HOLD_POSITION",
                status="success",
                started_at=start_t,
                ended_at=time.time(),
                final_position=state.position,
                battery_remaining=state.battery_level,
                details={"hold_duration_s": duration}
            )
        except Exception as e:
            state = self.adapter.get_state(vehicle_id)
            return SkillResult(
                vehicle_id=vehicle_id,
                skill_name="HOLD_POSITION",
                status="failed",
                started_at=start_t,
                ended_at=time.time(),
                final_position=state.position,
                error_code=str(e)
            )

    def act_as_relay(self, command: SkillCommand) -> SkillResult:
        start_t = time.time()
        vehicle_id = command.vehicle_id
        duration = command.duration_seconds if command.duration_seconds > 0 else 10.0

        try:
            if command.target_position:
                self.adapter.move_to_position(vehicle_id, command)
            
            self.adapter.stop(vehicle_id)
            time.sleep(duration)

            state = self.adapter.get_state(vehicle_id)
            self._inspect_position(vehicle_id)
            return SkillResult(
                vehicle_id=vehicle_id,
                skill_name="ACT_AS_RELAY",
                status="success",
                started_at=start_t,
                ended_at=time.time(),
                final_position=state.position,
                battery_remaining=state.battery_level,
                details={"relay_duration_s": duration, "relay_active": True}
            )
        except Exception as e:
            state = self.adapter.get_state(vehicle_id)
            return SkillResult(
                vehicle_id=vehicle_id,
                skill_name="ACT_AS_RELAY",
                status="failed",
                started_at=start_t,
                ended_at=time.time(),
                final_position=state.position,
                error_code=str(e)
            )

    def return_home(self, command: SkillCommand) -> SkillResult:
        start_t = time.time()
        vehicle_id = command.vehicle_id
        try:
            state = self.adapter.get_state(vehicle_id)
            home_pos = state.home_position

            cmd = SkillCommand(
                skill_name="GO_TO_WAYPOINT",
                vehicle_id=vehicle_id,
                target_position=home_pos,
                velocity=command.velocity
            )
            self.adapter.move_to_position(vehicle_id, cmd)

            state_after = self.adapter.get_state(vehicle_id)
            self._inspect_position(vehicle_id)
            return SkillResult(
                vehicle_id=vehicle_id,
                skill_name="RETURN_HOME",
                status="success",
                started_at=start_t,
                ended_at=time.time(),
                final_position=state_after.position,
                battery_remaining=state_after.battery_level
            )
        except Exception as e:
            state = self.adapter.get_state(vehicle_id)
            return SkillResult(
                vehicle_id=vehicle_id,
                skill_name="RETURN_HOME",
                status="failed",
                started_at=start_t,
                ended_at=time.time(),
                final_position=state.position,
                error_code=str(e)
            )

    def land(self, command: SkillCommand) -> SkillResult:
        start_t = time.time()
        try:
            res = self.adapter.land(command.vehicle_id)
            state = self.adapter.get_state(command.vehicle_id)
            self._inspect_position(command.vehicle_id)
            return SkillResult(
                vehicle_id=command.vehicle_id,
                skill_name="LAND",
                status="success",
                started_at=start_t,
                ended_at=time.time(),
                final_position=state.position,
                battery_remaining=state.battery_level
            )
        except Exception as e:
            state = self.adapter.get_state(command.vehicle_id)
            return SkillResult(
                vehicle_id=command.vehicle_id,
                skill_name="LAND",
                status="failed",
                started_at=start_t,
                ended_at=time.time(),
                final_position=state.position,
                error_code=str(e)
            )
