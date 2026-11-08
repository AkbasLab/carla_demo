# Phase 17 resilience V2 diagnostic batch

Stage: focused; 8/8 runs; 5 completed missions.
Architectures: A, B, C, D. Each includes a control and a policy-failure case.
Stored size: 6.18 MiB. Fault trigger: owned_motion. Telemetry: alive.

This is a new declared scenario, not final calibration. Replay is not LLM inference. Successful state-triggered recovery does not validate full radio-loss recovery.

B deliberately does not reassign failed-peer tasks. Its incomplete fault outcome is retained, not treated as a technical error. The all-mission diagnostic flag is separate from technical validity.

| Case | Completed tasks | Complete | Time (s) | Replacement accepted at (s) | Productive resume at (s) |
|---|---:|---|---:|---:|---:|
| A_n2_nominal_control_s11 | 4 | True | 117.60007714400126 | None | None |
| A_n2_nominal_loss_s11 | 3 | False | 239.80008398499922 | 100.00008146399341 | None |
| B_n2_nominal_control_s11 | 2 | False | 239.80008442200779 | None | None |
| B_n2_nominal_loss_s11 | 1 | False | 239.80009183599032 | None | None |
| C_n2_nominal_control_s11 | 4 | True | 88.00009261500963 | None | None |
| C_n2_nominal_loss_s11 | 4 | True | 159.40008362900699 | 106.20010540400108 | 143.00011156999972 |
| D_n2_nominal_control_s11 | 4 | True | 112.80009833400254 | None | None |
| D_n2_nominal_loss_s11 | 4 | True | 222.0001054530003 | 104.20009964099154 | 142.20010187399748 |

![Overview](overview.png)
