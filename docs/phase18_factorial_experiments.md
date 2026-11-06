# Phase 18 — main factorial experiment

This phase adds a prospective factorial definition, validation gates, a resumable runner and replication accounting. It does **not** establish the Phase 18 exit criterion by itself. That requires collecting the declared number of technically valid replications in every selected cell. Mission failures remain valid observations.

## Design and scope

| Factor | Initial design |
| --- | --- |
| Architecture | A centralized rules; B independent persistent LLM agents; C decentralized rules; D decentralized LLM agents |
| Team size | 2 and 4 |
| Application network | Nominal, moderate, severe, temporary partition |
| Vehicle fault | None; one actor silenced at the frozen simulation time |
| Held-out seeds | 101–120, common across all cells |
| Replications | 20 per cell |

This is **64 cells / 1,280 planned runs**. The optional eight-drone configuration produces **96 cells / 1,920 runs**. Eight-drone validation starts only after the smaller cases have technically valid logs and sufficiently stable nominal references. The fixed workload remains four tasks; B has four idle agents in the eight-drone case because it deliberately does not coordinate or reassign work. This is a fixed-work scalability experiment, not an increasing-workload experiment.

The shared backend is the existing kinematic mock-flight adapter. CARLA-Air is not required. The guardian, skills, transport, scenario schedule and metric definitions are shared. This does not establish live flight, real RF performance, sensed area coverage, target detection or verified safe return. Those metrics remain unavailable where the benchmark has no corresponding observation.

The two/four-drone missions come from the verified Phase 17 lock. The eight-drone fixture adds a second row of starting positions without enlarging the guardian bounds; it must pass extension validation before main use. No safety envelope is relaxed to obtain completion.

## Before using held-out seeds

Install/commit the Phase 18 implementation **before** collecting the pinned calibration used for its lock. Source hashes are frozen, so changing the shared implementation afterward invalidates that lock.

The historical Phase 17 example reserves only ten seeds. The new `configs/phase18/calibration_pilot.example.json` reserves twenty, without rewriting historical pilot results. Run the actual-model pilot on the machine running the pinned Ollama model:

```bash
python -u scripts/run_phase17_pilots.py run \
  --config configs/phase18/calibration_pilot.example.json \
  --profile pinned --output-dir results/phase17/main_calibration_run1
```

Inspect its report and timelines. If calibration is eligible, use the existing Phase 17 freeze command with a substantive rationale JSON:

```bash
python -u scripts/run_phase17_pilots.py freeze \
  --pilot-dir results/phase17/main_calibration_run1 \
  --rationale configs/phase17/final_rationale.local.json \
  --output-dir results/phase17/main_calibration_lock1
```

A missing lock, inadequate calibration, replay evidence masquerading as inference, or an insufficient reserved seed pool blocks the main experiment. This is an implementation prerequisite, not a request for manual approval.

The supplied profiles and partition interval are **candidate parameters**, not a claim that calibration is finished. There is no validated final Phase 17 lock in the supplied evidence. In particular, fixed fault timing must be meaningful for the fast centralized architecture as well as the slower auction-based architectures. If A finishes before the fault, or C/D have not begun assigned work, calibrate the shared task rules/scenario on development or validation data before freezing. Do not change it after viewing held-out outcomes.

## Commands

Use a fresh output directory for planning, validation and freezing; only `run` resumes an existing directory. From the repository root, create a draft without contacting Ollama or consuming held-out data:

```bash
python -u scripts/run_phase18_factorial.py plan \
  --config configs/phase18/factorial.example.json \
  --output-dir results/phase18/draft_local_run1
```

The draft reports the matrix, replication count and exclusion rules. To include eight drones, use `configs/phase18/factorial.eight.example.json` consistently in the following steps; this is a separate prospective definition, not an alteration of an existing main run.

Validate A/B/C/D, all four profiles and both fault conditions on **validation seeds 44–46**, separate from pilot seeds 41–43 and held-out seeds 101–120:

```bash
python -u scripts/run_phase18_factorial.py validate \
  --config configs/phase18/factorial.example.json \
  --phase17-lock results/phase17/main_calibration_lock1 \
  --output-dir results/phase18/extension_validation_run1
```

Validation saves a directory for every run. Its report lists missing/corrupt logs, nominal instability, ineffective fault exposure, ineffective partitions and trivial severe controls. It requires actual pinned-model evidence for B/D. A manually edited `eligible_for_main` flag cannot bypass inspection of the raw runs.

If it is ready, freeze the main definition:

```bash
python -u scripts/run_phase18_factorial.py prepare \
  --config configs/phase18/factorial.example.json \
  --phase17-lock results/phase17/main_calibration_lock1 \
  --validation-dir results/phase18/extension_validation_run1 \
  --output-dir results/phase18/final_definition_run1
```

This freezes the selected cells, seeds, run order, fixtures, model, four network profiles, rules/prompts/source hashes, registered metrics, validation evidence and technical-exclusion policy. There are no main-run CLI overrides for prompts, duration, communication settings or architecture factors. Duration and fault time are inherited from the calibrated Phase 17 settings; the current candidate horizon is **600 seconds per run**.

