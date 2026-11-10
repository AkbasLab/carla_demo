# Phase 17 mechanism diagnostics

Secondary diagnostic measurements; original evidence and primary metrics are unchanged. Missing measurements remain null.

| Case | Unique waypoints | Progress reports | Local lease expirations | Claims | Releases | Health transitions | Policy errors | Policy fallbacks |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| D_n2_severe_control_s10 | 15 | 20 | 0 | 4 | 0 | 134 | 0 | 0 |
| D_n2_severe_loss_s10 | 8 | 14 | 1 | 4 | 0 | 15 | 2 | 0 |

Release counts are local events. Controller observations of the same releases are recorded separately in JSON, not double-counted.
See each JSON file for per-task versions, censored acceptance-to-arrival intervals, inference latency, guardian counts and source artifacts.

## Guardian and inference diagnostics

| Case | Guardian evaluations | Rejected evaluations | Corrective interventions | LLM calls | Mean LLM latency (s) | P95 LLM latency (s) | Failed response records |
|---|---:|---:|---:|---:|---:|---:|---:|
| D_n2_severe_control_s10 | 162 | 4 | 4 | 18 | 10.0 | 13.791 | 0 |
| D_n2_severe_loss_s10 | 94 | 1 | 1 | 14 | 9.571 | 11.14 | 0 |

## Replacement acceptance to productive arrival

| Case | Task | Acceptance timestamp (s) | First productive arrival (s) | Interval (s) | Arrival censored |
|---|---|---:|---:|---:|---|
| D_n2_severe_loss_s10 | SEARCH_SECTOR_A | 130.60008946200833 | unavailable | unavailable | True |

A missing arrival is censored, not a zero-second recovery. No rows means no affected failure task was identified.

## Task lifecycle

| Case | Task | Claims | Claimed versions | Releases | Unique waypoint arrivals |
|---|---|---:|---|---:|---:|
| D_n2_severe_control_s10 | SEARCH_SECTOR_A | 1 | 1 | 0 | 4 |
| D_n2_severe_control_s10 | SEARCH_SECTOR_B | 1 | 1 | 0 | 4 |
| D_n2_severe_control_s10 | SEARCH_SECTOR_C | 1 | 1 | 0 | 4 |
| D_n2_severe_control_s10 | SEARCH_SECTOR_D | 1 | 1 | 0 | 3 |
| D_n2_severe_loss_s10 | SEARCH_SECTOR_A | 2 | 1, 2 | 0 | 0 |
| D_n2_severe_loss_s10 | SEARCH_SECTOR_B | 1 | 1 | 0 | 4 |
| D_n2_severe_loss_s10 | SEARCH_SECTOR_C | 1 | 1 | 0 | 4 |
| D_n2_severe_loss_s10 | SEARCH_SECTOR_D | 0 |  | 0 | 0 |

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

- `D_n2_severe_control_s10`: `/opt/carla_demo/results/phase17/severe_recovery_v4_verified/severe_D_n2_s10/runs/D_n2_severe_control_s10`; missing artifacts: []; evidence issues: [].
- `D_n2_severe_loss_s10`: `/opt/carla_demo/results/phase17/severe_recovery_v4_verified/severe_D_n2_s10/runs/D_n2_severe_loss_s10`; missing artifacts: []; evidence issues: [].
