# Phase 14: experiment runner and logging audit

Status: implementation validated offline; real pinned-model logging still requires a server run. The Phase 13 comparison runner, allocation implementation and suite scripts are unchanged by this work. Do not update a running Phase 13 batch's source or compete for its Ollama server.

## Requirement review

| Requirement | Existing Phase 13 coverage | Phase 14 local addition |
|---|---|---|
| 14.1 One configuration | Resolved comparison settings and a generated fixed test matrix | An explicit list of experiments with experiment ID, architecture, scenario ID, team size, network/failure profile, seed and planner |
| Git revision | Source-file hashes, but no explicit run Git SHA | Git commit SHA, tracked-dirty flag and actual source hashes, including untracked Python source |
| Configuration files | Resolved settings and embedded mission data | Byte-preserving copies of the batch, referenced comparison config and mission, with SHA-256 hashes |
| Model and parameters | Verified provider identity, pinned digest and options in successful initialized runs | Requested policy saved before verification; actual verified identity and server details linked into the final manifest |
| Start/finish and software versions | Simulated/elapsed time; incomplete environment metadata | UTC start/finish timestamps, Python/platform and installed-package versions |
| Run completion and errors | Per-case status and summary, some early errors separate | Manifest exists before setup; test completion and mission success remain distinct, including preflight failures |
| 14.3 Structured events | Distributed JSON arrays and per-agent JSONL | Unified streaming `events.jsonl` with a common envelope and normalized event names |
| 14.4 Failed runs | Existing archives and retained retry attempts | Configuration failures, model failures, runtime failures and graceful interruptions retain manifests and partial event logs; ordinary errors do not prevent subsequent cases |
| Batch exit criterion | Automatic fixed scenario matrix | Serial execution of an arbitrary explicit configuration list, with one result folder per experiment and no prompts |

The prior implementation substantially covered the exit criterion but not all manifest/event details. Phase 14 is not evidence that every mission succeeds or that actual aircraft are safe.

## Configuration

`configs/phase14/batch.example.json` is a small **offline** batch: deterministic nominal coordination, deterministic moderate communication, and a replay-policy failure case. It does not invoke Ollama. Each entry has the required research metadata and a `settings` object for the existing comparison runner.

Supported architecture names are `centralized_fleet_controller`, `independent_persistent_agents`, `deterministic_decentralized`, `agentic_decentralized`, or A/B/C/D. The declared planner must match actual execution: `deterministic` for rules, `replay` for fixtures, or the exact pinned model identifier for Ollama. A model name is never accepted as evidence that inference actually occurred.

Paths in configuration entries are relative to the repository root unless absolute. `scenario` is a descriptive ID attached to the snapshotted mission configuration, not a separate scenario generator. `team_size` must match that mission. Named failure profiles must agree with the configured actor and timing. A requested failure can still remain unobserved if a mission ends first; the manifest records this distinction.

A pinned-model entry can reference the current v2 comparison config:

```json
{
  "experiment_id": "severe_agentic_seed42",
  "architecture": "agentic_decentralized",
  "scenario": "four_sector_search",
  "team_size": 4,
  "network_profile": "severe",
  "failure_profile": "none",
  "random_seed": 42,
  "planner": "phase12-agent:pinned",
  "comparison_config": "configs/phase13/comparison.resilient.pinned.json"
}
```

The full JSON file has `"schema_version": 1` and an `"experiments"` array. The referenced v2 file retains its 600-second budget and digest; other settings can be overridden explicitly. Configuration snapshots capture both the original files and resolved values.

## Test commands

```bash
cd /opt/carla_demo
python -u scripts/run_phase14_experiments.py \
  --batch configs/phase14/batch.example.json \
  --output-dir results/phase14/local_batch_run1
```

The smoke batch can run without CARLA, AirSim or Ollama. It uses a maximum of 30 simulated seconds per experiment (`300 * 0.1`), and normally finishes much faster in wall time. Expected output is three finished experiments, two successful missions and one preserved incomplete failure scenario.

Update the checkout only after an ongoing Phase 13 batch finishes, or use a separate checkout. New source files change provenance hashes used for safe resume. Run real-model tests after the ongoing batch finishes to avoid Ollama contention.

For one real-model logging test:

```bash
python -u scripts/run_phase14_experiments.py \
  --batch configs/phase14/batch.pinned.example.json \
  --output-dir results/phase14/pinned_logging_run1
```

This is one nominal D experiment using the existing v2 pinned model and a maximum of 600 wall-clock seconds. It ends earlier if the mission completes. It tests the logging pipeline with actual inference; it is not the full Phase 13 benchmark. Check nonzero `LLM_CALLED` coverage, `effective_provider`, and the per-agent prompt/response files. No real-model result is claimed by the offline verification below.

For focused regression tests:

```bash
python -m unittest discover -s tests -p 'test_phase14_runner.py' -v
```

## Output and manifests

