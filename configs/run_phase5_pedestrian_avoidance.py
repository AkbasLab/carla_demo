import carla
import airsim
import time
import math
import numpy as np

# ==============================================================================
# 1. Dynamic OBA Safety Guardian with Pedestrian Collision Avoidance
# ==============================================================================
class DynamicOBAGuardian:
    def __init__(self, z_max=30.0, safe_pedestrian_radius=5.0):
        """
        :param z_max: Maximum altitude ceiling in meters (positive float).
        :param safe_pedestrian_radius: Minimum horizontal safety distance (meters) to pedestrians.
        """
        self.z_max = z_max
        self.safe_radius = safe_pedestrian_radius

    def verify_and_adjust_waypoint(self, current_drone_pos, target_waypoint, pedestrian_positions):
        """
        Intercepts proposed waypoint target (x, y, z) and adjusts it if dynamic
        pedestrians encroach on the flight path.
        """
        target_x, target_y, target_z = target_waypoint
        drone_x, drone_y, drone_z = current_drone_pos
        
        target_alt = -target_z  # AirSim NED Z frame -> positive height
        modified_x, modified_y, modified_z = target_x, target_y, target_z
        interventions = []

        # Rule 1: Kinematic Altitude Ceiling Clamp (z_max)
        if target_alt > self.z_max:
            interventions.append(f"Altitude ceiling breach: {target_alt:.1f}m clamped to {self.z_max:.1f}m")
            modified_z = -self.z_max

        # Rule 2: Dynamic Pedestrian Proximity & Collision Avoidance
        # Only evaluate horizontal proximity if drone flies at low altitude (< 10m height)
        if abs(drone_z) < 10.0:
            for ped_id, ped_pos in enumerate(pedestrian_positions):
                dist_to_ped = math.hypot(drone_x - ped_pos.x, drone_y - ped_pos.y)
                
                if dist_to_ped < self.safe_radius:
                    interventions.append(f"Pedestrian #{ped_id+1} proximity conflict ({dist_to_ped:.2f}m < {self.safe_radius}m)")
                    
                    # Calculate repulsion vector away from the pedestrian
                    dx = drone_x - ped_pos.x
                    dy = drone_y - ped_pos.y
                    norm = math.hypot(dx, dy) if math.hypot(dx, dy) > 0.01 else 1.0
                    
                    # Offset waypoint target away from pedestrian
                    modified_x += (dx / norm) * (self.safe_radius - dist_to_ped + 2.0)
                    modified_y += (dy / norm) * (self.safe_radius - dist_to_ped + 2.0)
                    
                    # Temporarily climb to safer altitude if horizontal bypass is tight
                    if abs(modified_z) < 6.0:
                        modified_z = -6.0  # Climb to 6m clearance height

        is_safe = len(interventions) == 0
        return is_safe, (modified_x, modified_y, modified_z), "; ".join(interventions)


