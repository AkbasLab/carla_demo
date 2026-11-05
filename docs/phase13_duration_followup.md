# Phase 13 second suite: duration sensitivity and stall diagnostics

All 40 original pilot tests ran, but only 15 achieved the full mission objective. The second suite reruns **all 40 cases** at common 300, 600 and 1,200 second budgets, rather than rerunning only the 25 incomplete cases and combining their successes with the first batch. Each budget has its own folders, configurations, traces and metrics. The existing pilot results are preserved.

## What this study answers

Does additional mission time allow unfinished work to complete, or does the same safety/protocol blocker persist? A completed batch is not the same as successful missions. No result is marked successful solely because the runner finished.

This suite does **not** promise 40 successful missions. Architecture B deliberately never reassigns a failed actor's task. Its permanent-failure cases are useful negative controls. Stale peer-state checks, undelivered assignment transitions and active-command scheduling stalls can also persist indefinitely. These require separately validated implementation changes; disabling safety checks, silently giving B coordination, weakening the network or enlarging TTLs by hand would change the comparison.

The mission, speed, guardian, network presets, failure timing, auction windows, lease interval, inference timeouts and architecture-specific rules are unchanged. Only the configured observation budget (`ticks`) changes. Some existing implementation values depend on the horizon, including B's assignment lifetime, mission-message lifetimes and the model's remaining-time context. Consequently this is a **budget sensitivity study**, not a pure timing isolation. Every effective configuration is saved.

## Run on the Ollama machine

No CARLA or AirSim is needed: these remain mock-flight comparisons with real model inference for B/D. The shared server must have `phase12-agent:pinned` with digest `46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e`. Verification and warmup use the existing runner. A/C remain deterministic.

```bash
cd /opt/carla_demo

git pull origin main

python -u scripts/run_phase13_followup.py \
  --config configs/phase13/comparison.pinned.example.json \
  --profile pinned --durations 300 600 1200 \
  --seeds 42 --workers 1 \
  --output-dir results/phase13/duration_followup_run1
```

This schedules **120 runs**: 40 per budget for one seed. The maximum configured wall-clock observation time totals about 23.3 hours, plus warmup and processing; early completion reduces it. Runs are serial so model-server contention is not introduced.

For a smaller initial batch, run all 40 cases at 600 seconds:

```bash
python -u scripts/run_phase13_followup.py \
  --config configs/phase13/comparison.pinned.example.json \
  --profile pinned --durations 600 \
  --seeds 42 --workers 1 \
  --output-dir results/phase13/duration_600s_run1
```

That is a new 40-case pilot. The original 300-second results remain historical evidence; a newly run matched 300-second control is preferable for formal cross-budget comparisons.

To inspect the complete plan without contacting Ollama, append `--plan-only`. To execute that same plan later, repeat the identical command with `--resume` and without `--plan-only`. Resume an interrupted run the same way. Source and input mismatches are rejected. Do not change budgets/seeds on resume; choose a new root. After resolving the pilot's blockers, use multiple seeds in a new folder, for example `--seeds 42 43 44`. Three seeds remain a small exploratory sample.

## Output layout

```text
results/phase13/duration_followup_run1/
  followup_manifest.json
  budget_300s/       # original matrix rerun at this budget
  budget_600s/
  budget_1200s/
  duration_metrics.csv
  duration_metrics.json
  duration_summary.json
  REPORT.md
```

Each budget retains the normal `suite_manifest.json`, `suite_summary.json`, matching checks, and per-case summaries, arrivals, executed actions and lossless trace archives. Interrupted per-case retries remain under their original suite's retry convention.

The cross-budget outputs include:

- Task counts, full mission success and observed failure injection.
- Successful completion times; incomplete runs retain blank completion time and a censoring flag.
- Last recorded waypoint time and time since that arrival. No arrivals are represented as missing, not as a fictitious arrival at zero.
- Observed guardian reason counts, including stale-peer rejection.
- An explicit flag for incomplete B cases with an injected failure and no reassignment capability.
- The first observed successful budget, and cases completing at a larger budget after a smaller-budget incomplete run.

The diagnostic flags are evidence, not automatic root-cause determinations. These are independent runs at each budget, not continuations. Even with pinned inference and common seeds, model scheduling/context can change; exact LLM output and packet-trace equality across budgets is not asserted. Evaluate performance within matched budgets, keep every incomplete case, and report mission success separately from successful-time distributions.

If the model is unavailable, the first budget records blocked cases and the follow-up exits unsuccessfully without substituting replay or trying every remaining budget. No future-budget summaries are fabricated. `--profile validation` explicitly uses replay and simulated time (41 cases per seed including the reproducibility check); it cannot establish LLM performance.

## Verification

Focused tests cover the complete matrix at each budget, preserved architecture/network/failure settings, invalid budgets, plan-only operation, resume mismatch rejection, blocked-server behavior, real short-versus-long mock completion with archived arrivals, and retained stale-peer failures. No actual pinned-model follow-up results are claimed until this suite is run on the Ollama machine.
