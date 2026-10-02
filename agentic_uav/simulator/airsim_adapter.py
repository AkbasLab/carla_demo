import time
import airsim
from agentic_uav.core.models import VehicleState, Position3D, SkillCommand, SkillResult

class AirSimAdapter:
    def __init__(self):
        self.client = None

    def connect(self) -> None:
        self.client = airsim.MultirotorClient()
        self.client.confirmConnection()

    def enable_control(self, vehicle_id: str) -> None:
        self.client.enableApiControl(True, vehicle_name=vehicle_id)
        self.client.armDisarm(True, vehicle_name=vehicle_id)

    def get_state(self, vehicle_id: str) -> VehicleState:
        state = self.client.getMultirotorState(vehicle_name=vehicle_id)
        pos = state.kinematics_estimated.position
        
        # Check API control status instead of accessing non-existent state.armed
        is_controlled = self.client.isApiControlEnabled(vehicle_name=vehicle_id)
        is_flying = state.landed_state == airsim.LandedState.Flying

        return VehicleState(
            vehicle_id=vehicle_id,
            position=Position3D(x=pos.x_val, y=pos.y_val, z=pos.z_val),
            armed=is_controlled,
            in_air=is_flying
        )

    def takeoff(self, vehicle_id: str) -> SkillResult:
        start_t = time.time()
        # Non-blocking takeoff join to ensure complete airborne state
        self.client.takeoffAsync(vehicle_name=vehicle_id).join()
        state = self.get_state(vehicle_id)
        return SkillResult(
            vehicle_id=vehicle_id,
            status="success",
            started_at=start_t,
            ended_at=time.time(),
            final_position=state.position
        )

    def land(self, vehicle_id: str) -> SkillResult:
        start_t = time.time()
        self.client.landAsync(vehicle_name=vehicle_id).join()
        self.client.armDisarm(False, vehicle_name=vehicle_id)
        self.client.enableApiControl(False, vehicle_name=vehicle_id)
        state = self.get_state(vehicle_id)
        return SkillResult(
            vehicle_id=vehicle_id,
            status="success",
            started_at=start_t,
            ended_at=time.time(),
            final_position=state.position
        )

    def move_to_position(self, vehicle_id: str, command: SkillCommand) -> SkillResult:
        start_t = time.time()
        pos = command.target_position
        self.client.moveToPositionAsync(
            pos.x, pos.y, pos.z, velocity=command.velocity, vehicle_name=vehicle_id
        ).join()
        state = self.get_state(vehicle_id)
        return SkillResult(
            vehicle_id=vehicle_id,
            status="success",
            started_at=start_t,
            ended_at=time.time(),
            final_position=state.position
        )

    def stop(self, vehicle_id: str) -> None:
        self.client.hoverAsync(vehicle_name=vehicle_id)
