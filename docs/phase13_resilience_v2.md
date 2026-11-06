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

The repository contains compact manifests, metrics, arrival evidence and archive checksums. Large per-case raw trace archives remain in the execution workspace and can be regenerated with the validator command. Three seeds are an engineering check, not a statistical reliability estimate. These offline checks do not establish actual teammate-failure recovery or real-model performance; the subsequent pinned-model results are documented below.

## Observed pinned-model results: resilience_v2_pinned_run1

The uploaded [suite summary](../results/phase13/resilience_v2_pinned_run1/suite_summary.json) and [per-case metrics](../results/phase13/resilience_v2_pinned_run1/metrics.json) were reviewed at repository commit `ac834a7e6f4f0c647e1622937b831937ad20984c`. The reference is the [previous 600-second suite](../results/phase13/duration_600s_run1/budget_600s/metrics.json). Both are single-seed pilots (seed 42) with a 600-second budget and mock flight. A/C are deterministic; B/D use actual pinned Ollama inference. These results are separate from the replay-based offline validation above.

### Completion across the suite

| Measure | Previous 600-second suite | Pinned resilience v2 |
|---|---:|---:|
| Tests finished | 40/40 | 40/40 |
| Successful missions | 15/40 | **19/40** |
| Incomplete missions | 25/40 | 21/40 |
| Successful baselines without an intentionally stopped drone | 12/16 | **16/16** |
| Observed actor-failure injections | 21 | 21 |
| Successful missions after an observed actor failure | 0/21 | **0/21** |

The new suite reports zero runtime errors, zero validation failures, zero mismatched-input checks and 21 actual-model runs. All 40 summaries, validation records, waypoint files and fault-event files were cross-checked: completion and injection flags agree, every completed task has waypoint indices 0 and 1, and all summaries report zero duplicate completions. The pinned profile does not perform the offline profile's exact same-seed packet-replay check.

### Previously incomplete moderate/severe baselines

| Architecture and condition | Previous result | Pinned resilience v2 |
|---|---|---|
| A, severe | 2/4 tasks; incomplete | **4/4 in 23.5 s** |
| C, severe | 0/4 tasks; incomplete | **4/4 in 163.0 s** |
| D, severe | 1/4 tasks; incomplete | **4/4 in 214.9 s** |
| C, moderate | 3/4 tasks; incomplete | **4/4 in 159.0 s** |
| D, moderate | 4/4 in 522.5 s | **4/4 in 168.1 s** |

The three newly completed severe cases and moderate C account for the four additional successful missions. Moderate D's observed completion time decreases by approximately 68% in this pair.

These baselines test communication degradation without intentionally stopping a drone. The inspected severe-D manifests retain the same mission, model digest and network parameters: 400 ms mean latency, ±200 ms jitter, 30% independent loss, a 60-recipient-packets/s per-sender rate limit and 50,000 bytes/s per-sender bandwidth.

All v2 no-agent-failure baselines complete:

| Condition | A: centralized | B: independent LLM | C: decentralized rules | D: decentralized LLM |
|---|---:|---:|---:|---:|
| Nominal | 10.6 s | 88.2 s | 158.5 s | 169.9 s |
| Moderate | 11.2 s | 38.9 s | 159.0 s | 168.1 s |
| Severe | 23.5 s | 60.5 s | 163.0 s | 214.9 s |
| Partitioned | 17.6 s | 50.1 s | 158.9 s | 167.3 s |

Every cell is 4/4 tasks and full mission success. This does not imply every completion time improved: nominal B increases from 38.3 s to 88.2 s and nominal A from 8.1 s to 10.6 s. C remains faster than D under severe communication.

### Evidence for actual LLM participation in severe D

The severe-D run uses `phase12-agent:pinned`, digest `46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e`, temperature 0. Each drone completes one sector, and productive LLM decisions are observed for every drone:

| Drone / sector | Final waypoint time |
|---|---:|
| Drone1 / A | 123.9 s |
| Drone2 / B | 114.1 s |
| Drone3 / C | 187.2 s |
| Drone4 / D | 214.9 s |

All eight arrivals link to applied LLM request IDs in the archived decision histories. All recorded arrivals use task version 1, and the run reports no lease expirations. The inspected histories contain zero inference timeouts and one recorded policy fallback.

An independent check of the severe-D guardian archive matches all 47 actual effects to executed guardian selections. Minimum sampled inter-drone separation is 8.0 m; this is not a physical or between-sample safety guarantee. The 56 guardian records comprise 38 approved bounded-segment modifications, 9 approvals and 9 rejections. Routine segment modifications must not be counted as unsafe LLM proposals. The retry archive records 255 bounded retry events, which still consume the configured degraded channel.

### Remaining failure-recovery limitation

All 21 incomplete v2 cases have actual actor-failure injections. Completion under severe packet loss has improved, but mission completion after a permanently silent teammate remains unresolved. Stale-peer safety stops still appear in the failed cases; an unreachable aircraft is not deleted or assumed safely contained.

The D relay-failure control now changes Drone4 from RESERVE to RELAY at 70.8 s, whereas the previous D control made no role change. The archived source is **deterministic_role_fallback**, not an LLM-selected role change. The run still completes zero tasks. This demonstrates the role-decision deadline rule, not successful relay positioning, restored RF connectivity or full mission recovery.

### Interpretation and ablations

The nominal deterministic policy replacement finishes at 158.7 s versus 169.9 s for nominal D. Memory-off D finishes at 170.5 s. These single observations do not establish an LLM or memory advantage. Perfect-communication D finishes at 169.0 s; severe D now also completes, at 214.9 s. The network override changes several network properties together.

V2 changes shared retry/coordination support and the guardian to `ReachablePeerGuardian`. The observed gains support that combined implementation, not an isolated claim that LLM reasoning improved. They do not establish statistical reliability, live-flight safety or general superiority of D. Matched multiple-seed pinned trials and safe execution under missing-peer uncertainty remain necessary.

A suitable research statement is:

> In a seed-42 pinned-model mock-flight pilot, the revised shared resilience infrastructure increased no-agent-failure mission completion from 12/16 to 16/16 across four communication conditions. Centralized, deterministic decentralized and agentic decentralized architectures all completed the severe-loss mission within 600 seconds; mission recovery after intentional actor silence remained incomplete.
