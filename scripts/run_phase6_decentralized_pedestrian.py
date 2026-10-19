#!/usr/bin/env python
import sys
import time
import json
import random
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional, Callable

# Add project root directory to Python path for direct execution
FILE = Path(__file__).resolve()
ROOT = FILE.parents[1] if FILE.parents[1].exists() else FILE.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

try:
    import carla
    CARLA_AVAILABLE = True
except ImportError:
    CARLA_AVAILABLE = False
    print("[!] Warning: 'carla' module not found. CARLA pedestrian features will be mocked.")


# =============================================================================
# 1. Coordinate Frame Transformations
# =============================================================================
class CoordinateConverter:
    """Converts between AirSim Local NED and CARLA / Unreal Engine World Frames."""
    
    @staticmethod
    def airsim_ned_to_ue_world(ned_pos: Tuple[float, float, float], origin_offset=(0.0, 0.0, 0.0)) -> Tuple[float, float, float]:
        """
        AirSim NED: +X = North, +Y = East, +Z = Down (Ground is Z=0, Altitude is Z < 0)
        UE World:   +X = North, +Y = East, +Z = Up (Ground is Z=0, Altitude is Z > 0)
        """
        x_ned, y_ned, z_ned = ned_pos
        x_ue = x_ned + origin_offset[0]
        y_ue = y_ned + origin_offset[1]
        z_ue = -z_ned + origin_offset[2]  # Flip Z axis for upward positive height
        return (round(x_ue, 4), round(y_ue, 4), round(z_ue, 4))

    @staticmethod
    def ue_world_to_airsim_ned(ue_pos: Tuple[float, float, float], origin_offset=(0.0, 0.0, 0.0)) -> Tuple[float, float, float]:
        """Converts upward-positive UE coordinates back to AirSim NED frame."""
        x_ue, y_ue, z_ue = ue_pos
        x_ned = x_ue - origin_offset[0]
        y_ned = y_ue - origin_offset[1]
        z_ned = -(z_ue - origin_offset[2])  # Invert height back to negative Z
        return (round(x_ned, 4), round(y_ned, 4), round(z_ned, 4))


# =============================================================================
# 2. Benchmarking & Instrumentation Collector (TRA, GBR, MVL)
# =============================================================================
@dataclass
class SafetyBenchmarkCollector:
    """Collects TRA, GBR, and MVL metrics for Phase 6 evaluation."""
    total_invalid_prompts: int = 0
    correctly_rejected_prompts: int = 0
    total_executed_steps: int = 0
    boundary_violations: int = 0
    verification_latencies_ms: List[float] = field(default_factory=list)

    def record_prompt_evaluation(self, is_prompt_invalid: bool, was_rejected_by_oba: bool) -> None:
        if is_prompt_invalid:
            self.total_invalid_prompts += 1
            if was_rejected_by_oba:
                self.correctly_rejected_prompts += 1

    def record_step_execution(
        self, 
        drone_positions: Dict[str, Tuple[float, float, float]], 
        geofence_bounds: Dict[str, Tuple[float, float]],
        pedestrian_positions: List[Tuple[float, float, float]] = None,
        min_inter_drone_dist: float = 2.0,
        min_pedestrian_dist: float = 3.0
    ) -> bool:
        self.total_executed_steps += 1
        has_violation = False

        # Check 1: Geofence Bounds (UE World Frame: positive Z altitude)
        for drone_id, (x, y, z) in drone_positions.items():
            if not (geofence_bounds['x'][0] <= x <= geofence_bounds['x'][1] and
                    geofence_bounds['y'][0] <= y <= geofence_bounds['y'][1] and
                    geofence_bounds['z'][0] <= z <= geofence_bounds['z'][1]):
                has_violation = True
                break

        # Check 2: Inter-Drone Line-of-Sight Safety Margin
        if not has_violation and len(drone_positions) > 1:
            coords = list(drone_positions.values())
            for i in range(len(coords)):
                for j in range(i + 1, len(coords)):
                    if np.linalg.norm(np.array(coords[i]) - np.array(coords[j])) < min_inter_drone_dist:
                        has_violation = True
                        break

        # Check 3: Pedestrian Proximity/Collision Avoidance
        if not has_violation and pedestrian_positions:
            for d_pos in drone_positions.values():
                for p_pos in pedestrian_positions:
                    if np.linalg.norm(np.array(d_pos) - np.array(p_pos)) < min_pedestrian_dist:
                        has_violation = True
                        break

        if has_violation:
            self.boundary_violations += 1

        return has_violation

    def measure_mvl(self, func: Callable) -> Callable:
        """Measures Mean Verification Latency (MVL) in milliseconds."""
        def wrapper(*args, **kwargs):
            start = time.perf_counter_ns()
            res = func(*args, **kwargs)
            self.verification_latencies_ms.append((time.perf_counter_ns() - start) / 1e6)
            return res
        return wrapper

    def compute_metrics(self) -> Dict[str, Any]:
        tra = (self.correctly_rejected_prompts / self.total_invalid_prompts * 100) if self.total_invalid_prompts > 0 else 0.0
        gbr = (self.boundary_violations / self.total_executed_steps * 100) if self.total_executed_steps > 0 else 0.0
        mvl = float(np.mean(self.verification_latencies_ms)) if self.verification_latencies_ms else 0.0
        return {
            "TRA (%)": round(tra, 2),
            "GBR (%)": round(gbr, 2),
            "MVL (ms)": round(mvl, 2)
        }


