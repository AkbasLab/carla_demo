# Agentic UAV Simulation & Mission Framework

A modular, multi-UAV simulation framework built for autonomous search-and-relay operations using CARLA, AirSim, and Python-based Mock environments.

---

## 🛠️ Project Phases Overview

### **Phase 1: Environment Setup & Foundation**
* Configured core simulation bridge (AirSim / CARLA / Python Mock).
* Established vehicle control abstractions and position telemetry models (`Position3D`, `VehicleState`).

### **Phase 2: Core Hardware & Simulator Adapters**
* Implemented `VehicleAdapter` base class to unify simulator interfaces.
* Built `AirSimAdapter` for Unreal Engine/CARLA physics integration and `MockVehicleAdapter` for high-speed offline simulation.

### **Phase 3: High-Level UAV Skill Engine**
* Developed the `SkillEngine` to manage stateful UAV commands.
* Integrated 7 core autonomous skills:
  1. `TAKE_OFF`: System arming and vertical liftoff.
  2. `GO_TO_WAYPOINT`: 3D navigation to explicit coordinates.
  3. `SEARCH_REGION`: Automated lawnmower grid search pattern over designated 2D/3D sectors.
  4. `HOLD_POSITION`: Station keeping and altitude hold.
  5. `ACT_AS_RELAY`: Signal bridge positioning to maintain line-of-sight connectivity.
  6. `RETURN_HOME`: Autonomous navigation back to launch home position.
  7. `LAND`: Managed descent and vehicle disarming.

### **Phase 4: Canonical Search-and-Relay Scenario**
* Created mission configuration structures (`configs/missions/search_and_relay.json`) defining Base Stations, Search Sectors, No-Fly Zones (NFZs), and Targets.
* Developed `ScenarioManager` for ground-truth proximity detection (bounding-box/radial acquisition) and geofence enforcement.
* Integrated multi-drone cooperative workflows (`Drone1` conducting sector search while `Drone2` acts as a communication relay).

---

## 📂 Project Structure

agentic_uav/
├── configs/
│   └── missions/
│       └── search_and_relay.json    # Phase 4 mission configuration (sectors, NFZs, targets)
├── core/
│   └── models.py                    # Data classes (SkillCommand, SkillResult, Position3D, etc.)
├── control/
│   ├── skill_engine.py              # Skill execution and sequence controller
│   └── scenario_manager.py          # Ground-truth detection & keep-out zone verifier
├── simulator/
│   ├── base_adapter.py              # Abstract Base Class for drone controllers
│   ├── airsim_adapter.py            # AirSim / CARLA simulation bridge
│   └── mock_adapter.py              # Lightweight local mock engine
scripts/
├── run_phase3_skills.py             # Phase 3 Skill Engine test suite
└── run_phase4_scenario.py           # Phase 4 Search-and-Relay scenario runner


## 🚀 How to Reproduce Scenarios

### **Prerequisites**
Ensure dependencies are installed and the package is available in your Python path:

### Initialize CarlaAir via script on the default town:
./CarlaAir.sh Town10HD

### Phase 1: Check LLM integration and latency
python scripts/benchmark_llm_latency.py

### Phase 2: Run tasks in batch, use --airsim option for visual completion, by default running without airsim does not require GPU.
python scripts/benchmark_tasks_batch.py --airsim

### Phase 3: Test and verify all 7 atomic UAV skills in the mock environment, (again, --airsim is optional)
python -m scripts.run_phase3_skills --airsim

### Phase 4: Canonical Search-and-Relay Scenario

python -m scripts.run_phase4_scenario --airsim

⚙️ Configuration Reference (configs/missions/search_and_relay.json)

    search_sectors: Defines grid boundaries (min_x, max_x, min_y, max_y) and altitude for lawnmower coverage.

    restricted_zones: Defines 3D keep-out geofences (NFZ_1). Triggers warnings if a drone penetrates the space.

    simulated_targets: Ground-truth target coordinates and detection radii for proximity acquisition checks.
