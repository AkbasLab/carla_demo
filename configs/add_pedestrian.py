import carla
import random
import time

def run_crashproof_pedestrian_test():
    print("[CarlaAir Debug] Connecting to CARLA server...")
    client = carla.Client('localhost', 2000)
    client.set_timeout(10.0)
    world = client.get_world()
    
    # 1. Enable Synchronous Mode
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05  # 20 FPS
    world.apply_settings(settings)

    bp_lib = world.get_blueprint_library()
    ped_bps = bp_lib.filter('walker.pedestrian.*')
    
    # 2. Get Spectator position to spawn in front of camera
    spectator = world.get_spectator()
    spec_transform = spectator.get_transform()
    spawn_loc = spec_transform.location + spec_transform.get_forward_vector() * 8.0
    spawn_loc.z += 1.0  # Slightly above ground to prevent mesh clipping
    
    print(f"[CarlaAir Debug] Spawning pedestrian at: {spawn_loc}")
    
    # 3. Spawn Walker Actor
    walker_bp = random.choice(ped_bps)
    walker_transform = carla.Transform(spawn_loc)
    walker_actor = world.try_spawn_actor(walker_bp, walker_transform)
    
    if not walker_actor:
        print("[ERROR] Could not spawn walker at target location.")
        return

    print(f"[SUCCESS] Spawned Walker Actor ID: {walker_actor.id}")

    # Allow physics to settle
    world.tick()
    time.sleep(0.1)

    # 4. DIRECT MOVEMENT CONTROL (Bypasses NavMesh go_to_location segfault)
    control = carla.WalkerControl()
    control.speed = 1.4  # Walking speed (1.4 m/s)
    # Move forward relative to camera orientation
    control.direction = spec_transform.get_forward_vector()
    
    # Apply direct walker control
    walker_actor.apply_control(control)
    print("[SUCCESS] Direct WalkerControl applied (NavMesh bypassed).")

    # 5. Ticking Simulation Loop
    print("\n[CarlaAir Debug] Running 10-second tick loop. Check CarlaAir window...")
    try:
        for i in range(200):  # 10 seconds
            world.tick()
            
            # Re-apply control periodically to keep pedestrian walking
            if i % 20 == 0:
                walker_actor.apply_control(control)
                pos = walker_actor.get_location()
                print(f"Tick {i}: Pedestrian Location = (X={pos.x:.2f}, Y={pos.y:.2f}, Z={pos.z:.2f})")
                
            time.sleep(0.05)
            
    finally:
        # Cleanup
        walker_actor.destroy()
        settings.synchronous_mode = False
        world.apply_settings(settings)
        print("[CarlaAir Debug] Pedestrian actor cleaned up safely.")

if __name__ == "__main__":
    run_crashproof_pedestrian_test()
