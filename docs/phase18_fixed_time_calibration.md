# Prepare and test a fixed-time V4 calibration candidate

This is a new candidate scenario, not an approved calibration or final design.
Do not freeze it simply because preparation succeeds.

The original short four-drone A route finished in approximately 21.4 seconds
in an offline nominal check, so a candidate fault at 25 seconds never occurred.
The candidate therefore explicitly uses **three passes of each route**: four
tasks, twelve required waypoint visits per task, forty-eight work units total.
The waypoint coordinates and guardian bounds are unchanged; repeating visits
does not establish additional unique area coverage. Do not pool this longer
mission with the old sixteen-waypoint pilots.

Candidate parameters in `configs/phase18/calibration_v4.candidate.json`:

- V4 runtime settings: 240-second budget, 75-second leases, six-second bids.
- A common fixed policy-stop time at 40 seconds, independent telemetry alive.
- Development seeds 10, 11 and 12; reserved held-out seeds 101–120.
- C/D × teams 2/4 × nominal/severe × control/failure: 48 calibration cases.
- The existing pinned local model, network settings and safety thresholds.

An offline four-drone A check confirms that this longer candidate still owns
moving work at 40 seconds. That is not evidence that all pinned architectures
have suitable exposure. The following small checks establish that next.

## 1. Prepare the candidate and two-case checks

After installing the accompanying source changes, from `/opt/carla_demo`:

```bash
python scripts/prepare_phase18_calibration.py \
  --config configs/phase18/calibration_v4.candidate.json \
  --output-dir results/phase17/fixed_time_v4_plan1
```

This contacts no model and runs no mission. It writes the full candidate plan,
shared two/four-drone fixtures and four small batch files. Each `precheck_A.json`
through `precheck_D.json` contains just one four-drone nominal control/failure
pair at seed 10. A/B entries use the same fixtures and settings as C/D.

## 2. Run small prechecks on the execution VM

Keep Ollama running for B/D; CARLA-Air is not required. Run A first:

```bash
python -u scripts/run_phase14_experiments.py \
  --batch results/phase17/fixed_time_v4_plan1/precheck_A.json \
  --output-dir results/phase17/fixed_time_v4_precheck_A1 \
  --evaluate
```

Then test D's actual inference timing:

```bash
python -u scripts/run_phase14_experiments.py \
  --batch results/phase17/fixed_time_v4_plan1/precheck_D.json \
  --output-dir results/phase17/fixed_time_v4_precheck_D1 \
  --evaluate
```

Use the same command with `precheck_B.json` / `fixed_time_v4_precheck_B1` and
`precheck_C.json` / `fixed_time_v4_precheck_C1` for the other two architectures.
Run serially, inspect each pair, and retain every attempt. Phase 14 is used here
because it is the shared instrumented execution/evaluation engine; this does
not restart the Phase 14 research phase.

Check that the failure occurs at approximately 40 seconds while the selected
agent owns a task and is moving. Inspect `scenario_events.json`,
`flight_trace.json`, waypoint arrivals, model histories and guardian audits.
Mission completion alone does not prove valid fault exposure; a mission that
finishes before the fault is not an informative interrupted-work calibration.
If exposure is wrong, revise the candidate prospectively and use a fresh plan
and output folder. Do not modify saved results or use held-out seeds for tuning.

These small prechecks are not themselves an eligible calibration folder.

## 3. Run the declared repeated calibration only after prechecks are understood

```bash
python -u scripts/run_phase17_pilots.py run \
  --config configs/phase18/calibration_v4.candidate.json \
  --profile pinned \
  --output-dir results/phase17/main_calibration_v4_run1
```

This is the full 48-case calibration, not another two-case diagnostic. Reserve
disk space for complete prompts and traces; unlike the compact V2 diagnostic
runner, the calibration runner retains raw audited evidence. Do not launch this
large step until the small checks establish that the chosen timing is useful.
Use a new folder if this name already contains an earlier attempt. Do not use
the preparation folder from step 1 as the run output folder.

Collect under a committed, unchanged source version; changing source during
collection will block freezing. Keep the model pinned. Unsuccessful missions
remain valid outcomes and must not be rerun merely to improve the results.

## 4. Inspect eligibility and then write the rationale

```bash
python scripts/run_phase17_pilots.py analyze \
  --pilot-dir results/phase17/main_calibration_v4_run1
```

Read `analysis/calibration_report.json` and `analysis/REPORT.md`. Require actual
`eligible_for_freeze: true`, rather than merely a finished batch. If blockers
remain, investigate them; do not bypass the checks. Only then complete the four
rationale fields using this calibration's actual evidence.

The resulting freeze command is:

```bash
python scripts/run_phase17_pilots.py freeze \
  --pilot-dir results/phase17/main_calibration_v4_run1 \
  --rationale configs/phase17/final_rationale_v4.local.json \
  --output-dir results/phase17/main_calibration_v4_lock1
```

The rationale is not supplied as an assertion of success in advance. Once the
lock exists, proceed to Phase 18 extension validation and final preparation.
Neither this candidate nor its offline checks authorize main held-out execution.
