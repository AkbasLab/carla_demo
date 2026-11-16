# Phase 15 evaluation
Definition: phase15.route_metrics.v1. Type: predeclared.

| Experiment | Success | Completed time (s) | Observation status | Route work | Continuity |
|---|---|---:|---|---:|---:|
| A_n4_nominal_control_s10 | True | 66.0002748791594 | completed | 1.0 | 1.0 |
| A_n4_nominal_loss_s10 | False | None | timeout | 0.8958333333333334 | None |

Missing measurements and reference failures have explicit reasons in the per-run JSON. Successful times are never filled with timeout endpoints.
Route waypoint work is not area coverage
Absent collision/target/return sensing is not a zero measurement
Recovery acceptance is local ownership, not consensus or safe execution
Physical/between-sample safety is not certified
Retrospective analysis does not establish preregistration
