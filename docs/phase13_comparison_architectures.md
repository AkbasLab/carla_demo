# Phase 13 — configurable comparison architectures

## Scope and exit criterion

`scripts/run_phase13_comparison.py` selects A, B, C or D through one JSON configuration or `--architecture`. All four run through the same experiment loop, mission loader, observed-waypoint executor, kinematic vehicle adapter, injection schedule, seeded application-network model and independent runtime guardian. The architecture-selection exit criterion is implemented and covered by nominal execution tests.

**This initial comparison runner supports mock flight only.** Phase 12's successful pinned-Ollama `easy_run4` remains separate evidence; it is not an Architecture D Phase 13 result. Phase 13 replay fixtures verify interfaces and control boundaries. Actual pinned-model comparisons, multiple seeds and a common live-flight backend remain necessary for paper performance claims. Optional E is not implemented; the older preflight runners remain historical baselines.

## What differs

| Architecture | Assignment authority | High-level policy | Communication/recovery |
|---|---|---|---|
| A — centralized fleet | `FleetController`, using only vehicle states delivered to its own inbox | Deterministic nearest-cost idle-vehicle assignment; no LLM | Uplink status and downlink task commands pass through the network. Commands are retried, expire and require fresh delivery; disconnected vehicles cancel/hold through the guardian. Central task leases and delivered progress permit reassignment. |
| B — independent persistent | Reliable initial operator briefing, configured once per drone | Same pinned model as D when Ollama is selected; replay fixture for offline checks | No negotiation, bidding, peer task adoption, role coordination or reassignment. Local route revalidation, safe hold and return-home remain available. Peers exchange safety beacons only. |
| C — deterministic decentralized | Local contract-net ledgers and delivered messages | Transparent rule policy using the shared structured tools; no inference | Deterministic costs, task leases, staged peer health, local role rules and reauction. Same observed communication-health inputs as D. |
| D — agentic decentralized | Same local contract-net ledgers and delivered messages as C | Pinned Ollama high-level policy; replay explicitly labelled for fixture testing | Same tool constraints, role eligibility, network, leases and guardian; persistent per-agent contexts. Deadline bids and bounded safety releases remain explicitly deterministic support. |

A is a greedy nominal-efficiency baseline, not an optimal global fleet planner. B's pre-mission assignments are not lossy startup messages. These assumptions are recorded, rather than silently giving one architecture ground-truth updates during a run.

Safety beacons in A/B supply the same guardian interface; they do not authorize decentralized task decisions. The controller never reads the backend, bus queue or another actor's private ledger. C/D actors receive endpoints, not the transport object. Their local beliefs update from addressed delivered messages. Peer health reports silence as UNREACHABLE rather than confirmed physical failure. Dynamic role changes affect role/tool eligibility and guarded relay motion, never teleportation. Initial safety-beacon acquisition precedes policy requests; missing early telemetry alone does not trigger replacement of a known initial relay.

## Shared infrastructure and matching

* `agentic_uav/policy/mission.py`: shared Phase 12/13 mission and guardian configuration loader.
* `WaypointExecutor` and `MockFlight`: observed arrivals and the same segmented motion/battery model for all four architectures.
* `ExperimentSchedule`: the same configured actor-silence time for all architectures. The harness cancels the injected actor's motion; no failure oracle is delivered to policies.
* `DegradedMessageBus` and `ObservedEndpoint`: nominal, moderate, severe and partitioned conditions, seeded loss/latency, expiry and locally measured heartbeat/sequence/ack/RTT inputs.
* `RuntimeGuardian` and `GuardedExecutor`: the same geometry, separation, stale-state, battery, command and actuation checks on every dispatched movement.

`manifest.json` saves the effective configuration, source hashes, model identity/options, common input fingerprint, authority, effective clock and lease-ablation semantics. The common fingerprint includes mission/safety configuration, timing, network, seed, scenario, initial briefing and requested primary model configuration; architecture and intentional ablations are separately labelled. Inspect the manifest rather than comparing folder names alone.

