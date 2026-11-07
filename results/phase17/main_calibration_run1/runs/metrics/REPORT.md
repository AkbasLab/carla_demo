# Phase 15 evaluation
Definition: phase15.route_metrics.v1. Type: recomputed from individually verified pre-run registrations.

| Experiment | Success | Completed time (s) | Observation status | Route work | Continuity |
|---|---|---:|---|---:|---:|
| C_n2_nominal_control_s41 | True | 183.00007118199574 | completed | 1.0 | 1.0 |
| C_n2_nominal_control_s42 | True | 244.60009467700002 | completed | 1.0 | 1.0 |
| C_n2_nominal_loss_s41 | False | None | timeout | 0.0625 | None |
| C_n2_nominal_loss_s42 | False | None | timeout | 0.125 | None |
| C_n2_severe_control_s41 | False | None | timeout | 0.4375 | 0.0 |
| C_n2_severe_control_s42 | False | None | timeout | 0.4375 | 0.0 |
| C_n2_severe_loss_s41 | False | None | timeout | 0.0625 | None |
| C_n2_severe_loss_s42 | False | None | timeout | 0.0625 | None |
| C_n4_nominal_control_s41 | True | 174.20009295599448 | completed | 1.0 | 1.0 |
| C_n4_nominal_control_s42 | False | None | error | 0.0 | None |
| C_n4_nominal_loss_s41 | False | None | timeout | 0.0625 | None |
| C_n4_severe_control_s41 | False | None | timeout | 0.75 | 0.0 |
| C_n4_severe_loss_s41 | False | None | timeout | 0.0625 | None |
| D_n2_nominal_control_s41 | True | 241.00009032800153 | completed | 1.0 | 1.0 |
| D_n2_nominal_loss_s41 | False | None | timeout | 0.0 | None |
| D_n2_severe_control_s41 | False | None | timeout | 0.3125 | 0.0 |
| D_n2_severe_loss_s41 | False | None | timeout | 0.0 | None |
| D_n4_nominal_control_s41 | True | 185.60009877900302 | completed | 1.0 | 1.0 |
| D_n4_nominal_loss_s41 | False | None | timeout | 0.0 | None |
| D_n4_severe_control_s41 | False | None | timeout | 0.75 | 0.0 |
| D_n4_severe_loss_s41 | False | None | timeout | 0.0 | None |

Missing measurements and reference failures have explicit reasons in the per-run JSON. Successful times are never filled with timeout endpoints.
Route waypoint work is not area coverage
Absent collision/target/return sensing is not a zero measurement
Recovery acceptance is local ownership, not consensus or safe execution
Physical/between-sample safety is not certified
Retrospective analysis does not establish preregistration
