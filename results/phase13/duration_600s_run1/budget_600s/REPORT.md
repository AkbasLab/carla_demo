# Phase 13 automated suite
Profile: **pinned**. Cases: 40. Actual LLM runs: 21.
Incomplete missions are experimental outcomes; they are not automatically runtime/test failures.

| Test | Status | Tasks completed | Mission success | End time (s) |
|---|---|---:|---|---:|
| ablations/moderate/D/without_task_leases/seed_42 | completed | 0 | False | 599.9000814959873 |
| ablations/nominal/D/fallback_policy/seed_42 | completed | 4 | True | 158.3001143420115 |
| ablations/nominal/D/without_dynamic_roles/seed_42 | completed | 0 | False | 599.9000959430123 |
| ablations/nominal/D/without_memory/seed_42 | completed | 4 | True | 167.80008133803494 |
| ablations/severe/D/perfect_communication/seed_42 | completed | 4 | True | 168.90008968603797 |
| baselines/moderate/A/control/seed_42 | completed | 4 | True | 12.10005640401505 |
| baselines/moderate/B/control/seed_42 | completed | 4 | True | 37.200080659007654 |
| baselines/moderate/C/control/seed_42 | completed | 3 | False | 599.9000819459325 |
| baselines/moderate/D/control/seed_42 | completed | 4 | True | 522.5001190529438 |
| baselines/nominal/A/control/seed_42 | completed | 4 | True | 8.100080411997624 |
| baselines/nominal/B/control/seed_42 | completed | 4 | True | 38.30008322105277 |
| baselines/nominal/C/control/seed_42 | completed | 4 | True | 158.50007682398427 |
| baselines/nominal/D/control/seed_42 | completed | 4 | True | 167.80008310405537 |
| baselines/partitioned/A/control/seed_42 | completed | 4 | True | 44.60007774701808 |
| baselines/partitioned/B/control/seed_42 | completed | 4 | True | 55.30009934492409 |
| baselines/partitioned/C/control/seed_42 | completed | 4 | True | 158.20018593291752 |
| baselines/partitioned/D/control/seed_42 | completed | 4 | True | 167.20009683899116 |
| baselines/severe/A/control/seed_42 | completed | 2 | False | 599.9000894529745 |
| baselines/severe/B/control/seed_42 | completed | 4 | True | 270.1000827839598 |
| baselines/severe/C/control/seed_42 | completed | 0 | False | 599.9000851298915 |
| baselines/severe/D/control/seed_42 | completed | 1 | False | 599.900482535013 |
| drone1_failure/moderate/A/control/seed_42 | completed | 1 | False | 599.900081826956 |
| drone1_failure/moderate/B/control/seed_42 | completed | 0 | False | 599.9000951000489 |
| drone1_failure/moderate/C/control/seed_42 | completed | 0 | False | 599.9000763969962 |
| drone1_failure/moderate/D/control/seed_42 | completed | 0 | False | 599.9000997890253 |
| drone1_failure/nominal/A/control/seed_42 | completed | 3 | False | 599.9000739180483 |
| drone1_failure/nominal/B/control/seed_42 | completed | 0 | False | 599.9002532439772 |
| drone1_failure/nominal/C/control/seed_42 | completed | 0 | False | 599.9001439519925 |
| drone1_failure/nominal/D/control/seed_42 | completed | 0 | False | 599.9000770209823 |
| drone1_failure/partitioned/A/control/seed_42 | completed | 0 | False | 599.9000840440858 |
| drone1_failure/partitioned/B/control/seed_42 | completed | 0 | False | 599.900097745005 |
| drone1_failure/partitioned/C/control/seed_42 | completed | 0 | False | 599.9000821359223 |
| drone1_failure/partitioned/D/control/seed_42 | completed | 0 | False | 599.9000784599921 |
| drone1_failure/severe/A/control/seed_42 | completed | 0 | False | 599.9000966189196 |
| drone1_failure/severe/B/control/seed_42 | completed | 0 | False | 599.9000886400463 |
| drone1_failure/severe/C/control/seed_42 | completed | 0 | False | 599.9000820430228 |
| drone1_failure/severe/D/control/seed_42 | completed | 0 | False | 599.9000781120267 |
| relay_failure/nominal/C/control/seed_42 | completed | 0 | False | 599.9000900529791 |
| relay_failure/nominal/D/control/seed_42 | completed | 0 | False | 599.9000972959911 |
| relay_failure/nominal/D/fallback_policy/seed_42 | completed | 0 | False | 599.9000790040009 |

Full per-case data are under each test folder. `run/traces.zip` preserves the large raw traces losslessly.
`metrics.csv` is for future figures; unsuccessful completion times are blank rather than fabricated successes.
Role/memory benefits cannot be inferred from replay. See individual validation files for whether a path was exercised.