```text
output/
  batch_configuration.json
  batch_manifest.json
  experiment_id/
    manifest.json
    events.jsonl
    configuration_files/
    error.json                 # present on caught errors
    run/                       # original comparison outputs
      manifest.json
      summary.json
      messages.json
      guardian_audit.json
      waypoint_arrivals.json
      ...
      Drone1/prompts.jsonl
      Drone1/responses.jsonl
      ...
```

Each attempt has a unique run ID. An existing nonempty output folder is rejected rather than overwritten; retry with a new folder. A normal but incomplete mission has `run_completed: true`, `mission_complete: false`, and status `incomplete`. A preflight/configuration/runtime error has status `error` and retains its evidence. Configuration/model errors do not manufacture a flight-start or mission-completion event.

The Git SHA identifies the checkout; a dirty checkout is explicitly marked, and hashes identify the actual Python sources used. Source changes during a run are flagged. For formal experiments, freeze/review the implementation before collecting a new batch. A hash cannot turn uncommitted code into a reproducible released revision.

## Event semantics

Events contain `event_id`, `experiment_id`, `attempt_id`, `wall_time_utc`, `simulation_time_s`, `agent_id`, and a structured `data` object. They are written and closed per record; a later crash does not discard the complete earlier records. The original Phase 14 observer is recorded as `phase14_scoped_observers_v1`. The Phase 15 extension records `phase14_phase15_observers_v2` and adds own-telemetry series, final/fault task snapshots and provider-reported usage. Both add logging overhead.

All requested names are supported:

`MISSION_STARTED`, `OBSERVATION_RECEIVED`, `BELIEF_UPDATED`, `MESSAGE_SENT`, `MESSAGE_DROPPED`, `MESSAGE_RECEIVED`, `TASK_ANNOUNCED`, `TASK_BID`, `TASK_ASSIGNED`, `TASK_RELEASED`, `ROLE_CHANGED`, `LLM_CALLED`, `DECISION_PROPOSED`, `GUARDIAN_INTERVENED`, `SKILL_STARTED`, `SKILL_COMPLETED`, `TARGET_FOUND`, `FAULT_INJECTED`, `MISSION_COMPLETED`.

They are emitted only when the corresponding path occurs. A replay/rule run records `POLICY_CALLED`, not `LLM_CALLED`. Target reports are labeled as delivered reports, not ground-truth detections; this route benchmark does not acquire a perception system through logging. Role, target and LLM coverage may legitimately be zero. `event_coverage` records zeros explicitly instead of fabricating events.

Receipt and belief update are separate events: receipt is logged by infrastructure, while belief updates are recorded after the agent/controller processes delivered data. Sent/received records preserve envelopes. Drops identify the recipient and reason; one broadcast can yield several recipient outcomes. Guardian intervention includes modification/rejection/fallback audit data; an approved skill starting is distinct from observed completion or cancellation. `MISSION_COMPLETED` is not emitted merely because the time limit expired. Pending packets remain pending in the original message log and are not relabeled as dropped.

## Preservation and limitations

The wrapper writes its manifest before loading/validating referenced settings or contacting the model. It retains the original Phase 13 outputs, raw per-agent prompt/response files and partial structured logs. Caught failures receive error information; graceful keyboard interruption finalizes the attempt and stops the batch. Invalid duplicate/path-traversal experiment IDs are rejected before execution.

An uncatchable kill, host loss or filesystem failure can leave the initial manifest marked `running` with only partial logs. Such a record is an unfinished attempt, not a successful experiment. This implementation does not infer an exact finish time for a dead process. No automatic resume, multi-process logging, Parquet backend or live-AirSim integration is claimed.

Instrumentation is scoped to the new serial runner process and restored afterward; it is not installed by the existing Phase 13 commands. Tests compare deterministic outcomes with and without observers and exercise model/configuration/runtime failures, dropped packets, delivered target reports, graceful interruption and retention of incomplete missions. Real-model event paths require a subsequent pinned-server run; offline validation does not establish real LLM inference.

## Local verification results

- Full repository suite: **205 tests passed**.
- New Phase 14 focused tests: **12 passed**.
- Example batch: **3 finished experiments**, **2 successful missions**, **1 intentionally incomplete failure mission**, **0 runtime errors**. These are offline mock/replay checks, not real-model evidence.
- Independent event audit: received/dropped recipient counts matched the original message logs; skill-start counts matched actual effects; guardian-intervention counts matched the audit; mission-completion events matched the summaries. No replay/rule run was labeled as an LLM call.
- Byte-hash checks confirm that the pre-existing Phase 13 comparison, architecture, suite and CLI files were not modified by this Phase 14 task.

The exit criterion is locally demonstrated for the current mock comparison backend: a single command executes an explicit scenario list without prompts and retains a complete result folder per finished attempt, including unsuccessful missions. Real-model, live-flight and uncatchable-host-failure behavior should not be inferred from these offline checks. The existing Phase 13 commands do not gain the new normalized logs automatically; use the new Phase 14 wrapper for future batches after review.
