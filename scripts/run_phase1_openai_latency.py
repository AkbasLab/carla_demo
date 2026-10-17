"""Benchmark OpenAI with the same inputs and result fields as phase 1.

Setup: python -m pip install openai
Set OPENAI_API_KEY in your environment, then run:
    python scripts/run_phase1_openai_latency.py --model gpt-4.1-mini

API calls incur usage charges. No simulator is required.
"""

import argparse
import json
import os
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PROMPT = (
    "You are a dual-drone flight controller for 'Drone1' and 'Drone2'. "
    "Parse user instructions into target coordinates x, y, and z (meters, AirSim NED frame). "
    "Respond ONLY with a valid JSON array of objects with keys: "
    "\"drone\" (string: 'Drone1' or 'Drone2'), \"x\" (float), \"y\" (float), \"z\" (float)."
)


def run_benchmark(client, model, prompts_file, output_log):
    with open(prompts_file, encoding="utf-8") as f:
        prompts = json.load(f)

    results = []
    print(f"Running OpenAI Benchmark ({len(prompts)} prompts, model={model})...")
    for index, p in enumerate(prompts, 1):
        start_time = time.perf_counter()
        valid_json = False
        raw_output = ""
        parsed_data = None
        error = None
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": p["prompt"]},
                ],
            )
            elapsed_time = time.perf_counter() - start_time
            raw_output = (response.choices[0].message.content or "").strip()
            cleaned = re.sub(
                r"```(?:json)?\s*(.*?)\s*```", r"\1", raw_output, flags=re.DOTALL
            ).strip()
            parsed_data = json.loads(cleaned)
            valid_json = isinstance(parsed_data, list)
        except Exception as exc:
            elapsed_time = time.perf_counter() - start_time
            error = str(exc)

        result = {
            "id": p["id"],
            "category": p["category"],
            "prompt": p["prompt"],
            "latency_seconds": round(elapsed_time, 3),
            "valid_syntax": valid_json,
            "raw_output": raw_output,
            "parsed_targets": parsed_data,
            "model": model,
        }
        if error is not None:
            result["error"] = error
        results.append(result)
        print(
            f"[{index}/{len(prompts)}] {p['category']} - "
            f"Latency: {elapsed_time:.2f}s | Valid: {valid_json}"
        )

    output_log = Path(output_log)
    output_log.parent.mkdir(parents=True, exist_ok=True)
    with output_log.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nOpenAI benchmark complete! Results saved to '{output_log}'.")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
    parser.add_argument("--prompts-file", type=Path, default=ROOT / "configs/baseline_prompts.json")
    parser.add_argument("--output-log", type=Path, default=ROOT / "docs/baseline_results_openai.json")
    args = parser.parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        parser.error("Set the OPENAI_API_KEY environment variable before running.")
    try:
        from openai import OpenAI
    except ImportError:
        parser.error("Install the OpenAI SDK: python -m pip install openai")

    # Disable automatic retries so each timing measures one request attempt.
    with OpenAI(max_retries=0, timeout=60.0) as client:
        results = run_benchmark(client, args.model, args.prompts_file, args.output_log)
    if any("error" in result for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
