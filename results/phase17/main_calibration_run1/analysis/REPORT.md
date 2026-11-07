# Phase 17 pilot calibration
Profile: pinned. 48 planned cases; 5 missions completed.

These are methodology pilots, not final comparisons. Every successful time excludes censored runs.

| Architecture | Team | Network | Fault | Successes / runs | Median successful time (s) |
|---|---:|---|---|---:|---:|
| C | 2 | nominal | none | 2/3 | 213.80008292949788 |
| C | 2 | nominal | drone_failure_midmission | 0/3 | None |
| C | 2 | severe | none | 0/3 | None |
| C | 2 | severe | drone_failure_midmission | 0/3 | None |
| C | 4 | nominal | none | 1/3 | 174.20009295599448 |
| C | 4 | nominal | drone_failure_midmission | 0/3 | None |
| C | 4 | severe | none | 0/3 | None |
| C | 4 | severe | drone_failure_midmission | 0/3 | None |
| D | 2 | nominal | none | 1/3 | 241.00009032800153 |
| D | 2 | nominal | drone_failure_midmission | 0/3 | None |
| D | 2 | severe | none | 0/3 | None |
| D | 2 | severe | drone_failure_midmission | 0/3 | None |
| D | 4 | nominal | none | 1/3 | 185.60009877900302 |
| D | 4 | nominal | drone_failure_midmission | 0/3 | None |
| D | 4 | severe | none | 0/3 | None |
| D | 4 | severe | drone_failure_midmission | 0/3 | None |

## Communication-level calibration
These are candidate application-network settings, not calibrated radio claims. Latency jitter is a uniform half-width; delivery delays also include queueing and polling. Pending packets are excluded from resolved delivery ratios.

| Level | Independent loss | Latency mean +/- half-width (ms) | Recipient packets/s | Egress bytes/s | Control mission success | Mean resolved delivery fraction |
|---|---:|---:|---:|---:|---:|---:|
| nominal | 0 | 10 +/- 2 | None | None | 0.4166666666666667 | 1.0 |
| severe | 0.3 | 400 +/- 200 | 60 | 50000 | 0.0 | 0.6988765700447689 |

All-success or all-failure severe controls, mostly unusable delivery, inadequate nominal references, missing model evidence, or ineffective fault timing require more calibration. Do not remove those runs or relax the guardian to manufacture recovery.

## Final selection status
Eligible for freeze: False.

- incomplete_or_inconsistent_run_evidence
- implementation_changed_across_pilots
- fault_did_not_interrupt_owned_moving_work
- actual_llm_calls_missing
- nominal_agentic_execution_not_demonstrated
- model_identity_not_consistent
- severe_control_outcomes_degenerate_all_fail_or_all_succeed
- nominal_control_not_a_usable_reference

## Individual timelines
Each plot contains trajectories, local ownership, roles, traffic, heartbeat age, task claims, policy proposals, guardian outcomes and mission progress. Missing evidence is flagged; no-event paths remain explicitly empty.
