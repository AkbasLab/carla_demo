# Phase 17: nominal recovery corrections

Status: implemented. Development verification uses mock flight
and replay policies. New pinned-Ollama measurements are still required.

## Evidence and diagnosis

The nominal A/B/C/D batches at seeds 11, 12, 15 and 20 show that A accepts a
replacement task but does not finish it. B's normal missions now succeed; its
lack of failed-peer takeover is intentional. C and D finish nominal recovery.

Inspection of `A_n2_nominal_loss_s11` exposed two separate issues:

1. The controller emits fresh task-authority renewals every beacon interval.
   The retry endpoint keyed them only by payload and suppressed the fresh
   timestamp while retransmitting an older authorization. The vehicle therefore
   repeatedly hit its three-second command timeout even on nominal transport.
2. Once those interruptions are removed, the stopped aircraft can physically
   obstruct a required waypoint. In the deterministic replay it stops at
   `(4.4, 0, -3)` while the waypoint is `(6, 0, -3)`. Their separation is only
   1.6 m. Even the far edge of the existing 0.4 m arrival region cannot satisfy
   the 2 m separation plus the guardian's conservative uncertainty allowance.

These are different problems. Correct message renewal does not make an occupied
waypoint safe, and an accepted replacement is not evidence of productive work.

## Changes

- `resilience.py`: a newly issued controller award supersedes an older pending
  renewal of the same assignment. Retries of each issuance retain its original
  timestamp and TTL. The command-timeout threshold is unchanged.
- `pilot_resilience_v2.py`: an idle structured-correction state no longer pauses
  the sampled geometric-blockage timer. Admitted inference and queued requests
  still pause it. Repeated identical actual unsafe decisions at an unchanged
  position use the existing rejection limit and require confirmed cancellation
  before releasing the task. Preview checks alone do not trigger this rule.
- `architectures.py`: vehicles report blocked approaches through the existing
  message bus. The controller logs the reason without counting it as progress
  or renewing the lease. After release it honors the V2 retry cooldown and
  defers the same blocked agent/task pairing while delivered physical geometry
  is unchanged. A position change of at least 0.2 m permits another feasibility
  check; it does not authorize movement. Other eligible agents remain candidates.
- `pilot_v2_runner.py`: adds `diagnostic_groups` for normal operation,
  recovery-capable A/C/D cases and independent B baseline outcomes. Existing
  `diagnostic_checks_passed` and `all_missions_complete` retain their original
  strict meanings for backward compatibility. B is not silently counted as a
  completed recovery mission.

Every movement still uses the existing deterministic approach planner and runtime
guardian. Geometry, arrival tolerance, speed/separation limits, lease duration,
inference timeout, fault predicate and 240-second mission budget are unchanged.
The renewal correction applies to the shared resilient transport; bounded
rejection recovery and geometry-based reassignment deferral are V2 behavior.

## Verification

Full offline suite: **302 tests passed**, followed by an additional passing
controller-link outage integration test. Focused regression suite: **39 tests
passed** before that additional test. Tests cover controller-renewal freshness
and retry expiry, genuine controller loss stopping both drones, inference
waiting, repeated rejection release, unchanged-geometry
deferral, delivered geometry changes, blocked arrival regions, and separate
diagnostic outcomes. The existing A/B runner integration verifies that B does not
negotiate and that a failed policy continues publishing only its own telemetry.

A fresh eight-case replay batch, nominal networking, two drones, seed 11:

| Architecture | Control tasks | Control completion time | Fault tasks | Fault completion time |
|---|---:|---:|---:|---:|
| A | 4/4 | 72.8 s | 3/4 | Not completed at 239.8 s |
| B | 4/4 | 63.4 s | 2/4 | Not completed at 239.8 s |
| C | 4/4 | 84.2 s | 4/4 | 149.0 s |
| D, replay only | 4/4 | 84.2 s | 4/4 | 149.0 s |

All eight cases are technically valid with guarded dispatched actions and zero
sampled separation violations. Collision sensing is unavailable. D's replay
times are not LLM latency or performance evidence and must not be compared with
the uploaded pinned runs as an isolated software-effect estimate.

In A's final fault replay, the replacement is accepted at 75.4 s. It reports the
blockage, releases the task at 107.4 s, and the controller does not repeatedly
assign that unchanged blocked approach. The physically obstructed work remains
unfinished. No waypoint arrival or mission success is fabricated.

## Small next tests

Start with A only, in a fresh output directory:

