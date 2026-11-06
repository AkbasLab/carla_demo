# Phase 15 evaluation
Definition: phase15.route_metrics.v1. Type: predeclared.

| Experiment | Success | Completed time (s) | Observation status | Route work | Continuity |
|---|---|---:|---|---:|---:|
| agentic_decentralized_moderate_42 | True | 10.8 | completed | 1.0 | 1.0 |
| agentic_decentralized_nominal_42 | True | 10.6 | completed | 1.0 | 1.0 |
| agentic_decentralized_severe_42 | True | 16.1 | completed | 1.0 | 1.0 |
| deterministic_decentralized_moderate_42 | True | 10.8 | completed | 1.0 | 1.0 |
| deterministic_decentralized_nominal_42 | True | 10.6 | completed | 1.0 | 1.0 |
| deterministic_decentralized_severe_42 | True | 16.3 | completed | 1.0 | 1.0 |
| failed_worker_rules | False | None | timeout | 0.0 | None |

Missing measurements and reference failures have explicit reasons in the per-run JSON. Successful times are never filled with timeout endpoints.
Route waypoint work is not area coverage
Absent collision/target/return sensing is not a zero measurement
Recovery acceptance is local ownership, not consensus or safe execution
Physical/between-sample safety is not certified
Retrospective analysis does not establish preregistration
