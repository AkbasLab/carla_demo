# Phase 17 resilience V2 diagnostic batch

Stage: smoke; 2/2 runs; 1 completed missions.
Stored size: 2.07 MiB. Fault trigger: owned_motion. Telemetry: silent.

This is a new declared scenario, not final calibration. Replay is not LLM inference. Successful state-triggered recovery does not validate full radio-loss recovery.

| Case | Completed tasks | Complete | Time (s) | Replacement accepted at (s) | Productive resume at (s) |
|---|---:|---|---:|---:|---:|
| C_n4_nominal_control_s7 | 4 | True | 51.8 | None | None |
| C_n4_nominal_loss_s7 | 0 | False | 239.8 | None | None |

![Overview](overview.png)
