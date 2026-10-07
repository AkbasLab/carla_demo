import json
import time
import ollama
import re

PROMPTS_FILE = "configs/baseline_prompts.json"
OUTPUT_LOG = "docs/baseline_results.json"

SYSTEM_PROMPT = (
    "You are a dual-drone flight controller for 'Drone1' and 'Drone2'. "
    "Parse user instructions into target coordinates x, y, and z (meters, AirSim NED frame). "
    "Respond ONLY with a valid JSON array of objects with keys: "
    "\"drone\" (string: 'Drone1' or 'Drone2'), \"x\" (float), \"y\" (float), \"z\" (float)."
)

def run_benchmark():
    with open(PROMPTS_FILE, "r") as f:
        prompts = json.load(f)

    results = []
    
    print(f"Running Baseline Benchmark ({len(prompts)} prompts)...")

    for p in prompts:
        start_time = time.time()
        parsing_error = False
        valid_json = False
        raw_output = ""
        parsed_data = None

        try:
            response = ollama.chat(
                model="llama3.1:latest",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": p["prompt"]},
                ],
            )
            elapsed_time = time.time() - start_time
            raw_output = response["message"]["content"].strip()
            
            # Clean JSON formatting
            cleaned = re.sub(r'```(?:json)?\s*(.*?)\s*```', r'\1', raw_output, flags=re.DOTALL).strip()
            parsed_data = json.loads(cleaned)
            valid_json = isinstance(parsed_data, list)
            
        except Exception as e:
            elapsed_time = time.time() - start_time
            parsing_error = True
            raw_output = str(e)

        results.append({
            "id": p["id"],
            "category": p["category"],
            "prompt": p["prompt"],
            "latency_seconds": round(elapsed_time, 3),
            "valid_syntax": valid_json and not parsing_error,
            "raw_output": raw_output,
            "parsed_targets": parsed_data
        })
        print(f"[{p['id']}/10] {p['category']} - Latency: {elapsed_time:.2f}s | Valid: {valid_json and not parsing_error}")

    with open(OUTPUT_LOG, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nBaseline benchmark complete! Results saved to '{OUTPUT_LOG}'.")

if __name__ == "__main__":
    run_benchmark()
