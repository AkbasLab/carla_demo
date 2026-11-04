# Phase 13 automated tests and local pinned-model commands

The suite implements the scenarios in [the architecture guide](phase13_comparison_architectures.md), with a separate folder per case. Validation and actual-model evidence are separate profiles.

## Run the real-model tests on the Ollama machine

```bash
cd /opt/carla_demo
git pull origin main

python -u scripts/run_phase13_suite.py \
  --config configs/phase13/comparison.pinned.example.json \
  --profile pinned --seeds 42 --workers 1 \
  --output-dir results/phase13/automated_pinned_run1
```

The pinned configuration selects `phase12-agent:pinned`, digest `46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e`, and a wall clock for all four architectures. A/C remain deterministic; B/D use that model. The whole matrix runs serially to avoid introducing model-server contention. It includes 40 cases per seed: 16 main architecture/condition combinations, 16 Drone1-disruption combinations, role-bearing C/D controls, five D ablations, and a role-bearing D fallback-policy control. C itself supplies the communication-health-matched deterministic comparison.

Allow several hours for the full pinned suite at the default five-minute maximum per case plus model warmup. Start with one seed. Add seeds only in a new output folder, for example `--seeds 42 43 44`; a single seed is not a statistical reliability study. Resume an interrupted suite by repeating the exact same command with `--resume`. Inputs and source hashes must match. Partial evidence is retained under a new attempt directory rather than overwritten. Model verification failure creates blocked case records, never replay substitutes or fabricated summaries.

## Run cases manually

All commands below use the same pinned model and wall-clock settings. Use a new root folder if these results already exist.

Four architectures under all communication conditions:

```bash
for condition in nominal moderate severe partitioned; do
  for architecture in A B C D; do
    python -u scripts/run_phase13_comparison.py \
      --config configs/phase13/comparison.pinned.example.json \
      --architecture "$architecture" --condition "$condition" --seed 42 \
      --output-dir "results/phase13/manual_pinned_run1/baselines/$condition/$architecture"
  done
done
```

Disruption comparisons (same failure time across architectures):

```bash
for condition in nominal moderate severe partitioned; do
  for architecture in A B C D; do
    python -u scripts/run_phase13_comparison.py \
      --config configs/phase13/comparison.pinned.example.json \
      --architecture "$architecture" --condition "$condition" --seed 42 \
      --fail-agent Drone1 --fail-at 8 \
      --output-dir "results/phase13/manual_pinned_run1/drone1_failure/$condition/$architecture"
  done
done
```

The guide's eight-second injection is a pilot parameter. Check `scenario_events.json`: a fast baseline can finish before injection, in which case it is not a failure-recovery trial. To test an earlier disruption, use `--fail-at 2` consistently across a new matched set. To exercise lease expiry specifically, establish from the control's protocol log that the failed drone already owned an unfinished task; the suite records whether the expiry path was exercised. Do not infer a lease benefit from an unexercised path.

Selected D ablations, with their controls from the runs above:

```bash
python -u scripts/run_phase13_comparison.py \
  --config configs/phase13/comparison.pinned.example.json \
  --architecture D --condition nominal --seed 42 --without-memory \
  --output-dir results/phase13/manual_pinned_run1/ablations/without_memory

python -u scripts/run_phase13_comparison.py \
  --config configs/phase13/comparison.pinned.example.json \
  --architecture D --condition moderate --seed 42 \
  --fail-agent Drone1 --fail-at 8 --without-task-leases \
  --output-dir results/phase13/manual_pinned_run1/ablations/without_task_leases

python -u scripts/run_phase13_comparison.py \
  --config configs/phase13/comparison.pinned.example.json \
  --architecture D --condition severe --seed 42 --perfect-communication \
  --output-dir results/phase13/manual_pinned_run1/ablations/perfect_communication

python -u scripts/run_phase13_comparison.py \
  --config configs/phase13/comparison.pinned.example.json \
  --architecture D --condition nominal --seed 42 --fallback-policy \
  --output-dir results/phase13/manual_pinned_run1/ablations/fallback_policy
```

Role-specific controls and ablations use the same alternate mission: two SCOUTs, Drone3 as RELAY, and Drone4 as RESERVE. They must not be compared with a four-scout control:

