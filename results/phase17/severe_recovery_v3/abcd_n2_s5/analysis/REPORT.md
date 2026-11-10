# Phase 17 resilience V2 diagnostic batch

Stage: severe; 4/4 runs; 2 completed missions.
Architectures: C, D. Each includes a control and a policy-failure case.
Stored size: 3.19 MiB. Fault trigger: owned_motion. Telemetry: alive.

This is a new declared scenario, not final calibration. Replay is not LLM inference. Successful state-triggered recovery does not validate full radio-loss recovery.

B deliberately does not reassign failed-peer tasks. Its incomplete fault outcome is retained, not treated as a technical error. The all-mission diagnostic flag is separate from technical validity.

Normal-operation and recovery-capable checks are reported separately in v2_manifest.json diagnostic_groups. B fault cases are baseline outcomes, not required recovery passes.

| Case | Completed tasks | Complete | Time (s) | Replacement accepted at (s) | Productive resume at (s) |
|---|---:|---|---:|---:|---:|
| C_n2_severe_control_s5 | 4 | True | 129.20028489397373 | None | None |
| C_n2_severe_loss_s5 | 4 | True | 197.60027617006563 | 114.80026905005798 | 161.20027329400182 |
| D_n2_severe_control_s5 | 3 | False | 239.80025010800455 | None | None |
| D_n2_severe_loss_s5 | 1 | False | 239.80027930194046 | 92.60015885799658 | None |

![Overview](overview.png)