```bash
python -u scripts/run_phase17_resilience_v2.py run \
  --config configs/phase17/resilience_v2.json \
  --stage focused --profile pinned --architectures A \
  --team-size 2 --seed 11 --telemetry alive --fault-trigger owned_motion \
  --output-dir results/phase17/nominal_recovery_v3/a_n2_s11
```

A is deterministic; the selected pinned profile gives wall-clock execution but
does not turn A into an LLM architecture. Inspect `central_execution_blocked`,
`central_task_released`, `central_approach_recheck`, controller-command timeouts,
and waypoint arrivals. A physically blocked task may correctly remain incomplete.

Then run one matched regression batch, serially:

```bash
python -u scripts/run_phase17_resilience_v2.py run \
  --config configs/phase17/resilience_v2.json \
  --stage focused --profile pinned --architectures A B C D \
  --team-size 2 --seed 11 --telemetry alive --fault-trigger owned_motion \
  --output-dir results/phase17/nominal_recovery_v3/abcd_n2_s11
```

Preserve the old results. Do not increase the budget or relax safety merely to
obtain completion. If the intended study requires every required waypoint to
remain physically accessible after a policy failure, declare and validate that
scenario property prospectively. Changing routes, failure exposure, failure
fallback behavior or task-completion semantics creates a new scenario cohort.

Further C/D timing changes should follow measured detection, lease, admission,
acceptance and productive-resumption intervals; this change does not shorten
leases blindly or claim an LLM advantage.

## Pinned validation: nominal recovery V3

Results uploaded in commit `56a334c` include:

- `results/phase17/nominal_recovery_v3/a_n2_s11`
- `results/phase17/nominal_recovery_v3/abcd_n2_s11`

Both batches record clean source commit `00737f4`, which includes the corrections
from `9a80eff`. Their recorded source hashes match. Both used nominal networking,
two drones, development seed 11, surviving own-vehicle telemetry and the
`owned_motion` fault trigger. The execution-isolation lock was enabled.

### Comparison with the previous pinned seed-11 run

The previous results are in
`results/phase17/all_architecture_run1/focused_n2_s11`.

| Metric | Previous pinned run | V3 A/B/C/D batch |
|---|---:|---:|
| A normal mission completion time | 114.8 s | 78.0 s |
| A normal controller-command timeout events | 45 | 1 |
| A failure-case controller-command timeout events | 66 | 2 |
| A failure-case completed tasks | 3/4 | 3/4 |
| A replacement acceptance timestamp | 98.8 s | 76.0 s |
| Completed missions across A/B/C/D | 6/8 | 6/8 |

A's observed normal completion time decreases by approximately 32%. The separate
A-only batch gives a similar result: normal completion in 79.2 s, one normal
timeout event, and three of four tasks completed in the failure case. Its
replacement acceptance occurs at 75.4 s.

The remaining timeout events in the V3 A/B/C/D batch occur while the affected
vehicle owns no task: 48.0 s in the control, and 71.2 s and 113.8 s in the failure
case. They no longer repeatedly interrupt assigned work. These traces support
the intended controller-renewal correction; they do not establish a statistical
effect across multiple independent replications.

### Recovery behavior and the remaining physical blockage

In the V3 A/B/C/D failure case, the controller receives four blocked-execution
reports. The replacement releases Sector A at 111.0 s with reason
`peer_reachable_region_conflict`. The controller does not repeatedly assign the
same unchanged blocked approach. The A-only case similarly releases the task at
110.4 s. Both retain the stopped aircraft in the safety model and leave its
unfinished work incomplete.

The failed drone stops at approximately `(4.2, 0, -3)` in the A/B/C/D batch and
`(4.0, 0, -3)` in the A-only batch, near the required waypoint `(6, 0, -3)`.
The approach remains inadmissible under the existing arrival tolerance,
separation bound and conservative peer-uncertainty checks. No waypoint arrival
or safe passage should be inferred from replacement acceptance alone.

The earlier pinned run stopped the failed drone near `(3.0, 0, -3)`. Because the
fault is movement-triggered, correcting execution changes the physical fault
exposure even with the same seed. The earlier and V3 failure outcomes therefore
do not isolate an identical-geometry recovery effect.

### Other architectures and verification status

| Architecture | V3 normal mission | V3 policy-failure mission |
|---|---|---|
| B: independent persistent LLM | 4/4 tasks, 107.6 s | 2/4 tasks; incomplete at 239.8 s |
| C: deterministic decentralized | 4/4 tasks, 88.4 s | 4/4 tasks, 158.4 s |
| D: agentic decentralized | 4/4 tasks, 109.6 s | 4/4 tasks, 204.8 s |

