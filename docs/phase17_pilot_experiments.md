# Phase 17: pilot experiments and final-configuration selection

## Purpose and status

Pilots debug the methodology; they do not establish final architecture rankings or an LLM advantage. Phase 17 reuses the Phase 13 execution/guardian/network path, Phase 14 batch manifests and event logs, and Phase 15 registered metrics. It does not replace those components with a different experiment implementation.

Two-drone support is added to the comparison path only. The earlier Phase 12 and Phase 16 mission loaders still require four configured vehicles by default. Two- and four-drone pilots share the same four tasks and route geometry; the two-drone team has more work per survivor. Agents still use delivered inboxes and local state, and the stopped actor is not deleted from safety checks.

This implementation provides the pilot workflow. Completing Phase 17 additionally requires real pinned-model pilots, interpretable evidence, meaningful selected communication levels and an explicit final lock. A replay-only validation batch cannot satisfy that final-selection requirement.

## 17.1 Small matrix

[Default pilot configuration](../configs/phase17/pilot.example.json):

| Factor | Values |
|---|---|
| Architectures | C: deterministic decentralized; D: agentic decentralized |
| Team sizes | 2 and 4 |
| Network candidates | Nominal and severe |
| Fault type | Drone1 agent silence while the physical actor remains represented |
| Fault states | No-failure control, plus the one Drone1-loss condition |
| Pilot seeds | 41, 42, 43 |
| Reserved held-out seeds | 101–110 |
| Workload | The same four routes, four waypoints each |
| Default mission horizon | 600 seconds |
| Default injection | 73 seconds from mission start |

This is **48 cases**: 2 architectures × 2 team sizes × 2 networks × 2 fault states × 3 seeds. There is one fault type; no-failure controls provide matched references. Initial assignment mappings are generated for the actual team, while C/D continue to allocate through their decentralized protocol.

The generated routes are longer than the earlier 8 m line segments so the fixed fault can interrupt useful work. Fault timing is a candidate, not an assumption that it always interrupts motion: the analyzer requires a fault-onset owned task and an active movement skill. If a particular architecture has not started work, or already finished it, the run remains preserved and the timing must be recalibrated in a new pilot batch.

### Inspect the plan without execution

Run from the repository root:

```bash
python scripts/run_phase17_pilots.py prepare \
  --config configs/phase17/pilot.example.json \
  --profile pinned \
  --output-dir results/phase17/plan_preview1
```

Inspect `pilot_batch.json`, `pilot_config.json`, `pilot_plan.json`, and `fixtures/team_2.json` / `team_4.json`. Preparation does not contact Ollama or execute a mission. Use a different empty directory for execution; existing evidence is not overwritten.

### Fast software-validation pilots

```bash
python scripts/run_phase17_pilots.py run \
  --config configs/phase17/pilot.validation.json \
  --profile validation \
  --output-dir results/phase17/validation_run3
```

The validation configuration runs the same 48-case factor matrix with a **120-second simulated horizon**, 0.5-second ticks, a 0.5-second bidding window, a 20-second lease and a 4-second candidate fault. C uses deterministic rules; **D uses replay, not actual inference**. This faster protocol checks matrix generation, transport, logging, analysis and failure preservation. It is not pooled with the pinned profile or used to select final agentic settings.

### Actual pinned-model pilots

Start the configured Ollama server, then:

```bash
python scripts/run_phase17_pilots.py run \
  --config configs/phase17/pilot.example.json \
  --profile pinned \
  --output-dir results/phase17/pinned_run1
```

This uses the existing model `phase12-agent:pinned`, digest `46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e`, temperature zero and each run's seed. A server/model identity preflight occurs before any C/D mission. A failed preflight preserves a `pilot_error.json` rather than silently substituting replay.

Both C and D use wall-clock execution in this profile, the same 600-second budget, routes, bids/leases, network profiles, safety settings and fault schedule. Only D makes model calls. Runs execute serially against the shared model server. The 48 mission budgets total at most **8 hours**, plus warmup, setup, evaluation and plotting; successful early completion can shorten this. All flight execution remains kinematic mock flight, not CARLAAir.

