# Phase 13 resilience v2: reliable coordination and short guarded execution

This is a new, opt-in benchmark implementation. The existing 300/600-second pilot datasets remain historical results. It changes the common transport support and guardian implementation, so improved outcomes must not be attributed to the LLM alone. Within v2, A/B/C/D use the same mission, network presets, skills, retry support and guardian.

## Changes

- Critical protocol messages receive bounded retries through the same degraded network. Packet IDs and sequences change; original creation time, payload observation times and expiration do not. Retry traffic consumes the configured rate/bandwidth. Version checks and task acknowledgments still govern execution; this is not a consensus protocol or an exactly-once guarantee under partitions.
- A delivered award can include its original bid evidence, allowing a receiver that missed the bid or announcement to reconcile ownership. Repeated awards do not restart an already adopted lease.
- Completed-work facts are included in C/D state reports. Trusted peers can reconcile a late completion even when their local task epoch advanced. This prevents stale local ledgers from repeatedly reauctioning known-finished work. Facts keep their original owner and observation time, and never fabricate local completion events. The model assumes honest fixed-membership peers; these are not cryptographically verified execution certificates.
- Older status/heartbeat observations cannot overwrite newer ones. Fresh delivered status counts as contact evidence alongside heartbeats.
- The centralized controller briefly collects delivered initial reports before choosing nearest available workers; it still proceeds after a bounded wait if some reports are missing. It never reads hidden backend state. Old command retries cannot shorten a newer command's authorization window.
- Motion is executed in short, repeatedly validated segments. The guardian checks each segment against every peer's reachable region, bounded by the fleet maximum speed and the elapsed observation age plus segment horizon. It can shorten segments further when necessary. Unknown, nearby, future-dated, excessively old or speed-bound-violating peer observations still prevent motion. No peer is deleted or silently assumed stationary.
- Temporary uncertainty leads to waiting for new evidence, rather than treating the route as permanently unsuitable and repeatedly releasing/reassigning its task. Static route failures retain release/replan handling. Existing active commands are awaited rather than replaced by repeated HOLD proposals.
- Role-recovery context explicitly identifies a locally justified missing role. A bounded deterministic role fallback is logged with separate provenance; it is not credited as an LLM decision or as successful RF restoration.

## Safety assumptions and limits

`ReachablePeerGuardian` is a new mock safety model, not a claim of certified or live avoidance. A peer can be anywhere within `max_speed_mps * (observation_age + future_time)` of its last observed position. That speed bound is imposed by the common action gate; an observed violation is rejected. The entire segment is checked using a conservative end-of-segment radius. All peers and original observation times remain in the guardian audit. Uncertainty prediction is capped at five seconds by default; indefinitely silent peers can still stop the mission.

The default segment horizon is one second, adaptively shortened no lower than the simulation tick. Geometry, altitude, reserve, command validity and concurrent-trajectory checks remain in force. Predicted safety in a discrete kinematic mock is not evidence about physical braking, perception, live containment or between-sample aircraft behavior.

A permanently silenced drone remains an unknown hazard. This version does not add a supervisor oracle, an unchecked landing, a sensing system or a false safe-stop assertion. It targets the incomplete **no-agent-failure** moderate/severe cases first. Actual teammate-failure scenarios may remain incomplete. B remains independent and never acquires cooperative reassignment.

Retries are bounded repeats supporting the existing TASK_ACCEPT handshake; no new reliable radio or guaranteed-delivery channel is assumed. Network priority scheduling, Byzantine peer handling, global partition consensus, and verified safe containment are not implemented here.

## Run the new pinned-model benchmark

```bash
cd /opt/carla_demo
git pull origin main

python -u scripts/run_phase13_suite.py \
  --config configs/phase13/comparison.resilient.pinned.json \
  --profile pinned --seeds 42 --workers 1 \
  --output-dir results/phase13/resilience_v2_pinned_run1
```

This runs the full 40-case matrix at a 600-second budget. A/C remain deterministic; B/D use `phase12-agent:pinned` with digest `46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e`. Original auction windows, lease interval, inference settings, flight speed limit, mission routes and degraded-network presets are retained. The changed guardian, retry settings, source hashes and benchmark version are recorded in the manifest. Resume only with identical source and inputs using `--resume`.

For one severe case first:

```bash
python -u scripts/run_phase13_comparison.py \
  --config configs/phase13/comparison.resilient.pinned.json \
  --architecture D --condition severe --seed 42 \
  --output-dir results/phase13/resilience_v2_severe_D_run1
```

After pilot validation, run matched seeds in a **new** output directory, for example `--seeds 42 43 44`. Do not mix v1 and v2 runs into a single architecture success estimate. A cross-version improvement includes shared infrastructure changes; C versus D within v2 is the relevant policy comparison.

## Offline engineering validation

```bash
python -u scripts/run_phase13_resilience_validation.py \
  --seeds 42 43 44 \
  --output-dir results/phase13/resilience_v2_validation_local
```

This is an 18-case subset: A/C/D, moderate/severe, three seeds, 600-second budgets. It explicitly uses simulated time and replay for D. It does not contact Ollama or establish LLM performance. All cases use the common comparison runner, complete traces are archived losslessly, and compact summaries/arrivals/validation evidence are saved. Inspect `suite_summary.json`, `metrics.csv`, `validation_evidence.json`, and case manifests before interpreting results.

Unit tests cover bounded retries through an actual partition, preserved TTL, idempotent ownership repair, delivered-only completion reconciliation, out-of-order observations, spatial uncertainty and retained hazards, unsafe-route rejection, temporary waiting and separately attributed role fallback. Legacy configurations retain v1 behavior unless `resilience.enabled` is set.

## Observed offline validation results

All 18 targeted engineering missions completed within 600 simulated seconds across seeds 42, 43 and 44. Runtime errors, validation failures, duplicate task completions and mismatched shared inputs were zero. Actual LLM runs: **zero**. D used a replay fixture; these results do not replace the user's real-model 600-second pilot.

| Condition | Architecture | Successful runs | Completion time range (s) |
|---|---|---:|---:|
| moderate | A | 3/3 | 10.4–11.2 |
| moderate | C | 3/3 | 158.2–158.3 |
| moderate | D | 3/3 | 158.2–158.3 |
| severe | A | 3/3 | 14.9–21.6 |
| severe | C | 3/3 | 160.2–160.8 |
| severe | D | 3/3 | 160.2–161.1 |

Independent checks matched all actual effects to executed guardian selections, checked both arrival indices for every completed task, checked packet TTL at delivery, and found no duplicate completions. All 18 cases used identical core implementation hashes. Minimum sampled inter-drone separation was 8.0 m; that is a sampled mock metric, not a physical safety guarantee. The repository regression suite passed **193 tests**, including 13 resilience tests.

[Validation summary](../results/phase13/resilience_v2_validation_final/suite_summary.json) · [Metrics CSV](../results/phase13/resilience_v2_validation_final/metrics.csv) · [Arrival and validation evidence](../results/phase13/resilience_v2_validation_final/validation_evidence.json) · [Independent audit](../results/phase13/resilience_v2_validation_final/independent_audit.json)

The repository contains compact manifests, metrics, arrival evidence and archive checksums. Large per-case raw trace archives remain in the execution workspace and can be regenerated with the validator command. Three seeds are an engineering check, not a statistical reliability estimate. No new result is claimed for actual teammate-failure recovery or real pinned-model D until those experiments are run.
