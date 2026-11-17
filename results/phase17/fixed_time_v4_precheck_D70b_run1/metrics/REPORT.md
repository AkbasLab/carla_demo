# Phase 15 evaluation
Definition: phase15.route_metrics.v1. Type: predeclared.

| Experiment | Success | Completed time (s) | Observation status | Route work | Continuity |
|---|---|---:|---|---:|---:|
| D_n4_nominal_control_s10_70b | True | 223.20010665990412 | completed | 1.0 | 1.0 |
| D_n4_nominal_loss_s10_70b | True | 237.40013078786433 | completed | 1.0 | 1.0 |

Missing measurements and reference failures have explicit reasons in the per-run JSON. Successful times are never filled with timeout endpoints.
Route waypoint work is not area coverage
Absent collision/target/return sensing is not a zero measurement
Recovery acceptance is local ownership, not consensus or safe execution
Physical/between-sample safety is not certified
Retrospective analysis does not establish preregistration