```bash
for architecture in C D; do
  python -u scripts/run_phase13_comparison.py \
    --config configs/phase13/comparison.roles.pinned.example.json \
    --architecture "$architecture" --condition nominal --seed 42 \
    --fail-agent Drone3 --fail-at 8 \
    --output-dir "results/phase13/manual_pinned_run1/relay_failure/control_$architecture"
done

python -u scripts/run_phase13_comparison.py \
  --config configs/phase13/comparison.roles.pinned.example.json \
  --architecture D --condition nominal --seed 42 \
  --fail-agent Drone3 --fail-at 8 --without-dynamic-roles \
  --output-dir results/phase13/manual_pinned_run1/relay_failure/without_dynamic_roles

python -u scripts/run_phase13_comparison.py \
  --config configs/phase13/comparison.roles.pinned.example.json \
  --architecture D --condition nominal --seed 42 \
  --fail-agent Drone3 --fail-at 8 --fallback-policy \
  --output-dir results/phase13/manual_pinned_run1/relay_failure/fallback_policy
```

## Optional targeted lease-expiry pair

For the default 30-second auction, an eight-second failure can happen before D owns a task. A targeted nominal pair at 65 seconds is more useful for observing lease expiry: verify the control log contains a Drone1 claim before injection and unfinished work at injection. Both runs must use the same timing.

```bash
python -u scripts/run_phase13_comparison.py \
  --config configs/phase13/comparison.pinned.example.json \
  --architecture D --condition nominal --seed 42 \
  --fail-agent Drone1 --fail-at 65 \
  --output-dir results/phase13/manual_pinned_run1/lease_pair/control

python -u scripts/run_phase13_comparison.py \
  --config configs/phase13/comparison.pinned.example.json \
  --architecture D --condition nominal --seed 42 \
  --fail-agent Drone1 --fail-at 65 --without-task-leases \
  --output-dir results/phase13/manual_pinned_run1/lease_pair/without_leases
```

Even an observed reauction does not imply that the common guardian can authorize further flight with stale peer information.

## Offline validation already performed

```bash
python -u scripts/run_phase13_suite.py \
  --profile validation --seeds 42 --workers 2 \
  --output-dir results/phase13/automated_validation_run2
```

This profile explicitly uses simulated clocks and replay for B/D. It has the same 40-case design plus an exact same-seed packet-replay check: 41 cases per seed. It does not call Ollama. It must not be combined with the pinned profile as if both were real-model measurements.

The session-workspace `results/phase13/automated_validation` dataset records 41 completed simulations, zero runtime or validation errors, 15 successful missions, 26 incomplete missions, zero mismatched input checks, and a successful same-seed replay check. There are **zero actual LLM runs**. The local pinned server was not accessible from this managed workspace, so real-model cases are to be run on the user's Ollama machine. Full offline trace archives are retained in this workspace; the repository includes the compact summary/CSV and this reproducible runner.

Coverage matters: the offline nominal independent baseline finished before its planned eight-second failure, so that injection was not observed. In the relay-failure fixture, C and the deterministic fallback replacement changed role; D's replay fixture did not. This is fixture behavior, not evidence about an LLM's role reasoning. Use per-case coverage flags before making a recovery or ablation claim. The common guardian can also prevent completion after losing fresh peer state; it is not relaxed to force success.

The repository regression suite passes 166 tests, including seven new suite tests. Tests cover the plan, paired controls, explicit profiles, trace-archive roundtrips, incomplete/censored outcomes, blocked-model records without fake summaries, replay equality and source-safe resume.

## Files for later figures

Each case has `test_definition.json`, `status.json`, `metrics.json`, `validation.json` and its own `run` directory. Large traces are stored losslessly in `run/traces.zip`; core manifests, summaries, arrivals, executed actions and scenario/controller events remain directly readable. `trace_index.json` contains checksums. No samples are smoothed or downsampled.

At suite root:

* `suite_manifest.json`: complete test list, inputs, role fixture and source hashes.
* `metrics.csv` / `metrics.json`: tidy per-run values for later figures.
* `matched_checks.json`: paired/common-input checks and replay equality.
* `suite_summary.json` / `REPORT.md`: batch outcomes and data limitations.

Unsuccessful completion times are blank, with observation end and censoring flags retained. Incomplete missions must not be plotted as successful completions at the time limit. `failure_requested` and `failure_injected` distinguish planned and observed disruptions. Delivery ratios use resolved recipient packets; pending packets remain separately counted. Application delivery latency includes polling/queueing and is not RF latency. Real inference latency is blank for replay/deterministic cases.

Figure code can read either manual raw JSON or archived suite traces:

```python
from agentic_uav.experiments.suite import read_trace
messages = read_trace(case_folder / "run", "messages.json")
flight = read_trace(case_folder / "run", "flight_trace.json")
```

A suite completing without runtime errors does not mean all missions completed, that all feature paths were exercised, or that the proposed system outperformed its controls.
