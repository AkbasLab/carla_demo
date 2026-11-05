# Phase 13 automated suite
Profile: **pinned**. Cases: 40. Actual LLM runs: 21.
Incomplete missions are experimental outcomes; they are not automatically runtime/test failures.

| Test | Status | Tasks completed | Mission success | End time (s) |
|---|---|---:|---|---:|
| ablations/moderate/D/without_task_leases/seed_42 | completed | 0 | False | 299.90009056800045 |
| ablations/nominal/D/fallback_policy/seed_42 | completed | 4 | True | 158.30008494399954 |
| ablations/nominal/D/without_dynamic_roles/seed_42 | completed | 0 | False | 299.9000953589566 |
| ablations/nominal/D/without_memory/seed_42 | completed | 4 | True | 168.00009695498738 |
| ablations/severe/D/perfect_communication/seed_42 | completed | 4 | True | 168.50008465198334 |
| baselines/moderate/A/control/seed_42 | completed | 4 | True | 14.20007344102487 |
| baselines/moderate/B/control/seed_42 | completed | 4 | True | 40.900081955012865 |
| baselines/moderate/C/control/seed_42 | completed | 1 | False | 299.9000831829617 |
| baselines/moderate/D/control/seed_42 | completed | 1 | False | 299.9000850659795 |
| baselines/nominal/A/control/seed_42 | completed | 4 | True | 8.000083551974967 |
| baselines/nominal/B/control/seed_42 | completed | 4 | True | 38.000095274997875 |
| baselines/nominal/C/control/seed_42 | completed | 4 | True | 158.30007789400406 |
| baselines/nominal/D/control/seed_42 | completed | 4 | True | 168.1000761060277 |
| baselines/partitioned/A/control/seed_42 | completed | 4 | True | 44.40007868898101 |
| baselines/partitioned/B/control/seed_42 | completed | 4 | True | 58.50007583096158 |
| baselines/partitioned/C/control/seed_42 | completed | 4 | True | 158.40008798905183 |
| baselines/partitioned/D/control/seed_42 | completed | 4 | True | 169.10009238496423 |
| baselines/severe/A/control/seed_42 | completed | 1 | False | 299.9000912409974 |
| baselines/severe/B/control/seed_42 | completed | 4 | True | 218.20008047600277 |
| baselines/severe/C/control/seed_42 | completed | 0 | False | 299.900078590028 |
| baselines/severe/D/control/seed_42 | completed | 0 | False | 299.9000785090029 |
| drone1_failure/moderate/A/control/seed_42 | completed | 1 | False | 299.90007986605633 |
| drone1_failure/moderate/B/control/seed_42 | completed | 0 | False | 299.9001923550386 |
| drone1_failure/moderate/C/control/seed_42 | completed | 0 | False | 299.90007492003497 |
| drone1_failure/moderate/D/control/seed_42 | completed | 0 | False | 299.9000852169702 |
| drone1_failure/nominal/A/control/seed_42 | completed | 4 | True | 7.900085277971812 |
| drone1_failure/nominal/B/control/seed_42 | completed | 0 | False | 299.9000991160283 |
| drone1_failure/nominal/C/control/seed_42 | completed | 0 | False | 299.90007746510673 |
| drone1_failure/nominal/D/control/seed_42 | completed | 0 | False | 299.90008957404643 |
| drone1_failure/partitioned/A/control/seed_42 | completed | 0 | False | 299.9000795419561 |
| drone1_failure/partitioned/B/control/seed_42 | completed | 0 | False | 299.9001004709862 |
| drone1_failure/partitioned/C/control/seed_42 | completed | 0 | False | 299.9000833450118 |
| drone1_failure/partitioned/D/control/seed_42 | completed | 0 | False | 299.90009462903254 |
| drone1_failure/severe/A/control/seed_42 | completed | 0 | False | 299.90008286596276 |
| drone1_failure/severe/B/control/seed_42 | completed | 0 | False | 299.90008133801166 |
| drone1_failure/severe/C/control/seed_42 | completed | 0 | False | 299.9000765540404 |
| drone1_failure/severe/D/control/seed_42 | completed | 0 | False | 299.9001023330493 |
| relay_failure/nominal/C/control/seed_42 | completed | 0 | False | 299.90008406399284 |
| relay_failure/nominal/D/control/seed_42 | completed | 0 | False | 299.90009415894747 |
| relay_failure/nominal/D/fallback_policy/seed_42 | completed | 0 | False | 299.9000883620465 |

Full per-case data are under each test folder. `run/traces.zip` preserves the large raw traces losslessly.
`metrics.csv` is for future figures; unsuccessful completion times are blank rather than fabricated successes.
Role/memory benefits cannot be inferred from replay. See individual validation files for whether a path was exercised.
