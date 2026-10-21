import carla
import airsim
import time
import math
import numpy as np
import matplotlib.pyplot as plt

# ==============================================================================
# Operational Boundary Assurance (OBA) Safety Guardian
# ==============================================================================
class DynamicOBAGuardian:
    def __init__(self, z_max=30.0, safe_pedestrian_radius=4.0):
        self.z_max = z_max
        self.safe_radius = safe_pedestrian_radius

    def verify_target_waypoint(self, current_drone_pos, candidate_waypoint, pedestrian_pos):
        target_x, target_y, target_z = candidate_waypoint
        drone_x, drone_y, drone_z = current_drone_pos
        
        target_alt = -target_z
        modified_x, modified_y, modified_z = target_x, target_y, target_z
        interventions = []

        # Rule 1: Altitude Ceiling Clamp
        if target_alt > self.z_max:
            interventions.append(f"Altitude ceiling breach: {target_alt:.1f}m clamped to {self.z_max:.1f}m")
            modified_z = -self.z_max

        # Rule 2: Single-Pedestrian Proximity Safety Check
        if abs(drone_z) < 10.0:
            dist_to_ped = math.hypot(drone_x - pedestrian_pos.x, drone_y - pedestrian_pos.y)
            if dist_to_ped < self.safe_radius:
                interventions.append(f"Pedestrian proximity conflict ({dist_to_ped:.2f}m < {self.safe_radius}m)")
                
                dx = drone_x - pedestrian_pos.x
                dy = drone_y - pedestrian_pos.y
                norm = math.hypot(dx, dy) if math.hypot(dx, dy) > 0.01 else 1.0
                
                modified_x += (dx / norm) * (self.safe_radius - dist_to_ped + 1.5)
                modified_y += (dy / norm) * (self.safe_radius - dist_to_ped + 1.5)
                
                if abs(modified_z) < 5.0:
                    modified_z = -5.0

        is_safe = len(interventions) == 0
        return is_safe, (modified_x, modified_y, modified_z), "; ".join(interventions)


