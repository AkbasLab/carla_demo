"""Phase 2 Groq drone-target planner using the OpenAI-compatible SDK; AirSim execution is opt-in."""
import argparse
import json
import math
import os
import time
from pathlib import Path
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = '''Plan simulated AirSim movements for Drone1 and Drone2. Respond with a JSON
object containing a "targets" array. Each array item must have exactly these
fields: "drone" (Drone1 or Drone2), "x", "y", "z" (numbers).
Use AirSim NED coordinates (negative z is above ground). Never invent
coordinates; only return explicit requested targets. If none, use an empty array.'''

def tasks(path):
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        data = data.get('prompts', data.get('tasks', []))
    if not isinstance(data, list):
        raise ValueError('Expected a list of prompts/tasks')
    for i, entry in enumerate(data, 1):
        if isinstance(entry, str):
            yield i, entry
        elif isinstance(entry, dict):
            yield entry.get('id', i), entry.get('prompt') or entry.get('task') or entry.get('mission')
        else:
            raise ValueError(f'Invalid task #{i}')

def parse_targets(content):
    data = json.loads(content)
    if not isinstance(data, dict) or not isinstance(data.get('targets'), list):
        raise ValueError('Expected JSON object with targets array')
    targets = data['targets']
    if not targets:
        raise ValueError('No explicit drone targets returned')
    clean = []
    for t in targets:
        if not isinstance(t, dict) or t.get('drone') not in ('Drone1', 'Drone2'):
            raise ValueError('Invalid drone name')
        coords = {}
        for axis in ('x', 'y', 'z'):
            value = t.get(axis)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f'Invalid {axis} coordinate')
            coords[axis] = float(value)
        clean.append({'drone': t['drone'], **coords})
    return clean

def execute_airsim(targets, velocity):
    import airsim
    client = airsim.MultirotorClient()
    client.confirmConnection()
    drones = sorted({t['drone'] for t in targets})
    enabled = []
    try:
        for drone in drones:
            client.enableApiControl(True, vehicle_name=drone)
            enabled.append(drone)
            client.armDisarm(True, vehicle_name=drone)
        for drone in drones:
            client.takeoffAsync(vehicle_name=drone).join()
        for t in targets:
            client.moveToPositionAsync(t['x'], t['y'], t['z'], velocity,
                                       vehicle_name=t['drone']).join()
    finally:
        for drone in reversed(enabled):
            try:
                client.landAsync(vehicle_name=drone).join()
                client.armDisarm(False, vehicle_name=drone)
                client.enableApiControl(False, vehicle_name=drone)
            except Exception as exc:
                print(f'AirSim cleanup warning for {drone}: {exc}')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prompts', type=Path, default=ROOT / 'configs/baseline_prompts.json')
    ap.add_argument('--output', type=Path, default=ROOT / 'docs/baseline_simulation_results_groq.json')
    ap.add_argument('--model', default=os.getenv('GROQ_MODEL', 'openai/gpt-oss-20b'))
    ap.add_argument('--airsim', action='store_true', help='Actually execute planned moves')
    ap.add_argument('--velocity', type=float, default=5.0)
    args = ap.parse_args()
    if not os.getenv('GROQ_API_KEY'):
        ap.error('Set GROQ_API_KEY in your environment')
    if args.velocity <= 0:
        ap.error('Velocity must be positive')
    results = []
    with OpenAI(
        api_key=os.environ['GROQ_API_KEY'],
        base_url='https://api.groq.com/openai/v1',
        max_retries=0,
        timeout=60,
    ) as client:
        for ident, prompt in tasks(args.prompts):
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError(f'Task {ident} has no prompt')
            start = time.perf_counter()
            item = {'id': ident, 'prompt': prompt, 'executed': False}
            try:
                response = client.chat.completions.create(
                    model=args.model, temperature=0,
                    messages=[{'role': 'system', 'content': SYSTEM},
                              {'role': 'user', 'content': prompt}],
                    response_format={'type': 'json_object'},
                )
                raw = response.choices[0].message.content or ''
                targets = parse_targets(raw)
                item.update(success=True, raw_response=raw, targets=targets)
                if args.airsim:
                    execute_airsim(targets, args.velocity)
                    item['executed'] = True
            except Exception as exc:
                item.update(success=False, error=f'{type(exc).__name__}: {exc}')
            item['latency_seconds'] = round(time.perf_counter() - start, 4)
            results.append(item)
            print(f"{ident}: {'OK' if item['success'] else 'ERROR'} ({item['latency_seconds']}s)")
            if not item['success']:
                print(f"  Error details: {item['error']}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'provider': 'groq', 'model': args.model,
                                       'airsim': args.airsim, 'results': results}, indent=2))
    print(f'Saved {args.output}')

if __name__ == '__main__':
    main()