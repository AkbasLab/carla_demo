# Phase 17 resilience V2 diagnostic batch

Stage: severe; 2/2 runs; 1 completed missions.
Architectures: A. Each includes a control and a policy-failure case.
Stored size: 2.36 MiB. Fault trigger: owned_motion. Telemetry: alive.

This is a new declared scenario, not final calibration. Replay is not LLM inference. Successful state-triggered recovery does not validate full radio-loss recovery.

B deliberately does not reassign failed-peer tasks. Its incomplete fault outcome is retained, not treated as a technical error. The all-mission diagnostic flag is separate from technical validity.

Normal-operation and recovery-capable checks are reported separately in v2_manifest.json diagnostic_groups. B fault cases are baseline outcomes, not required recovery passes.

| Case | Completed tasks | Complete | Time (s) | Replacement accepted at (s) | Productive resume at (s) |
|---|---:|---|---:|---:|---:|
| A_n2_severe_control_s10 | 4 | True | 122.20007665100275 | None | None |
| A_n2_severe_loss_s10 | 3 | False | 239.80007753000245 | 81.60008600098081 | None |

![Overview](overview.png)
