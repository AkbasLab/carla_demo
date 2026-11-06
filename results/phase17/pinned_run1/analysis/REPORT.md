# Phase 17 pilot calibration
Profile: pinned. 48 planned cases; 16 missions completed.

These are methodology pilots, not final comparisons. Every successful time excludes censored runs.

| Architecture | Team | Network | Fault | Successes / runs | Median successful time (s) |
|---|---:|---|---|---:|---:|
| C | 2 | nominal | none | 3/3 | 183.60024617693853 |
| C | 2 | nominal | drone_failure_midmission | 0/3 | None |
| C | 2 | severe | none | 0/3 | None |
| C | 2 | severe | drone_failure_midmission | 0/3 | None |
| C | 4 | nominal | none | 3/3 | 175.00008156802505 |
| C | 4 | nominal | drone_failure_midmission | 0/3 | None |
| C | 4 | severe | none | 3/3 | 214.80008743098006 |
| C | 4 | severe | drone_failure_midmission | 0/3 | None |
| D | 2 | nominal | none | 3/3 | 518.2001049370738 |
| D | 2 | nominal | drone_failure_midmission | 0/3 | None |
| D | 2 | severe | none | 1/3 | 325.4000863760011 |
| D | 2 | severe | drone_failure_midmission | 0/3 | None |
| D | 4 | nominal | none | 3/3 | 190.2000859400723 |
| D | 4 | nominal | drone_failure_midmission | 0/3 | None |
| D | 4 | severe | none | 0/3 | None |
| D | 4 | severe | drone_failure_midmission | 0/3 | None |

## Communication-level calibration
These are candidate application-network settings, not calibrated radio claims. Latency jitter is a uniform half-width; delivery delays also include queueing and polling. Pending packets are excluded from resolved delivery ratios.

| Level | Independent loss | Latency mean +/- half-width (ms) | Recipient packets/s | Egress bytes/s | Control mission success | Mean resolved delivery fraction |
|---|---:|---:|---:|---:|---:|---:|
| nominal | 0 | 10 +/- 2 | None | None | 1.0 | 1.0 |
| severe | 0.3 | 400 +/- 200 | 60 | 50000 | 0.3333333333333333 | 0.7037797713453927 |

All-success or all-failure severe controls, mostly unusable delivery, inadequate nominal references, missing model evidence, or ineffective fault timing require more calibration. Do not remove those runs or relax the guardian to manufacture recovery.

## Final selection status
Eligible for freeze: False.

- fault_did_not_interrupt_owned_moving_work

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
