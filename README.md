# Agentic UAV Simulation & Mission Framework

A modular multi-UAV research framework for search-and-relay operations using CARLA–AirSim and Python mock environments. The project progresses from simulator adapters and deterministic skills to message-based task allocation, dynamic roles, and reproducible degraded-communication experiments.

LLM benchmarks and command-generation experiments are separate from the deterministic coordination baselines: **Phases 7–10 do not require an LLM**. Mock task completion, live waypoint execution, communication delivery, and flight safety are distinct measurements.

## Project phases: 1–10

| Phase | Focus | Main entry point | Execution / evidence |
|---|---|---|---|
| 1 | Environment foundation and LLM syntax/latency baseline | `scripts/run_phase1_llm_latency.py` | Ollama benchmark; no flight required |
| 2 | Simulator adapters and batch command execution | `scripts/run_phase2_batch_tasks.py` | Two-drone AirSim execution benchmark |
| 3 | Seven deterministic UAV skills | `scripts/run_phase3_skills.py` | Mock or AirSim |
| 4 | Canonical search-and-relay scenario | `scripts/run_phase4_scenario.py` | Mock or AirSim; configured ground-truth detection |
| 5 | Structured mission planning and orchestration | `scripts/run_phase5_planner.py` | Current directive runner uses deterministic fallback planning |
| 6 | Event-driven inter-drone communication and reactive relay | `scripts/run_phase6_decentralized.py` | Mock or AirSim; relay positioning does not prove RF improvement |
| 7 | Perfect-communication message protocol | `scripts/run_phase7_resilience.py` | Four-agent mock and four-vehicle AirSim backends |
| 8 | Decentralized task allocation without an LLM | `scripts/run_phase8_allocation.py` | Mock and live waypoint execution; leases and reassignment |
| 9 | Dynamic roles and teammate-disruption recovery | `scripts/run_phase9_roles.py` | Deterministic mock baseline |
| 10 | Seeded degraded-communications simulator | `scripts/run_phase10_network.py` | Mock network validation and matched-seed mission trials |

### Phase 1: environment setup, foundation, and LLM baseline

- Established the CARLA–AirSim / Python mock development setup and vehicle telemetry abstractions such as `Position3D` and `VehicleState`.
- Benchmarked structured coordinate generation from natural-language prompts, including inference latency, JSON parsing and raw responses.
- The local baseline uses Ollama with `llama3.1:latest`; separate GPT/Groq scripts are also present. Output is recorded in `docs/baseline_results*.json`.
- Environment details: [baseline environment](docs/BASELINE_ENVIRONMENT.md) and [benchmark documentation](docs/BENCHMARK.md). Historical hardware and two-vehicle settings describe that baseline, not requirements for every later phase.

### Phase 2: simulator adapters and batch execution

- `VehicleAdapter` defines the common control interface; `AirSimAdapter` connects to the simulator and `MockVehicleAdapter` supports offline work.
- The batch benchmark generates target coordinates, commands Drone1 and Drone2 in AirSim, and records parsing, execution and timing results in `docs/baseline_simulation_results*.json`.
- The current `run_phase2_batch_tasks.py` connects directly to AirSim; it does not offer a `--airsim` switch or a mock CLI mode. Mock support is provided by subsequent skill/scenario runners.

### Phase 3: high-level UAV skill engine

`SkillEngine` abstracts flight commands into seven reusable deterministic skills:

| Skill | Function |
|---|---|
| `TAKE_OFF` | Arm and initiate takeoff |
| `GO_TO_WAYPOINT` | Navigate to a 3D target |
| `SEARCH_REGION` | Generate and execute a grid/lawnmower search pattern |
| `HOLD_POSITION` | Station keeping / hover |
| `ACT_AS_RELAY` | Position at a designated relay point |
| `RETURN_HOME` | Navigate back to the launch position |
| `LAND` | Execute the landing sequence |

`SkillResult` records status, timestamps, skill identity and telemetry. A relay skill describes vehicle positioning; it does not establish that a wireless link was restored.

### Phase 4: canonical search-and-relay scenario

- [Mission configuration](configs/missions/search_and_relay.json) defines a base station, NW/NE/SW/SE search sectors, restricted volumes such as `NFZ_1`, and targets such as `Survivor_Alpha` and `Vehicle_Bravo`.
- `ScenarioManager` uses configured ground truth and proximity/geometry checks for early target-detection experiments, rather than a computer-vision detector.
- Keep-out checking detects/logs configured geometric violations. Cooperative examples use Drone1 for search and Drone2 for relay positioning.
- Optional camera capture is documented in [camera capture](docs/camera_capture.md).

