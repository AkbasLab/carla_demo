# Phase 18 transition: factorial collection readiness

Phase 18 collects the frozen comparisons; Phase 17 develops and calibrates them.
Poor mission outcomes are data, not automatic reasons to keep tuning. However,
the intended scenario, fault exposure, evidence and calibration must be valid
before opening the held-out experiment.

## Starting scope

Use all four architectures, teams of two and four, all four network profiles,
and both failure conditions. This is **64 cells** and, with 20 common seeds,
**1,280 planned runs**. Defer eight drones until the smaller cases are validated;
the optional extension produces 96 cells and 1,920 runs.

The repository already implements this through
`scripts/run_phase18_factorial.py` and `configs/phase18/factorial.example.json`.
It shares the mission, vehicle execution, network and guardian across A/B/C/D.
A is centralized rules, B independent persistent LLM agents without takeover,
C deterministic decentralized coordination, and D agentic decentralized policy.
The backend remains mock flight. This does not establish actual radio or live
CARLA-Air performance.

## Requirements and current implementation

| Requirement | Implementation / remaining prerequisite |
|---|---|
| Common initial conditions, task geometry and restrictions | Shared frozen team fixtures for all architectures |
| Common scheduled fault time | Fixed-time scenario schedule; new guard rejects enabled V2 `owned_motion` settings in factorial entries |
| Equivalent network randomness where applicable | Seeded transport with matching-message random draws; distinct architecture traffic is not forced to lose identical packets |
| Development/validation/test separation | Declared disjoint pools; candidate development seeds include previously inspected pilots, validation 44–46, test 101–120 |
| Pinned local model | Locked identifier, digest and options, with identity checks; no silent replay/cloud substitution |
| Complete decisions | Per-agent prompts, request specifications, outputs, validation dispositions, actions and fallback records; technical audit checks completeness |
| Valid replications per cell | Resumable runner and replication report; first technically valid attempt per seed |
| Outcome-independent exclusions | Frozen technical categories, bounded same-seed retries and retained failed attempts |
| Final readiness | A verified calibration lock and matching extension validation are still required |

The 17 Phase 18 software tests pass after adding the common-fault-time check.
A draft plan confirms 64 cells and 1,280 planned runs. No final held-out mission
has been launched as part of this transition check.

## Do not silently inherit the development fault scenario

Recent V2 tests intentionally use `owned_motion`: a selected policy stops only
after it owns moving work. The actual stop time therefore differs across
architectures. Those are useful recovery diagnostics, but do not satisfy the
proposed Phase 18 requirement of the same fault time across architectures.

For the fixed-time main design, the calibrated pilot must explicitly use
`pilot_resilience_v2.enabled=true` and `fault_mode=fixed_time` if retaining V4's
independent telemetry and approach mechanisms. The common `fail_at_s` must be
within the mission horizon. Its usefulness must be calibrated on development or
validation data: a fast architecture may finish before a late fault, while a
slower architecture may not yet own moving work at an early fault.

Do not choose a fault time after seeing held-out outcomes. Do not replace it
with `owned_motion` under the same final scenario name. A state-triggered main
study would be a different prospective design with different matching claims.

Also freeze the failure meaning. A stopped agent policy with surviving physical
telemetry and guarded holding is not a complete aircraft hardware failure or
whole-vehicle radio loss. Report the actual injected condition precisely.

## Existing calibration example is not the V4 lock

`configs/phase18/calibration_pilot.example.json` retains the older 600-second,
180-second-lease, 30-second-bid settings, a fixed fault at 73 s, and no enabled V2
settings. The recent V4 pilots use a 240-second budget, 75-second leases and
six-second bids. Neither configuration should silently stand in for the other.

Before main use:

1. Prospectively select the mission horizon, task rules, fixed fault time,
   telemetry-failure model, all four network profiles and model options.
2. Save the selected configuration in a new candidate file. Freeze or commit the
   source before collecting calibration that will be source-hash locked.
3. Calibrate fixed-time exposure and the meaning of the network levels using
   development/validation seeds. Existing V4 results remain supporting evidence;
   their `owned_motion` scenarios cannot silently fill fixed-time cells.
4. Use the existing Phase 17 freeze and Phase 18 extension-validation gates.
   Do not edit a calibration flag or bypass a source-hash mismatch.
5. Freeze the final definition and collect its selected cells serially on the
   pinned model service. Do not tune prompts or rules after inspecting test data.

The aim is not to force D, or every other architecture, to succeed under severe
communication. Reliable nominal references, meaningful fault exposure, readable
logs and interpretable conditions are prerequisites; mission failures under those
conditions remain legitimate observations.

## Safe first command: plan only

From the repository root, use a new folder:

```bash
python -u scripts/run_phase18_factorial.py plan \
  --config configs/phase18/factorial.example.json \
  --output-dir results/phase18/design_draft_v4_run1
```

This creates a draft and contacts no model server. It neither runs missions nor
consumes the held-out dataset. Existing calibration and result folders must be
retained.

After calibration and extension validation pass, follow
[the Phase 18 commands](phase18_factorial_experiments.md#commands). The main
runner supports `--max-runs` for small resumable collection batches, rather than
launching the whole matrix at once. Continue with the same frozen definition
and output directory; do not create a new definition to replace poor outcomes.

If computational cost requires fewer than 20 replications, select and justify
that smaller design before collecting test outcomes. Do not stop collecting a
cell because its early results are unfavorable or substitute easier seeds.

## Completion criterion

Phase 18 is complete when each selected cell has its predeclared number of
technically valid distinct-seed replications, with exclusions accounted for.
It is not complete merely because the runner passes software tests, and it does
not require every mission to succeed. Report incomplete mission times as censored
observations and preserve every failed or excluded attempt.
