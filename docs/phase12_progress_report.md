# Phase 12: productive persistent-policy validation

## Why the second Ollama run was insufficient

The uploaded `results/phase12/easy_run2` fixed the earlier schema failure: 40 decisions were applied across four contexts. However, 37 selected HOLD and three selected bidding; no waypoint arrivals or completed tasks were recorded. Four inference timeouts triggered four deterministic fallbacks. Accepted JSON demonstrated integration, not useful mission cooperation. The historical `llm_exit_criterion_observed: true` used an insufficient test (any applied airborne decision per drone); do not interpret that old flag as demonstrated mission-level control.

## Essential changes

* Offer the 15-tool catalog through a context-specific subset with locally valid task IDs, versions and waypoint indices. Show an owned, executable search task as the decision example instead of always showing HOLD. Tool handlers still independently validate ownership, epoch, role and safety when responses arrive.
* Keep separate identities, delivered-message beliefs, task ledgers, memory, inboxes and histories. Summarize important messages without letting routine heartbeats displace task events. Include recent deterministic calculation results and outstanding work in each prompt.
* Warm and verify the pinned model before vehicle setup. Admit requests fairly with one outstanding server request by default; admission scheduling controls shared compute capacity, not task assignment. Waiting for admission is logged separately from inference latency. Request decisions when there is an actionable local opportunity, correction or relevant condition change.
* Limit individual HOLD requests to two seconds by default. When a safe, executable opportunity has been repeatedly deferred (at least two accepted deferrals and the configured progress timeout), request one structured correction; continued failure invokes the existing deterministic fallback. Unknown/stale peer state, hazards and communication uncertainty do not force motion. Fallback motion still passes the guardian and receives no LLM credit.
* Attribute observed waypoint arrivals and completed motion to their authorizing policy request and source. Archive the exact Ollama request payload, including system prompt, context-specific schema and model options, separately from raw responses and guardian logs.

## Requirements and evidence boundary

| Requirement | Implementation and remaining validation |
|---|---|
| 12.1 Persistent per-drone agent | Four isolated in-run contexts; one shared model service. Not process-restart persistence. |
| 12.2 Restricted structured tools | Closed catalog and context-specific choices; no arbitrary code or raw SDK action channel. |
| 12.3 Decision schema | All five root fields required; strict tool parameters and controlled message intents. |
| 12.4 Relevant context | Bounded local beliefs, important messages, task/role, constraints, skill result, calculations and unresolved opportunities. |
| 12.5 Deterministic calculations | Existing tool handlers compute costs, distance/time, battery budget, local communication observations and route/separation checks; guardian checks actual dispatch. These are configured models, not physical battery/RF guarantees. |
| 12.6 Correction and fallback | One correction where appropriate, timeout/staleness protection, bounded deferral handling, source-labelled fallback and separate safety audit. |
| 12.7 Frozen model | Explicit tag and full digest verified around inference; fixed configuration and exact request/response archives. A fresh real-model run remains necessary. |

`llm_integration_observed` records applied airborne LLM decisions for every agent, guarded dispatch and no run error. `llm_exit_criterion_observed` additionally requires an accepted mission-motion decision with an observed effect for **every** drone. HOLD, a schema-valid bid, fallback motion and arrival at a point already occupied do not count as productive LLM motion. `live_exit_criterion_observed` additionally requires AirSim. `cooperative_mission_success` additionally requires mission completion with no duplicate task completions. These conservative software checks support log review; none certifies flight safety.

For a successful Phase 12 demonstration, inspect all these conditions alongside per-agent histories, fallback frequency and guardian intervention. A mixed policy/fallback mission can complete without establishing reliable LLM cooperation. Mock flight is useful development evidence; the literal during-flight exit criterion needs the separately validated live backend.

## Regression experiments

The full suite passes 126 tests, including 36 Phase 12 tests. Added cases check actionable tool schemas, safe correction handling, bounded HOLD, authorization provenance, fair admission, model warmup, preflight abort and evidence attribution.

Compact summaries in `results/phase12/progress_validation` are **replay fixtures, not new Ollama experiments**:

| Fixture | Mission complete | Simulated time | Productive fixture decisions per drone | Fallbacks per drone | LLM exit flag |
|---|---|---:|---|---|---|
| Progressing replay | yes | 18.8 s | 1, 1, 1, 1 | 0, 0, 0, 0 | false |
| HOLD-only replay, progress timeout 2 s | yes | 29.8 s | 0, 0, 0, 0 | 2, 3, 4, 5 | false |

The negative control proves that deterministic recovery cannot inflate the LLM success metric. Reproduce these behaviors with `python -m unittest discover -s tests -p 'test_phase12_progress.py' -v`. Full traces are generated into temporary directories by tests; the committed compact summaries are not substitutes for formal raw experiment logs.

## Next real-model pilot

Ensure the explicit tag exists and its installed digest matches the one below. Use a new output directory:

```bash
python -u scripts/run_phase12_agents.py \
  --backend mock --provider ollama \
  --model phase12-agent:pinned \
  --model-digest 46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e \
  --seed 42 --ticks 1500 --dt 0.2 \
  --inference-timeout 30 --max-context-age 35 \
  --inference-parallelism 1 --progress-timeout 60 \
  --lease-seconds 180 --bid-window 30 \
  --output-dir results/phase12/easy_run3
```

This pilot gives the shared server a longer bid window and lease than `easy_run2`; it changes both policy behavior and protocol timing. It is not a controlled attribution of improvement to one change. Calibrate on the actual hardware, then freeze timings for formal comparisons. The deadline is approximately 300 seconds of mission wall time, excluding preflight warmup. Do not replace the expected digest automatically if verification fails.

First inspect `mission_complete`, `error`, `llm_productive_decisions_by_agent`, `fallbacks_by_agent`, `policy_errors_by_agent` and the three criterion/success flags. Every drone needs genuine productive LLM evidence, not only a positive aggregate decision count. Preserve `request_specs.jsonl`, prompts, responses, histories, telemetry and guardian audits. Repeat with fixed settings and multiple seeds before paper claims. No new real-model or live-flight success is claimed by this implementation report.
