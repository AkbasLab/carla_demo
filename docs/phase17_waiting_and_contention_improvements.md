# Phase 17 local improvements: waiting, approach endpoints and VM contention

Status: implemented locally; not pushed. The inspected evidence is commit `5715eba` under `results/phase17/all_architecture_run1`. Original result directories and reports remain unchanged. This revision requires a new development cohort; old runs are comparisons, not interchangeable replications.

## Evidence motivating the changes

In B's four-drone nominal seed-11 control, initial `missing_peer_beliefs` starts a blockage timer near time zero. All four tasks are released at approximately 15.0 seconds even though some policies are merely waiting for shared inference. Seed 12 shows the same release for Drone3 and Drone4. B has no reallocation mechanism, so these releases permanently orphan otherwise useful assignments. Its low completion is therefore confounded by this implementation interaction.

D's severe traces show repeated task releases, rebidding and superseded versions. Some release timing includes time spent awaiting a model result or a clear route. A's failed vehicle can stop close to a required waypoint, where aiming only at the waypoint centre is more restrictive than the existing arrival criterion. Concurrent pinned batches on one VM introduce another uncontrolled source of wall-clock admission/inference delay.

## Implemented changes

### 1. Distinguish telemetry waiting from geometric blockage

`pilot_resilience_v2.py` labels state/communication uncertainty separately from geometric rejection. Initial or stale telemetry does not consume the route-release budget. When valid telemetry clears that condition, the old wait record and matching rejection cache are cleared and `state_wait_resolved` is logged.

Missing information still prevents motion. It does not cause a fabricated position, a freshened timestamp, task progress or a forced safety approval.

### 2. Charge the timer only for sampled geometric blockage

The bounded-release budget now accumulates rejected geometric intervals while the agent is not waiting for its own inference, correction or admission. Clear-route intervals do not consume this budget. Preview approval does not reset accumulated blockage to zero; observed movement still resets it. A release can occur only while the route is currently rejected, the geometric budget is exhausted, no decision is in flight, and cancellation is confirmed.

This replaces the previous wall-time-since-first-rejection behavior. It addresses the case where one early startup rejection, or a short rejection followed by a slow model call, invalidates the task at 15 seconds. Task leases, command deadlines and model timeouts are unchanged: waiting is not counted as productive progress and does not renew leases.

This should reduce premature releases and version churn; it does not guarantee that a genuinely blocked mission can complete.

### 3. Approach an admissible point within the existing waypoint region

`approach_planner.py` can consider a small set of arrival points inside 90% of the existing horizontal arrival tolerance. The original waypoint is tried first. Candidate geometry, battery cost, current peer occupancy and the immediate guardian check are retained. Every subsequent segment is revalidated against live safety state.

The recorded required waypoint, route, checkpoint index, metric denominator and arrival tolerance remain unchanged. The executor records arrival against the original required waypoint. No region is enlarged, no peer is removed and no safety limit is reduced. This may permit a legal edge approach around a nearby stopped drone; it cannot make an entirely unsafe arrival region feasible.

### 4. Prevent overlapping pinned batches on the VM

`batch_isolation.py` uses an OS advisory lock for cooperating Phase 17 pinned runners under the same VM user. A second pinned batch fails before creating a new result directory. The lock is released when the batch exits, including on errors, and the selected mode is recorded in `v2_manifest.json.execution_isolation`.

An explicit `--allow-concurrent` development override is available and recorded as such. Replay and simulated smoke checks do not take the lock. This guard does not isolate arbitrary Ollama clients, other VM users or unrelated workloads. It is a reproducibility measure, not proof of constant hardware performance.

## What remains intentionally unchanged

- A uses central assignments and delivered reports; B does not negotiate or reassign work; C uses deterministic decentralized policy; D uses persistent LLM policy.
- The guardian implementation and its separation/geofence/altitude/battery requirements are unchanged.
- Model identity/options, 30-second inference timeout, shared within-mission inference capacity, 75-second task lease, 240-second budget and failure trigger are unchanged.
- No fault is silently moved to a more convenient location, and no failed result is replaced.
- No pinned experiments or CARLA-Air flights were launched for this work.

## Verification

The regression checks cover startup telemetry followed by 30 seconds of artificial model admission waiting, pending-inference intervals, persistent real blockage, arrival-region limits, stale-peer rejection, bid capacity, and VM-lock release/override behavior. A temporary mock/replay integration with four independent B agents deliberately delays all model admission by 30 simulated seconds and requires all four preassigned tasks to finish without release. This is a software regression check, not an LLM benchmark.

Run the focused checks locally with:

```bash
python -m unittest discover -s tests -p test_phase17_recovery_regressions.py -v
python -m unittest discover -s tests -p test_phase17_all_architectures.py -v
python -m unittest discover -s tests -p test_phase17_batch_isolation.py -v
```

The full unittest suite passed **295 tests**. Performance gains under actual Ollama/network timings still need a new, serial, matched development batch after review. Existing `all_runs_technically_valid` metadata describes retained evidence, not proof of calibration readiness or architectural superiority.
