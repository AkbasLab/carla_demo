# Phase 17 resilience V2 diagnostic batch

Stage: severe; 4/4 runs; 1 completed missions.
Architectures: C, D. Each includes a control and a policy-failure case.
Stored size: 10.42 MiB. Fault trigger: owned_motion. Telemetry: alive.

This is a new declared scenario, not final calibration. Replay is not LLM inference. Successful state-triggered recovery does not validate full radio-loss recovery.

B deliberately does not reassign failed-peer tasks. Its incomplete fault outcome is retained, not treated as a technical error. The all-mission diagnostic flag is separate from technical validity.

Normal-operation and recovery-capable checks are reported separately in v2_manifest.json diagnostic_groups. B fault cases are baseline outcomes, not required recovery passes.

| Case | Completed tasks | Complete | Time (s) | Replacement accepted at (s) | Productive resume at (s) |
|---|---:|---|---:|---:|---:|
| C_n4_severe_control_s20 | 3 | False | 239.80008011401515 | None | None |
| C_n4_severe_loss_s20 | 4 | True | 176.20008501800476 | 95.40008161601145 | 136.80007911400753 |
| D_n4_severe_control_s20 | 1 | False | 239.80008699800237 | None | None |
| D_n4_severe_loss_s20 | 2 | False | 239.80013249098556 | 116.20009552998818 | None |

![Overview](overview.png)