Start with a limited number of attempts if desired:

```bash
python -u scripts/run_phase18_factorial.py run \
  --definition-dir results/phase18/final_definition_run1 \
  --output-dir results/phase18/main_run1 --max-runs 4
```

Resume the same output directory to continue. Omitting `--max-runs` executes the remaining planned attempts serially:

```bash
python -u scripts/run_phase18_factorial.py run \
  --definition-dir results/phase18/final_definition_run1 \
  --output-dir results/phase18/main_run1
```

At a 600-second horizon the initial matrix has a serial upper bound of about **213 hours**, before technical retries and validation. Runs can finish earlier. Plan storage and local-model capacity before launching it. Concurrent writers to the same result directory are rejected.

Recompute the replication report without running missions:

```bash
python -u scripts/run_phase18_factorial.py summarize \
  --definition-dir results/phase18/final_definition_run1 \
  --output-dir results/phase18/main_run1
```

## Common random numbers and model identity

Within a team size and seed, all architectures receive the same frozen task/vehicle geometry, initial states, restricted regions, fault actor/time and network configuration. The network uses keyed draws from seed, mission, sender, sequence number and recipient. Matching message keys receive matching random draws; architectures with different traffic are **not** claimed to lose identical packets. Run-order randomization uses a separate RNG and is fixed prospectively.

The scenario currently has fixed routes and no randomized target placer. Therefore there is no new random target-placement claim. Simulation timings, common inputs and every actual packet outcome are preserved. Wall-clock timing is used for all formal architectures, so shared-server inference/admission delay is charged to B/D rather than hidden. Temperature zero and a pinned digest improve reproducibility but do not guarantee bitwise-identical model behavior; actual prompts, request options, outputs and latencies remain available for analysis.

The model identifier and full digest come from the Phase 17 lock. Four or eight independent contexts can share one Ollama server. A/C remain deterministic; B/D use the pinned local model. A cloud `latest` model is not substituted.

## Replication accounting and exclusions

The predeclared technical categories are: no mission start; an unhandled runtime error/interruption; missing or corrupt required artifacts; configuration/provenance mismatch; model identity mismatch; inconsistent metric evidence; incomplete decision audit. A failed identity preflight stops execution rather than silently substituting replay. Detected model drift stops the batch.

The following are **valid unfavorable outcomes**: timeout, unfinished work, failed reassignment/recovery, safety violations, rejected commands, malformed model output handled by correction/fallback, inference timeout, fallback use, zero productive LLM decisions and completion before the scheduled fault. These never justify rerunning a technically valid seed to obtain a better result.

For each cell/seed, the **first technically valid attempt** is selected. Technical failures may be retried with the **same seed**, at most twice under the example configuration. Every failed attempt and exclusion reason is retained. Exhausted seeds leave the cell short of its declared replication count; no favorable replacement seed is drawn. Interrupted or orphaned attempt directories are preserved and treated as technical failures on resume.

`replication_report.json` includes per-cell valid/exhausted/missing seeds, successes, technical exclusions, the common valid seed intersection for architecture comparisons, selected Phase 15 metrics and all attempt assessments. Failed completion times remain censored timeouts, not fast successful completions. Continuity uses matched nominal references. Its `exit_criterion_passed` means every selected cell has the declared number of technically valid distinct seeds; it does **not** mean every mission succeeded.

The evidence audit checks each model request against a stored prompt and request specification, plus either a returned response with its validation disposition or an explicit timeout/shutdown record. Invalid model outputs remain visible. No private reasoning is requested.

## Output layout

```text
final_definition_run1/
  definition_lock.json
  design.json / pilot_inputs.json / exclusion_policy.json
  final_batch.json
  fixtures/team_2.json / team_4.json
main_run1/
  execution_registration.json
  metric_registration.json / metric_contract.json / metric_definitions.md
  model_preflight.json / progress.json
  attempt_definitions/<cell>_s<seed>_a<attempt>.json
  attempts/<cell>_s<seed>_a<attempt>/
    manifest.json / events.jsonl / technical_assessment.json
    run/summary.json / flight_trace.json / messages.json / guardian_audit.json
    run/waypoint_arrivals.json / executed_actions.json / scenario_events.json
    run/Drone*/prompts.jsonl / request_specs.jsonl / responses.jsonl
    run/Drone*/decision_history.jsonl / memory.json
  replication_report.json
```

Use the existing Phase 17 individual-run plotting tools on retained Phase 14-style attempt folders. Do not discard unsuccessful timelines.

## Software verification

```bash
python -m unittest discover -s tests -p 'test_phase18_factorial.py' -v
python scripts/run_phase16_verification.py \
  --output-dir results/phase18/software_verification.local_run1
```

These checks use temporary mock runs and never consume the held-out main dataset. They cover design counts, disjoint seeds, common inputs, team-specific partitions, eight-drone idle assignments, blocked preconditions, technical versus mission failure, request auditing, first-valid selection, retry/resume and immutable definitions. Passing software tests is infrastructure evidence; Phase 18 remains incomplete until the actual frozen main replications are collected.

The local implementation verification passed 262 tests; see [the software-results report](phase18_software_results.md). This is not a main-experiment completion claim.
