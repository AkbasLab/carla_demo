# Phase 17 mechanism diagnostics

Secondary diagnostic measurements; original evidence and primary metrics are unchanged. Missing measurements remain null.

| Case | Unique waypoints | Progress reports | Local lease expirations | Claims | Releases | Health transitions | Policy errors | Policy fallbacks |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| C_n2_severe_control_s20 | 16 | 17 | 0 | 5 | 1 | 79 | 5 | 1 |
| C_n2_severe_loss_s20 | 16 | 18 | 1 | 5 | 0 | 9 | 0 | 0 |
| D_n2_severe_control_s20 | 16 | 22 | 1 | 5 | 0 | 122 | 3 | 0 |
| D_n2_severe_loss_s20 | 8 | 13 | 1 | 4 | 0 | 15 | 1 | 0 |

Release counts are local events. Controller observations of the same releases are recorded separately in JSON, not double-counted.
See each JSON file for per-task versions, censored acceptance-to-arrival intervals, inference latency, guardian counts and source artifacts.

## Guardian and inference diagnostics

| Case | Guardian evaluations | Rejected evaluations | Corrective interventions | LLM calls | Mean LLM latency (s) | P95 LLM latency (s) | Failed response records |
|---|---:|---:|---:|---:|---:|---:|---:|
| C_n2_severe_control_s20 | 194 | 22 | 22 | 0 | unavailable | unavailable | 0 |
| C_n2_severe_loss_s20 | 151 | 9 | 11 | 0 | unavailable | unavailable | 0 |
| D_n2_severe_control_s20 | 150 | 0 | 0 | 16 | 8.873 | 10.353 | 0 |
| D_n2_severe_loss_s20 | 105 | 3 | 3 | 13 | 10.097 | 12.279 | 0 |

## Replacement acceptance to productive arrival

| Case | Task | Acceptance timestamp (s) | First productive arrival (s) | Interval (s) | Arrival censored |
|---|---|---:|---:|---:|---|
| C_n2_severe_loss_s20 | SEARCH_SECTOR_A | 112.40004499000497 | 154.00006118201418 | 41.60001619200921 | False |
| D_n2_severe_loss_s20 | SEARCH_SECTOR_A | 114.80008774599992 | unavailable | unavailable | True |

A missing arrival is censored, not a zero-second recovery. No rows means no affected failure task was identified.

## Task lifecycle

| Case | Task | Claims | Claimed versions | Releases | Unique waypoint arrivals |
|---|---|---:|---|---:|---:|
| C_n2_severe_control_s20 | SEARCH_SECTOR_A | 1 | 1 | 0 | 4 |
| C_n2_severe_control_s20 | SEARCH_SECTOR_B | 1 | 1 | 0 | 4 |
| C_n2_severe_control_s20 | SEARCH_SECTOR_C | 2 | 1, 2 | 1 | 4 |
| C_n2_severe_control_s20 | SEARCH_SECTOR_D | 1 | 1 | 0 | 4 |
| C_n2_severe_loss_s20 | SEARCH_SECTOR_A | 2 | 1, 2 | 0 | 4 |
| C_n2_severe_loss_s20 | SEARCH_SECTOR_B | 1 | 1 | 0 | 4 |
| C_n2_severe_loss_s20 | SEARCH_SECTOR_C | 1 | 1 | 0 | 4 |
| C_n2_severe_loss_s20 | SEARCH_SECTOR_D | 1 | 1 | 0 | 4 |
| D_n2_severe_control_s20 | SEARCH_SECTOR_A | 2 | 1, 2 | 0 | 4 |
| D_n2_severe_control_s20 | SEARCH_SECTOR_B | 1 | 1 | 0 | 4 |
| D_n2_severe_control_s20 | SEARCH_SECTOR_C | 1 | 1 | 0 | 4 |
| D_n2_severe_control_s20 | SEARCH_SECTOR_D | 1 | 1 | 0 | 4 |
| D_n2_severe_loss_s20 | SEARCH_SECTOR_A | 2 | 1, 2 | 0 | 0 |
| D_n2_severe_loss_s20 | SEARCH_SECTOR_B | 1 | 1 | 0 | 4 |
| D_n2_severe_loss_s20 | SEARCH_SECTOR_C | 1 | 1 | 0 | 4 |
| D_n2_severe_loss_s20 | SEARCH_SECTOR_D | 0 |  | 0 | 0 |

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

- `C_n2_severe_control_s20`: `/opt/carla_demo/results/phase17/severe_recovery_v3/cd_n2_s20/runs/C_n2_severe_control_s20`; missing artifacts: []; evidence issues: [].
- `C_n2_severe_loss_s20`: `/opt/carla_demo/results/phase17/severe_recovery_v3/cd_n2_s20/runs/C_n2_severe_loss_s20`; missing artifacts: []; evidence issues: [].
- `D_n2_severe_control_s20`: `/opt/carla_demo/results/phase17/severe_recovery_v3/cd_n2_s20/runs/D_n2_severe_control_s20`; missing artifacts: []; evidence issues: [].
- `D_n2_severe_loss_s20`: `/opt/carla_demo/results/phase17/severe_recovery_v3/cd_n2_s20/runs/D_n2_severe_loss_s20`; missing artifacts: []; evidence issues: [].
