# Phase 17 resilience V2 diagnostic batch

Stage: severe; 2/2 runs; 2 completed missions.
Architectures: C. Each includes a control and a policy-failure case.
Stored size: 1.71 MiB. Fault trigger: owned_motion. Telemetry: alive.

This is a new declared scenario, not final calibration. Replay is not LLM inference. Successful state-triggered recovery does not validate full radio-loss recovery.

B deliberately does not reassign failed-peer tasks. Its incomplete fault outcome is retained, not treated as a technical error. The all-mission diagnostic flag is separate from technical validity.

Normal-operation and recovery-capable checks are reported separately in v2_manifest.json diagnostic_groups. B fault cases are baseline outcomes, not required recovery passes.

| Case | Completed tasks | Complete | Time (s) | Replacement accepted at (s) | Productive resume at (s) |
|---|---:|---|---:|---:|---:|
| C_n2_severe_control_s10 | 4 | True | 164.40006161297788 | None | None |
| C_n2_severe_loss_s10 | 4 | True | 215.20008539102855 | 113.4000773440057 | 174.40008449202287 |

![Overview](overview.png)
