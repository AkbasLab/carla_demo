# Phase 12: persistent high-level agent policies

## What is implemented, and what has been demonstrated

Four persistent agent instances share one local Ollama model server. Each instance owns its identity, local task ledger, delivered-message beliefs, bounded memory, inbox endpoint, active task authorization and decision history. An asynchronous inference worker per agent keeps model waiting off the protocol/watchdog loop; these are client threads, not four GPU model copies.

The implementation includes a replay fixture, a pinned Ollama provider, a kinematic airborne mock backend and an optional AirSim adapter. **The recorded baseline is replay + mock flight, not LLM inference or a live AirSim experiment.** It validates isolation, structured tool plumbing, deterministic protocol behavior and guarded actuation. The phase's real-LLM exit criterion must still be demonstrated with an actual pinned model. The AirSim path requires scene-specific live validation; SDK-interface tests are not flight evidence.

The deterministic team already works under nominal conditions. Phase 10's degraded/partition recovery weaknesses remain documented and are not fixed by inserting an LLM. This initial policy runner uses perfect delivery to isolate the effect of high-level agent reasoning.

## Requirement mapping

| Requirement | Implementation |
|---|---|
| 12.1 Persistent per-drone state | `PersistentAgent` creates separate local ledgers, memory deques, recent-message summaries, inboxes, task authorizations and per-agent JSONL histories. No other agent memory is included in a prompt. Persistence is across decisions within a run, not safe process restart/rejoin. |
| 12.2 Structured tools | Closed allowlist of 15 tools. No arbitrary Python, AirSim calls, numerical bid injection or unrestricted waypoint generation. |
| 12.3 Structured decisions | Strict fields for categorical assessment, selected tool, tool-specific parameters, optional constrained message intent and confidence. Extra fields, duplicate JSON keys, nonfinite values, wrong types and invalid recipients are rejected. |
| 12.4 Relevant context | Mission, constraints, own role/task/telemetry, local task beliefs, five recent message summaries, twelve memory entries, local communication estimates, latest skill/tool result and correction feedback. No complete raw flight log or other agents' histories. |
| 12.5 Deterministic calculations | `compute_task_cost` and bid/claim handlers compute distance, travel time, battery budget, local contact observations, cost, route feasibility and separation reasons. Actual motion is checked again by the guardian. |
| 12.6 Timeouts and fallback | One structured correction for correctable schema/tool/unsafe-action errors; otherwise deterministic bidding/guarded continuation or hold. Inference failures/timeouts use fallback directly. Responses arriving after timeout or from stale contexts cannot actuate. Ownership/version is revalidated when applying a response. |
| 12.7 Frozen primary model | Explicit non-`latest` tag plus full expected digest, verified before/after inference; temperature zero, fixed seed, token/context settings, model details and server version saved. Identity changes abort the formal run. Prompts, raw structured responses and decision histories are recorded per agent. |

## Decision and tool boundary

Example valid decision:

```json
{
  "situation_assessment": {
    "mission_progress": "partial",
    "communication_status": "nominal",
    "current_risk": "low"
  },
  "selected_tool": "send_bid",
  "parameters": {"task_id": "SEARCH_SECTOR_A", "task_version": 1},
  "outgoing_messages": [],
  "confidence": 0.9
}
```

The assessment is an untrusted model report, not authoritative telemetry. No private chain of thought is requested. Tools perform the actual calculations and checks; confidence does not authorize violating a constraint.

| Tool | Deterministic contract |
|---|---|
| `accept_task` | Confirm current valid local ownership and send protocol acceptance. |
| `decline_task` | Withdraw own bid or release own task; cannot revoke another agent's ownership. |
| `compute_task_cost` | Calculate full known route distance/travel time, entry distance, battery budget, Phase 8 bid components, local contact status and guardian feasibility. |
| `announce_task` | Announce known unassigned work only when no auction is already open. |
| `send_bid` | Require an open auction, idle eligible scout and current epoch; compute bid numerically. |
| `claim_task` | Require the closed auction, eligible own bid and deterministic winning score/ID. |
| `release_task` | Require valid ownership/version; confirm stopping old motion before releasing. |
| `change_role` | Apply battery/mission constraints and deterministic relay-candidate checks; release incompatible work and withdraw bids. |
| `request_help` | Send a bounded reason-code message to known recipients. |
| `report_target` | Use an existing trusted local sensor observation ID; cannot fabricate target coordinates. Sensor/perception integration is not provided by this phase. |
| `start_search` | Authorize deterministic execution of an owned, acknowledged, unexpired task route. |
| `go_to_waypoint` | Select only the next waypoint index of the owned route; cannot skip checkpoints or invent coordinates. |
| `act_as_relay` | Require relay role; send the configured relay-point action through the guardian. |
| `return_home` | Send a checked approach-point command; no implicit landing. |
| `hold` | Send a checked bounded hold command. |

