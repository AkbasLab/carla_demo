import carla
import random
import time

def run_two_pedestrians_test():
    print("[CarlaAir Debug] Connecting to CARLA server on localhost:2000...")
    client = carla.Client('localhost', 2000)
    client.set_timeout(10.0)
    world = client.get_world()
    
    # 1. Enable Synchronous Mode (Fixed 20 FPS tick)
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05
    world.apply_settings(settings)

    bp_lib = world.get_blueprint_library()
    ped_bps = bp_lib.filter('walker.pedestrian.*')
    
    # 2. Get Spectator camera transform
    spectator = world.get_spectator()
    spec_transform = spectator.get_transform()
    forward_vec = spec_transform.get_forward_vector()
    right_vec = spec_transform.get_right_vector()
    
    # Base center location 8 meters in front of spectator
    base_loc = spec_transform.location + forward_vec * 8.0
    
    # Define spawn locations for 2 pedestrians (offset left and right by 2 meters)
    spawn_locations = [
        base_loc - right_vec * 2.0 + carla.Location(z=1.0),  # Pedestrian 1 (Left)
        base_loc + right_vec * 2.0 + carla.Location(z=1.0)   # Pedestrian 2 (Right)
    ]
    
    # Define trajectory control vectors
    # Pedestrian 1 walks diagonal-right, Pedestrian 2 walks diagonal-left (Crossing paths)
    directions = [
        forward_vec + right_vec * 0.5,
        forward_vec - right_vec * 0.5
    ]
    
    spawned_walkers = []

    # 3. Spawn Both Pedestrians
    for i, loc in enumerate(spawn_locations):
        walker_bp = random.choice(ped_bps)
        if walker_bp.has_attribute('is_invincible'):
            walker_bp.set_attribute('is_invincible', 'false')
            
        transform = carla.Transform(loc)
        walker_actor = world.try_spawn_actor(walker_bp, transform)
        
        if walker_actor:
            spawned_walkers.append((walker_actor, directions[i]))
            print(f"[SUCCESS] Spawned Pedestrian #{i+1} (ID: {walker_actor.id}) at {loc}")
        else:
            print(f"[ERROR] Failed to spawn Pedestrian #{i+1}")

    if not spawned_walkers:
        print("[ERROR] No pedestrians were spawned. Exiting.")
        return

    # Settle physics in simulation world
    world.tick()
    time.sleep(0.1)

    # 4. Apply Direct Movement Controls (Bypassing NavMesh segfault)
    for walker_actor, dir_vector in spawned_walkers:
        control = carla.WalkerControl()
        control.speed = 1.4  # Standard human walking speed (1.4 m/s)
        control.direction = dir_vector
        walker_actor.apply_control(control)

    print("\n[CarlaAir Debug] 2 Pedestrians active. Ticking simulation for 10 seconds...")
    
    # 5. Simulation Ticking Loop
    try:
        for tick_idx in range(200):  # 10 seconds at 20 FPS
            world.tick()
            
            # Re-apply velocity control every 1 second (20 ticks) to maintain movement
            if tick_idx % 20 == 0:
                print(f"\n--- Simulation Tick {tick_idx} ---")
                for idx, (walker, dir_vec) in enumerate(spawned_walkers):
                    control = carla.WalkerControl()
                    control.speed = 1.4
                    control.direction = dir_vec
                    walker.apply_control(control)
                    
                    pos = walker.get_location()
                    print(f"Pedestrian #{idx+1} Position: X={pos.x:.2f}, Y={pos.y:.2f}, Z={pos.z:.2f}")
                    
            time.sleep(0.05)
            
    finally:
        # Cleanup actors cleanly
        print("\n[CarlaAir Debug] Cleaning up pedestrian actors...")
        for walker, _ in spawned_walkers:
            walker.destroy()
            
        settings.synchronous_mode = False
        world.apply_settings(settings)
        print("[CarlaAir Debug] Simulation reset safely.")

if __name__ == "__main__":
    run_two_pedestrians_test()
