# Phase 17 mechanism diagnostics

Secondary diagnostic measurements; original evidence and primary metrics are unchanged. Missing measurements remain null.

| Case | Unique waypoints | Progress reports | Local lease expirations | Claims | Releases | Health transitions | Policy errors | Policy fallbacks |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| D_n4_severe_control_s15 | 8 | 18 | 7 | 8 | 0 | 626 | 7 | 2 |
| D_n4_severe_loss_s15 | 9 | 18 | 3 | 7 | 0 | 324 | 3 | 0 |

Release counts are local events. Controller observations of the same releases are recorded separately in JSON, not double-counted.
See each JSON file for per-task versions, censored acceptance-to-arrival intervals, inference latency, guardian counts and source artifacts.

## Guardian and inference diagnostics

| Case | Guardian evaluations | Rejected evaluations | Corrective interventions | LLM calls | Mean LLM latency (s) | P95 LLM latency (s) | Failed response records |
|---|---:|---:|---:|---:|---:|---:|---:|
| D_n4_severe_control_s15 | 87 | 5 | 5 | 20 | 12.05 | 16.731 | 0 |
| D_n4_severe_loss_s15 | 155 | 7 | 9 | 23 | 10.578 | 12.873 | 0 |

## Replacement acceptance to productive arrival

| Case | Task | Acceptance timestamp (s) | First productive arrival (s) | Interval (s) | Arrival censored |
|---|---|---:|---:|---:|---|
| D_n4_severe_loss_s15 | SEARCH_SECTOR_A | 87.80009750497993 | unavailable | unavailable | True |

A missing arrival is censored, not a zero-second recovery. No rows means no affected failure task was identified.

## Task lifecycle

| Case | Task | Claims | Claimed versions | Releases | Unique waypoint arrivals |
|---|---|---:|---|---:|---:|
| D_n4_severe_control_s15 | SEARCH_SECTOR_A | 1 | 1 | 0 | 4 |
| D_n4_severe_control_s15 | SEARCH_SECTOR_B | 2 | 1, 2 | 0 | 4 |
| D_n4_severe_control_s15 | SEARCH_SECTOR_C | 3 | 1, 2, 3 | 0 | 0 |
| D_n4_severe_control_s15 | SEARCH_SECTOR_D | 2 | 1, 2 | 0 | 0 |
| D_n4_severe_loss_s15 | SEARCH_SECTOR_A | 3 | 1, 2 | 0 | 0 |
| D_n4_severe_loss_s15 | SEARCH_SECTOR_B | 1 | 1 | 0 | 4 |
| D_n4_severe_loss_s15 | SEARCH_SECTOR_C | 2 | 1, 2 | 0 | 1 |
| D_n4_severe_loss_s15 | SEARCH_SECTOR_D | 1 | 1 | 0 | 4 |

## Evidence sources

| Measurement | Logical source artifacts (also read from ZIP archives) |
|---|---|
| Required waypoint work | `run/waypoint_arrivals.json`, `run/manifest.json` |
| Progress, claims, releases and leases | `run/protocol_events.json`, `run/controller_events.json` |
| Acceptance-to-arrival interval | `events.jsonl`, `run/waypoint_arrivals.json`, `run/manifest.json` |
| Health, approach changes, policy errors/fallbacks | `run/<agent>/decision_history.jsonl` |
| Inference | `run/<agent>/responses.jsonl`, registered call counts from `events.jsonl` |
| Guardian | `run/guardian_audit.json` and registered primary safety metrics |

LLM latency summarizes reported response records, including failures with a recorded latency; it is unavailable for replay/deterministic policies.

- `D_n4_severe_control_s15`: `/opt/carla_demo/results/phase17/severe_recovery_v4_verified/severe_D_n4_s15/runs/D_n4_severe_control_s15`; missing artifacts: []; evidence issues: [].
- `D_n4_severe_loss_s15`: `/opt/carla_demo/results/phase17/severe_recovery_v4_verified/severe_D_n4_s15/runs/D_n4_severe_loss_s15`; missing artifacts: []; evidence issues: [].
