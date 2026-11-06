# Phase 18 — implementation verification

The final simulator-free regression run passed **262 tests, with zero failures, errors or skips**. Its source hashes did not change during execution. Evidence is in `results/phase18/software_verification_run2/summary.json` and `unittest.log`.

The 16 Phase 18 tests cover matrix sizes, seed separation, common architecture inputs, partitions for the actual team membership, eight-drone mock execution with idle independent agents, blocked missing prerequisites, completed versus timed-out mission accounting, corrupted manifests, pinned-model mismatch, explicit inference timeout and invalid-output audit records, immutable definitions, first-valid attempt selection, same-seed technical retries, interrupted-run resume, and stopping after a user interrupt.

Two draft plans were generated without executing the main experiment:

| Plan | Cells | Held-out runs | Maximum attempts with technical retries |
| --- | ---: | ---: | ---: |
| Two/four drones | 64 | 1,280 | 2,560 |
| Two/four/eight drones | 96 | 1,920 | 3,840 |

These are prospective designs, not measured mission outcomes. Temporary software fixtures do not constitute the frozen actual-model experiment. No pinned main-experiment replications or CARLA-Air flights were run here.

The Phase 18 experimental exit criterion remains **not demonstrated**. It requires the pinned Phase 17 calibration lock, extension validation and the declared valid replications in every selected final cell. Incomplete but technically valid missions count toward replication coverage and remain failures in the mission-success metric. Technical exclusions and retries must stay visible.

See [the experiment guide](phase18_factorial_experiments.md) for the prospective design, calibration requirements, commands, exclusion definitions and output layout.
