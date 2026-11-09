# Phase 17 resilience V2 diagnostic batch

Stage: severe; 2/2 runs; 1 completed missions.
Architectures: C. Each includes a control and a policy-failure case.
Stored size: 4.96 MiB. Fault trigger: owned_motion. Telemetry: alive.

This is a new declared scenario, not final calibration. Replay is not LLM inference. Successful state-triggered recovery does not validate full radio-loss recovery.

B deliberately does not reassign failed-peer tasks. Its incomplete fault outcome is retained, not treated as a technical error. The all-mission diagnostic flag is separate from technical validity.

Normal-operation and recovery-capable checks are reported separately in v2_manifest.json diagnostic_groups. B fault cases are baseline outcomes, not required recovery passes.

| Case | Completed tasks | Complete | Time (s) | Replacement accepted at (s) | Productive resume at (s) |
|---|---:|---|---:|---:|---:|
| C_n4_severe_control_s20 | 4 | True | 138.40007833900745 | None | None |
| C_n4_severe_loss_s20 | 3 | False | 239.80009011700167 | 95.20008391299052 | 134.00008928001625 |

![Overview](overview.png)
