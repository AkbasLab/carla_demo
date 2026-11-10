# Phase 17 mechanism diagnostics

Secondary diagnostic measurements; original evidence and primary metrics are unchanged. Missing measurements remain null.

| Case | Unique waypoints | Progress reports | Local lease expirations | Claims | Releases | Health transitions | Policy errors | Policy fallbacks |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| C_n4_severe_control_s15 | 16 | 18 | 0 | 4 | 0 | 222 | 10 | 3 |
| C_n4_severe_loss_s15 | 16 | 17 | 1 | 6 | 0 | 241 | 14 | 7 |
| D_n4_severe_control_s15 | 16 | 18 | 1 | 5 | 0 | 314 | 0 | 0 |
| D_n4_severe_loss_s15 | 9 | 19 | 2 | 6 | 0 | 267 | 2 | 0 |

Release counts are local events. Controller observations of the same releases are recorded separately in JSON, not double-counted.
See each JSON file for per-task versions, censored acceptance-to-arrival intervals, inference latency, guardian counts and source artifacts.

## Guardian and inference diagnostics

| Case | Guardian evaluations | Rejected evaluations | Corrective interventions | LLM calls | Mean LLM latency (s) | P95 LLM latency (s) | Failed response records |
|---|---:|---:|---:|---:|---:|---:|---:|
| C_n4_severe_control_s15 | 275 | 47 | 47 | 0 | unavailable | unavailable | 0 |
| C_n4_severe_loss_s15 | 338 | 72 | 76 | 0 | unavailable | unavailable | 0 |
| D_n4_severe_control_s15 | 111 | 4 | 4 | 12 | 11.434 | 20.889 | 0 |
| D_n4_severe_loss_s15 | 162 | 5 | 5 | 23 | 10.225 | 13.002 | 0 |

## Replacement acceptance to productive arrival

| Case | Task | Acceptance timestamp (s) | First productive arrival (s) | Interval (s) | Arrival censored |
|---|---|---:|---:|---:|---|
| C_n4_severe_loss_s15 | SEARCH_SECTOR_A | 88.20020839298377 | 115.40022455897997 | 27.200016165996203 | False |
| D_n4_severe_loss_s15 | SEARCH_SECTOR_A | 90.60022553498857 | 174.40023645598558 | 83.80001092099701 | False |

A missing arrival is censored, not a zero-second recovery. No rows means no affected failure task was identified.

## Task lifecycle

| Case | Task | Claims | Claimed versions | Releases | Unique waypoint arrivals |
|---|---|---:|---|---:|---:|
| C_n4_severe_control_s15 | SEARCH_SECTOR_A | 1 | 1 | 0 | 4 |
| C_n4_severe_control_s15 | SEARCH_SECTOR_B | 1 | 1 | 0 | 4 |
| C_n4_severe_control_s15 | SEARCH_SECTOR_C | 1 | 1 | 0 | 4 |
| C_n4_severe_control_s15 | SEARCH_SECTOR_D | 1 | 1 | 0 | 4 |
| C_n4_severe_loss_s15 | SEARCH_SECTOR_A | 3 | 1, 2 | 0 | 4 |
| C_n4_severe_loss_s15 | SEARCH_SECTOR_B | 1 | 1 | 0 | 4 |
| C_n4_severe_loss_s15 | SEARCH_SECTOR_C | 1 | 1 | 0 | 4 |
| C_n4_severe_loss_s15 | SEARCH_SECTOR_D | 1 | 1 | 0 | 4 |
| D_n4_severe_control_s15 | SEARCH_SECTOR_A | 2 | 1, 2 | 0 | 4 |
| D_n4_severe_control_s15 | SEARCH_SECTOR_B | 1 | 1 | 0 | 4 |
| D_n4_severe_control_s15 | SEARCH_SECTOR_C | 1 | 1 | 0 | 4 |
| D_n4_severe_control_s15 | SEARCH_SECTOR_D | 1 | 1 | 0 | 4 |
| D_n4_severe_loss_s15 | SEARCH_SECTOR_A | 2 | 1, 2 | 0 | 1 |
| D_n4_severe_loss_s15 | SEARCH_SECTOR_B | 1 | 1 | 0 | 4 |
| D_n4_severe_loss_s15 | SEARCH_SECTOR_C | 2 | 1, 2 | 0 | 0 |
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

- `C_n4_severe_control_s15`: `/opt/carla_demo/results/phase17/severe_recovery_v4_verified/severe_C_D_n2_s15/runs/C_n4_severe_control_s15`; missing artifacts: []; evidence issues: [].
- `C_n4_severe_loss_s15`: `/opt/carla_demo/results/phase17/severe_recovery_v4_verified/severe_C_D_n2_s15/runs/C_n4_severe_loss_s15`; missing artifacts: []; evidence issues: [].
- `D_n4_severe_control_s15`: `/opt/carla_demo/results/phase17/severe_recovery_v4_verified/severe_C_D_n2_s15/runs/D_n4_severe_control_s15`; missing artifacts: []; evidence issues: [].
- `D_n4_severe_loss_s15`: `/opt/carla_demo/results/phase17/severe_recovery_v4_verified/severe_C_D_n2_s15/runs/D_n4_severe_loss_s15`; missing artifacts: []; evidence issues: [].
