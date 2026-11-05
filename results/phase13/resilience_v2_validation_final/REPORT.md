# Phase 13 automated suite
Profile: **validation**. Cases: 18. Actual LLM runs: 0.
Incomplete missions are experimental outcomes; they are not automatically runtime/test failures.

| Test | Status | Tasks completed | Mission success | End time (s) |
|---|---|---:|---|---:|
| baselines/moderate/A/control/seed_42 | completed | 4 | True | 10.4 |
| baselines/moderate/A/control/seed_43 | completed | 4 | True | 10.6 |
| baselines/moderate/A/control/seed_44 | completed | 4 | True | 11.2 |
| baselines/moderate/C/control/seed_42 | completed | 4 | True | 158.3 |
| baselines/moderate/C/control/seed_43 | completed | 4 | True | 158.2 |
| baselines/moderate/C/control/seed_44 | completed | 4 | True | 158.3 |
| baselines/moderate/D/control/seed_42 | completed | 4 | True | 158.3 |
| baselines/moderate/D/control/seed_43 | completed | 4 | True | 158.2 |
| baselines/moderate/D/control/seed_44 | completed | 4 | True | 158.3 |
| baselines/severe/A/control/seed_42 | completed | 4 | True | 14.9 |
| baselines/severe/A/control/seed_43 | completed | 4 | True | 21.6 |
| baselines/severe/A/control/seed_44 | completed | 4 | True | 20.1 |
| baselines/severe/C/control/seed_42 | completed | 4 | True | 160.2 |
| baselines/severe/C/control/seed_43 | completed | 4 | True | 160.8 |
| baselines/severe/C/control/seed_44 | completed | 4 | True | 160.8 |
| baselines/severe/D/control/seed_42 | completed | 4 | True | 160.2 |
| baselines/severe/D/control/seed_43 | completed | 4 | True | 160.8 |
| baselines/severe/D/control/seed_44 | completed | 4 | True | 161.1 |

Full per-case data are under each test folder. `run/traces.zip` preserves the large raw traces losslessly.
`metrics.csv` is for future figures; unsuccessful completion times are blank rather than fabricated successes.
Role/memory benefits cannot be inferred from replay. See individual validation files for whether a path was exercised.