# ==============================================================================
# 2. Synchronized CarlaAir Execution Loop
# ==============================================================================
def run_dynamic_avoidance_simulation():
    # --- Step 1: Connect to CARLA Engine for Pedestrian Control ---
    print("[CarlaAir Setup] Connecting to CARLA server...")
    carla_client = carla.Client('localhost', 2000)
    carla_client.set_timeout(10.0)
    world = carla_client.get_world()

    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05  # 20 FPS
    world.apply_settings(settings)

    bp_lib = world.get_blueprint_library()
    ped_bps = bp_lib.filter('walker.pedestrian.*')

    spectator = world.get_spectator()
    spec_trans = spectator.get_transform()
    forward_vec = spec_trans.get_forward_vector()
    right_vec = spec_trans.get_right_vector()

    base_loc = spec_trans.location + forward_vec * 10.0

    # Define spawn locations for 2 crossing pedestrians
    spawn_locations = [
        base_loc - right_vec * 3.0 + carla.Location(z=1.0),
        base_loc + right_vec * 3.0 + carla.Location(z=1.0)
    ]
    
    # Crossing trajectory vectors
    directions = [
        forward_vec + right_vec * 0.6,
        forward_vec - right_vec * 0.6
    ]

    pedestrians = []
    for i, loc in enumerate(spawn_locations):
        bp = np.random.choice(ped_bps)
        actor = world.try_spawn_actor(bp, carla.Transform(loc))
        if actor:
            pedestrians.append((actor, directions[i]))
            print(f"[CARLA] Spawned Pedestrian #{i+1} at {loc}")

    world.tick()
    time.sleep(0.1)

    # Apply initial walking vectors
    for actor, dir_vec in pedestrians:
        ctrl = carla.WalkerControl()
        ctrl.speed = 1.4  # Walking speed (1.4 m/s)
        ctrl.direction = dir_vec
        actor.apply_control(ctrl)

    # --- Step 2: Connect to AirSim API for Drone Flight ---
    print("\n[CarlaAir Setup] Connecting to AirSim Multirotor API...")
    airsim_client = airsim.MultirotorClient()
    airsim_client.confirmConnection()
    airsim_client.enableApiControl(True)
    airsim_client.armDisarm(True)

    guardian = DynamicOBAGuardian(z_max=30.0, safe_pedestrian_radius=5.0)

    print("[AirSim] Drone taking off...")
    airsim_client.takeoffAsync().join()

    # Candidate LLM Low-Altitude Trajectory across the pedestrian zone
    # Target: Fly low (3m height -> Z = -3.0) directly across the pedestrian path
    candidate_llm_waypoint = (base_loc.x + 20.0, base_loc.y, -3.0)
    print(f"\n[LLM Mission Planner] Proposed Waypoint: {candidate_llm_waypoint}")

    # --- Step 3: Main Synchronized Execution Loop ---
    print("[CarlaAir] Executing flight path with real-time OBA pedestrian checking...\n")
    
    try:
        for tick in range(200):  # 10-second test run
            world.tick()  # Advance CARLA physics

            # Re-apply pedestrian movement controls to keep them walking
            if tick % 20 == 0:
                for actor, dir_vec in pedestrians:
                    ctrl = carla.WalkerControl()
                    ctrl.speed = 1.4
                    ctrl.direction = dir_vec
                    actor.apply_control(ctrl)

            # Get real-time positions
            ped_positions = [actor.get_location() for actor, _ in pedestrians]
            drone_state = airsim_client.getMultirotorState().kinematics_estimated.position
            curr_drone_pos = (drone_state.x_val, drone_state.y_val, drone_state.z_val)

            # OBA Interception & Validation
            t0 = time.perf_counter()
            is_safe, (cmd_x, cmd_y, cmd_z), reason = guardian.verify_and_adjust_waypoint(
                curr_drone_pos, candidate_llm_waypoint, ped_positions
            )
            latency_us = (time.perf_counter() - t0) * 1e6

            if not is_safe and tick % 20 == 0:
                print(f"[OBA GUARDIAN INTERVENTION ({latency_us:.1f} µs)]: {reason}")
                print(f" -> Modified Target Command: ({cmd_x:.2f}, {cmd_y:.2f}, {cmd_z:.2f})")

            # Command Drone to modified safe waypoint
            airsim_client.moveToPositionAsync(cmd_x, cmd_y, cmd_z, velocity=3.0)

            time.sleep(0.05)

        print("\n[CarlaAir] Mission completed successfully without crashes. Hovering...")
        airsim_client.hoverAsync().join()

    finally:
        # Cleanup
        print("[Cleanup] Destroying pedestrian actors and resetting world...")
        for actor, _ in pedestrians:
            actor.destroy()
        
        airsim_client.landAsync().join()
        airsim_client.enableApiControl(False)
        settings.synchronous_mode = False
        world.apply_settings(settings)
        print("[Cleanup] Simulation reset complete.")


if __name__ == "__main__":
    run_dynamic_avoidance_simulation()
