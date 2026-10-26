# Experiments A and C: OBA effectiveness and latency

Run from the repository root:

```bash
python scripts/run_oba_ac_benchmark.py --random-cases 200 --repeats 1000 --seed 42
```

No simulator or LLM API key is needed. The benchmark uses deterministic synthetic waypoint cases and a **new exact 2D segment/AABB intersection check**, not the original midpoint heuristic. The baseline is a *counterfactual geometric unguarded proposal*; it is **not an observed simulator collision**. The guardian rejects unsafe candidate segments rather than repairing trajectories.

Outputs: `results/oba_ac/cases.csv`, `latency_scaling.csv`, and `summary.json`.

**Experiment A:** unsafe proposal rate, guarded unsafe dispatch rate, intervention rate, unsafe-command prevention rate, false-rejection rate. Denominators are respectively all proposals, all proposals, all proposals, unsafe proposals, safe proposals. These are proposal-level results, **not** executed-step Guardrail Breach Rate (GBR) or mission completion.

**Experiment C:** per-call Python guardian wall-clock latency (microseconds) across 1, 2, 4, 8, and 16 obstacles; mean, median, P95, P99, max. Latency excludes LLM inference, RPC, and telemetry. Report machine, Python version, repetitions, and seed when using results in the paper.

For a physical simulation claim, run paired AirSim/CARLA flights with the same seeds, reset world state, log time-series trajectories and collision events, and verify clearances along the *executed* trajectory. This benchmark alone cannot establish zero physical breaches.
