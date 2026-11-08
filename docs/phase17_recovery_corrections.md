# Phase 17 recovery corrections after seed 11/12 trace inspection

These are development changes prompted by `v2_recovery_checks` in commit `7386c2b`. Existing results, configurations and archived traces are preserved. This revision changes runtime behavior and therefore needs a new development result directory and new source hashes; it must not be mixed into the old calibration cohort.

## Corrections

### Assignment capacity

`agentic_uav/coordination/contract_net.py` now rechecks local assignment capacity when each auction closes, not just when a bid is computed. A drone cannot self-claim a second task while it owns another. Outstanding bids for other tasks are withdrawn through the existing message protocol; receivers remove those bids. Remote owners' claims remain local beliefs rather than being rejected because the observing drone is busy.

This prevents the seed-12 pattern in which Drone2 acquired A and D together and D's lease expired while A was being executed. It does not renew a lease for nonexistent task progress or disable lease expiry.

### Separate acknowledgment eligibility

V2 now has an explicit `coordination_timeout_s` (default 3 seconds), independent of the 75-second task lease. Only locally received HEARTBEAT evidence determines this coordination membership. Fresh independent physical STATUS_UPDATE telemetry does not impersonate the failed policy or renew task progress.

A peer whose heartbeat is older than this timeout no longer blocks acknowledgments for the survivor's own task. The peer remains in the safety state's expected membership and physical occupancy. The failed owner's task still waits for its original lease to expire before reassignment.

Membership changes are logged as `coordination_membership_observed`, including retained physical peers and the local-timeout assumption. This is a trusted-team failure detector, not consensus under network partitions. A returned heartbeat restores the acknowledgment requirement; safe agent rejoin/fencing is not established by this change. Legacy non-V2 coordination retains its original acknowledgment timeout.

### Decision freshness

`agentic_uav/policy/persistent.py` records task identity, version, status, owner and offered task candidates with each pending inference. A response superseded by a changed task epoch, ownership/status or expired lease is retained but not executed. Its disposition is logged as `policy_error: task_context_changed` and `decision_superseded`; the next request receives a fresh context rather than a correction of an obsolete assignment.

Task-specific responses must refer to a task/version offered for that tool. Existing ownership, executability and guardian checks still run at application time. Response timeout and invalid-schema handling remain separate, and a context refresh is not counted as productive LLM work or successful execution.

### Alternative approaches and bounded blockage

The new shared deterministic helper `agentic_uav/coordination/approach_planner.py` constructs a bounded set of lateral approach candidates from the drone's own position and delivered peer observations. V2 enables it through `approach_detours` (default true). It can route around a peer occupying the straight approach before the drone reaches a tight separation boundary.

The helper checks every candidate leg against static bounds, keepouts, altitude and cumulative battery reserve, screens current peer occupancy, and requires guardian approval of the next short segment. Each subsequent dispatch is rechecked against current complete safety state. Candidate geometry is not a guarantee of future clearance, trajectory reservation, global planning or certified collision avoidance. If observations become stale, geometry is obstructed or no candidate is admissible, motion is not authorized.

Intermediate approach points do not alter task routes, checkpoint indices or the metric denominator. Only observed arrivals at original required waypoints count as productive waypoint work.

V2's blockage timestamp now survives changing rejection reasons and intermittent preview approvals while the drone remains stationary. Observed displacement resets it; merely obtaining another LLM authorization does not. If the bounded wait expires, confirmed cancellation is required before task release and rebid cooldown. Release does not assert that another agent can safely execute the task.

## Scope and comparison integrity

- Guardian thresholds and the guardian implementation are unchanged.
- No physical peer is removed from runtime safety checks.
- Duration, speed, model pin, inference deadline, task routes and failure trigger were not increased or relaxed.
- Capacity and decision-freshness fixes are shared protocol/policy infrastructure. New acknowledgment and detour behavior is enabled only in the V2 wrapper used by C/D.
- The existing V2 runner still supports C/D only. A/B need the same declared execution-support assumptions before a formal four-architecture comparison.
- Existing formal locks, if any, cannot be reused after these source changes.

## Verification

`tests/test_phase17_recovery_regressions.py` covers:

1. Two simultaneously closing auctions cannot self-assign two tasks.
2. A delivered bid withdrawal removes the outstanding peer bid.
3. Coordination timeout does not shorten the task lease or remove physical peer occupancy; returned heartbeat restores acknowledgment eligibility.
4. Full telemetry silence still fails closed.
5. A superseded inference response is not executed or converted into a fallback-driven success.
6. An admissible lateral candidate retains the mission route and loses authorization when telemetry becomes stale.
7. No candidate is accepted through a full keepout wall or invalid own state.
8. A guarded mock approach reaches the original mission waypoint and counts no staging-point arrivals.
9. Preview approvals without physical movement do not reset the bounded-blockage timer.

The full unittest discovery passed 283 tests; the latest focused recovery regression run passed all nine checks. These are software/mocked execution checks, not new pinned-model experiments. Performance improvement in actual Ollama runs remains to be measured after review. No old failed result is replaced by these checks.

## Small-batch development testing after this revision

Use these commands after pulling the complete correction series. They do not run Phase 18 held-out seeds. Ollama is required for pinned stages; CARLA-Air is not. Keep the model/server settings and competing workloads consistent. Every pinned invocation contains four cases (C/D × no fault/policy fault), with 240 seconds per case and lossless ZIP packing.

Start with local software checks and the two-case deterministic smoke check:

```bash
cd /opt/carla_demo
git pull --ff-only
python -m unittest discover -s tests -p test_phase17_recovery_regressions.py -v
ollama ps

python -u scripts/run_phase17_resilience_v2.py run \
  --stage smoke --profile replay --team-size 2 --seed 11 \
  --telemetry alive --fault-trigger owned_motion \
  --output-dir results/phase17/recovery_fixed_run1/smoke_n2_s11
```

Then execute **one** pinned batch and inspect it before continuing. Output directories must be new; never overwrite an old result or select retries based on a better mission outcome.

### Step 1: matched nominal reference, two drones, seed 11

This repeats the old development cell with the corrected software. Source changes are the treatment; do not describe old/new outcomes as replications of one frozen implementation. Record inference latency as well as mission results.

```bash
python -u scripts/run_phase17_resilience_v2.py run \
  --stage focused --profile pinned --team-size 2 --seed 11 \
  --telemetry alive --fault-trigger owned_motion \
  --output-dir results/phase17/recovery_fixed_run1/focused_n2_s11
```

### Step 2: change only the development seed to 12

```bash
python -u scripts/run_phase17_resilience_v2.py run \
  --stage focused --profile pinned --team-size 2 --seed 12 \
  --telemetry alive --fault-trigger owned_motion \
  --output-dir results/phase17/recovery_fixed_run1/focused_n2_s12
```

### Step 3: keep seed 12 and change only team size to four

```bash
python -u scripts/run_phase17_resilience_v2.py run \
  --stage focused --profile pinned --team-size 4 --seed 12 \
  --telemetry alive --fault-trigger owned_motion \
  --output-dir results/phase17/recovery_fixed_run1/focused_n4_s12
```

### Step 4: keep team size/seed and change only the network profile to severe

```bash
python -u scripts/run_phase17_resilience_v2.py run \
  --stage severe --profile pinned --team-size 4 --seed 12 \
  --telemetry alive --fault-trigger owned_motion \
  --output-dir results/phase17/recovery_fixed_run1/severe_n4_s12
```

The severe profile jointly changes loss, latency, rate and bandwidth as previously declared. This compares profiles; it does not isolate packet loss alone. Do not change duration, lease, inference deadline, speed or telemetry behavior at the same time. A different output path is storage isolation, not a change in the experimental factors.

For each batch, read `analysis/REPORT.md`, `v2_manifest.json`, `analysis/metrics.json` and each `runs/<case>/run/summary.json`. Check all of:

- Four run records, no runtime/metric-evidence errors, guarded dispatch and sampled separation results.
- Fault during owned movement, replacement acceptance and productive resumption.
- Productive LLM decisions in D, inference timeouts/admission delay and deterministic fallback use.
- Claim capacity, superseded-decision records, detour selection/revalidation, blocked-task release and lease expirations in retained ZIP traces.
- Original task waypoint work; intermediate detour points must not increase the denominator or arrival count.

`status: finished` is not mission success. `diagnostic_checks_passed` requires completed missions/recovery milestones but is not by itself proof of functioning LLM participation; inspect the productive LLM counters too. If the same defect repeats, preserve the result and inspect it before the next step. Do not launch all four pinned batches as an unattended matrix or increase the budget simply to obtain completion. Even passing all these checks would remain development evidence, not a final calibration lock or Phase 18 completion.
