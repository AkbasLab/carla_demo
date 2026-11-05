# Testing Phases 14 and 15 together

Phase 15 extends the Phase 14 runner with `--evaluate`. Update to the Phase 15 commit before using these commands. Finish any active experiment batch before updating its checkout, or use a separate checkout so source/provenance hashes remain stable.

## Quick offline integration test

```bash
cd /opt/carla_demo
python -u scripts/run_phase14_experiments.py \
  --batch configs/phase15/paired.example.json \
  --evaluate \
  --output-dir results/phase15/combined_offline_run1
```

This runs seven experiments: nominal/moderate/severe for deterministic C and replay-based D, plus one failed-worker scenario. Each has a **40-second simulated budget** (`400 * 0.1`). It requires neither CARLA/AirSim nor Ollama. It checks collection, matching, failure preservation and evaluation, not real-model performance. Incomplete missions are valid observations; the runner does not force mission success to pass the logging test.

The definitions, numeric contract and evaluator source hash are captured **before** the first run:

```text
combined_offline_run1/
  metric_contract.json
  metric_definitions.md
  metric_registration.json
  batch_manifest.json
  <experiment_id>/manifest.json
  <experiment_id>/events.jsonl
  <experiment_id>/run/...
  metrics/
    evaluation_summary.json
    metrics.csv
    metrics.json
    <experiment_id>.metrics.json
    REPORT.md
```

Check that:

- `evaluation_summary.json` reports `prespecified: true` and `evidence_issues: 0`.
- Each no-failure degraded case identifies its corresponding nominal experiment in `primary.continuity_retention.nominal_experiment_id`.
- Successful runs have a measured completion time. Timeouts have `value_s: null`, `censored: true`, an observation endpoint and a budget.
- Collision sensing, true searched area, verified target detection and safe return remain null where not collected/defined. Route waypoint work is separately named.
- A failed worker's task without observed replacement acceptance has censored recovery, never a fabricated zero-second recovery.

Use a new output directory each time. Existing evidence and metric outputs are not overwritten.

## Real pinned-model logging and metrics

After the current Phase 13 batch finishes, use the existing pinned-model Phase 14 configuration with evaluation enabled:

```bash
python -u scripts/run_phase14_experiments.py \
  --batch configs/phase14/batch.pinned.example.json \
  --evaluate \
  --output-dir results/phase15/pinned_logging_metrics_run1
```

This is **one nominal D experiment**, maximum **600 wall-clock seconds**. It is a logging/metrics test, not the full architecture comparison. The model remains `phase12-agent:pinned`, digest `46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e`. Check the verified provider identity, `LLM_CALLED` and `LLM_USAGE` events, saved prompts/responses, response latency and token-usage completeness. The observer records counts returned by Ollama; no token estimates are inferred from text length. A failed or abandoned request can leave usage incomplete.

To measure continuity for real-model degraded conditions, add nominal/moderate/severe entries with distinct experiment IDs but otherwise matched architecture, seed, mission, budget, model, ablations, source and fault configuration. A single nominal entry cannot establish degraded performance. Do not run concurrent model benchmarks against the same shared server.

## Evaluate an existing Phase 14 batch

```bash
python -u scripts/evaluate_phase15_metrics.py \
  --input-dir results/phase14/offline_run1 \
  --output-dir results/phase15/retrospective_review1
```

A batch without the original pre-run metric registration is labeled **retrospective**. The evaluator does not backdate registration. It can read archived raw traces, keeps corrupt-case error records, and includes started attempts that were not appended to the batch manifest after a crash. Missing provenance or sensors are not replaced with invented values.

Old Phase 14 logs may lack the new own-telemetry series, final task snapshots or provider usage. The corresponding diagnostics remain unavailable. The evaluator targets Phase 14 batch directories; it does not silently reinterpret a Phase 13 suite as a Phase 14 experiment list.

## Regression checks

```bash
python -m unittest discover -s tests -p 'test_phase14_runner.py' -v
python -m unittest discover -s tests -p 'test_phase15_metrics.py' -v
```

The Phase 15 tests use hand-calculated cases for work/duplicate efficiency, completion/censoring, matched continuity and zero references, replacement acceptance versus peer acknowledgment, partition interruption/resumption, sample-based safety, retry/broadcast bytes, initialized versus missing sensors, partial provider tokens, orphaned claims, sampled distance/battery, corrupted evidence and pre-run versus retrospective evaluation.

## What the phase does not claim

The written definitions are in [Phase 15 evaluation metrics](phase15_evaluation_metrics.md). The default mission score is strict **route execution success**, not a weighted area-search score. No sensing system, calibrated energy model or live aircraft safety proof is added by evaluation. Do not pool simulated/replay timing with actual pinned-model wall-clock performance, or compare architectures using unmatched nominal references.

## Verified local results

- Repository regression suite: **227 tests passed**.
- Phase 15 focused suite: **22 tests passed**, including hand-calculated checks for every primary metric.
- Combined seven-run example: **6 successful missions**, **1 censored failure mission**, **0 evidence-consistency issues**.
- Evaluation provenance: `prespecified: true`; definitions and evaluator hash were saved before the batch.
- Actual LLM calls in this offline batch: **0**. Provider-usage instrumentation was checked with a stub response, not presented as real inference.

The implementation, definitions and tests are published together. Old pilot results have not been edited or relabeled as preregistered.
