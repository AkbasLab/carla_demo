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

🚁 Phase 3: High-Level UAV Skill Engine

Goal: Abstract low-level flight commands into deterministic, reusable autonomous skills.

    Unified Skill API: Built the SkillEngine to manage stateful UAV commands across simulation backends.

    Implemented 7 Core Skills:

        TAKE_OFF: Armed the vehicle and initiated vertical liftoff.

        GO_TO_WAYPOINT: Handled 3D spatial navigation to target coordinates.

        SEARCH_REGION: Generated automated lawnmower/grid-search patterns over target sectors.

        HOLD_POSITION: Managed station-keeping and hover stability.

        ACT_AS_RELAY: Positioned the drone to serve as an airborne communication signal bridge.

        RETURN_HOME: Autonomous navigation back to initial launch coordinates.

        LAND: Controlled descent and disarm sequence.

    Fixes & Telemetry: Standardized SkillResult metadata so every executed skill returned status, execution timestamps, position telemetry, and skill_name.

📍 Phase 4: Canonical Search-and-Relay Scenario

Goal: Build a standardized, reproducible multi-UAV mission scenario with keep-out zones and target acquisition.

    Mission Configurations (configs/missions/search_and_relay.json): Defined base station coordinates, 4 search sectors (NW, NE, SW, SE), 3D No-Fly Zones (NFZ_1), and ground-truth targets (Survivor_Alpha, Vehicle_Bravo).

    Ground-Truth Target Detection: Created ScenarioManager to trigger target acquisition using bounding box and radial proximity checks (avoiding heavy CV models during early testing).

    Geofence Enforcement: Added real-time checking to detect and log keep-out zone (NFZ) violations during flight.

    Multi-Drone Coordination: Tested cooperative workflows where Drone1 searched designated sectors while Drone2 established a comm relay position above the base station.

🧠 Phase 5: LLM Mission Planner & Autonomous Orchestration

Goal: Connect natural language commander directives to the deterministic UAV Skill Engine.

    Structured Planning Schemas (planner_models.py): Defined input/output models (HighLevelGoal, PlanStep, MissionPlan) to structure high-level directives into ordered execution steps.

    LLM Task Planner (planner.py): Built a task planner that takes natural language prompts (e.g., "Search Sector NE for survivors using Drone1 and position Drone2 as a communication relay") and decomposes them into executable SkillCommand sequences.

    Autonomous Orchestrator (orchestrator.py): Managed step-by-step mission execution, geofence pre-validation, live telemetry checks, and emergency safety protocols (triggering RETURN_HOME and LAND across all active drones if a step fails).

    Verification Script (run_phase5_planner.py): Created a unified test script to execute natural language directives end-to-end in both Mock and AirSim/CARLA environments.

## 📂 Project Structure

```text
agentic_uav/
├── configs/
│   └── missions/
│       └── search_and_relay.json    # Phase 4 mission configuration (sectors, NFZs, targets)
├── core/
│   ├── models.py                    # Data classes (SkillCommand, SkillResult, Position3D, etc.)
│   └── planner_models.py            # Phase 5 planning schemas (MissionPlan, PlanStep, HighLevelGoal)
├── control/
│   ├── skill_engine.py              # Phase 3 skill execution and sequence controller
│   ├── scenario_manager.py          # Phase 4 ground-truth detection & keep-out zone verifier
│   ├── planner.py                   # Phase 5 LLM task planner & command parser
│   └── orchestrator.py              # Phase 5 mission orchestrator & emergency handler
├── simulator/
│   ├── base_adapter.py              # Abstract Base Class for drone controllers
│   ├── airsim_adapter.py            # AirSim / CARLA simulation bridge
│   └── mock_adapter.py              # Lightweight local mock engine
scripts/
├── run_phase3_skills.py             # Phase 3 Skill Engine test suite
├── run_phase4_scenario.py           # Phase 4 Search-and-Relay scenario runner
└── run_phase5_planner.py            # Phase 5 LLM natural language mission runner

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


Simulation Videos: [https://myerauedu-my.sharepoint.com/:f:/g/personal/metint_my_erau_edu/IgDTU9PjAa2vTrS4DH4rMRclASlWYhu1K67p_uJ6AcI05-Q?e=UuyeQs](https://myerauedu-my.sharepoint.com/:f:/g/personal/metint_my_erau_edu/IgDTU9PjAa2vTrS4DH4rMRclASlWYhu1K67p_uJ6AcI05-Q?e=NtjSqZ)
