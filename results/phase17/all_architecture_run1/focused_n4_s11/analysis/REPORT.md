# Phase 17 resilience V2 diagnostic batch

Stage: focused; 8/8 runs; 6 completed missions.
Architectures: A, B, C, D. Each includes a control and a policy-failure case.
Stored size: 10.67 MiB. Fault trigger: owned_motion. Telemetry: alive.

This is a new declared scenario, not final calibration. Replay is not LLM inference. Successful state-triggered recovery does not validate full radio-loss recovery.

B deliberately does not reassign failed-peer tasks. Its incomplete fault outcome is retained, not treated as a technical error. The all-mission diagnostic flag is separate from technical validity.

| Case | Completed tasks | Complete | Time (s) | Replacement accepted at (s) | Productive resume at (s) |
|---|---:|---|---:|---:|---:|
| A_n4_nominal_control_s11 | 4 | True | 33.00009288900765 | None | None |
| A_n4_nominal_loss_s11 | 3 | False | 239.80007846502122 | 75.40008416000637 | None |
| B_n4_nominal_control_s11 | 4 | True | 54.00008120399434 | None | None |
| B_n4_nominal_loss_s11 | 3 | False | 239.80008054402424 | None | None |
| C_n4_nominal_control_s11 | 4 | True | 54.20008264199714 | None | None |
| C_n4_nominal_loss_s11 | 4 | True | 129.60008907300653 | 93.80010251299245 | 112.60008661300526 |
| D_n4_nominal_control_s11 | 4 | True | 73.80008774599992 | None | None |
| D_n4_nominal_loss_s11 | 4 | True | 148.40007630499895 | 104.20018424099544 | 131.00008590999641 |

![Overview](overview.png)