Communication traffic is allowed to differ because protocols differ. Same seed reproduces the same architecture and message stream; it does not guarantee identical dropped messages across architectures whose senders, sequences and traffic differ. Sequence gaps are local delivery observations, not calibrated RF loss measurements. Perfect communication removes intentional latency, loss, range limits, partitions, rate limits and bandwidth limits; recipient polling can still add one simulation tick.

The partition preset places `FleetController` with Drone1/Drone2 while Drone3/Drone4 are separated during the configured interval. The same station identity and partition geometry are present in every architecture's network; only A uses that station for decisions.

## Run the four architectures

From the repository root, no Ollama or CARLA–AirSim is required for initial wiring checks:

```bash
python -u scripts/run_phase13_comparison.py --architecture A --output-dir results/phase13/A_nominal_run1
python -u scripts/run_phase13_comparison.py --architecture B --output-dir results/phase13/B_nominal_run1
python -u scripts/run_phase13_comparison.py --architecture C --output-dir results/phase13/C_nominal_run1
python -u scripts/run_phase13_comparison.py --architecture D --output-dir results/phase13/D_replay_run1
```

These use `configs/phase13/comparison.example.json`. Default B/D use replay fixtures, **not real LLM inference**. A/C use the deterministic provider regardless of the requested model provider, and record this explicitly. Use a new output directory on every run; existing evidence is never overwritten.

For a pinned-model D run:

```bash
python -u scripts/run_phase13_comparison.py \
  --architecture D --provider ollama \
  --model phase12-agent:pinned \
  --model-digest 46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e \
  --condition nominal --seed 42 \
  --output-dir results/phase13/D_ollama_nominal_run1
```

Run B with the same provider/model/digest and shared settings when isolating coordination from independent LLM policies; running deterministic B versus real-model D would change two factors. Temperature zero, digest checks, warmup and request/response archives come from Phase 12. Verification occurs before creating the vehicle backend; preflight errors are saved separately. The runner rejects a simulated clock for real inference. For strict formal wall-time matching, set `clock_mode: "wall"` for all four architectures; auto uses a simulated clock for fixtures and wall pacing for Ollama. Do not treat host execution speed as vehicle mission time.

For a formal four-way matrix, put the pinned provider/model/digest and `clock_mode: "wall"` into one shared configuration file, then vary only architecture and output folder. A/C will record that requested primary configuration while using deterministic policies; B/D will call the same model. This keeps the common-input fingerprints comparable.

The default 30-second bid window and 180-second lease preserve the latest Phase 12 pilot settings. The contract-net implementation also waits a bid window before execution after a claim. These timers dominate C/D's simple nominal-route fixture time; their values are experimental parameters, not evidence of intrinsic architectural inefficiency. Calibrate, then freeze them for comparisons. A does not incur an artificial auction delay.

## Degradation and disruption

Select the same condition, seed and scenario for each architecture:

```bash
python -u scripts/run_phase13_comparison.py \
  --architecture C --condition moderate --seed 42 \
  --fail-agent Drone1 --fail-at 8 \
  --output-dir results/phase13/C_moderate_drone1_run1
```

Change only `--architecture` and output folder for the matched A/B/D cases. For real B/D inference, also retain the same pinned-model settings. Network overrides belong in the JSON `network` object and apply equally to the four architectures.

A failed or disconnected drone becomes a stale peer hazard under the common guardian. **Reassignment does not guarantee mission completion** if its current position cannot be established safely. The harness retains that fail-closed behavior and does not fabricate fresh failed-drone telemetry, remove a hazard, relax separation or share ground truth to force successful recovery. Such incomplete trials are valid results to analyze, not successful resilience demonstrations.

## Ablations

Use D and change one flag at a time, keeping the remaining mission, seed, provider and timing settings fixed:

| Flag | Exact change |
|---|---|
| `--without-memory` | Remove episodic policy memory from prompts. Keep required identity, current beliefs/task, current skill result, inbox and audit history. This is not a stateless-vehicle ablation. |
| `--without-task-leases` | Suppress automatic task expiry for the run horizon. Keep ordinary packet TTLs, heartbeat eligibility, health thresholds, progress reporting and explicit voluntary/safety releases unchanged. |
| `--without-dynamic-roles` | Remove role-change tools/recommendations and reject role changes. Initial roles remain fixed. |
| `--perfect-communication` | Override the effective network to zero intentional latency/loss and no capacity/range/partition restrictions. |
| `--fallback-policy` | Replace LLM policy selection with the deterministic structured fallback/rule selector, including locally justified roles. No model is called and no LLM evidence is claimed. |

C already uses the same communication-health inputs as D; it is the requested input-matched deterministic comparison, rather than a second C runner with different observations.

Example (add the same Ollama arguments as above for a real-model memory ablation):

```bash
python -u scripts/run_phase13_comparison.py \
  --architecture D --without-memory \
  --output-dir results/phase13/D_without_memory_replay_run1
```

The default mission starts four scouts, so its successful nominal run does not exercise role changes. Use one common mission with relay/reserve roles and a disruption when testing role-specific ablations; do not claim a role benefit from an unexercised flag. Replay cannot measure the benefit of LLM memory or reasoning.

## Evidence and initial validation

The full regression suite passes 159 tests, including 20 Phase 13 tests. They cover all four nominal paths, common-input fingerprints, B isolation, delivered-only central state, downlink loss with local fallback, station partitions, exact same-seed message replay, input-matched C/D contexts, memory/lease/role/perfect-network/fallback ablations, failure schedules, pin verification before control and common keepout protection. Existing Phase 12 tests continue to pass after the shared loader extraction and the replay fixture's safer unknown-state HOLD handling.

`results/phase13/wiring_baselines` contains compact summaries/manifests for offline wiring checks. Detailed traces are generated under `work/phase13`; use formal output directories to retain full traces for actual experiments. A/C are deterministic; B/D in these smoke results are replay, not model inference. Identical nominal results for some ablations are expected: a four-scout, no-failure replay mission does not exercise every ablated feature.

The default nominal wiring runs complete in 8.0 s (A), 7.9 s (B), and 158.1 s (C/D). All have zero duplicate completions and guardian-covered dispatches. C/D time is dominated by the configured 30-second auction and claim-settling timers; D here is replay with no inference. These are plumbing measurements, not a paper result about model superiority or architectural optimality.

Primary outputs:

| File | Purpose |
|---|---|
| `manifest.json` | Effective inputs, fingerprint, model, clock, source hashes and architecture authority. |
| `summary.json` | Actual route completion, duplicates, decisions, source-specific productive effects, deterministic support, role/lease events, guardian and network outcomes. |
| `messages.json` | Scheduled/delivered/dropped/expired recipient packets, latency draws and decision-use marking. |
| `controller_events.json` | A's assignments, command retries and lease expiry; empty for B/C/D. |
| `scenario_events.json` | Harness-only injection time and cancellation acknowledgment. |
| `protocol_events.json`, `waypoint_arrivals.json`, `flight_trace.json` | Local task protocol, observed arrivals, roles and locally measured communication health. |
| `guardian_audit.json`, `executed_actions.json` | Independent validation decisions and actual mock effects. |
| `DroneN/*.jsonl`, `memory.json` | Isolated prompts, exact Ollama requests, raw replies, decision history and retained audit memory. |

The common stop criterion is observed route completion, not universal agreement of all ledgers. Packets or completion acknowledgments still pending at stop are censored. Duplicate completions are reported and never converted into an allocation success claim. No LLM or live exit flag can become true for a replay fixture. `mission_execution_success` is the common completion/no-duplicates/guard-coverage check. `llm_supported_execution_success` measures attributable LLM-supported completion, while `decentralized_coordination_enabled` identifies C/D. Independent B model decisions must not be described as negotiated cooperation.

```bash
python -m unittest discover -s tests -p 'test_phase13*.py' -v
python -m unittest discover -s tests
```

## Automated matrix and manual pinned-model commands

See [automated testing and local commands](phase13_automated_testing.md) for one-folder-per-test execution, shared pinned configurations, role-specific controls, serial real-model testing, safe resume and figure-ready lossless trace archives. The offline validation dataset is separate from real-model evidence.