The deterministic contract-net layer still opens auctions, resolves bids/claims, exchanges heartbeats and enforces leases. The LLM chooses bids, task execution, releases, roles and bounded skills; it does not replace the protocol with free-form negotiation. Outgoing `ROLE_CHANGE`/`HELP_REQUEST` intents must exactly match the selected tool, parameters and known recipients. Task bids/awards/completions are generated by deterministic handlers, not copied from model payloads. Models cannot declare a task complete: completion comes from observed ordered waypoint arrivals.

## Runtime assurance and execution

Every dispatched segment—including setup takeoff, model-selected skills, deterministic waypoint continuation, fallback and cleanup hold—passes through the Phase 11 `GuardedExecutor`. Ordered search routes are expanded into individual segments, each checked afresh. This does not imply that every policy message is a physical action: non-motion tools pass schema and protocol/ownership validation rather than being sent to the flight guardian.

The guardian additionally reserves active concurrent routes and applies geometry, speed, battery, freshness, deadline and separation checks. An in-progress takeoff is identified as `TAKEOFF` by the trusted runtime, permitting its approved ascent to continue through the lower flight boundary; ordinary airborne takeoff proposals remain invalid. Cancellation must be confirmed before releasing an active task, changing incompatible roles or replacing its motion. A failed/unknown cancellation is recorded and does not authorize another command.

The fallback policy keeps deterministic bidding alive and can continue a valid owned search authorization. All resulting segments are guarded. If no search is executable and no command is active, it requests a guarded hold. The guardian may choose another validated fallback or reject the hold if the state cannot establish safety. A hung server occupies at most one daemon worker per agent; the control loop abandons its decision after the wall-time budget and discards any late result. No unbounded replacement threads are launched.

## Run 1: offline plumbing validation

No AirSim, CARLA, GPU or model server is required:

```bash
python -u scripts/run_phase12_agents.py \
  --backend mock --provider replay \
  --output-dir results/phase12/replay_run1

python -m unittest discover -s tests -p 'test_phase12_agents.py' -v
```

The mock vehicles start airborne at height 3 m. The example uses four scouts and four separated two-waypoint routes; this is intentionally a new controlled policy-plumbing scenario, not a matched numerical comparison with the earlier eight-work-unit Phase 9 mission. The replay provider is deterministic hand-written decision selection, **not an LLM baseline result**.

## Run 2: real pinned Ollama policy with mock flight

Start one local Ollama server and install the desired explicit model tag. Structured JSON-schema output support is required. Inspect the installed full identifiers before choosing the expected digest:

```bash
python - <<'PY'
import json, urllib.request
with urllib.request.urlopen('http://localhost:11434/api/tags') as response:
    for model in json.load(response)['models']:
        print(model['name'], model['digest'])
PY
```
ollama cp llama3.1:latest phase12-agent:pinned

Record the inspected digest as part of your experiment configuration; do not automatically adopt a changed digest on every rerun. Replace the placeholder below with the recorded full 64-hex digest (an optional `sha256:` prefix is accepted):

```bash
python -u scripts/run_phase12_agents.py \
  --backend mock --provider ollama \
  --model phase12-agent:pinned \
  --model-digest YOUR_RECORDED_64_HEX_DIGEST \
  --seed 42 --ticks 1500 --dt 0.2 \
  --inference-timeout 15 --max-context-age 20 \
  --lease-seconds 45 --bid-window 2 \
  --output-dir results/phase12/ollama_mock_run1
```

Actual-model runs are paced in wall time, including mock flight, so timeout and inference latency measurements are meaningful. Four requests may queue on a single server. Calibrate inference budget, bid window and leases through pilot runs and freeze the chosen values for comparisons; server queueing can otherwise bias task allocation. Temperature zero plus a pinned digest does not guarantee bitwise-identical generated outputs across hardware/server scheduling, so preserve the recorded prompts and responses.

## Run 3: optional live CARLA–AirSim adapter

