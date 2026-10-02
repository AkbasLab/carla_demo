# Phase 2: Modular Architecture & Vehicle Abstraction Layer

## Overview
Phase 2 decouples the agentic decision-making logic from simulator execution. Instead of direct API calls (e.g., `client.moveToPositionAsync()`), all drone actions flow through standard protocol interfaces. This design allows switching between live simulation environments (AirSim/CARLA) and lightweight offline test execution (Mock Adapter) without modifying high-level planner code.

---

## Directory Structure
```text
agentic_uav/
├── core/
│   └── models.py            # Dataclasses: Position3D, VehicleState, SkillCommand, SkillResult
├── simulator/
│   ├── base_adapter.py      # Abstract VehicleAdapter protocol interface
│   ├── airsim_adapter.py    # Concrete AirSim client implementation
│   └── mock_adapter.py      # Math-based mock simulator for fast unit testing
└── planners/
    ├── base_planner.py      # MissionPlanner interface protocol
    └── llama_planner.py     # Ollama/Llama 3.1 LLM prompt parser & tool mapper

# Run without simulation tools.
python -m scripts.run_modular_mission

# Run with CARLA/AirSim Simulation attached.
python -m scripts.run_modular_mission --airsim
