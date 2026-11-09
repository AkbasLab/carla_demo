# Phase 17 resilience V2 diagnostic batch

Stage: severe; 2/2 runs; 0 completed missions.
Architectures: D. Each includes a control and a policy-failure case.
Stored size: 4.83 MiB. Fault trigger: owned_motion. Telemetry: alive.

This is a new declared scenario, not final calibration. Replay is not LLM inference. Successful state-triggered recovery does not validate full radio-loss recovery.

B deliberately does not reassign failed-peer tasks. Its incomplete fault outcome is retained, not treated as a technical error. The all-mission diagnostic flag is separate from technical validity.

Normal-operation and recovery-capable checks are reported separately in v2_manifest.json diagnostic_groups. B fault cases are baseline outcomes, not required recovery passes.

| Case | Completed tasks | Complete | Time (s) | Replacement accepted at (s) | Productive resume at (s) |
|---|---:|---|---:|---:|---:|
| D_n4_severe_control_s15 | 2 | False | 239.800108394993 | None | None |
| D_n4_severe_loss_s15 | 2 | False | 239.80008089900366 | 87.80009750497993 | None |

![Overview](overview.png)
