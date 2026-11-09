# Phase 17 resilience V2 diagnostic batch

Stage: severe; 2/2 runs; 0 completed missions.
Architectures: D. Each includes a control and a policy-failure case.
Stored size: 1.80 MiB. Fault trigger: owned_motion. Telemetry: alive.

This is a new declared scenario, not final calibration. Replay is not LLM inference. Successful state-triggered recovery does not validate full radio-loss recovery.

B deliberately does not reassign failed-peer tasks. Its incomplete fault outcome is retained, not treated as a technical error. The all-mission diagnostic flag is separate from technical validity.

Normal-operation and recovery-capable checks are reported separately in v2_manifest.json diagnostic_groups. B fault cases are baseline outcomes, not required recovery passes.

| Case | Completed tasks | Complete | Time (s) | Replacement accepted at (s) | Productive resume at (s) |
|---|---:|---|---:|---:|---:|
| D_n2_severe_control_s10 | 3 | False | 239.800082731992 | None | None |
| D_n2_severe_loss_s10 | 2 | False | 239.80010186499567 | 130.60008946200833 | None |

![Overview](overview.png)
