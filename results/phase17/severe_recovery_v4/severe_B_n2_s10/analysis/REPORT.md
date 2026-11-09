# Phase 17 resilience V2 diagnostic batch

Stage: severe; 2/2 runs; 1 completed missions.
Architectures: B. Each includes a control and a policy-failure case.
Stored size: 1.44 MiB. Fault trigger: owned_motion. Telemetry: alive.

This is a new declared scenario, not final calibration. Replay is not LLM inference. Successful state-triggered recovery does not validate full radio-loss recovery.

B deliberately does not reassign failed-peer tasks. Its incomplete fault outcome is retained, not treated as a technical error. The all-mission diagnostic flag is separate from technical validity.

Normal-operation and recovery-capable checks are reported separately in v2_manifest.json diagnostic_groups. B fault cases are baseline outcomes, not required recovery passes.

| Case | Completed tasks | Complete | Time (s) | Replacement accepted at (s) | Productive resume at (s) |
|---|---:|---|---:|---:|---:|
| B_n2_severe_control_s10 | 4 | True | 116.60008552498766 | None | None |
| B_n2_severe_loss_s10 | 2 | False | 239.8000515270105 | None | None |

![Overview](overview.png)
