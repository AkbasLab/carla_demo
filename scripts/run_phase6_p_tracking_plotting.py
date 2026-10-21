import carla
import airsim
import time
import math
import matplotlib.pyplot as plt

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
# Rectangular Path Navigation & Trajectory Tracking
# ==============================================================================
def run_rectangular_tracking_simulation():
    print("[CarlaAir] Connecting to CARLA server...")
    carla_client = carla.Client('localhost', 2000)
    carla_client.set_timeout(10.0)
    world = carla_client.get_world()

    # Synchronous Mode (20 FPS)
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05
    world.apply_settings(settings)

    bp_lib = world.get_blueprint_library()
    ped_bps = bp_lib.filter('walker.pedestrian.*')

    spectator = world.get_spectator()
    spec_transform = spectator.get_transform()
    forward_vec = spec_transform.get_forward_vector()
    right_vec = spec_transform.get_right_vector()

    spawn_loc = spec_transform.location + forward_vec * 8.0
    spawn_loc.z += 1.0

    # Spawn Walker
    walker_bp = ped_bps[0]
    if walker_bp.has_attribute('is_invincible'):
        walker_bp.set_attribute('is_invincible', 'false')

    walker_actor = world.try_spawn_actor(walker_bp, carla.Transform(spawn_loc))
    if not walker_actor:
        print("[ERROR] Failed to spawn pedestrian actor.")
        return

    world.tick()

    # Connect to AirSim
    print("[CarlaAir] Connecting to AirSim API...")
    airsim_client = airsim.MultirotorClient()
    airsim_client.confirmConnection()
    airsim_client.enableApiControl(True)
    airsim_client.armDisarm(True)

    guardian = DynamicOBAGuardian(z_max=30.0)

    print("[AirSim] Drone taking off...")
    airsim_client.takeoffAsync().join()

    # Establish Reference Frame Alignment
    initial_ped_pos = walker_actor.get_transform().location
    initial_drone_pos = airsim_client.getMultirotorState().kinematics_estimated.position

    # Define Rectangular Path Vectors (15m x 10m rectangle)
    # Side 1: Forward 15m, Side 2: Right 10m, Side 3: Backward 15m, Side 4: Left 10m
    leg_directions = [
        forward_vec,
        right_vec,
        carla.Vector3D(-forward_vec.x, -forward_vec.y, 0.0),
        carla.Vector3D(-right_vec.x, -right_vec.y, 0.0)
    ]
    leg_durations = [120, 80, 120, 80]  # Ticks per leg (Total 400 ticks / 20 seconds)

    FOLLOW_DISTANCE = 2.5  # meters behind pedestrian
    TARGET_HEIGHT = 3.0    # meters altitude

    # Telemetry data containers for plotting
    telemetry = {
        "ped_x": [], "ped_y": [],
        "drone_cmd_x": [], "drone_cmd_y": [],
        "drone_act_x": [], "drone_act_y": []
    }

    current_leg = 0
    leg_tick_counter = 0

    last_sent_cmd = (None, None, None)
    print("\n[CarlaAir] Starting rectangular navigation and drone tracking...\n")

    try:
        for tick in range( sum(leg_durations) ):
            world.tick()

            # Switch rectangle leg direction when duration expires
            if leg_tick_counter >= leg_durations[current_leg]:
                current_leg = (current_leg + 1) % len(leg_directions)
                leg_tick_counter = 0
                print(f"[CARLA] Pedestrian turning onto Rectangle Leg #{current_leg + 1}")

            active_dir = leg_directions[current_leg]
            leg_tick_counter += 1

            # Apply direct movement control to pedestrian
            ctrl = carla.WalkerControl()
            ctrl.speed = 3.0  # Walking speed
            ctrl.direction = active_dir
            walker_actor.apply_control(ctrl)

            # Get live pedestrian transform
            ped_transform = walker_actor.get_transform()
            ped_pos = ped_transform.location

            # Convert CARLA displacement to AirSim-local coordinates
            delta_x = ped_pos.x - initial_ped_pos.x
            delta_y = ped_pos.y - initial_ped_pos.y

            # Calculate drone target behind pedestrian along active movement direction
            behind_offset_x = -(active_dir.x * FOLLOW_DISTANCE)
            behind_offset_y = -(active_dir.y * FOLLOW_DISTANCE)

            target_drone_x = initial_drone_pos.x_val + delta_x + behind_offset_x
            target_drone_y = initial_drone_pos.y_val + delta_y + behind_offset_y
            target_drone_z = -TARGET_HEIGHT

            # Verify with OBA Layer
            _, (cmd_x, cmd_y, cmd_z) = guardian.verify_target_waypoint(
                (target_drone_x, target_drone_y, target_drone_z)
            )

            # Send flight movement command
            if last_sent_cmd[0] is None or math.dist((cmd_x, cmd_y, cmd_z), last_sent_cmd) > 0.20:
                airsim_client.moveToPositionAsync(cmd_x, cmd_y, cmd_z, velocity=2.5)
                last_sent_cmd = (cmd_x, cmd_y, cmd_z)

            # Record telemetry
            drone_actual = airsim_client.getMultirotorState().kinematics_estimated.position
            
            # Map pedestrian position into AirSim coordinate frame for consistent plotting
            telemetry["ped_x"].append(initial_drone_pos.x_val + delta_x)
            telemetry["ped_y"].append(initial_drone_pos.y_val + delta_y)
            telemetry["drone_cmd_x"].append(cmd_x)
            telemetry["drone_cmd_y"].append(cmd_y)
            telemetry["drone_act_x"].append(drone_actual.x_val)
            telemetry["drone_act_y"].append(drone_actual.y_val)

            if tick % 40 == 0:
                print(f"Tick {tick:03d} | Ped Local: ({delta_x:.2f}, {delta_y:.2f}) | "
                      f"Drone Target: ({cmd_x:.2f}, {cmd_y:.2f})")

    finally:
        print("\n[Cleanup] Landing drone and destroying pedestrian actor...")
        walker_actor.destroy()
        airsim_client.landAsync().join()
        airsim_client.enableApiControl(False)
        settings.synchronous_mode = False
        world.apply_settings(settings)
        print("[Cleanup] Simulation execution complete.")

    # Plot the results
    plot_trajectory(telemetry)


