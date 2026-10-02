---

### Step 1.3: Create and Run the Baseline Test Suite

Create a benchmark script to run 10 fixed natural language commands. This logs syntactic validity, execution time, and parsing errors so you can compare future multi-agent architectures against this baseline.

#### 1. Define the 10 Benchmark Commands (`configs/baseline_prompts.json`)
Create a file defining your benchmark dataset:

Initial coordinates: X=-0.05, Y=0.05, Z=27.65

```json
[
  {"id": 1, "category": "single_drone_simple", "prompt": "Drone1 move to 10, 5, -5"},
  {"id": 2, "category": "single_drone_altitude", "prompt": "Fly Drone2 up to altitude -15"},
  {"id": 3, "category": "dual_drone_simultaneous", "prompt": "Send Drone1 to 10, 0, -10 and Drone2 to -5, 10, -8"},
  {"id": 4, "category": "multi_step_movement", "prompt": "Drone1 fly 20 meters forward then climb 5 meters up"},
  {"id": 5, "category": "return_to_origin", "prompt": "Move Drone1 back to 0, 0, -2 and Drone2 to 2, 0, -2"},
  {"id": 6, "category": "ambiguous_wording", "prompt": "Have Drone1 check out the area on the right near 15, 15, -5"},
  {"id": 7, "category": "altitude_hold", "prompt": "Drone2 maintain position at current location but drop to -3 meters"},
  {"id": 8, "category": "quad_sector_split", "prompt": "Drone1 search sector 10, 10, -5 while Drone2 searches -10, -10, -5"},
  {"id": 9, "category": "relative_direction", "prompt": "Move Drone1 left 5 meters and Drone2 right 10 meters"},
  {"id": 10, "category": "land_command", "prompt": "Return both drones to base and prepare to land"}
]
