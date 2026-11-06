# Phase 17 pilot calibration
Profile: validation. 48 planned cases; 15 missions completed.

These are methodology pilots, not final comparisons. Every successful time excludes censored runs.

| Architecture | Team | Network | Fault | Successes / runs | Median successful time (s) |
|---|---:|---|---|---:|---:|
| C | 2 | nominal | none | 3/3 | 70.5 |
| C | 2 | nominal | drone_failure_midmission | 0/3 | None |
| C | 2 | severe | none | 1/3 | 73.5 |
| C | 2 | severe | drone_failure_midmission | 0/3 | None |
| C | 4 | nominal | none | 3/3 | 28.5 |
| C | 4 | nominal | drone_failure_midmission | 0/3 | None |
| C | 4 | severe | none | 0/3 | None |
| C | 4 | severe | drone_failure_midmission | 0/3 | None |
| D | 2 | nominal | none | 3/3 | 70.5 |
| D | 2 | nominal | drone_failure_midmission | 0/3 | None |
| D | 2 | severe | none | 2/3 | 92.25 |
| D | 2 | severe | drone_failure_midmission | 0/3 | None |
| D | 4 | nominal | none | 3/3 | 28.5 |
| D | 4 | nominal | drone_failure_midmission | 0/3 | None |
| D | 4 | severe | none | 0/3 | None |
| D | 4 | severe | drone_failure_midmission | 0/3 | None |

## Communication-level calibration
These are candidate application-network settings, not calibrated radio claims. Latency jitter is a uniform half-width; delivery delays also include queueing and polling. Pending packets are excluded from resolved delivery ratios.

| Level | Independent loss | Latency mean +/- half-width (ms) | Recipient packets/s | Egress bytes/s | Control mission success | Mean resolved delivery fraction |
|---|---:|---:|---:|---:|---:|---:|
| nominal | 0 | 10 +/- 2 | None | None | 1.0 | 1.0 |
| severe | 0.3 | 400 +/- 200 | 60 | 50000 | 0.25 | 0.7000111261778804 |

All-success or all-failure severe controls, mostly unusable delivery, inadequate nominal references, missing model evidence, or ineffective fault timing require more calibration. Do not remove those runs or relax the guardian to manufacture recovery.

## Final selection status
Eligible for freeze: False.

- validation_replay_cannot_select_final_agentic_configuration
- fault_did_not_interrupt_owned_moving_work
- actual_llm_calls_missing
- nominal_agentic_execution_not_demonstrated
- model_identity_not_consistent

## Individual timelines
Each plot contains trajectories, local ownership, roles, traffic, heartbeat age, task claims, policy proposals, guardian outcomes and mission progress. Missing evidence is flagged; no-event paths remain explicitly empty.

- [C_n2_nominal_control_s41](C_n2_nominal_control_s41.png)
- [C_n2_nominal_loss_s41](C_n2_nominal_loss_s41.png)
- [C_n2_severe_control_s41](C_n2_severe_control_s41.png)
- [C_n2_severe_loss_s41](C_n2_severe_loss_s41.png)
- [C_n4_nominal_control_s41](C_n4_nominal_control_s41.png)
- [C_n4_nominal_loss_s41](C_n4_nominal_loss_s41.png)
- [C_n4_severe_control_s41](C_n4_severe_control_s41.png)
- [C_n4_severe_loss_s41](C_n4_severe_loss_s41.png)
- [D_n2_nominal_control_s41](D_n2_nominal_control_s41.png)
- [D_n2_nominal_loss_s41](D_n2_nominal_loss_s41.png)
- [D_n2_severe_control_s41](D_n2_severe_control_s41.png)
- [D_n2_severe_loss_s41](D_n2_severe_loss_s41.png)
- [D_n4_nominal_control_s41](D_n4_nominal_control_s41.png)
- [D_n4_nominal_loss_s41](D_n4_nominal_loss_s41.png)
- [D_n4_severe_control_s41](D_n4_severe_control_s41.png)
- [D_n4_severe_loss_s41](D_n4_severe_loss_s41.png)
- [C_n2_nominal_control_s42](C_n2_nominal_control_s42.png)
- [C_n2_nominal_loss_s42](C_n2_nominal_loss_s42.png)
- [C_n2_severe_control_s42](C_n2_severe_control_s42.png)
- [C_n2_severe_loss_s42](C_n2_severe_loss_s42.png)
- [C_n4_nominal_control_s42](C_n4_nominal_control_s42.png)
- [C_n4_nominal_loss_s42](C_n4_nominal_loss_s42.png)
- [C_n4_severe_control_s42](C_n4_severe_control_s42.png)
- [C_n4_severe_loss_s42](C_n4_severe_loss_s42.png)
- [D_n2_nominal_control_s42](D_n2_nominal_control_s42.png)
- [D_n2_nominal_loss_s42](D_n2_nominal_loss_s42.png)
- [D_n2_severe_control_s42](D_n2_severe_control_s42.png)
- [D_n2_severe_loss_s42](D_n2_severe_loss_s42.png)
- [D_n4_nominal_control_s42](D_n4_nominal_control_s42.png)
- [D_n4_nominal_loss_s42](D_n4_nominal_loss_s42.png)
- [D_n4_severe_control_s42](D_n4_severe_control_s42.png)
- [D_n4_severe_loss_s42](D_n4_severe_loss_s42.png)
- [C_n2_nominal_control_s43](C_n2_nominal_control_s43.png)
- [C_n2_nominal_loss_s43](C_n2_nominal_loss_s43.png)
- [C_n2_severe_control_s43](C_n2_severe_control_s43.png)
- [C_n2_severe_loss_s43](C_n2_severe_loss_s43.png)
- [C_n4_nominal_control_s43](C_n4_nominal_control_s43.png)
- [C_n4_nominal_loss_s43](C_n4_nominal_loss_s43.png)
- [C_n4_severe_control_s43](C_n4_severe_control_s43.png)
- [C_n4_severe_loss_s43](C_n4_severe_loss_s43.png)
- [D_n2_nominal_control_s43](D_n2_nominal_control_s43.png)
- [D_n2_nominal_loss_s43](D_n2_nominal_loss_s43.png)
- [D_n2_severe_control_s43](D_n2_severe_control_s43.png)
- [D_n2_severe_loss_s43](D_n2_severe_loss_s43.png)
- [D_n4_nominal_control_s43](D_n4_nominal_control_s43.png)
- [D_n4_nominal_loss_s43](D_n4_nominal_loss_s43.png)
- [D_n4_severe_control_s43](D_n4_severe_control_s43.png)
- [D_n4_severe_loss_s43](D_n4_severe_loss_s43.png)