# ==============================================================================
# Plotting Utility
# ==============================================================================
def plot_trajectory(data):
    print("\n[CarlaAir Data] Generating trajectory comparison plot...")
    plt.figure(figsize=(10, 8))

    # Plot Pedestrian Rectangle Path
    plt.plot(data["ped_x"], data["ped_y"], 'r--', linewidth=2, label="Pedestrian Path (CARLA)")
    
    # Plot OBA Target Waypoints
    plt.plot(data["drone_cmd_x"], data["drone_cmd_y"], 'g:', linewidth=1.5, label="OBA Target Waypoints")
    
    # Plot Drone Actual Flight Path
    plt.plot(data["drone_act_x"], data["drone_act_y"], 'b-', linewidth=2, label="Drone Actual Flight Path (AirSim)")

    # Mark Start / End Points
    plt.scatter(data["ped_x"][0], data["ped_y"][0], color='red', marker='o', s=100, label="Pedestrian Start")
    plt.scatter(data["drone_act_x"][0], data["drone_act_y"][0], color='blue', marker='^', s=100, label="Drone Start")

    plt.title("Phase 5 Benchmark: Dynamic Pedestrian Rectangular Tracking (CarlaAir)", fontsize=13, fontweight='bold')
    plt.xlabel("X Position (meters - AirSim Local Frame)", fontsize=7)
    plt.ylabel("Y Position (meters - AirSim Local Frame)", fontsize=7)
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.legend(loc="upper right", fontsize=11)
    plt.axis('equal')  # Maintain 1:1 aspect ratio for spatial accuracy

    plt.tight_layout()
    plt.savefig("pedestrian_rectangular_tracking_plot.png", dpi=300)
    print("[CarlaAir Data] Plot successfully saved to 'pedestrian_rectangular_tracking_plot.png'.")
    plt.show()


if __name__ == "__main__":
    run_rectangular_tracking_simulation()
