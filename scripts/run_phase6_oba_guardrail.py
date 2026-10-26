import time
import json
import airsim
import numpy as np

# ==============================================================================
# 1. Operational Boundary Assurance (OBA) Runtime Safety Guardian
# ==============================================================================
class OperationalBoundaryGuardian:
    def __init__(self, z_max=30.0, d_min_obstacle=15.0, obstacle_bbox=None):
        """
        :param z_max: Max altitude ceiling in meters (positive float).
        :param d_min_obstacle: Minimum clearance distance to obstacles (meters).
        :param obstacle_bbox: Dict defining geometric blocker (x_min, x_max, y_min, y_max)
        """
        self.z_max = z_max
        self.d_min_obstacle = d_min_obstacle
        self.obstacle = obstacle_bbox or {'x_min': 35.0, 'x_max': 65.0, 'y_min': 25.0, 'y_max': 55.0}

    def verify_and_modify_waypoint(self, start_pos, target_waypoint):
        """
        Intercepts proposed waypoint target (x, y, z) and returns:
        (is_safe, modified_waypoint, intervention_reason)
        Note: AirSim uses NED frame where negative Z is altitude above ground.
        """
        x_target, y_target, z_target = target_waypoint
        
        # In AirSim NED coordinates, altitude is -Z. Convert z_target to positive altitude:
        target_alt = -z_target
        reasons = []
        modified_x, modified_y, modified_z = x_target, y_target, z_target

        # Check 1: Altitude Ceiling Enforcement (z_max)
        if target_alt > self.z_max:
            reasons.append(f"Altitude ceiling breach: {target_alt:.1f}m exceeds z_max={self.z_max:.1f}m")
            modified_z = -self.z_max  # Clamp to max ceiling in AirSim NED frame

        # Check 2: Geometric Blocker / Spatial Obstacle Avoidance
        if self._intersects_obstacle(start_pos[0], start_pos[1], x_target, y_target):
            reasons.append(f"Spatial obstacle collision detected in bounding box {self.obstacle}")
            # Reroute around the building (detour via exterior coordinate)
            modified_x = self.obstacle['x_min'] - self.d_min_obstacle
            modified_y = self.obstacle['y_max'] + self.d_min_obstacle

        is_safe = len(reasons) == 0
        return is_safe, (modified_x, modified_y, modified_z), "; ".join(reasons)

    def _intersects_obstacle(self, x1, y1, x2, y2):
        """Simple AABB check for trajectory segment intersecting building bounds."""
        x_mid, y_mid = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        in_x = self.obstacle['x_min'] <= x_mid <= self.obstacle['x_max']
        in_y = self.obstacle['y_min'] <= y_mid <= self.obstacle['y_max']
        return in_x and in_y


# ==============================================================================
# 2. CarlaAir Flight Execution & Evaluation Loop
# ==============================================================================
def run_carlaair_benchmark(enable_oba=True, log_filename="trajectory_log.json"):
    # Connect to CarlaAir Multirotor client
    print("[CarlaAir Test Harness] Connecting to CarlaAir simulator...")
    client = airsim.MultirotorClient()
    client.confirmConnection()
    client.enableApiControl(True)
    client.armDisarm(True)

    # Instantiate Guardian
    guardian = OperationalBoundaryGuardian(z_max=30.0, d_min_obstacle=10.0)

    # Initial state logging setup
    trajectory_log = {
        "mode": "Guardrailed (OBA)" if enable_oba else "Unguarded LLM",
        "time": [],
        "x": [],
        "y": [],
        "z": [],
        "interventions": []
    }

    print("[CarlaAir Test Harness] Taking off...")
    client.takeoffAsync().join()
    time.sleep(1)

    # Initial drone position
    start_state = client.getMultirotorState().kinematics_estimated.position
    start_pos = (start_state.x_val, start_state.y_val, start_state.z_val)

    # Candidate LLM Action Plan (e.g. Unconstrained direct flight to (100, 80) at 50m altitude)
    # AirSim NED Z = -50.0 corresponds to +50m altitude above ground
    candidate_llm_waypoint = (100.0, 80.0, -50.0)
    target_x, target_y, target_z = candidate_llm_waypoint

    print(f"\n[LLM Mission Planner] Proposed Candidate Action Plan: Waypoint=({target_x}, {target_y}, {target_z})")

    if enable_oba:
        t_start = time.perf_counter()
        is_safe, (target_x, target_y, target_z), reason = guardian.verify_and_modify_waypoint(start_pos, candidate_llm_waypoint)
        t_verify_ms = (time.perf_counter() - t_start) * 1000.0
        
        print(f"[OBA Guardian] Verification completed in {t_verify_ms:.4f} ms")
        if not is_safe:
            print(f"[OBA INTERVENTION]: {reason}")
            print(f"[OBA Guardian] Modified Safe Waypoint: ({target_x:.1f}, {target_y:.1f}, {target_z:.1f})")
            trajectory_log["interventions"].append({
                "time": 0.0,
                "reason": reason,
                "original": candidate_llm_waypoint,
                "modified": (target_x, target_y, target_z)
            })
    else:
        print("[WARNING] Running UNGUARDED mode! Direct LLM execution dispatched.")

    # Flight trajectory tracking loop
    print("[CarlaAir Executor] Dispatching flight command to multirotor API...")
    flight_task = client.moveToPositionAsync(target_x, target_y, target_z, velocity=5.0)

    start_time = time.time()
    
    # Non-blocking telemetry logging loop using position threshold check
    while True:
        curr_state = client.getMultirotorState().kinematics_estimated.position
        
        # Log telemetry in real time
        trajectory_log["time"].append(time.time() - start_time)
        trajectory_log["x"].append(curr_state.x_val)
        trajectory_log["y"].append(curr_state.y_val)
        trajectory_log["z"].append(-curr_state.z_val)  # Log altitude as positive height

        # Check if drone has reached within position threshold
        dx = curr_state.x_val - target_x
        dy = curr_state.y_val - target_y
        dz = curr_state.z_val - target_z
        dist_to_target = (dx**2 + dy**2 + dz**2)**0.5
        
        if dist_to_target < 1.0:  # Within 1 meter threshold of target
            break

        time.sleep(0.1)  # 10 Hz telemetry polling

    # Wait for flight task completion
    flight_task.join()

    print("[CarlaAir Executor] Target waypoint reached. Hovering and landing...")
    client.hoverAsync().join()
    time.sleep(1)
    client.landAsync().join()
    client.enableApiControl(False)

    # Save log output to JSON
    with open(log_filename, "w") as f:
        json.dump(trajectory_log, f, indent=4)
    print(f"[CarlaAir Test Harness] Simulation complete. Telemetry saved to '{log_filename}'.\n")


# ==============================================================================
# 3. Execution Driver
# ==============================================================================
if __name__ == "__main__":
    print("==========================================================")
    print(" RUNNING EXPERIMENT 1: Guardrailed Mode (LLM + OBA Layer) ")
    print("==========================================================")
    run_carlaair_benchmark(enable_oba=True, log_filename="carlaair_guardrailed_log.json")

    time.sleep(3)

    print("==========================================================")
    print(" RUNNING EXPERIMENT 2: Unguarded Mode (Standalone LLM)     ")
    print("==========================================================")
    run_carlaair_benchmark(enable_oba=False, log_filename="carlaair_unguarded_log.json")
