# Phase 12 easy_run1: zero applied LLM decisions

## Evidence and confirmed finding

Reviewed the uploaded `results/phase12/easy_run1` files from repository commit `2f35ff048f1430212688f391a73de31231343598`: all four decision histories, responses, model/run manifests, the saved decision schema, effective mission and initial/correction prompts.

**All 28 returned model responses were valid JSON but failed the required top-level decision structure.** Every response contained only `selected_tool` and `parameters`. The validator requires five fields:

```text
situation_assessment
selected_tool
parameters
outgoing_messages
confidence
```

The missing fields were always `situation_assessment`, `outgoing_messages`, and `confidence`. The recorded error was `decision_fields` for every returned response. Validation stopped before any tool could be applied; this explains the zero applied decisions for all four agents.

| Agent | Returned responses / schema failures | Correction requests | Deterministic fallbacks | Applied decisions |
|---|---:|---:|---:|---:|
| Drone1 | 6 | 3 | 3 | 0 |
| Drone2 | 7 | 4 | 3 | 0 |
| Drone3 | 7 | 4 | 3 | 0 |
| Drone4 | 8 | 4 | 4 | 0 |
| Total | 28 | 15 | 13 | 0 |

Four further requests were marked abandoned at experiment shutdown; they are not counted as returned responses or additional schema failures.

## What did not cause these rejections

The model was reachable and returned content. Its recorded identity was `phase12-agent:pinned`, full digest `46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e`, Llama 8.0B Q4_K_M, served by Ollama 0.32.1 at temperature zero.

The inference budget was 30 s. Returned-response latencies ranged from **6.301 to 28.864 s**, averaging **12.296 s**. No inference-timeout or provider-error event was recorded in these histories. Increasing the timeout would therefore not repair the observed structural failures. This does not establish that server queueing has no performance effect; it establishes that these 28 rejections were schema failures.

One separate `drone_separation` guardian intervention was recorded for Drone1 at approximately 60.005 s during deterministic execution. It does not explain the schema rejection of every LLM response.

## Integration defect and likely mechanism

The old schema declared the five common fields at the root, but each `oneOf` branch described only `selected_tool` and `parameters`. The saved prompts listed tool parameter signatures without an explicit full decision example. After rejection, the correction prompt said only to return a schema-valid decision; it did not identify the missing fields.

A standards-compliant JSON Schema validator should apply the root and branch constraints together. Schema-to-grammar engines can instead select an alternative without merging its sibling constraints. The exact two-field pattern in every returned response matches the incomplete alternatives. This is an integration defect in how the schema/prompt were supplied, not evidence that the model could not propose any tool. An internal Ollama grammar-compilation trace was not captured, so converter behavior is a supported mechanism rather than independently traced server internals.

## Correction implemented

1. Every tool alternative now contains a complete standalone object schema, including all five required fields, assessment enums, confidence and outgoing-message structure, plus the exact tool-specific parameters.
2. The textual system prompt and each bounded agent context explicitly name all five fields and provide a complete shape example.
3. Validation errors include exact missing/unexpected fields. One structured correction receives these details and the full required shape.
4. Strict validation remains in place: missing assessments/confidence are not fabricated or silently filled in; arbitrary extra fields, invented tools and invalid recipients remain rejected.
5. Ownership, task-version, guardian and fallback checks are unchanged. The run manifest now also records `max_context_age` for timing reproducibility.

Regression tests reproduce the observed two-field reply, verify standalone alternatives even without parent merging, check independent branch structures and prove that an actual corrected response is required before a decision can be applied. The full regression suite passed **113 tests**, including **23 Phase 12 tests**. This is offline implementation evidence, not a claim that a new real-model run has succeeded.

## Further findings and rerun interpretation

The responses included 21 `send_bid` proposals and 7 `hold` proposals. One response referred to `SEARCH_SECTOR_E`, which does not exist in the four-task mission. After the format correction, the existing unknown-task check must still reject that proposal. Other tool/ownership errors may also become visible once structural validation succeeds.

The old run completed all four tasks in 104.005 s without duplicate completions through deterministic recovery. It remains fallback-continuity evidence, not successful LLM cooperation. Preserve it unchanged and use a new output directory for the repaired run.

```bash
python -u scripts/run_phase12_agents.py \
  --backend mock --provider ollama \
  --model phase12-agent:pinned \
  --model-digest "46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e" \
  --seed 42 --ticks 1500 --dt 0.2 \
  --inference-timeout 30 --max-context-age 35 \
  --lease-seconds 90 --bid-window 5 \
  --output-dir results/phase12/easy_run2
```

Keep the same model, timing, mission and seed initially to isolate the schema/prompt change. Check that all four `decisions_by_agent` become positive, that accepted responses contain all five fields, and that `llm_exit_criterion_observed` is true. Separately report task completion, fallback frequency, rejected tools and guardian interventions; none should be inferred from a completion flag alone. The repair still requires a real Ollama rerun on the user's server, and no new live-flight result is claimed.