B's lack of takeover is intentional. C and D retain successful nominal recovery.
B and D use actual LLM inference and record zero fallback-policy activations in
these cases. D's completion remains slower than C's; this pilot does not
demonstrate an LLM performance advantage.

Both batches finish with no reported runtime or metric errors, all dispatched
actions guarded, and zero sampled separation violations. Collision sensing
remains unavailable. The separate A-only pair is an additional execution check,
not another independent seed.

The new diagnostics correctly report normal-operation checks as passing and
identify A as the incomplete recovery-capable case. B's failure mission remains
an explicitly non-reassigning baseline outcome. The strict all-mission flag
remains false rather than concealing these incomplete outcomes.

**Assessment:** the changes meaningfully improve A's normal execution efficiency
and make blocked recovery bounded and auditable. Overall mission completion
remains unchanged. The next scenario-design decision is whether a failed
aircraft may physically obstruct required work, or whether a separately declared
and validated recovery mechanism must make that work accessible. Do not relax
the guardian or count blocked work as complete to resolve this limitation.

## Severe-communication development corrections

Status: implemented; new pinned-inference validation remains pending.
This section preserves the earlier nominal findings and describes a subsequent
development change, not a reinterpretation of the saved experiments.

### Evidence motivating the changes

The additional dataset in commit `a9c4352` is
`results/phase17/all_architecture_run1/severe_n2_s10`. It records source
`56a334c`, includes the nominal fixes, and completes two of eight missions.
Its task counts are:

| Architecture | Severe control | Severe policy failure |
|---|---:|---:|
| A | 4/4 | 3/4 |
| B | 3/4 | 2/4 |
| C | 4/4 | 3/4 |
| D | 1/4 | 2/4 |

Here “control” means no injected policy failure; communication is still severe.
Earlier four-drone severe seeds 10 and 20 also show repeated safety waits,
handover churn and frequent peer-health transitions. Their source predates the
nominal fixes, so they are supporting diagnostic evidence, not a matched test of
the latest implementation. The uploaded four-drone severe seed-10 batch lacks
its two D cases and must not be counted as eight finished runs.

One concrete defect appears in `C_n2_severe_loss_s10`: at approximately 155.8 s,
Drone2 is at `(6, 0.35, -3)`, within the 0.4 m tolerance of Sector A's first
waypoint `(6, 0, -3)`, while owning its current task epoch. No Sector A arrival is
recorded. The executor checked prospective movement safety before recording
already observed work, so a rejection could prevent checkpoint advancement.

### Implementation

1. **Arrival observations precede next-command checks.** `persistent.py` now
   reconciles an arrival for an existing executor, current owned epoch and fresh
   own-position observation. V2 performs the same reconciliation before its
   approach preview. Stale own telemetry and old epochs cannot create arrivals.
   Recording a real arrival does not authorize the next movement; the guardian
   still checks every dispatched action. A reached final waypoint can finish a
   task without requiring another MOVE approval at that same position.
2. **Progress follows the selected approach.** V2 supplies the waypoint executor
   with remaining distance along its selected detour. Actual reduction can renew
   the existing lease even when straight-line distance to the mission waypoint
   initially increases. Creating or changing a plan resets the measurement
   baseline; it does not count as progress. Stationary observations, model
   waiting and intermediate staging points do not create mission work.
3. **Cached approaches are revalidated.** If a newly delivered peer observation
   blocks the cached next segment, V2 discards that approach and searches again
   from the current local state. Unknown or stale state still fails closed.
4. **Shorter detours are tried first.** The deterministic planner tries a narrower
   lateral candidate before its existing larger offsets. Every full candidate
   leg still passes the original occupancy/static/battery screens, and every
   live segment still passes the guardian. This changes candidate ordering,
   not minimum separation, uncertainty bounds or speed limits.
5. **V2 role-health recovery is debounced.** A suspected peer requires sustained
   fresh heartbeat evidence over the existing one-second recovery dwell before
   returning to HEALTHY. Duplicate and older heartbeat timestamps do not
   rejuvenate it. The three-second unreachable threshold, raw-heartbeat
   coordination eligibility, physical occupancy and guardian freshness checks
   remain unchanged. This does not implement partition consensus or certify a
   failed vehicle's safe rejoin.

The mission budget, network profile, lease length, arrival tolerances, model
settings and fault trigger are unchanged. The severe profile remains 400 ms mean
latency, 200 ms jitter, 30% independent loss, 60 messages/s and 50,000 bytes/s.
These are application-network experiment settings, not measured radio claims.

