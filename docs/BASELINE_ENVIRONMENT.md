# Baseline Environment Setup (v0.1-open-loop-baseline)

## Hardware & Operating System
- **OS:** Ubuntu 20.04 LTS
- **GPU:** NVIDIA GTX 1070 (8GB VRAM)
- **RAM:** 12 GB

## Simulation Environment
- **CARLAAir Version: v0.1.7**
- **Map Name:** Town10HD 

## LLM & Local Inference Stack
- **Ollama Version:** v0.3.1
- **Model Identifier:** `llama3.1:latest` 

## AirSim Settings Configuration
Located at `~/Documents/AirSim/settings.json`:

```json
{
  "SeeDocsAt": "https://github.com/Microsoft/AirSim/blob/main/docs/settings.md",
  "SimMode": "Multirotor",
  "Vehicles": {
    "Drone1": {
      "VehicleType": "SimpleFlight",
      "X": 0, "Y": 0, "Z": 0
    },
    "Drone2": {
      "VehicleType": "SimpleFlight",
      "X": 2, "Y": 0, "Z": 0
    }
  }
}

