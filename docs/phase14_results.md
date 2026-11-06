# Phase 14 experiment results

## Assessment

The uploaded results satisfy Phase 14's experiment-runner and logging exit criterion for the mock backend. The review covered manifests, configuration snapshots, structured event logs, raw message records, guardian records, and saved LLM prompts and responses.

Reviewed result snapshot: [c81c90b3c736d340c126d6189761e8a3a32c9912](https://github.com/AkbasLab/carla_demo/commit/c81c90b3c736d340c126d6189761e8a3a32c9912).

## Requirements and evidence

| Requirement | Assessment |
|---|---|
| 14.1 One experiment configuration | Present: experiment ID, architecture, scenario, team size, seed, network and failure profiles, and planner. |
| 14.2 Complete run manifest | Present: Git SHA, configuration copies and hashes, model settings, software versions, timestamps, and completion/error information. Saved configuration hashes match their contents. |
| 14.3 Structured event logging | Verified across 37,918 JSONL event records. Manifest counts match the logs and the underlying message, skill, and guardian records. |
| 14.4 Preserve unsuccessful runs | Demonstrated by `failure_replay`, including its partial logs, fault event, manifest, and incomplete mission outcome. Actual crash capture was not exercised by these uploads. |
| Exit criterion: automatic batches with separate result directories | Both batches finished every configured run and produced a separate result directory per experiment. |

## Experiment outcomes

| Batch | Experiment | Mission outcome | Mission-clock duration | Event records |
|---|---|---|---:|---:|
| [offline_run1](../results/phase14/offline_run1) | nominal_rules | All four tasks completed | 10.6 simulated s | 2,006 |
| offline_run1 | moderate_centralized | All four tasks completed | 26.8 simulated s | 5,555 |
| offline_run1 | failure_replay | Incomplete; correctly preserved | 29.9 simulated s of a 30 s budget | 4,104 |
| [pinned_logging_run1](../results/phase14/pinned_logging_run1) | nominal_pinned_agent | All four tasks completed | 175.3 wall-clock mission s | 26,253 |

The offline batch reports three finished runs, two successful missions, and zero runtime errors. The pinned batch reports one finished run, one successful mission, and zero runtime errors.

For `failure_replay`, `run_completed=true` and `mission_complete=false` correctly distinguish a runner that finished normally from a mission that remained unfinished. The injected Drone1 failure is recorded, and no false mission-completion event appears.

## Pinned-model evidence

The pinned run records five actual LLM calls, five saved prompts and responses, and five matching usage records. All four distinct agent identities appear in the saved contexts.

- Model: `phase12-agent:pinned`
- Verified digest: `46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e`
- Temperature: 0; seed: 42
- Reported usage: 15,204 prompt tokens and 378 output tokens
- Mission result: all four tasks completed, with zero duplicate task completions

All 32 executed actions link to guardian decisions. Their skill lifecycle contains 31 observed completions and one confirmed cancellation. The 24 guardian modifications are bounded-motion-segment adjustments; they should not be interpreted as 24 unsafe proposals. This run records no guardian rejections.

The batch's approximately 189.2 seconds of elapsed time includes setup, model warmup, and output processing. The corresponding mission-completion observation is 175.3 seconds.

## Coverage limits

`ROLE_CHANGED` and `TARGET_FOUND` have zero occurrences in these batches. Their absence is reasonable for the selected scenarios, but these uploads do not validate those event paths. A role-changing mission and a controlled target-report scenario would provide that coverage.

No software crash occurred. The incomplete replay demonstrates preservation of unsuccessful missions; a deliberate configuration error or controlled runtime exception would provide additional evidence for crash/error preservation.

These results validate the automatic runner and logging for mock experiments. They do not establish live CARLA–AirSim performance or physical flight safety. The reviewed batches also lack Phase 15 metric-registration/evaluation outputs and should not be presented as predeclared Phase 15 evaluations.

Phase 14 can be treated as validated for this mock setup, with the additional event and crash cases remaining as coverage extensions.