### Offline checks and limits

A regression first reproduced the missing-arrival defect, then passed with the
correction. Additional checks cover stale observations and old epochs, blocked
cached approaches, energy-feasible shorter detours, sustained health recovery,
real detour progress, and no renewal from stationary replanning.
The full offline suite passes **310 tests**.

A fresh two-drone severe replay at seed 10 finishes all eight cases without
runtime or metric errors, with six completed missions. Its outcomes are:

| Architecture | Control | Policy failure |
|---|---|---|
| A | 4/4, 63.6 s | 3/4, timeout |
| B, replay policy | 4/4, 68.4 s | 2/4, timeout |
| C | 4/4, 87.8 s | 4/4, 187.4 s |
| D, replay policy | 4/4, 87.8 s | 4/4, 187.4 s |

The pre-change matched A/C replay completed A's control in 72.8 s, C's control in
116.2 s and C's failure mission in 191.8 s. A's failure mission completed three
tasks in both versions. Thus this small replay shows shorter successful times,
not an increase in A/C mission-success counts. Changed execution can also change
the physical position at a movement-triggered fault.

Replay B/D are not actual LLM measurements. These numbers cannot establish a
pinned-model completion improvement, a statistical architecture ranking, or live
flight safety. All new pilot data must remain separate from the saved older
runs. No held-out seed was used for these checks.

An additional four-drone C severe replay at development seed 20 completes both
cases: 64.4 s for the control and 145.8 s for policy failure. Across these ten
post-change replay cases, all dispatched actions are guarded, no sampled
separation violation is recorded, and no runtime or metric error is reported.
The two batches occupy approximately 8.2 MiB after lossless packing. They are
temporary offline validation artifacts, not newly published pinned results.

### Test in small, serial batches

Run the offline regressions first; CARLA-Air and Ollama are not needed:

```bash
MPLCONFIGDIR=/tmp/phase17-mpl python -m unittest \
  tests.test_phase17_recovery_regressions \
  tests.test_phase17_all_architectures \
  tests.test_phase13_resilience -q
```

For actual inference, keep the pinned Ollama model from
`configs/phase17/resilience_v2.json` available and run one batch at a time. The
following helper fixes team size and seed and creates separate output folders:

```bash
check_severe_fix() {
  python -u scripts/run_phase17_resilience_v2.py run \
    --config configs/phase17/resilience_v2.json \
    --stage "$1" --profile pinned --architectures "$2" \
    --team-size 2 --seed 10 \
    --telemetry alive --fault-trigger owned_motion \
    --output-dir "results/phase17/severe_recovery_v4/${1}_${2}_n2_s10"
}

check_severe_fix focused C
check_severe_fix severe C
check_severe_fix severe D
```

Each command creates only two cases: control and policy failure. Inspect each
batch before running the next. C is deterministic; D requires actual pinned
inference. A useful result includes recorded real waypoint arrivals, replacement
acceptance and productive resumption, with no runtime/metric errors and all
actions guarded. A false aggregate diagnostic is an outcome to inspect, not a
reason to discard a run or silently increase its duration.

Once those checks are understood, test the remaining baselines separately:

```bash
check_severe_fix severe A
check_severe_fix severe B
```

A may retain physically obstructed work. B must finish its own surviving work
but still cannot take over a failed peer's assignments. Do not add negotiation
to B simply to improve its score.

Then check the previously problematic four-drone seed-20 case without launching
a full matrix:

```bash
python -u scripts/run_phase17_resilience_v2.py run \
  --config configs/phase17/resilience_v2.json \
  --stage severe --profile pinned --architectures C D \
  --team-size 4 --seed 20 --telemetry alive --fault-trigger owned_motion \
  --output-dir results/phase17/severe_recovery_v4/severe_cd_n4_s20
```

Inspect `waypoint_arrivals.json`, `progress_reported` and `lease_expired` protocol
events, `alternative_approach_invalidated`, `alternative_approach_selected`,
`peer_health_changed`, policy errors and guardian audits. The existing Evidence
reader can read losslessly packed traces without restoring all raw JSON files.
Retain the archives and use another new folder for any repeat attempt.

Long model admission delays and genuinely infeasible approaches may still cause
incompletion. These changes do not enlarge leases merely because an LLM is
waiting, delete uncertain physical peers, or guarantee every severe case will
complete in 240 seconds. Pinned validation must establish the remaining effect.
