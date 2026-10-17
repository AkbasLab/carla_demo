"""Phase 1 Groq latency benchmark using the OpenAI-compatible SDK. Run from the carla_demo repository."""
import argparse
import json
import os
import statistics
import time
from pathlib import Path
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]

def prompts(path):
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        data = data.get('prompts', data.get('tasks', []))
    if not isinstance(data, list):
        raise ValueError('Expected a JSON list or an object containing prompts/tasks')
    for index, entry in enumerate(data, 1):
        if isinstance(entry, str):
            yield index, entry
        elif isinstance(entry, dict):
            yield entry.get('id', index), entry.get('prompt') or entry.get('task') or entry.get('mission')
        else:
            raise ValueError(f'Invalid prompt #{index}')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prompts', type=Path, default=ROOT / 'configs/baseline_prompts.json')
    ap.add_argument('--output', type=Path, default=ROOT / 'docs/baseline_results_groq.json')
    ap.add_argument('--model', default=os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile'))
    args = ap.parse_args()
    if not os.getenv('GROQ_API_KEY'):
        ap.error('Set GROQ_API_KEY in your environment')
    results = []
    with OpenAI(
        api_key=os.environ['GROQ_API_KEY'],
        base_url='https://api.groq.com/openai/v1',
        max_retries=0,
        timeout=60,
    ) as client:
        for ident, prompt in prompts(args.prompts):
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError(f'Prompt {ident} is empty')
            start = time.perf_counter()
            item = {'id': ident, 'prompt': prompt}
            try:
                response = client.chat.completions.create(
                    model=args.model, temperature=0,
                    messages=[
                        {'role': 'system', 'content': 'You are a UAV mission planning assistant. Respond concisely and do not invent mission details.'},
                        {'role': 'user', 'content': prompt},
                    ],
                )
                content = response.choices[0].message.content or ''
                item.update(success=True, response=content,
                            usage=response.usage.model_dump() if response.usage else None)
                try:
                    item['parsed_json'] = json.loads(content)
                except json.JSONDecodeError:
                    item['parsed_json'] = None
            except Exception as exc:
                item.update(success=False, error=f'{type(exc).__name__}: {exc}')
            item['latency_seconds'] = round(time.perf_counter() - start, 4)
            results.append(item)
            print(f"{ident}: {item['latency_seconds']}s ({'OK' if item['success'] else 'ERROR'})")
            if not item['success']:
                print(f"  Error details: {item['error']}")
    values = [r['latency_seconds'] for r in results if r['success']]
    report = {'provider': 'groq', 'model': args.model, 'results': results,
              'mean_latency_seconds': statistics.mean(values) if values else None,
              'median_latency_seconds': statistics.median(values) if values else None}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    print(f'Saved {args.output}')

if __name__ == '__main__':
    main()