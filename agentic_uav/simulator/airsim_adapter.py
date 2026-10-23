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
        self.client.takeoffAsync(vehicle_name=vehicle_id).join()
        state = self.get_state(vehicle_id)
        return SkillResult(
            vehicle_id=vehicle_id,
            skill_name="TAKE_OFF",
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
            skill_name="LAND",
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
            skill_name=command.skill_name,
            status="success",
            started_at=start_t,
            ended_at=time.time(),
            final_position=state.position
        )

    def stop(self, vehicle_id: str) -> None:
        self.client.hoverAsync(vehicle_name=vehicle_id)

    def capture_image(self, vehicle_id: str, output_dir: str = "results/camera",
                      camera_name: str = "0") -> dict:
        """Capture a PNG from an AirSim RGB camera and save capture metadata.

        Requires a running AirSim/CarlaAir simulator. The vehicle-specific
        camera name defaults to AirSim's camera '0'.
        """
        import json
        import re
        from datetime import datetime, timezone
        from pathlib import Path

        if self.client is None:
            raise RuntimeError("AirSim is not connected; call connect() first")

        responses = self.client.simGetImages(
            [airsim.ImageRequest(str(camera_name), airsim.ImageType.Scene,
                                 pixels_as_float=False, compress=True)],
            vehicle_name=vehicle_id,
        )
        if not responses or not responses[0].image_data_uint8:
            raise RuntimeError(
                f"No RGB image returned for {vehicle_id} camera {camera_name}"
            )
        response = responses[0]
        image_bytes = bytes(response.image_data_uint8)
        if not image_bytes.startswith(bytes.fromhex("89504e470d0a1a0a")):
            raise RuntimeError("AirSim did not return a valid PNG image")

        folder = Path(output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        safe_vehicle = re.sub(r"[^A-Za-z0-9_-]", "_", vehicle_id)
        safe_camera = re.sub(r"[^A-Za-z0-9_-]", "_", str(camera_name))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        stem = f"{safe_vehicle}_{safe_camera}_{stamp}"
        image_path = folder / f"{stem}.png"
        metadata_path = folder / f"{stem}.json"
        image_path.write_bytes(image_bytes)

        state = self.get_state(vehicle_id)
        metadata = {
            "vehicle_id": vehicle_id,
            "camera_name": str(camera_name),
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "sim_timestamp_ns": getattr(response, "time_stamp", None),
            "image_width": response.width,
            "image_height": response.height,
            "vehicle_position_ned_m": {
                "x": state.position.x, "y": state.position.y,
                "z": state.position.z,
            },
            "image_path": str(image_path),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n",
                                 encoding="utf-8")
        return {"image_path": str(image_path),
                "metadata_path": str(metadata_path)}
