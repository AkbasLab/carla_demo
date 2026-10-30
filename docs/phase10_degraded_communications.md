# Phase 10: reproducible degraded communications

This mock benchmark replays the Phase 9 team mission through a new application-level network. No LLM, AirSim, RF hardware, or calibrated radio propagation is involved. Agents retain only send/receive endpoints. Configuration, infrastructure positions, queues and delivery logs remain outside agents. Phase 7–9 default perfect transport is unchanged.

## Run

From the repository root:

```bash
python -u scripts/run_phase10_network.py --condition nominal --seed 42 --output-dir results/phase10/nominal
python -u scripts/run_phase10_network.py --condition moderate --seed 42 --output-dir results/phase10/moderate
python -u scripts/run_phase10_network.py --condition severe --seed 42 --output-dir results/phase10/severe
python -u scripts/run_phase10_network.py --condition partitioned --seed 42 --output-dir results/phase10/partitioned
```

All use the same four tasks, starting positions, roles and deterministic execution. Target placement is fixed at (5,5,-3), so it also stays identical across seeds/architectures. Use `--critical-task --target-at 5` to enable discovery. Add `--fail-agent Drone3 --fail-at 2` to inject relay silence at exactly simulation second 2. Default has no stopped agent. `--ticks 1200 --dt 0.1` sets a maximum 120 simulated seconds; the run stops early if all active local task ledgers agree on completion. Pending packets at that stop are censored, not failures. Fixed-step polling quantizes actual inbox receipt times.

`--network-config configs/phase10/network.example.json` overrides the selected preset. Unknown keys and invalid numbers fail configuration validation.

| Condition | Mean latency | Uniform jitter half-width | Independent loss | Additional limits |
|---|---:|---:|---:|---|
| nominal | 10 ms | 2 ms | 0% | none |
| moderate | 100 ms | 50 ms | 10% | none |
| severe | 400 ms | 200 ms | 30% | 60 recipient packets/s, 50,000 bytes/s |
| partitioned | 10 ms | 2 ms | 0% | Drone1/2 isolated from Drone3/4 during [5,12) s |

These are pilot parameters, not properties of a particular radio. A base station can be another registered endpoint in a custom harness and assigned to a partition group; the current team mission has no base station. Burst loss, interference zones and asymmetric links are future extensions, not implemented settings.

## Network semantics

Each recipient copy is a packet. Multicast consumes one egress slot and its serialized envelope bytes per recipient. Each sender has a shared FIFO egress: service duration is the greater of the rate-limit interval and byte serialization duration. This is deterministic pacing/queueing, not a queue-overflow loss model. Independent loss and latency draws are keyed by seed, mission, sender, sequence and recipient, so unrelated traffic does not shift another packet's random draws. Loss draws exist even for packets blocked by geometry or partitions; logs distinguish causes. Same *offered trace* and seed produce identical network outcomes; divergent architectures can generate different traces and therefore different packets.

Latency samples are uniform over mean ± jitter, requiring mean >= jitter. Range uses infrastructure positions at transmission scheduling and delivery processing; it is a hard distance cutoff, not RF propagation. Partition membership is checked at scheduled transmission and network arrival times. Position sampling is at the simulator's current processing step, not an interpolated future physical trajectory. Rate-limited packets wait in an unbounded egress queue and may expire before delivery. TTL uses message creation time, with `now >= expires_at` rejected. At the Phase 10 endpoint, heartbeat TTL is 1.5 s, intent TTL 2 s, target TTL 60 s, mission-update TTL longer than the configured experiment horizon; remaining protocol messages retain the existing lease-dependent TTL.

## Local health estimates

`ObservedEndpoint` adds delivery acknowledgments to outgoing envelopes and removes this metadata on receipt before passing messages to the allocator. It creates no extra message type or privileged side channel. Each agent sees heartbeat arrival rate/age, missing sequence counts (corrected for later reordering), latest acknowledgment RTT and recent acknowledgment counts. ACKs summarize the highest received sequence, not a cumulative assertion that all lower sequences arrived. RTT includes scheduling and piggyback wait; it is not pure link latency. Sequence gaps are evidence of missing observations, not proof of loss. The four-agent runner broadcasts to all peers, which makes sequence gaps interpretable; selective-recipient traffic would need per-link sequences. Estimates are logged for analysis; the existing Phase 9 role policy continues to use received heartbeat ages rather than reading loss configuration or automatically tuning safety thresholds.

## Outputs and interpretation

`summary.json` includes the effective configuration, seed, replay parameters, network status/drop counts, mission completion, duplicate work, roles and final health estimates. `messages.json` records independent draws, sampled latency, queue delay, delivery scheduling, expiry and outcomes per recipient. `beliefs.json` contains only local agent views plus estimates; `events.json` records task and role decisions. Incomplete missions, duplicate tasks and role disagreement under partitions are valid experimental findings. The existing allocator is not distributed consensus and is not guaranteed to complete safely under all degradation.

## Validation

```bash
python -m unittest discover -s tests -p 'test_phase10_network.py' -v
```

Tests send 10,000 messages per seed, compare independent loss against 30% (±2 percentage points), mean latency against 100 ms (±2 ms), check uniform support/variance, identical/different seed behavior, partition link/interval isolation, TTL, rate/bandwidth service, range, local ACK observation and byte-identical mission outputs on repeated runs under all four conditions. Statistical bounds concern raw network draws; mission-observed losses additionally include partitions, range and expiration. Successful replay is distinct from successful task recovery.

## Initial seed-42 pilot

With no agent failure and the default 120-second maximum, nominal completed at 18.1 s. Moderate, severe and partitioned conditions reached the 119.9 s final sample without mission completion. No duplicate completions were observed in these four runs. These are individual deterministic pilot results, not a statistical recovery-success estimate. The current protocol requires further reliability/reconciliation work before claiming resilient mission completion under degraded transport.
