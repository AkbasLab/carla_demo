import carla
import airsim
import random
import time
import math

# ==============================================================================
# Operational Boundary Assurance (OBA) Safety Guardian
# ==============================================================================
class DynamicOBAGuardian:
    def __init__(self, z_max=30.0):
        self.z_max = z_max

    def verify_target_waypoint(self, candidate_waypoint):
        x_target, y_target, z_target = candidate_waypoint
        target_height = -z_target
        
        modified_z = z_target
        is_safe = True

        if target_height > self.z_max:
            is_safe = False
            modified_z = -self.z_max

        return is_safe, (x_target, y_target, modified_z)


# ==============================================================================
# Calibrated Tracking Loop (AirSim <-> CARLA Coordinate Frame Alignment)
# ==============================================================================
def run_calibrated_pedestrian_tracking():
    print("[CarlaAir] Connecting to CARLA server...")
    carla_client = carla.Client('localhost', 2000)
    carla_client.set_timeout(10.0)
    world = carla_client.get_world()

    # Configure Fixed Delta Seconds for Synchronous Physics
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05  # 20 FPS
    world.apply_settings(settings)

    bp_lib = world.get_blueprint_library()
    ped_bps = bp_lib.filter('walker.pedestrian.*')

    spectator = world.get_spectator()
    spec_transform = spectator.get_transform()
    forward_vec = spec_transform.get_forward_vector()

    spawn_loc = spec_transform.location + forward_vec * 8.0
    spawn_loc.z += 1.0

    # Spawn Walker
    walker_bp = random.choice(ped_bps)
    if walker_bp.has_attribute('is_invincible'):
        walker_bp.set_attribute('is_invincible', 'false')

    walker_actor = world.try_spawn_actor(walker_bp, carla.Transform(spawn_loc))
    if not walker_actor:
        print("[ERROR] Failed to spawn pedestrian.")
        return

    world.tick()

    # Apply initial walking velocity
    control = carla.WalkerControl()
    control.speed = 3.4  # 1.4 m/s walking speed
    control.direction = forward_vec
    walker_actor.apply_control(control)

    # Connect AirSim API
    print("[CarlaAir] Connecting to AirSim API...")
    airsim_client = airsim.MultirotorClient()
    airsim_client.confirmConnection()
    airsim_client.enableApiControl(True)
    airsim_client.armDisarm(True)

    guardian = DynamicOBAGuardian(z_max=30.0)

    print("[AirSim] Drone taking off...")
    airsim_client.takeoffAsync().join()

    # Sample initial state to establish coordinate reference frame mapping
    initial_ped_transform = walker_actor.get_transform()
    initial_ped_pos = initial_ped_transform.location
    
    # AirSim drone starting position (0,0,0) in local NED frame
    initial_drone_pos = airsim_client.getMultirotorState().kinematics_estimated.position

    FOLLOW_DISTANCE = 4.0  # meters behind pedestrian
    TARGET_HEIGHT = 0.5    # meters altitude above ground

    last_sent_cmd = (None, None, None)
    print("\n[CarlaAir] Calibrated tracking loop active. Drone following pedestrian...\n")

    try:
        for tick in range(300):  # 15-second tracking loop
            world.tick()

            # Maintain walking velocity every 20 ticks
            if tick % 20 == 0:
                walker_actor.apply_control(control)

            # Get live pedestrian transform from CARLA
            ped_transform = walker_actor.get_transform()
            ped_pos = ped_transform.location
            ped_forward = ped_transform.get_forward_vector()

            # 1. Compute delta movement relative to pedestrian's initial spawn point
            delta_x = ped_pos.x - initial_ped_pos.x
            delta_y = ped_pos.y - initial_ped_pos.y

            # 2. Compute offset vector to position drone behind the pedestrian along heading
            behind_offset_x = -(ped_forward.x * FOLLOW_DISTANCE)
            behind_offset_y = -(ped_forward.y * FOLLOW_DISTANCE)

            # 3. Combine in AirSim local NED frame
            target_drone_x = initial_drone_pos.x_val + delta_x + behind_offset_x
            target_drone_y = initial_drone_pos.y_val + delta_y + behind_offset_y
            target_drone_z = -TARGET_HEIGHT  # AirSim NED Z frame

            # OBA Guardrail Verification
            _, (cmd_x, cmd_y, cmd_z) = guardian.verify_target_waypoint(
                (target_drone_x, target_drone_y, target_drone_z)
            )

            # Dispatch waypoint only when position changes by > 0.20m to keep flight fluid
            if last_sent_cmd[0] is None or math.dist((cmd_x, cmd_y, cmd_z), last_sent_cmd) > 0.20:
                # Maintain tracking velocity
                airsim_client.moveToPositionAsync(cmd_x, cmd_y, cmd_z, velocity=2.5)
                last_sent_cmd = (cmd_x, cmd_y, cmd_z)

            # Telemetry readout
            if tick % 20 == 0:
                print(f"Frame {tick:03d} | Ped Delta: ({delta_x:.2f}, {delta_y:.2f}) | AirSim Target Cmd: ({cmd_x:.2f}, {cmd_y:.2f}, {cmd_z:.2f})")

    finally:
        print("\n[Cleanup] Landing drone and destroying pedestrian actor...")
        walker_actor.destroy()
        airsim_client.landAsync().join()
        airsim_client.enableApiControl(False)
        settings.synchronous_mode = False
        world.apply_settings(settings)
        print("[Cleanup] Done.")


if __name__ == "__main__":
    run_calibrated_pedestrian_tracking()