# ==============================================================================
# Extended Single-Pedestrian Zigzag Tracking Simulation
# ==============================================================================
def run_single_pedestrian_extended_zigzag():
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

    # Spawn 1 Walker Actor
    walker_bp = np.random.choice(ped_bps)
    if walker_bp.has_attribute('is_invincible'):
        walker_bp.set_attribute('is_invincible', 'false')

    walker_actor = world.try_spawn_actor(walker_bp, carla.Transform(spawn_loc))
    if not walker_actor:
        print("[ERROR] Failed to spawn pedestrian actor.")
        return

    print(f"[CARLA] Spawned Single Pedestrian (ID: {walker_actor.id}) at {spawn_loc}")
    world.tick()

    # Connect to AirSim
    print("[CarlaAir] Connecting to AirSim API...")
    airsim_client = airsim.MultirotorClient()
    airsim_client.confirmConnection()
    airsim_client.enableApiControl(True)
    airsim_client.armDisarm(True)

    guardian = DynamicOBAGuardian(z_max=30.0, safe_pedestrian_radius=4.0)

    print("[AirSim] Drone taking off...")
    airsim_client.takeoffAsync().join()

    # Reference points for alignment
    initial_ped_pos = walker_actor.get_transform().location
    initial_drone_pos = airsim_client.getMultirotorState().kinematics_estimated.position

    FOLLOW_DISTANCE = 3.5  # meters behind pedestrian
    TARGET_HEIGHT = 3.0    # meters altitude

    SWEEP_AMPLITUDE = 1.4  # Lateral sweep factor
    SWEEP_FREQUENCY = 0.06 # Sinusoidal sweep rate

    telemetry = {
        "ped_x": [], "ped_y": [],
        "drone_cmd_x": [], "drone_cmd_y": [],
        "drone_act_x": [], "drone_act_y": []
    }

    last_sent_cmd = (None, None, None)
    TOTAL_TICKS = 600  # 30 seconds of tracking

    print(f"\n[CarlaAir] Starting single-pedestrian extended zigzag tracking ({TOTAL_TICKS} ticks)...\n")

    try:
        for tick in range(TOTAL_TICKS):
            world.tick()

            # Single-axis forward progression + lateral sinusoidal sweep
            active_dir = carla.Vector3D(
                x=forward_vec.x + right_vec.x * (math.sin(tick * SWEEP_FREQUENCY) * SWEEP_AMPLITUDE),
                y=forward_vec.y + right_vec.y * (math.sin(tick * SWEEP_FREQUENCY) * SWEEP_AMPLITUDE),
                z=0.0
            )

            norm = math.hypot(active_dir.x, active_dir.y)
            if norm > 0:
                active_dir.x /= norm
                active_dir.y /= norm

            ctrl = carla.WalkerControl()
            ctrl.speed = 1.5  # 1.5 m/s walking speed
            ctrl.direction = active_dir
            walker_actor.apply_control(ctrl)

            # Get live transform
            ped_transform = walker_actor.get_transform()
            ped_pos = ped_transform.location

            delta_x = ped_pos.x - initial_ped_pos.x
            delta_y = ped_pos.y - initial_ped_pos.y

            # Drone target positioned behind pedestrian along movement vector
            behind_offset_x = -(active_dir.x * FOLLOW_DISTANCE)
            behind_offset_y = -(active_dir.y * FOLLOW_DISTANCE)

            target_drone_x = initial_drone_pos.x_val + delta_x + behind_offset_x
            target_drone_y = initial_drone_pos.y_val + delta_y + behind_offset_y
            target_drone_z = -TARGET_HEIGHT

            drone_actual = airsim_client.getMultirotorState().kinematics_estimated.position
            curr_drone_pos = (drone_actual.x_val, drone_actual.y_val, drone_actual.z_val)

            # Pass through OBA Guardian
            is_safe, (cmd_x, cmd_y, cmd_z), reason = guardian.verify_target_waypoint(
                curr_drone_pos, (target_drone_x, target_drone_y, target_drone_z), ped_pos
            )

            # Dispatch waypoint command on displacement threshold (> 0.20m shift)
            if last_sent_cmd[0] is None or math.dist((cmd_x, cmd_y, cmd_z), last_sent_cmd) > 0.20:
                airsim_client.moveToPositionAsync(cmd_x, cmd_y, cmd_z, velocity=3.2)
                last_sent_cmd = (cmd_x, cmd_y, cmd_z)

            # Record telemetry
            telemetry["ped_x"].append(initial_drone_pos.x_val + delta_x)
            telemetry["ped_y"].append(initial_drone_pos.y_val + delta_y)
            telemetry["drone_cmd_x"].append(cmd_x)
            telemetry["drone_cmd_y"].append(cmd_y)
            telemetry["drone_act_x"].append(drone_actual.x_val)
            telemetry["drone_act_y"].append(drone_actual.y_val)

            if tick % 50 == 0:
                print(f"Tick {tick:03d}/{TOTAL_TICKS} | Ped Local: ({delta_x:.2f}, {delta_y:.2f}) | "
                      f"Drone Target Cmd: ({cmd_x:.2f}, {cmd_y:.2f})")

    finally:
        print("\n[Cleanup] Destroying pedestrian actor and resetting environment...")
        walker_actor.destroy()
        
        airsim_client.landAsync().join()
        airsim_client.enableApiControl(False)
        settings.synchronous_mode = False
        world.apply_settings(settings)
        print("[Cleanup] Finished.")

    plot_single_zigzag_trajectory(telemetry)


# ==============================================================================
# Plotter
# ==============================================================================
def plot_single_zigzag_trajectory(data):
    print("\n[CarlaAir Data] Plotting single-pedestrian trajectory...")
    plt.figure(figsize=(14, 6))

    plt.plot(data["ped_x"], data["ped_y"], 'r--', linewidth=2, label="Pedestrian Extended Zigzag Path (CARLA)")
    plt.plot(data["drone_cmd_x"], data["drone_cmd_y"], 'g:', linewidth=1.5, label="OBA Target Waypoints")
    plt.plot(data["drone_act_x"], data["drone_act_y"], 'b-', linewidth=2, label="Drone Actual Flight Path (AirSim)")

    plt.scatter(data["ped_x"][0], data["ped_y"][0], color='red', marker='o', s=100, label="Pedestrian Start")
    plt.scatter(data["drone_act_x"][0], data["drone_act_y"][0], color='blue', marker='^', s=100, label="Drone Start")

    plt.title("Phase 5 Benchmark: Extended Single-Pedestrian Zigzag Tracking (CarlaAir)", fontsize=13, fontweight='bold')
    plt.xlabel("X Position (meters - AirSim Local Frame)", fontsize=11)
    plt.ylabel("Y Position (meters - AirSim Local Frame)", fontsize=11)
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.legend(loc="upper right", fontsize=10)
    plt.axis('equal')

    plt.tight_layout()
    plt.savefig("single_pedestrian_extended_zigzag_plot.png", dpi=300)
    print("[CarlaAir Data] Plot saved to 'single_pedestrian_extended_zigzag_plot.png'.")
    plt.show()


if __name__ == "__main__":
    run_single_pedestrian_extended_zigzag()