### Phase 5: structured mission planning and orchestration

- `HighLevelGoal`, `PlanStep` and `MissionPlan` represent high-level directives and ordered skill steps.
- `LLMTaskPlanner` defines the structured planning interface and a deterministic fallback that maps directives to skills.
- `AutonomousOrchestrator` executes steps, checks configured boundaries and handles failure through recovery skills.
- The current `run_phase5_planner.py` path uses fallback planning. Running it alone is **not evidence of a live LLM call**, grammar-constrained generation, or a general safety guarantee.

### Phase 6: decentralized event-driven relay behavior

`CommBus` provides an event-driven publish/subscribe transport. A search drone publishes a target-discovery event; `ReactiveRelayAgent` computes a spatial midpoint between that drone and the base station and commands relay positioning.

```text
Drone1: search / target discovery
             |
             | TARGET_DISCOVERED + position
             v
       CommBus (pub/sub)
             |
             v
Drone2: reactive midpoint positioning
             |
             v
      Base-station reference
```

This demonstrates message-triggered relay behavior without a central per-action LLM planner. It does not, by itself, establish sub-10 ms end-to-end decision latency, improved RF throughput, or autonomy under arbitrary communication loss. Controlled loss modeling and its limitations are addressed in Phase 10.

### Phase 7: perfect-communication inter-agent protocol

- Defines 13 message types: `HEARTBEAT`, `STATUS_UPDATE`, `TASK_ANNOUNCEMENT`, `TASK_BID`, `TASK_AWARD`, `TASK_ACCEPT`, `TASK_RELEASE`, `TASK_COMPLETE`, `INTENT_UPDATE`, `TARGET_FOUND`, `HELP_REQUEST`, `ROLE_CHANGE`, and `MISSION_UPDATE`.
- Uses a common envelope with IDs, sender/recipients, mission ID, creation time, sequence number, TTL, payload and optional confidence.
- Agents interact through `send(message)` and `receive_available()`; local peer beliefs update from delivered messages. Isolation is an API convention, not a security sandbox.
- Logs creation, scheduled/actual delivery, recipient, size, expiration and decision influence. Plots cover traffic, delivery counts, telemetry and local peer beliefs.
- A recorded four-vehicle run delivered **4,839/4,839 recipient copies from 1,613 unique messages**. Four landing-confirmation warnings mean successful delivery must not be interpreted as verified landing safety.

See [Phase 7 protocol](docs/phase7_protocol.md). The historical RF/low-battery demonstration remains available through `--legacy-resilience`; it is separate from the default perfect-communication protocol.

### Phase 8: decentralized task allocation without an LLM

- Represents work as explicit tasks with capabilities, priorities, status, owners, versions and leases.
- Contract-net-style announcements, deterministic cost bids, awards/acknowledgments, progress and release messages allocate work without a central per-task assignment controller.
- Version, bid and vehicle-ID rules resolve conflicting claims; expired leases return unfinished work to the pool.
- The live backend executes configured waypoints with separate horizontal/vertical arrival tolerances, bounded retries and delivered progress checkpoints for takeover.
- Failure scenarios demonstrate reassignment and surviving-agent waypoint completion in tested runs. Configured routes are not collision avoidance; coordinate offsets and map clearance require calibration.

See [Phase 8 allocation](docs/phase8_allocation.md) and [mission configuration example](configs/phase8/carlaair.example.json).

### Phase 9: dynamic roles and failure recovery

- Begins with Drone1/Drone2 as `SCOUT`, Drone3 as `RELAY`, and Drone4 as `RESERVE`.
- Supports `HEALTHY`, `SUSPECTED`, `UNREACHABLE`, `FAILED` and `RECOVERED` peer-health states. Silence alone means unreachable, not confirmed vehicle failure.
- A reserve can replace an unavailable scout or relay. Role changes, lease expiry and rebidding use local state and delivered messages.
- Mock scout-loss and relay-loss examples completed all four tasks without duplicate completions; this is logical task/role recovery, not live flight or measured radio-link recovery.
- Safe vehicle rejoin and general partition consensus remain outside this baseline.

