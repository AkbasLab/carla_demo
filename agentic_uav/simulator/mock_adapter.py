import time
import math
from agentic_uav.core.models import VehicleState, Position3D, SkillCommand, SkillResult

class MockVehicleAdapter:
    """Calculates position updates using trajectory math without CARLA/AirSim."""

    def __init__(self):
        self.states = {}

    def connect(self) -> None:
        print("[MockAdapter] Simulation environment connected.")

    def enable_control(self, vehicle_id: str) -> None:
        self.states[vehicle_id] = VehicleState(
            vehicle_id=vehicle_id,
            position=Position3D(x=0.0, y=0.0, z=0.0),
            armed=True,
            in_air=False
        )

    def get_state(self, vehicle_id: str) -> VehicleState:
        return self.states.get(
            vehicle_id, 
            VehicleState(vehicle_id=vehicle_id, position=Position3D(0.0, 0.0, 0.0))
        )

    def takeoff(self, vehicle_id: str) -> SkillResult:
        start_t = time.time()
        state = self.get_state(vehicle_id)
        state.position.z = -5.0
        state.in_air = True
        time.sleep(0.1)  # Simulate small delay
        return SkillResult(
            vehicle_id=vehicle_id,
            status="success",
            started_at=start_t,
            ended_at=time.time(),
            final_position=state.position
        )

    def land(self, vehicle_id: str) -> SkillResult:
        start_t = time.time()
        state = self.get_state(vehicle_id)
        state.position.z = 0.0
        state.in_air = False
        state.armed = False
        return SkillResult(
            vehicle_id=vehicle_id,
            status="success",
            started_at=start_t,
            ended_at=time.time(),
            final_position=state.position
        )

    def move_to_position(self, vehicle_id: str, command: SkillCommand) -> SkillResult:
        start_t = time.time()
        current = self.get_state(vehicle_id).position
        target = command.target_position

        # Compute Euclidean distance and mock traversal delay
        distance = math.sqrt(
            (target.x - current.x)**2 + (target.y - current.y)**2 + (target.z - current.z)**2
        )
        simulated_time = max(0.1, distance / command.velocity)
        time.sleep(min(simulated_time, 1.0))  # Cap delay for fast unit testing

        # Update position
        self.states[vehicle_id].position = Position3D(target.x, target.y, target.z)

        return SkillResult(
            vehicle_id=vehicle_id,
            status="success",
            started_at=start_t,
            ended_at=time.time(),
            final_position=self.states[vehicle_id].position
        )

    def stop(self, vehicle_id: str) -> None:
        pass
