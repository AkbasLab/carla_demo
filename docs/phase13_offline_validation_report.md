# Phase 13 automated suite
Profile: **validation**. Cases: 41. Actual LLM runs: 0.
Incomplete missions are experimental outcomes; they are not automatically runtime/test failures.

| Test | Status | Tasks completed | Mission success | End time (s) |
|---|---|---:|---|---:|
| ablations/moderate/D/without_task_leases/seed_42 | completed | 0 | False | 299.9 |
| ablations/nominal/D/fallback_policy/seed_42 | completed | 4 | True | 158.1 |
| ablations/nominal/D/without_dynamic_roles/seed_42 | completed | 0 | False | 299.9 |
| ablations/nominal/D/without_memory/seed_42 | completed | 4 | True | 158.1 |
| ablations/severe/D/perfect_communication/seed_42 | completed | 4 | True | 158.1 |
| baselines/moderate/A/control/seed_42 | completed | 4 | True | 13.0 |
| baselines/moderate/B/control/seed_42 | completed | 4 | True | 8.5 |
| baselines/moderate/C/control/seed_42 | completed | 3 | False | 299.9 |
| baselines/moderate/D/control/seed_42 | completed | 3 | False | 299.9 |
| baselines/nominal/A/control/seed_42 | completed | 4 | True | 8.0 |
| baselines/nominal/B/control/seed_42 | completed | 4 | True | 7.9 |
| baselines/nominal/C/control/seed_42 | completed | 4 | True | 158.1 |
| baselines/nominal/D/control/seed_42 | completed | 4 | True | 158.1 |
| baselines/partitioned/A/control/seed_42 | completed | 4 | True | 44.2 |
| baselines/partitioned/B/control/seed_42 | completed | 4 | True | 14.3 |
| baselines/partitioned/C/control/seed_42 | completed | 4 | True | 158.1 |
| baselines/partitioned/D/control/seed_42 | completed | 4 | True | 158.1 |
| baselines/severe/A/control/seed_42 | completed | 2 | False | 299.9 |
| baselines/severe/B/control/seed_42 | completed | 4 | True | 13.0 |
| baselines/severe/C/control/seed_42 | completed | 0 | False | 299.9 |
| baselines/severe/D/control/seed_42 | completed | 0 | False | 299.9 |
| drone1_failure/moderate/A/control/seed_42 | completed | 0 | False | 299.9 |
| drone1_failure/moderate/B/control/seed_42 | completed | 3 | False | 299.9 |
| drone1_failure/moderate/C/control/seed_42 | completed | 0 | False | 299.9 |
| drone1_failure/moderate/D/control/seed_42 | completed | 0 | False | 299.9 |
| drone1_failure/nominal/A/control/seed_42 | completed | 3 | False | 299.9 |
| drone1_failure/nominal/B/control/seed_42 | completed | 4 | True | 7.9 |
| drone1_failure/nominal/C/control/seed_42 | completed | 0 | False | 299.9 |
| drone1_failure/nominal/D/control/seed_42 | completed | 0 | False | 299.9 |
| drone1_failure/partitioned/A/control/seed_42 | completed | 0 | False | 299.9 |
| drone1_failure/partitioned/B/control/seed_42 | completed | 0 | False | 299.9 |
| drone1_failure/partitioned/C/control/seed_42 | completed | 0 | False | 299.9 |
| drone1_failure/partitioned/D/control/seed_42 | completed | 0 | False | 299.9 |
| drone1_failure/severe/A/control/seed_42 | completed | 0 | False | 299.9 |
| drone1_failure/severe/B/control/seed_42 | completed | 0 | False | 299.9 |
| drone1_failure/severe/C/control/seed_42 | completed | 0 | False | 299.9 |
| drone1_failure/severe/D/control/seed_42 | completed | 0 | False | 299.9 |
| relay_failure/nominal/C/control/seed_42 | completed | 0 | False | 299.9 |
| relay_failure/nominal/D/control/seed_42 | completed | 0 | False | 299.9 |
| relay_failure/nominal/D/fallback_policy/seed_42 | completed | 0 | False | 299.9 |
| reproducibility/moderate/C/repeat/seed_42 | completed | 3 | False | 299.9 |

Full per-case data are under each test folder. `run/traces.zip` preserves the large raw traces losslessly.
`metrics.csv` is for future figures; unsuccessful completion times are blank rather than fabricated successes.
Role/memory benefits cannot be inferred from replay. See individual validation files for whether a path was exercised.

## Coverage notes

- The nominal B fixture finished before its scheduled eight-second disruption; `failure_injected` is false for that case. It is not evidence of successful failure recovery.
- In the relay-failure fixtures, C and the deterministic replacement changed role; D's replay selector did not. This is not a real-model comparison.
- All 41 runs are deterministic/replay validation: there are no actual LLM results here. See the pinned profile for tests to run on the Ollama host.

Full traces are retained in the session workspace; this repository report is a compact record, not a replacement for the raw traces.
