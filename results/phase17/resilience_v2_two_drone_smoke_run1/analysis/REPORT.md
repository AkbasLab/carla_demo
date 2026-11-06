# Phase 17 resilience V2 diagnostic batch

Stage: smoke; 2/2 runs; 2 completed missions.
Stored size: 1.45 MiB. Fault trigger: owned_motion. Telemetry: alive.

This is a new declared scenario, not final calibration. Replay is not LLM inference. Successful state-triggered recovery does not validate full radio-loss recovery.

| Case | Completed tasks | Complete | Time (s) | Replacement accepted at (s) | Productive resume at (s) |
|---|---:|---|---:|---:|---:|
| C_n2_nominal_control_s9 | 4 | True | 180.2 | None | None |
| C_n2_nominal_loss_s9 | 4 | True | 192.8 | 111.6 | 140.8 |

![Overview](overview.png)
