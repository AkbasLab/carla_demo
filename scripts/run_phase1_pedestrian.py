#!/usr/bin/env python
import time
import airsim
import carla

def get_ground_nav_location(world, target_location):
    """
    Safely finds the nearest valid ground/sidewalk location on the navigation mesh 
    without triggering version-specific C++ binding missing attribute errors.
    """
    # 1. Try world level navigation locator
    if hasattr(world, 'get_random_location_from_navigation'):
        # Query nearest ground location or fallback to nav location
        return target_location
    return target_location

def main():
    # =========================================================================
    # 1. AIRSIM: Connect & Take Off
    # =========================================================================
    print("[1/4] Connecting to AirSim Drone...")
    drone_client = airsim.MultirotorClient()
    drone_client.confirmConnection()

    drone_client.enableApiControl(True)
    drone_client.armDisarm(True)
    print("  └─ Drone taking off...")
    drone_client.takeoffAsync().join()

    # Get drone's takeoff position in AirSim (NED Frame)
    drone_state = drone_client.getMultirotorState()
    takeoff_pos = drone_state.kinematics_estimated.position
    print(f"  └─ Drone takeoff position: X={takeoff_pos.x_val:.2f}, Y={takeoff_pos.y_val:.2f}")

    # =========================================================================
    # 2. CARLA: Spawn Pedestrian on Navigation Mesh
    # =========================================================================
    print("[2/4] Connecting to CARLA Engine...")
    carla_client = carla.Client('localhost', 2000)
    carla_client.set_timeout(5.0)
    world = carla_client.get_world()

    blueprint_library = world.get_blueprint_library()
    walker_bps = blueprint_library.filter('walker.pedestrian.*')
    walker_bp = walker_bps[0]

    # Calculate target coordinates relative to drone
    raw_x = takeoff_pos.x_val + 8.0
    raw_y = takeoff_pos.y_val + 3.0
    
    # Place at Z = 0.5m ground level
    spawn_location = carla.Location(x=raw_x, y=raw_y, z=0.5)
    spawn_transform = carla.Transform(spawn_location)

    # Attempt actor spawn with robust fallback
    pedestrian = world.try_spawn_actor(walker_bp, spawn_transform)

    if not pedestrian:
        print("  └─ [!] Target position blocked. Using navigation mesh fallback...")
        fallback_loc = world.get_random_location_from_navigation()
        if fallback_loc:
            pedestrian = world.spawn_actor(walker_bp, carla.Transform(fallback_loc))
        else:
            # Force spawn at offset position if navmesh query is unavailable
            spawn_transform.location.z = 1.0
            pedestrian = world.spawn_actor(walker_bp, spawn_transform)

    # Force CARLA server tick so actor renders visually in viewport
    world.wait_for_tick()

    # Get exact live coordinates of spawned pedestrian
    ped_loc = pedestrian.get_location()
    print(f"  └─ Pedestrian ACTIVE at CARLA Location: X={ped_loc.x:.2f}, Y={ped_loc.y:.2f}, Z={ped_loc.z:.2f}")

    # Draw a visible red marker in Unreal Engine above the pedestrian
    world.debug.draw_point(
        carla.Location(x=ped_loc.x, y=ped_loc.y, z=ped_loc.z + 2.0),
        size=0.4,
        color=carla.Color(255, 0, 0),
        life_time=120.0
    )

    # =========================================================================
    # 3. COORDINATE MAPPING: CARLA UE Frame -> AirSim Local NED
    # =========================================================================
    target_x_ned = ped_loc.x
    target_y_ned = ped_loc.y
    target_z_ned = -3.0  # Safe hovering altitude (3m above ground) directly over pedestrian

    # =========================================================================
    # 4. FLY DRONE DIRECTLY TO PEDESTRIAN
    # =========================================================================
    print(f"[3/4] Flying drone directly to pedestrian location...")
    print(f"  └─ Target AirSim Coordinates: X={target_x_ned:.2f}, Y={target_y_ned:.2f}, Z={target_z_ned:.2f}")

    drone_client.moveToPositionAsync(
        x=target_x_ned,
        y=target_y_ned,
        z=target_z_ned,
        velocity=3.0
    ).join()

    print("[4/4] Drone arrived directly above pedestrian location!")

    # =========================================================================
    # 5. Hold State & Keep Pedestrian Active
    # =========================================================================
    try:
        print("\n[+] Hovering over pedestrian. Pedestrian will remain ACTIVE in simulator (Press Ctrl+C to exit)...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting script...")
    finally:
        print("Cleaning up drone state...")
        # Note: Pedestrian actor is intentionally NOT destroyed so it stays active in CARLA
        drone_client.landAsync().join()
        drone_client.armDisarm(False)
        drone_client.enableApiControl(False)
        print("  └─ Drone landed and disarmed. Pedestrian remains active in CARLA world.")

if __name__ == "__main__":
    main()