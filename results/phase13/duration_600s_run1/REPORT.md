# Phase 13 duration follow-up

All architectures and planned cases are rerun at each common budget; the original pilot is preserved.
Completion is measured from the existing guarded mission criterion, never inferred from elapsed time.

| Budget (s) | Finished tests | Successful missions | Incomplete missions | Runtime errors |
|---|---:|---:|---:|---:|
| 600 | 40 | 15 | 25 | 0 |

New independent runs at each budget, not continuation or identical LLM-output replays
Budget changes horizon-dependent leases/TTL/context; this is budget sensitivity, not pure CPU timing
B has no task reassignment; a permanently lost worker can leave its fixed task incomplete
More time cannot guarantee resolution of safety or protocol stalls; no safety rules are relaxed

duration_metrics.json includes guard reason counts, arrival times and observed failure flags.
Cross-budget completion differences are descriptive; use repeated seeds before statistical claims.
