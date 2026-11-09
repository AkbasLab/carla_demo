# Phase 17 resilience V2 diagnostic batch

Stage: severe; 2/2 runs; 2 completed missions.
Architectures: C. Each includes a control and a policy-failure case.
Stored size: 1.66 MiB. Fault trigger: owned_motion. Telemetry: alive.

This is a new declared scenario, not final calibration. Replay is not LLM inference. Successful state-triggered recovery does not validate full radio-loss recovery.

B deliberately does not reassign failed-peer tasks. Its incomplete fault outcome is retained, not treated as a technical error. The all-mission diagnostic flag is separate from technical validity.

Normal-operation and recovery-capable checks are reported separately in v2_manifest.json diagnostic_groups. B fault cases are baseline outcomes, not required recovery passes.

| Case | Completed tasks | Complete | Time (s) | Replacement accepted at (s) | Productive resume at (s) |
|---|---:|---|---:|---:|---:|
| C_n2_severe_control_s10 | 4 | True | 152.80027377000079 | None | None |
| C_n2_severe_loss_s10 | 4 | True | 209.00024345100974 | 112.60023370300769 | 166.60012322300463 |

![Overview](overview.png)