## 17.2 Individual inspection

Every complete run gets a nine-panel PNG and an entry in `analysis/REPORT.md`:

1. Actual recorded drone trajectories.
2. Local execution selection and full owned-task set; assignment is not assumed to be authorized motion.
3. Role by drone, including an explicitly stopped actor's last recorded role.
4. Recipient delivery/drop/expiration/pending outcomes by packet creation time.
5. Observed peer heartbeat age, with actor-silence markers and configured partition shading only. A delayed heartbeat is not automatically a physical RF outage.
6. Local ownership acceptance and task reassignment events.
7. LLM call and policy-proposal timing, with tool names and distinct real/replay provenance.
8. Routine segment modifications, corrective modifications, rejections and fallbacks, separately labelled.
9. Unique waypoint work and unique task completion over time.

The comparison trace now records all locally owned tasks, execution-task identity and the active command kind alongside position, role and communication observations. This adds observations without changing the decision policy.

No-event panels say that nothing was recorded. Missing or inconsistent files are flagged rather than converted into zero events. Runtime errors and incomplete runs remain listed, with null successful completion times. An empty LLM panel in a replay validation run is correct.

To regenerate analysis after receiving an existing batch:

```bash
python scripts/run_phase17_pilots.py analyze \
  --pilot-dir results/phase17/pinned_run1
```

The analysis reads `runs/<experiment_id>/events.jsonl`, raw traces, manifests and Phase 15 metrics. It checks event counts, required artifacts, task/role/communication trace fields, model identity, productive model use and whether the fixed fault actually interrupted owned moving work. Aggregate tables accompany the individual plots; they never replace inspection of the timelines.

## 17.3 Calibrate candidate network levels

The initial candidates preserve the existing network presets explicitly:

| Level | Latency mean ± uniform half-width | Independent loss | Sender recipient-packet limit | Sender egress limit |
|---|---|---:|---:|---:|
| Nominal | 10 ± 2 ms | 0% | Unlimited | Unlimited |
| Severe | 400 ± 200 ms | 30% | 60 packets/s | 50,000 bytes/s |

These are application-network experiment settings, not radio specifications. Queueing and receiver polling add delay. A seed repeats keyed network draws for the same sender/sequence/recipient traffic; architectures can offer different traffic, so matching seeds does not imply identical traffic histories.

`analysis/calibration_report.json` and `analysis/REPORT.md` retain the configured values, observed resolved-delivery fractions, successful-only completion times, success counts by cell, and explicit freeze blockers. Pending messages remain censored. Observed delivered-packet delays exclude undelivered packets and must not be treated as a full latency distribution.

Final selection is blocked when:

- The evidence is replay-only, insufficiently repeated, incomplete, inconsistent or missing registered metric evaluation.
- Actual D calls or productive nominal D execution are absent, or model identity/options change unexpectedly. Per-run model seeds are expected to differ and are checked against the planned seed.
- The fault never happens or does not interrupt owned movement.
- Nominal controls succeed less than half the time.
- Every severe no-failure control succeeds, or every such control fails.
- Severe resolved delivery is below the declared 10% usability floor, or its mean delivery fraction is not at least 5% lower than nominal.

These are conservative **pilot selection rules**, specified before these pilots, not statistical significance tests or proof that any selected setting models a particular radio. Passing them is necessary but not sufficient: the written selection rationale must explain the timelines and operational meaning of each final level. Inspect failure-state results separately from network-only controls.

If outcomes are trivial, adjust candidate network values and/or the scenario timing in the input configuration, then run a **new** pilot directory with the common pilot seeds. If nominal execution is broken, debug that before making communications harsher. Do not change registered metric definitions, delete failed attempts, remove uncertain drones from guardian checks, or relabel replay as actual reasoning to improve the table.

## 17.4 Freeze only after calibration

A final lock is never created automatically from a completed batch. After actual pinned pilots satisfy the gates, write a JSON rationale with four substantive string fields:

