# Phase 10 validation and completion report

## Scope and assessment

The initial degraded-communications simulator is implemented for mock application-level messages. All checks in the accompanying `phase10_network_validation.json` passed: **PASS**. This establishes reproducible controlled faults, not resilient mission completion or calibrated RF behavior.

## Requirement coverage

| Requirement | Evidence / implementation |
|---|---|
| 10.1 Configurable model | All six initial settings: mean latency, jitter, independent loss, rate, bandwidth and hard distance cutoff. Timed partitions also implemented. |
| 10.2 Four conditions | Nominal, moderate, severe and partitioned presets; matched-seed mission results committed under `results/phase10/multiseed_1_30`. Base-station link isolation checked separately below. |
| 10.3 Reproducibility | Same seed and identical offered trace produce identical complete network-log hashes. Different seeds produce different traces. Fixed mission/target locations and explicitly scheduled failures are deterministic; target randomization is unnecessary for the current fixed scenario. |
| 10.4 Expiration | Creation-time TTL is enforced at receipt, including exact expiration. Phase 10 endpoints use 1.5 s heartbeat, 2 s intent, 60 s target, and mission-update lifetime beyond the experiment horizon. |
| 10.5 Local health estimates | Agents observe heartbeat arrival rate/age, missing sequences and piggyback ACK counts/RTT through their endpoint; network settings remain infrastructure-only. The recovery policy mainly uses heartbeat age. |
| 10.6 Statistical checks | Measured loss, uniform latency support/CDF/mean/variance, same-seed hashes, selective partitions and expiration, plus the automated network tests. |

## Statistical network measurements

Seed **42**, **10000 offered recipient packets per condition**, plus an identical-seed replay and a different-seed comparison for each condition. Distribution checks deliberately disable rate/bandwidth limits to isolate raw loss and latency sampling. They do not substitute for queueing tests. Loss tolerance is ±2 percentage points, mean latency ±2 ms, uniform CDF error ≤0.02, variance within 5% of the theoretical uniform variance, and exact support bounds.

| Condition | Configured loss | Measured loss | Configured mean (ms) | Measured mean (ms) | Checks |
|---|---:|---:|---:|---:|---|
| nominal | 0% | 0.000% | 10 | 9.998 | PASS |
| moderate | 10% | 9.990% | 100 | 99.939 | PASS |
| severe | 30% | 30.380% | 400 | 399.758 | PASS |

Raw latency is uniform over mean ± jitter. Actual application receipt includes polling, queueing and serialization, so it can exceed this interval. Full measured variances, CDF errors, counts and replay hashes are in the JSON evidence.

## Base-station partition and expiration

The focused test registers four drones plus `BaseStation`, with groups `[Drone1, Drone2]` and `[Drone3, Drone4, BaseStation]`. At 5.0 and 11.9 s, only the 12 directed cross-group copies are blocked; the 8 within-group copies arrive. At 4.0 and 12.0 s, all 20 directed copies arrive. This verifies both directions, unaffected links, base-station isolation from one group, and restoration at the interval boundary. This is a transport test, not a new five-agent mission controller.

The expiration test schedules 500 ms latency. A message with a 500 ms TTL is rejected at the exact deadline; one with a 2 s TTL arrives. No packet arrives before its scheduled time.

## Mission-level findings: seeds 1–30

All trials use the same four search tasks, no stopped agent and a 120 s maximum horizon. Task completion counts refer to mock work events; mission success additionally requires agreement across all active local task ledgers.

| Condition | Mission successes | Runs with all four tasks completed | Mean successful completion time |
|---|---:|---:|---:|
| Nominal | 30/30 | 30/30 | 18.1 s |
| Moderate | 10/30 | 27/30 | 55.38 s |
| Severe | 0/30 | 0/30 | Not observed |
| Partitioned | 0/30 | 0/30 | Not observed |

No duplicate completions were recorded. Incomplete trials are right-censored, not assigned a successful completion time. Moderate results expose completion-state reconciliation problems; severe results expose role/health instability and queue-driven expiration; partitioned results expose failure to restore full-mission execution after connectivity returns. These are coordination limitations, not evidence that message degradation failed to occur. Intervals in the multi-seed comparison apply to network randomness for this fixed mock mission, not real flight or other mission geometries.

## Reproduce

```bash
python scripts/validate_phase10_network.py --seed 42 --messages 10000
python -m unittest discover -s tests -p 'test_phase10*.py' -v
python scripts/run_phase10_sweep.py --seeds $(seq 1 30) --output-dir results/phase10/new_sweep
```

The validator regenerates this Markdown and `docs/phase10_network_validation.json`; a failed validation exits nonzero. Use a new sweep directory to preserve earlier results.

## Boundaries and deferred work

Burst loss, interference zones and asymmetric links are explicitly later extensions and remain deferred. No live CARLA–AirSim integration, RF calibration or relay-throughput improvement is claimed. Queueing is unbounded FIFO pacing; radio contention and propagation are not modeled. Range is a hard cutoff sampled by infrastructure, not sensed by agents. ACK RTT includes peer scheduling; sequence gaps can represent reordering or selective addressing rather than proven packet loss. The current all-peer broadcast mission makes sequence gaps interpretable. Common seeds align random draws for matching sender/sequence/recipient keys, not different packets generated by diverging architectures.

**Exit criterion:** satisfied for the initial mock scope: the same mission can be replayed under all four conditions with reproducible message delivery. Successful recovery across those conditions remains future coordination work.