See [Phase 9 dynamic roles](docs/phase9_dynamic_roles.md).

### Phase 10: degraded-communications simulator

- Configures seeded latency/jitter, independent loss, sender rate/bandwidth limits, hard range cutoffs and timed partitions.
- Includes nominal, moderate (~10% loss), severe (~30% loss plus rate limits), and partitioned conditions. These are experimental parameters, not calibrated radio specifications.
- Enforces TTL and records local heartbeat, sequence-gap and piggyback acknowledgment estimates. ACK RTT includes agent scheduling and polling.
- Statistical validation uses 10,000 packets per condition plus replay/different-seed comparisons. Observed loss was **0%, 9.99% and 30.38%**; selective base-station partitioning and expiration checks also passed.
- The matched-seed experiment used seeds **1–30**, a fixed four-task mock mission, no injected drone failure and a 120-second horizon:

| Condition | Mission completion | Runs with all four work tasks finished | Mean successful completion time |
|---|---:|---:|---:|
| Nominal | 30/30 | 30/30 | 18.1 s |
| Moderate | 10/30 | 27/30 | 55.38 s |
| Severe | 0/30 | 0/30 | Not observed |
| Partitioned | 0/30 | 0/30 | Not observed |

No duplicate completions were observed. Mission success additionally requires agreement among active local task ledgers; moderate results expose a reconciliation gap. Severe and partitioned results expose coordination/recovery limitations. They do not invalidate reproducible network replay. Burst loss, interference zones and asymmetric links remain later extensions.

[Phase 10 report](docs/phase10_report.md) · [Network documentation](docs/phase10_degraded_communications.md) · [Validation evidence](docs/phase10_network_validation.json) · [Multi-seed results](results/phase10/multiseed_1_30)

## Project structure

```text
agentic_uav/
├── comm/
│   ├── bus.py                      # Phase 6 pub/sub bus
│   ├── protocol.py                 # Phase 7 envelope and perfect transport
│   ├── phase7_demo.py              # Four-agent protocol demonstration
│   ├── phase7_live.py              # AirSim protocol backend
│   ├── degraded.py                 # Phase 10 abstract network / local estimates
│   └── llm_commands.py             # Experiment D asynchronous command generation
├── core/
│   ├── models.py                   # Skill commands/results and telemetry
│   └── planner_models.py           # Structured mission-plan schemas
├── control/
│   ├── skill_engine.py             # Phase 3 skills
│   ├── scenario_manager.py         # Phase 4 scenario and geometric checks
│   ├── planner.py                  # Phase 5 planning interface / fallback
│   ├── orchestrator.py             # Phase 5 execution and recovery
│   ├── reactive_relay.py           # Phase 6 reactive midpoint relay
│   └── oba_recovery.py             # Experiment D recovery geometry
├── coordination/
│   ├── contract_net.py             # Phase 8 task protocol
│   ├── flight_executor.py          # Ordered live waypoints / checkpoints
│   ├── phase8_live.py              # AirSim allocation backend
│   └── dynamic_roles.py            # Phase 9 roles and health states
└── simulator/
    ├── base_adapter.py
    ├── airsim_adapter.py
    └── mock_adapter.py
configs/                            # Missions, live coordinates, experiments, network
scripts/                            # Phase runners, validators and plotting tools
docs/                               # Setup, phase documentation and reports
tests/                              # Automated checks
results/                            # Recorded experiment outputs
```

## How to reproduce

Run commands from the repository root. Use the configured project Python environment and install the dependencies required by your chosen backend; see [requirements.txt](requirements.txt) and the setup documentation. Ollama/model access is required for the local LLM benchmarks. Mock coordination does not require CARLA, AirSim or an LLM; some early runners still import simulator packages.

### Live simulator setup

Start your CARLAAir installation before using an AirSim backend. With the launch script used in the original setup:

```bash
./CarlaAir.sh Town10HD
```

Launcher location/capitalization depends on your installation; the repository also contains `carlaAir.sh`. Configure four multirotors named `Drone1`–`Drone4` for the Phase 7/8 live backends. Calibrate vehicle-local/shared NED offsets and route clearance before live execution; NED Z increases downward.

### Phases 1–6

