import json
import time
import ollama
import re
import airsim

PROMPTS_FILE = "configs/baseline_prompts.json"
OUTPUT_LOG = "docs/baseline_simulation_results.json"
DRONE_NAMES = ["Drone1", "Drone2"]

SYSTEM_PROMPT = (
    "You are a dual-drone flight controller for 'Drone1' and 'Drone2'. "
    "Parse user instructions into target coordinates x, y, and z (meters, AirSim NED frame). "
    "Respond ONLY with a valid JSON array of objects with keys: "
    "\"drone\" (string: 'Drone1' or 'Drone2'), \"x\" (float), \"y\" (float), \"z\" (float)."
)

def parse_llm_json(raw_content: str):
    """Extract and parse JSON array from LLM response."""
    cleaned = re.sub(r'```(?:json)?\s*(.*?)\s*```', r'\1', raw_content, flags=re.DOTALL).strip()
    return json.loads(cleaned)

def run_simulation_benchmark():
    # 1. Initialize AirSim Connection
    print("Connecting to AirSim...")
    client = airsim.MultirotorClient()
    client.confirmConnection()

    print("Arming and enabling API control for both drones...")
    for drone in DRONE_NAMES:
        client.enableApiControl(True, vehicle_name=drone)
        client.armDisarm(True, vehicle_name=drone)

    print("Taking off both drones...")
    f1 = client.takeoffAsync(vehicle_name=DRONE_NAMES[0])
    f2 = client.takeoffAsync(vehicle_name=DRONE_NAMES[1])
    f1.join()
    f2.join()
    print("Drones airborne and hovering!\n")

    # 2. Load Prompts
    with open(PROMPTS_FILE, "r") as f:
        prompts = json.load(f)

    results = []

    try:
        for p in prompts:
            print(f"--- Prompt [{p['id']}/10]: {p['prompt']} ---")
            start_time = time.time()
            parsing_error = False
            valid_json = False
            parsed_targets = []
            execution_success = False

            # Call LLM
            try:
                response = ollama.chat(
                    model="llama3.1:latest",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": p["prompt"]},
                    ],
                )
                llm_latency = time.time() - start_time
                raw_output = response["message"]["content"].strip()
                parsed_targets = parse_llm_json(raw_output)
                valid_json = isinstance(parsed_targets, list)
                print(f"LLM Latency: {llm_latency:.2f}s | Parsed Targets: {parsed_targets}")

            except Exception as e:
                llm_latency = time.time() - start_time
                parsing_error = True
                raw_output = str(e)
                print(f"Parsing Error: {e}")

            # Execute Movements in AirSim if syntax is valid
            if valid_json and not parsing_error:
                try:
                    move_futures = []
                    for target in parsed_targets:
                        d_name = target.get("drone")
                        if d_name in DRONE_NAMES:
                            tx, ty, tz = float(target["x"]), float(target["y"]), float(target["z"])
                            print(f" Executing [{d_name}] -> moveToPositionAsync({tx}, {ty}, {tz})")
                            fut = client.moveToPositionAsync(tx, ty, tz, velocity=5, vehicle_name=d_name)
                            move_futures.append((d_name, fut))
                        else:
                            print(f" Unknown vehicle: {d_name}")

                    # Wait for drones to reach target positions in simulation window
                    for d_name, fut in move_futures:
                        fut.join()
                    
                    execution_success = True
                    print(" Movement complete.\n")
                    time.sleep(1) # Brief pause between prompts

                except Exception as e:
                    print(f" AirSim Execution Error: {e}\n")

            total_time = time.time() - start_time

            results.append({
                "id": p["id"],
                "category": p["category"],
                "prompt": p["prompt"],
                "llm_latency_s": round(llm_latency, 3),
                "total_time_s": round(total_time, 3),
                "valid_syntax": valid_json and not parsing_error,
                "execution_success": execution_success,
                "raw_output": raw_output,
                "parsed_targets": parsed_targets
            })

    finally:
        print("\nBenchmark complete. Landing drones...")
        l1 = client.landAsync(vehicle_name=DRONE_NAMES[0])
        l2 = client.landAsync(vehicle_name=DRONE_NAMES[1])
        l1.join()
        l2.join()

        for drone in DRONE_NAMES:
            client.armDisarm(False, vehicle_name=drone)
            client.enableApiControl(False, vehicle_name=drone)

        with open(OUTPUT_LOG, "w") as f:
            json.dump(results, f, indent=2)

        print(f"Simulation baseline results logged to '{OUTPUT_LOG}'.")

if __name__ == "__main__":
    run_simulation_benchmark()
