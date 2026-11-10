# Phase 17 mechanism diagnostics

Secondary diagnostic measurements; original evidence and primary metrics are unchanged. Missing measurements remain null.

| Case | Unique waypoints | Progress reports | Local lease expirations | Claims | Releases | Health transitions | Policy errors | Policy fallbacks |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A_n4_severe_control_s8 | unavailable | unavailable | unavailable | unavailable | unavailable | unavailable | unavailable | unavailable |

Release counts are local events. Controller observations of the same releases are recorded separately in JSON, not double-counted.
See each JSON file for per-task versions, censored acceptance-to-arrival intervals, inference latency, guardian counts and source artifacts.

## Guardian and inference diagnostics

| Case | Guardian evaluations | Rejected evaluations | Corrective interventions | LLM calls | Mean LLM latency (s) | P95 LLM latency (s) | Failed response records |
|---|---:|---:|---:|---:|---:|---:|---:|
| A_n4_severe_control_s8 | unavailable | unavailable | unavailable | 0 | unavailable | unavailable | unavailable |

## Replacement acceptance to productive arrival

| Case | Task | Acceptance timestamp (s) | First productive arrival (s) | Interval (s) | Arrival censored |
|---|---|---:|---:|---:|---|

A missing arrival is censored, not a zero-second recovery. No rows means no affected failure task was identified.

## Task lifecycle

| Case | Task | Claims | Claimed versions | Releases | Unique waypoint arrivals |
|---|---|---:|---|---:|---:|
| A_n4_severe_control_s8 | SEARCH_SECTOR_A | unavailable | unavailable | unavailable | unavailable |
| A_n4_severe_control_s8 | SEARCH_SECTOR_B | unavailable | unavailable | unavailable | unavailable |
| A_n4_severe_control_s8 | SEARCH_SECTOR_C | unavailable | unavailable | unavailable | unavailable |
| A_n4_severe_control_s8 | SEARCH_SECTOR_D | unavailable | unavailable | unavailable | unavailable |

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

- `A_n4_severe_control_s8`: `/opt/carla_demo/results/phase17/severe_recovery_v4_verified/severe_C_n4_s8/runs/A_n4_severe_control_s8`; missing artifacts: ['summary.json', 'protocol_events.json', 'waypoint_arrivals.json', 'guardian_audit.json']; evidence issues: [].