Configure four vehicles with calibrated shared NED coordinates and start the simulator. Copy `configs/phase12/carlaair.example.json` to your own local file and check every offset, altitude, route, home, relay point and boundary. The example assumes shared ground Z = 28 and Y offsets 0/5/10/15; it is not a map survey or collision-clearance guarantee. If AirSim reports already-shared positions, nonzero frame offsets would be wrong.

SimpleFlight commonly lacks battery telemetry. In that case the adapter refuses to proceed unless each vehicle has an explicit `assumed_battery_percent` test value; the example records 80. This is a documented assumption, not observed battery or proof of sufficient real energy. If a battery telemetry field is available it is interpreted as percent and must match that unit. The example's landing site is **not** marked surveyed clear.

```bash
python -u scripts/run_phase12_agents.py \
  --backend airsim --provider ollama \
  --mission-config configs/phase12/carlaair.local.json \
  --airsim-host 127.0.0.1 --carla-host localhost \
  --model llama3.1:8b \
  --model-digest YOUR_RECORDED_64_HEX_DIGEST \
  --flight-height 3 --setup-timeout 60 \
  --ticks 1500 --dt 0.2 --seed 42 \
  --output-dir results/phase12/ollama_airsim_run1
```

Start all four vehicles landed. Setup actions are guarded, and inference starts only after all four reach the desired airborne height. Takeoff uses AirSim's takeoff primitive followed by the approved vertical target; it requires at least 5 m configured overhead allowance because the primitive's intermediate response is not a certified trajectory. Peer state is exchanged through the message bus, rather than reading other agents' memories. Optional CARLA async settings are restored afterward.

Cleanup cancels active commands where confirmation is available and requests checked holds. It does **not** issue unchecked automatic landing/disarm commands. **Unlanded vehicles remain under API control and must be managed after the test.** Client RPC and watchdog timing are not onboard safety; perception, braking uncertainty, SDK/physics compatibility, landing performance and real battery models require separate validation. The live path has not been flown in this execution environment.

## Evidence files and interpretation

Use a new output directory for each run.

| File | Contents |
|---|---|
| `model_manifest.json` | Provider, requested model, verified digest, options, server version and model details; replay has no model identity. |
| `run_manifest.json` | Timing/lease settings, seed, Python version and source hashes. |
| `decision_schema.json`, `effective_mission.json` | Exact structured interface and mission/safety configuration. |
| `DroneN/prompts.jsonl` | Every submitted bounded prompt and correction attempt, with per-agent request ID. |
| `DroneN/responses.jsonl` | Raw returned content, latency/error and request ID. Returned shutdown results are discarded without actuation; still-outstanding requests are marked abandoned in history. |
| `DroneN/decision_history.jsonl`, `memory.json` | Applied decisions, failures, corrections, late responses, fallback events and bounded final memory. |
| `guardian_audit.json` | Separate safety decisions and executor acknowledgments; an approval is not completion evidence. |
| `flight_trace.json`, `executed_actions.json`, `waypoint_arrivals.json` | Own telemetry summaries, dispatched segments and measured arrivals. |
| `messages.json`, `protocol_events.json` | Message delivery and deterministic task-protocol evidence. |
| `summary.json` | Provider/backend, per-agent decisions/fallbacks, mission result, duplicate completions, dispatch coverage and exit-criterion observation flags. |

`llm_exit_criterion_observed` requires a genuine Ollama run, an applied airborne decision for every agent, guardian coverage of every dispatched action and no run error. `live_exit_criterion_observed` additionally requires the AirSim backend. These are observed software conditions, not a flight-safety certificate. Replay must keep both flags false even when it completes the mission.

Report task completion separately from LLM decision validity, repair/fallback frequency and guardian intervention. A completed mission with many deterministic corrections does not establish a reliable LLM. The separate logs make those distinctions measurable. Do not compare completion times directly across different task geometries, timing budgets or hardware.

## Initial validation status

The replay smoke run completes all four two-waypoint routes in 19.0 simulated seconds, without duplicate completions, with four independent contexts and guardian-covered dispatches. Twenty focused automated tests cover isolation, delivered-only beliefs, strict schema/message validation, deterministic calculation, ownership/epoch checks, correction limits, nonblocking timeout/late results, role constraints, unsafe motion rejection, all-agent mock execution, model pinning/mutation, guarded takeoff state and mocked AirSim frame conversion/cancellation.

The full repository regression suite passed **110 tests**, including these 20 focused policy tests.

This is implementation and plumbing evidence. No real Ollama inference or live flight result is claimed by the replay baseline. Run the pinned-model experiments and review their per-agent decision histories before marking Phase 12's real-LLM exit criterion complete.