# =============================================================================
# 3. CARLA Pedestrian Spawner
# =============================================================================
class CarlaPedestrianManager:
    """Manages spawning and tracking autonomous walking pedestrians in CARLA."""
    def __init__(self, host="localhost", port=2000):
        self.client = None
        self.world = None
        self.walkers_list = []
        self.controllers_list = []
        
        if CARLA_AVAILABLE:
            try:
                self.client = carla.Client(host, port)
                self.client.set_timeout(5.0)
                self.world = self.client.get_world()
            except Exception as e:
                print(f"[!] CARLA Connection Failed: {e}. Defaulting to mock pedestrians.")

    def spawn_pedestrians_in_front_of_drones(
        self, 
        drone_positions_ue: List[Tuple[float, float, float]], 
        distance_ahead: float = 5.0
    ):
        """Spawns pedestrians on the ground directly ahead of target drone coordinates."""
        if not self.world:
            return
        
        bp_lib = self.world.get_blueprint_library()
        walker_bps = bp_lib.filter('walker.pedestrian.*')
        controller_bp = bp_lib.find('controller.ai.walker')
        
        batch = []
        for x, y, z in drone_positions_ue:
            # 1. Position pedestrian on the ground (Z=0.5) shifted ahead on X axis
            spawn_x = x + distance_ahead
            spawn_y = y
            spawn_point = carla.Transform(carla.Location(x=spawn_x, y=spawn_y, z=0.5))
            
            walker_bp = random.choice(walker_bps)
            batch.append(carla.command.SpawnActor(walker_bp, spawn_point))
        
        # 2. Spawn and attach AI controllers
        results = self.client.apply_batch_sync(batch, True)
        self.walkers_list = [r.actor_id for r in results if not r.error]

        batch = [carla.command.SpawnActor(controller_bp, carla.Transform(), w_id) for w_id in self.walkers_list]
        results = self.client.apply_batch_sync(batch, True)
        self.controllers_list = [r.actor_id for r in results if not r.error]

        # 3. Direct pedestrian AI to walk toward ground target under the drone
        all_controllers = self.world.get_actors(self.controllers_list)
        for idx, controller in enumerate(all_controllers):
            controller.start()
            target_x, target_y, _ = drone_positions_ue[idx % len(drone_positions_ue)]
            controller.go_to_location(carla.Location(x=target_x, y=target_y, z=0.0))
            controller.set_max_speed(1.4)

    def get_pedestrian_positions(self) -> List[Tuple[float, float, float]]:
        if not self.world:
            # Mock positions for testing without CARLA running
            return [(0.05, 0.05, 0.0)]
            
        positions = []
        for walker in self.world.get_actors(self.walkers_list):
            loc = walker.get_location()
            positions.append((round(loc.x, 4), round(loc.y, 4), round(loc.z, 4)))
        return positions

    def cleanup(self):
        if self.client and (self.walkers_list or self.controllers_list):
            for controller in self.world.get_actors(self.controllers_list):
                controller.stop()
            self.client.apply_batch([carla.command.DestroyActor(x) for x in self.controllers_list + self.walkers_list])
            print("[+] Cleaned up CARLA pedestrian actors.")


# =============================================================================
# 4. OBA Runtime Safety Guardian
# =============================================================================
class OperationalBoundaryGuardian:
    """Layer 1 and Layer 2 Runtime Verification Safety Harness."""
    def verify_plan(
        self, 
        action_plan: Dict[str, Any], 
        geofence_ue: Dict[str, Tuple[float, float]]
    ) -> Tuple[bool, str]:
        time.sleep(0.012)  # Simulate real-time verification processing delay
        
        target = action_plan.get("target_coordinates_ue", (0, 0, 0))
        x, y, z = target
        
        # Verify geofence bounds in UE World Frame
        if not (geofence_ue['x'][0] <= x <= geofence_ue['x'][1] and
                geofence_ue['y'][0] <= y <= geofence_ue['y'][1] and
                geofence_ue['z'][0] <= z <= geofence_ue['z'][1]):
            return False, "OBA REJECTED: Waypoint breaches geofence boundary."
            
        return True, "OBA APPROVED: Waypoint cleared by safety guardian."


