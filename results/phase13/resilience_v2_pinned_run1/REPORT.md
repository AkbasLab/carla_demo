# Phase 13 automated suite
Profile: **pinned**. Cases: 40. Actual LLM runs: 21.
Incomplete missions are experimental outcomes; they are not automatically runtime/test failures.

| Test | Status | Tasks completed | Mission success | End time (s) |
|---|---|---:|---|---:|
| ablations/moderate/D/without_task_leases/seed_42 | completed | 0 | False | 599.9000895379577 |
| ablations/nominal/D/fallback_policy/seed_42 | completed | 4 | True | 158.70008756394964 |
| ablations/nominal/D/without_dynamic_roles/seed_42 | completed | 0 | False | 599.900095091085 |
| ablations/nominal/D/without_memory/seed_42 | completed | 4 | True | 170.5000846129842 |
| ablations/severe/D/perfect_communication/seed_42 | completed | 4 | True | 169.00008030503523 |
| baselines/moderate/A/control/seed_42 | completed | 4 | True | 11.200081052957103 |
| baselines/moderate/B/control/seed_42 | completed | 4 | True | 38.90008443000261 |
| baselines/moderate/C/control/seed_42 | completed | 4 | True | 159.00008418806829 |
| baselines/moderate/D/control/seed_42 | completed | 4 | True | 168.10008626198396 |
| baselines/nominal/A/control/seed_42 | completed | 4 | True | 10.600285312975757 |
| baselines/nominal/B/control/seed_42 | completed | 4 | True | 88.20009012299124 |
| baselines/nominal/C/control/seed_42 | completed | 4 | True | 158.50008217501454 |
| baselines/nominal/D/control/seed_42 | completed | 4 | True | 169.90007882600185 |
| baselines/partitioned/A/control/seed_42 | completed | 4 | True | 17.60008064599242 |
| baselines/partitioned/B/control/seed_42 | completed | 4 | True | 50.10008943697903 |
| baselines/partitioned/C/control/seed_42 | completed | 4 | True | 158.90013925195672 |
| baselines/partitioned/D/control/seed_42 | completed | 4 | True | 167.300078468048 |
| baselines/severe/A/control/seed_42 | completed | 4 | True | 23.500079741002992 |
| baselines/severe/B/control/seed_42 | completed | 4 | True | 60.50005723303184 |
| baselines/severe/C/control/seed_42 | completed | 4 | True | 163.000076913042 |
| baselines/severe/D/control/seed_42 | completed | 4 | True | 214.9000956909731 |
| drone1_failure/moderate/A/control/seed_42 | completed | 2 | False | 599.9000835149782 |
| drone1_failure/moderate/B/control/seed_42 | completed | 0 | False | 599.90009968495 |
| drone1_failure/moderate/C/control/seed_42 | completed | 0 | False | 599.9000504709547 |
| drone1_failure/moderate/D/control/seed_42 | completed | 0 | False | 599.9000838130014 |
| drone1_failure/nominal/A/control/seed_42 | completed | 2 | False | 599.9001551429974 |
| drone1_failure/nominal/B/control/seed_42 | completed | 0 | False | 599.90008954308 |
| drone1_failure/nominal/C/control/seed_42 | completed | 0 | False | 599.9000799990026 |
| drone1_failure/nominal/D/control/seed_42 | completed | 0 | False | 599.9000946190208 |
| drone1_failure/partitioned/A/control/seed_42 | completed | 0 | False | 599.9000940989936 |
| drone1_failure/partitioned/B/control/seed_42 | completed | 0 | False | 599.9000829299912 |
| drone1_failure/partitioned/C/control/seed_42 | completed | 0 | False | 599.9000886899885 |
| drone1_failure/partitioned/D/control/seed_42 | completed | 0 | False | 599.9000899519306 |
| drone1_failure/severe/A/control/seed_42 | completed | 0 | False | 599.9000866349088 |
| drone1_failure/severe/B/control/seed_42 | completed | 0 | False | 599.9000823949464 |
| drone1_failure/severe/C/control/seed_42 | completed | 0 | False | 599.9000958920224 |
| drone1_failure/severe/D/control/seed_42 | completed | 0 | False | 599.9000906920992 |
| relay_failure/nominal/C/control/seed_42 | completed | 0 | False | 599.900417135912 |
| relay_failure/nominal/D/control/seed_42 | completed | 0 | False | 599.9000835239422 |
| relay_failure/nominal/D/fallback_policy/seed_42 | completed | 0 | False | 599.9000873320037 |

Full per-case data are under each test folder. `run/traces.zip` preserves the large raw traces losslessly.
`metrics.csv` is for future figures; unsuccessful completion times are blank rather than fabricated successes.
Role/memory benefits cannot be inferred from replay. See individual validation files for whether a path was exercised.
