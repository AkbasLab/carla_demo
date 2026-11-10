# Phase 17 mechanism diagnostics

Secondary diagnostic measurements; original evidence and primary metrics are unchanged. Missing measurements remain null.

| Case | Unique waypoints | Progress reports | Local lease expirations | Claims | Releases | Health transitions | Policy errors | Policy fallbacks |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| C_n4_severe_control_s20 | 16 | 16 | 1 | 5 | 0 | 420 | 17 | 5 |
| C_n4_severe_loss_s20 | 14 | 21 | 3 | 15 | 10 | 331 | 189 | 72 |

Release counts are local events. Controller observations of the same releases are recorded separately in JSON, not double-counted.
See each JSON file for per-task versions, censored acceptance-to-arrival intervals, inference latency, guardian counts and source artifacts.

## Guardian and inference diagnostics

| Case | Guardian evaluations | Rejected evaluations | Corrective interventions | LLM calls | Mean LLM latency (s) | P95 LLM latency (s) | Failed response records |
|---|---:|---:|---:|---:|---:|---:|---:|
| C_n4_severe_control_s20 | 339 | 80 | 80 | 0 | unavailable | unavailable | 0 |
| C_n4_severe_loss_s20 | 613 | 315 | 316 | 0 | unavailable | unavailable | 0 |

## Replacement acceptance to productive arrival

| Case | Task | Acceptance timestamp (s) | First productive arrival (s) | Interval (s) | Arrival censored |
|---|---|---:|---:|---:|---|
| C_n4_severe_loss_s20 | SEARCH_SECTOR_A | 95.20008391299052 | 134.00008928001625 | 38.80000536702573 | False |

A missing arrival is censored, not a zero-second recovery. No rows means no affected failure task was identified.

## Task lifecycle

| Case | Task | Claims | Claimed versions | Releases | Unique waypoint arrivals |
|---|---|---:|---|---:|---:|
| C_n4_severe_control_s20 | SEARCH_SECTOR_A | 1 | 1 | 0 | 4 |
| C_n4_severe_control_s20 | SEARCH_SECTOR_B | 1 | 1 | 0 | 4 |
| C_n4_severe_control_s20 | SEARCH_SECTOR_C | 1 | 1 | 0 | 4 |
| C_n4_severe_control_s20 | SEARCH_SECTOR_D | 2 | 1, 2 | 0 | 4 |
| C_n4_severe_loss_s20 | SEARCH_SECTOR_A | 2 | 1, 2 | 0 | 4 |
| C_n4_severe_loss_s20 | SEARCH_SECTOR_B | 1 | 1 | 0 | 4 |
| C_n4_severe_loss_s20 | SEARCH_SECTOR_C | 11 | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 | 10 | 2 |
| C_n4_severe_loss_s20 | SEARCH_SECTOR_D | 1 | 1 | 0 | 4 |

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

- `C_n4_severe_control_s20`: `/opt/carla_demo/results/phase17/severe_recovery_v4_verified/severe_C_n4_s20/runs/C_n4_severe_control_s20`; missing artifacts: []; evidence issues: [].
- `C_n4_severe_loss_s20`: `/opt/carla_demo/results/phase17/severe_recovery_v4_verified/severe_C_n4_s20/runs/C_n4_severe_loss_s20`; missing artifacts: []; evidence issues: [].