```bash
# Phase 1: local LLM JSON/latency benchmark; writes baseline results
python scripts/run_phase1_llm_latency.py

# Phase 2: batch LLM coordinate execution; connects directly to AirSim
python scripts/run_phase2_batch_tasks.py

# Phases 3–6: mock by default; add --airsim to use the live backend
python -m scripts.run_phase3_skills
python -m scripts.run_phase4_scenario
python -m scripts.run_phase5_planner
python -m scripts.run_phase6_decentralized
```

The mission configuration uses `search_sectors` for grid geometry, `restricted_zones` for configured keep-out volumes, and `simulated_targets` for ground-truth target locations and detection radii.

### Phase 7: perfect communication

```bash
python -u scripts/run_phase7_resilience.py \
  --backend mock --ticks 200 --dt 0.1 \
  --output-dir results/phase7/protocol

# Live example: four configured vehicles, simulator running
python -u scripts/run_phase7_resilience.py \
  --backend airsim --vehicles Drone1 Drone2 Drone3 Drone4 \
  --carla-host localhost --setup-timeout 120 \
  --ticks 200 --dt 0.1 \
  --output-dir results/phase7/live_protocol
```

### Phase 8: allocation and task takeover

```bash
python -u scripts/run_phase8_allocation.py \
  --backend mock \
  --output-dir results/phase8/normal

python -u scripts/run_phase8_allocation.py \
  --backend mock --fail-agent Drone1 --fail-at 1.5 \
  --output-dir results/phase8/silent_drone1
```

For live execution, follow the [Phase 8 setup and command options](docs/phase8_allocation.md); supply `--backend airsim --mission-config configs/phase8/carlaair.local.json` with calibrated coordinates. A route-plan image shows planned waypoints, not the observed trajectory; use recorded arrivals/telemetry to evaluate execution.

### Phase 9: scout and relay disruption

```bash
python -u scripts/run_phase9_roles.py \
  --fail-agent Drone1 --fail-at 2 \
  --output-dir results/phase9/scout_loss

python -u scripts/run_phase9_roles.py \
  --fail-agent Drone3 --fail-at 2 \
  --output-dir results/phase9/relay_loss
```

### Phase 10: network conditions, seeds and validation

```bash
# Same fixed mission under all four conditions, seed 42
for condition in nominal moderate severe partitioned; do
  python -u scripts/run_phase10_network.py \
    --condition "$condition" --seed 42 --ticks 1200 --dt 0.1 \
    --output-dir "results/phase10/${condition}_seed42"
done

# Matched seeds 1–30; use a new output directory
python -u scripts/run_phase10_sweep.py \
  --seeds $(seq 1 30) --workers 4 \
  --output-dir results/phase10/new_sweep

python scripts/plot_phase10_sweep.py --input-dir results/phase10/new_sweep

# Regenerate measured network evidence and report in docs/
python scripts/validate_phase10_network.py --seed 42 --messages 10000
```

Individual detailed runs produce `summary.json`, `events.json`, `messages.json` and `beliefs.json`. Compact sweeps retain per-run summaries plus `manifest.json`, `trials.csv` and `comparison.json`. A seed reproduces the same trace for the same code, settings and offered traffic; different architectures can generate different traffic. Failure injection remains separately specified through `--fail-agent` and `--fail-at`.

### Automated verification

```bash
python -m unittest discover -s tests -q
python -m unittest discover -s tests -p 'test_phase10*.py' -v
```

The Phase 10 report update passed 73 automated tests. Passing mock tests is not evidence of collision-free flight, safe landing, real-radio resilience or restored RF connectivity.

## Related OBA and tracking experiments

These complement the numbered phases and should be evaluated using their own telemetry and limitations:

- [Experiments A/C: OBA benchmark](docs/oba_ac_benchmark.md) — configured boundary checks and comparative benchmark.
- [Experiment B: pedestrian tracking](docs/experiment_b_tracking.md) — CARLA pedestrian / AirSim drone tracking, arrival-height gating and tracking/separation plots.
- [Experiment D: communication resilience](docs/experiment_d_resilience.md) — application heartbeat/command faults, hover baseline, optional LLM command source and geometry-checked `oba-land` recovery. AirSim RPC remains available; selecting a recovery mode is not proof of successful landing.

## Simulation videos

[Recorded simulation videos](https://myerauedu-my.sharepoint.com/:f:/g/personal/metint_my_erau_edu/IgDTU9PjAa2vTrS4DH4rMRclASlWYhu1K67p_uJ6AcI05-Q?e=NtjSqZ)
