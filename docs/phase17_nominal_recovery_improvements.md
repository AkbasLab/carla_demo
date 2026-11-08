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