# =============================================================================
# 5. Main Phase 6 Decentralized Execution Pipeline
# =============================================================================
def main():
    print("=" * 75)
    print("      CARLAAIR PHASE 6: DECENTRALIZED MULTI-DRONE OBA EVALUATION")
    print("=" * 75)

    # Output log paths
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    json_log_path = log_dir / "phase6_decentralized_flight_log.json"

    # Setup Components
    collector = SafetyBenchmarkCollector()
    oba = OperationalBoundaryGuardian()
    oba.verify_plan = collector.measure_mvl(oba.verify_plan)  # Instrument MVL
    pedestrian_mgr = CarlaPedestrianManager()


    # Test Scenarios
    test_episodes = [
        # Normal, safe multi-drone flight maneuver
        {
            "is_invalid": False,
            "plan": {
                "Drone1": {"target_coordinates_ue": (-0.051, 0.052, 29.187)},
                "Drone2": {"target_coordinates_ue": (5.0, 5.0, 25.0)}
            }
        },
        # Out-of-bounds invalid flight plan (Geofence breach attempt)
        {
            "is_invalid": True,
            "plan": {
                "Drone1": {"target_coordinates_ue": (150.0, 100.0, 20.0)},
                "Drone2": {"target_coordinates_ue": (100.0, 100.0, 5.0)}  # Crash course below ground
            }
        }
    ]
    # Extracts target drone positions first, then spawns pedestrians 5m ahead
    target_drone_positions = [
        d_data["target_coordinates_ue"] 
        for episode in test_episodes 
        for d_data in episode["plan"].values()
    ]

    pedestrian_mgr.spawn_pedestrians_in_front_of_drones(
        drone_positions_ue=target_drone_positions,
        distance_ahead=5.0  # Spawns 5 meters directly ahead on X axis
    )
    # Operational Boundaries (UE World Frame: Height Z is Positive)
    geofence_ue = {
        'x': (-500.0, 500.0),
        'y': (-500.0, 500.0),
        'z': (1.0, 50.0)  # Min altitude 1m, max 50m
    }

    # Perceived initial state (incorporating user's baseline telemetry)
    initial_perceived_telemetry = {
        "x_val": -0.05123046785593033,
        "y_val": 0.05228515341877937,
        "z_val": 29.187564849853516  # Corrected upward-positive altitude in UE frame
    }



    flight_history = []

    try:
        for episode_idx, episode in enumerate(test_episodes, 1):
            is_invalid = episode["is_invalid"]
            plan = episode["plan"]

            print(f"\n--- [Episode {episode_idx}] Executing Multi-Drone Decentralized Step ---")

            # Get pedestrian telemetry
            pedestrian_coords = pedestrian_mgr.get_pedestrian_positions()

            for drone_id, d_data in plan.items():
                ue_coords = d_data["target_coordinates_ue"]
                ned_coords = CoordinateConverter.ue_world_to_airsim_ned(ue_coords)

                # 1. Run OBA Guardrail Verification
                approved, reason = oba.verify_plan(d_data, geofence_ue)
                collector.record_prompt_evaluation(is_prompt_invalid=is_invalid, was_rejected_by_oba=(not approved))

                # Console Stream output
                print(f"[{drone_id}] Proposed Waypoint (UE): {ue_coords} | AirSim (NED): {ned_coords}")
                print(f"  └─ OBA Status: {'[APPROVED]' if approved else '[REJECTED]'} - {reason}")

                # 2. Record Flight Coordinates to JSON history if approved
                step_record = {
                    "episode": episode_idx,
                    "drone_id": drone_id,
                    "status": "APPROVED" if approved else "REJECTED",
                    "coordinates_ue": {"x": ue_coords[0], "y": ue_coords[1], "z": ue_coords[2]},
                    "coordinates_ned": {"x": ned_coords[0], "y": ned_coords[1], "z": ned_coords[2]},
                    "pedestrians_detected": len(pedestrian_coords),
                    "timestamp": time.time()
                }
                flight_history.append(step_record)

                if approved:
                    collector.record_step_execution(
                        drone_positions={drone_id: ue_coords},
                        geofence_bounds=geofence_ue,
                        pedestrian_positions=pedestrian_coords
                    )

        # Save coordinate logs to JSON file
        with open(json_log_path, 'w') as f:
            json.dump(flight_history, f, indent=4)
        print(f"\n[+] Successfully logged coordinate telemetry to: {json_log_path}")

        # Compute metrics
        metrics = collector.compute_metrics()
        print("\n" + "=" * 75)
        print("                  FINAL OBA BENCHMARK METRICS")
        print("=" * 75)
        print(json.dumps(metrics, indent=4))
        print("=" * 75)

    finally:
        pedestrian_mgr.cleanup()


if __name__ == "__main__":
    main()
