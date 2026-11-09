# Phase 17 resilience V2 diagnostic batch

Stage: focused; 2/2 runs; 1 completed missions.
Architectures: A. Each includes a control and a policy-failure case.
Stored size: 1.88 MiB. Fault trigger: owned_motion. Telemetry: alive.

This is a new declared scenario, not final calibration. Replay is not LLM inference. Successful state-triggered recovery does not validate full radio-loss recovery.

B deliberately does not reassign failed-peer tasks. Its incomplete fault outcome is retained, not treated as a technical error. The all-mission diagnostic flag is separate from technical validity.

Normal-operation and recovery-capable checks are reported separately in v2_manifest.json diagnostic_groups. B fault cases are baseline outcomes, not required recovery passes.

| Case | Completed tasks | Complete | Time (s) | Replacement accepted at (s) | Productive resume at (s) |
|---|---:|---|---:|---:|---:|
| A_n2_nominal_control_s11 | 4 | True | 79.20007705900935 | None | None |
| A_n2_nominal_loss_s11 | 3 | False | 239.8000843200134 | 75.40007773900288 | None |

![Overview](overview.png)