```json
{
  "nominal": "Explain the observed reference behaviour and why this is a useful nominal level.",
  "severe": "Explain the observed delay, useful delivery and mixed outcomes at this severe level.",
  "scenario_families": "Explain the fixed four-route workload, two team sizes and effective fault timing.",
  "selection_reason": "Explain why this pilot evidence supports these choices without making final claims."
}
```

Then:

```bash
python scripts/run_phase17_pilots.py freeze \
  --pilot-dir results/phase17/pinned_run1 \
  --rationale configs/phase17/selection_rationale.local.json \
  --output-dir results/phase17/final_definition1

python scripts/run_phase17_pilots.py verify-frozen \
  --frozen-dir results/phase17/final_definition1
```

The lock captures the selected network/scenario configurations, mission fixtures, model identity and settings, prompts/tools/task rules through implementation hashes, metric definition/contract, and the pilot evidence used for selection. Its held-out batch uses only seeds 101–110, never the pilot seeds. Changes to locked source, configuration, definitions or retained pilot evidence cause verification to fail. This detects accidental drift; it is not a security sandbox or a substitute for version control and experimental discipline.

When the later main-experiment phase is authorized, its prepared batch can be executed with:

```bash
python scripts/run_phase17_pilots.py run-frozen \
  --frozen-dir results/phase17/final_definition1 \
  --output-dir results/phase17/held_out_run1
```

This does not run during pilot preparation or freezing. With ten held-out seeds it contains 160 cases; keep it separate from pilot analysis and do not tune the implementation after viewing those outcomes.

## Verification and exit criterion

```bash
python -m unittest discover -s tests -p 'test_phase17_pilots.py' -v
python scripts/run_phase16_verification.py \
  --output-dir results/phase17/software_verification_run2
```

Focused tests cover matrix completeness, equal work across team sizes, disjoint seeds, two-drone guarded execution, nine-panel rendering, retained preflight errors, immutable plans, ineffective fault detection, degenerate-condition rejection, multi-seed model identity checks and held-out configuration locking. Synthetic calibration fixtures are used only inside temporary unit tests and are not recorded as real pilot inference.

The Phase 17 exit criterion is met only after the team can explain meaningful final communication levels using actual pilot evidence and complete individual logs, then produce a verified final lock. Successful software tests or completion of a replay batch alone do not establish that milestone.

## Local development validation

The final software suite passed **246 tests**, including ten focused Phase 17 tests, with no source changes during the verification run. Two actual replay-validation matrices were retained:

| Batch | Finding |
|---|---|
| `validation_run1` | All 48 missions incomplete: the initial generated route exceeded the existing whole-route execution deadline, so agents never bid. This exposed a methodology defect. |
| `validation_run2` | Corrected routes fit the unchanged guardian contract. All 48 cases have consistent evaluated evidence and a nine-panel timeline. Nominal controls: 12/12 completed; severe controls: 3/12; injected-loss cases: 0/24. |

The corrected batch uses the faster validation protocol, not the 600-second pinned-model protocol. Its approximate mean resolved-delivery fractions are 1.00 nominal and 0.70 severe. These are application-transport observations, not radio calibration or final performance estimates. Only 2/24 injected faults interrupted owned movement in this fast profile, so its fault timing still requires calibration. The longer pinned profile uses its separately documented 73-second candidate timing, which must also be checked rather than assumed effective. Actual pinned-model evidence is absent by design, and no final configuration lock was created.

The original unsuccessful matrix remains available rather than being rewritten as the corrected one. Local artifacts are under `results/phase17/validation_run1`, `validation_run2`, and `software_verification_run1`. These development runs used the working tree and record its source hashes; they must not be described as clean-checkout results from the older base Git revision.

## Published development evidence

The development batch reports and timelines are browsable in [Phase 17 results](../results/phase17/EVIDENCE.md). Full raw evidence for both batches is preserved in checksum-verified, lossless archive parts. Restore a complete batch to a fresh directory before regenerating analysis; the repository's browsable subset alone intentionally omits the largest raw logs. See the evidence guide for verification and restore commands.
