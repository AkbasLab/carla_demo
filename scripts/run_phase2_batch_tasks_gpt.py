"""Run phase 2 with OpenAI; add --airsim to execute targets in the simulator.

Install: python -m pip install openai
Set OPENAI_API_KEY, then run:
    python scripts/run_phase2_openai_batch_tasks.py --model gpt-4.1-mini
AirSim mode also requires the airsim package and a running simulator with
Drone1 and Drone2. API calls incur usage charges, including in dry-run mode.
"""

import argparse
import json
import math
import os
from pathlib import Path
import re
import time

if __package__:
    from .run_phase1_openai_latency import ROOT, SYSTEM_PROMPT
else:
    from run_phase1_openai_latency import ROOT, SYSTEM_PROMPT

DRONE_NAMES = ("Drone1", "Drone2")


def parse_targets(raw_output):
    cleaned = re.sub(
        r"```(?:json)?\s*(.*?)\s*```", r"\1", raw_output, flags=re.DOTALL
    ).strip()
    targets = json.loads(cleaned)
    if not isinstance(targets, list) or not targets:
        raise ValueError("Expected a nonempty JSON array of targets")
    validated = []
    for target in targets:
        if not isinstance(target, dict) or target.get("drone") not in DRONE_NAMES:
            raise ValueError("Each target must identify Drone1 or Drone2")
        coordinates = {}
        for axis in ("x", "y", "z"):
            value = target.get(axis)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Target {axis} must be a number")
            if not math.isfinite(value):
                raise ValueError(f"Target {axis} must be finite")
            coordinates[axis] = float(value)
        validated.append({"drone": target["drone"], **coordinates})
    return validated


def run_benchmark(openai_client, model, prompts_file, output_log, simulator=None):
    with open(prompts_file, encoding="utf-8") as f:
        prompts = json.load(f)
    results = []
    controlled = []
    cleanup_errors = []
    output_log = Path(output_log)
    output_log.parent.mkdir(parents=True, exist_ok=True)
    try:
        if simulator is not None:
            simulator.confirmConnection()
            for drone in DRONE_NAMES:
                controlled.append(drone)
                simulator.enableApiControl(True, vehicle_name=drone)
                simulator.armDisarm(True, vehicle_name=drone)
            futures = [simulator.takeoffAsync(vehicle_name=d) for d in DRONE_NAMES]
            for future in futures:
                future.join()

        for index, prompt in enumerate(prompts, 1):
            start = time.perf_counter()
            result = {
                "id": prompt["id"],
                "category": prompt["category"],
                "prompt": prompt["prompt"],
                "model": model,
                "dry_run": simulator is None,
                "valid_syntax": False,
                "execution_success": False,
                "raw_output": "",
                "parsed_targets": [],
            }
            try:
                response = openai_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt["prompt"]},
                    ],
                )
                result["llm_latency_s"] = round(time.perf_counter() - start, 3)
                result["raw_output"] = (response.choices[0].message.content or "").strip()
                targets = parse_targets(result["raw_output"])
                result["parsed_targets"] = targets
                result["valid_syntax"] = True
                if simulator is not None:
                    # Join each move so repeated targets for one drone execute in order.
                    for target in targets:
                        simulator.moveToPositionAsync(
                            target["x"], target["y"], target["z"],
                            velocity=5, vehicle_name=target["drone"],
                        ).join()
                    result["execution_success"] = True
            except Exception as exc:
                result["error"] = str(exc)
            result.setdefault("llm_latency_s", round(time.perf_counter() - start, 3))
            result["total_time_s"] = round(time.perf_counter() - start, 3)
            results.append(result)
            print(
                f"[{index}/{len(prompts)}] {prompt['category']} | "
                f"LLM: {result['llm_latency_s']:.3f}s | "
                f"Valid: {result['valid_syntax']} | "
                f"Execution: {'skipped (dry run)' if simulator is None else result['execution_success']}"
            )
    finally:
        # Attempt all cleanup steps even if another vehicle or operation fails.
        for drone in controlled:
            try:
                simulator.landAsync(vehicle_name=drone).join()
            except Exception as exc:
                cleanup_errors.append(f"{drone} landing: {exc}")
                # Leave the drone armed if landing could not be confirmed.
                continue
            for operation in (simulator.armDisarm, simulator.enableApiControl):
                try:
                    operation(False, vehicle_name=drone)
                except Exception as exc:
                    cleanup_errors.append(f"{drone} {operation.__name__}: {exc}")
        with output_log.open("w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"Results saved to '{output_log}'.")
        for error in cleanup_errors:
            print(f"Cleanup error: {error}")
    if cleanup_errors:
        raise RuntimeError("AirSim cleanup failed; inspect the simulator and reported errors")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
    parser.add_argument("--airsim", action="store_true", help="Execute movements in AirSim")
    parser.add_argument("--prompts-file", type=Path, default=ROOT / "configs/baseline_prompts.json")
    parser.add_argument("--output-log", type=Path, default=ROOT / "docs/baseline_simulation_results_openai.json")
    args = parser.parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        parser.error("Set the OPENAI_API_KEY environment variable before running.")
    try:
        from openai import OpenAI
    except ImportError:
        parser.error("Install the OpenAI SDK: python -m pip install openai")
    simulator = None
    if args.airsim:
        try:
            import airsim
        except ImportError:
            parser.error("AirSim mode requires the airsim package.")
        simulator = airsim.MultirotorClient()
    print("Mode: AirSim execution" if args.airsim else "Mode: dry run (OpenAI calls only)")
    with OpenAI(max_retries=0, timeout=60.0) as client:
        results = run_benchmark(client, args.model, args.prompts_file, args.output_log, simulator)
    if any("error" in result for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
