# Phase 17 resilience V2 — small recovery diagnostics

V2 investigates the recovery failures in [the original pilot report](phase17_results.md). The original `pinned_run1` and its 32 unfinished missions remain unchanged. V2 is opt-in through **`scripts/run_phase17_resilience_v2.py`**; the old pilot configuration does not enable its behavior.

## Changes and scientific scope

1. **Task-policy failure is separated from physical telemetry.** A small independent service publishes only its own vehicle's position, velocity, battery and source timestamp. It continues if the high-level task-policy process stops. It uses the **same degraded message bus**, with the same packet loss, delays, TTL and bandwidth rules. It sends STATUS_UPDATE, never task-progress messages, acceptance acknowledgments or replacement heartbeats. Survivors must still infer policy unreachability from missing HEARTBEAT messages and wait for lease expiration. They learn physical position only from delivered telemetry.
2. **Full silence remains a negative control.** `--telemetry silent` stops telemetry along with the policy, retaining the original stale-peer uncertainty. A silent vehicle is never deleted from the guardian. Complete radio/vehicle failure is not reclassified as a safe, absent peer.
3. **Route calculations use the command granularity actually executed.** The earlier cost calculation could reject an entire multi-waypoint route because its total duration exceeded the 30-second per-command limit. V2 checks static geometry and deadlines per waypoint leg, plus the whole-route battery budget. Every runtime segment still goes through the unchanged bounded-reachability guardian, including peer uncertainty and separation checks. It does not assume that all future segments are safe.
4. **Persistent blocking has bounded ownership and logging.** Repeated identical blocked approaches are logged at bounded intervals. After 15 seconds of continuous blockage, the agent attempts confirmed cancellation, releases/reannounces its task, and waits through a rebid cooldown. When its safety context is currently unverifiable, it does not repeatedly ask the LLM to propose the same unsafe motion. Protocol and telemetry processing continue. This may still result in a safely incomplete mission; another feasible bidder is not guaranteed.
5. **Fault timing is explicitly changed and recorded.** The default `owned_motion` trigger waits until Drone1 owns a task, has an active MOVE command and nonzero measured velocity, and has displaced at least 0.6 m from its starting point. Five seconds is the earliest eligible trigger time, not the actual fault time. The actual onset can differ across architectures. This is a declared new scenario, **not** the old fixed-73-second experiment. `--fault-trigger fixed_time` is available for a separately configured fixed-time test.
6. **Less protocol waiting, same task routes and safety bounds.** The auction window is 6 seconds instead of 30, the task lease is 75 instead of 180 seconds, and the mission budget is 240 instead of 600 seconds. The same four rectangular routes and guardian geometry are used. The shared-server inference timeout remains 30 seconds and runtime speed remains bounded as before; no safety-distance or altitude limits are relaxed.

The telemetry-alive scenario is a **policy-process outage**, not a total radio outage. It assumes the separate vehicle telemetry service survives that fault. It does not use perfect telemetry: delayed, dropped and expired messages remain unavailable, timestamps are not freshened on receipt, and stale observations still block unsafe motion. There is no new sensor giving agents access to the scenario's ground truth or other agents' private memory.

The initial motion-triggered failure occurs on ingress, before the failed drone normally reaches its first search waypoint. This isolates the recovery chain while avoiding an initial test where the stopped vehicle occupies a required search waypoint. Success here does not establish recovery from every in-sector failure. A later, more demanding fault family must be separately declared and validated. This diagnostic cannot silently replace the original scenario or satisfy the final Phase 18 common-fault-time design.

## Small stages and storage target

Each invocation uses **one development seed, one team size, and one communication condition**.

| Stage | Cases | Policy source | Purpose |
| --- | ---: | --- | --- |
| `smoke` | 2 | C deterministic; no Ollama required | Nominal control plus one policy-stop recovery |
| `focused` | 4 | C deterministic, D pinned Ollama by default | Nominal matched control/fault pair for each architecture |
| `severe` | 4 | C deterministic, D pinned Ollama by default | Severe matched control/fault pair, after nominal inspection |

No command launches all 48 cases. Four cases are 1/12 of the old batch, and the horizon is 40% as long. Completed cases are additionally compressed losslessly. The desired storage ceiling is **well below 250 MB per diagnostic batch**, versus approximately 2.48 GB for the original pilot. A 200 MiB guard stops the batch before beginning another case when the directory has reached that size. This is not a hard live-write limit: one pathological case could exceed it, and its evidence will be preserved rather than deleted.

Packing happens **after** metrics evaluation and timeline plotting. ZIP member hashes and the complete archive hash are recorded; byte-for-byte round trips are verified before raw copies are removed. The metric evaluator is then rerun, and its result must match exactly. Prompts, complete model requests, raw outputs, corrections, guardian audits and failed outcomes are retained inside the archives. This reduces storage without downsampling runtime safety checks or omitting negative results.

The default config is `configs/phase17/resilience_v2.json`. Seeds 7–9 are development candidates; each invocation runs only its selected seed. The old pilot seeds 41–43 and held-out seeds 101–120 are protected from accidental use. The template reserves twenty held-out seeds for a future prospective design; this does not itself create an accepted calibration lock or establish sufficient replications.

## Commands

Run from the repository root, using a fresh output folder for every invocation. Do not change source/configuration files while a batch is running.

First run the two deterministic smoke cases:

```bash
python -u scripts/run_phase17_resilience_v2.py run \
  --stage smoke --team-size 4 --seed 7 \
  --output-dir results/phase17/v2_smoke_local1
```

Inspect `analysis/REPORT.md`, `analysis/overview.png` and the two individual timeline plots. A passing fault case must show an observed fault during owned movement, replacement acceptance, productive resumption and verified mission completion. A released or expired lease alone is not enough.

Then, with the pinned Ollama model running, execute only four nominal cases:

```bash
python -u scripts/run_phase17_resilience_v2.py run \
  --stage focused --profile pinned --team-size 4 --seed 7 \
  --output-dir results/phase17/v2_nominal_pinned_local1
```

The config uses `phase12-agent:pinned` and digest `46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e`, temperature zero, and one shared inference slot. A model identity/preflight failure is saved and stops execution; replay is not silently substituted. At the maximum horizon, four cases need approximately **16 minutes**, plus setup/analysis. Successful cases can finish earlier.

Only after inspecting nominal recovery, run four severe cases with another development seed:

```bash
python -u scripts/run_phase17_resilience_v2.py run \
  --stage severe --profile pinned --team-size 4 --seed 8 \
  --output-dir results/phase17/v2_severe_pinned_local1
```

Later repeat a small stage for two drones or another development seed by changing `--team-size 2` or `--seed 9` and the output folder. Do not infer final calibration from one successful four-run set.

To inspect the full-silence contrast without Ollama:

```bash
python -u scripts/run_phase17_resilience_v2.py run \
  --stage smoke --telemetry silent --team-size 4 --seed 7 \
  --output-dir results/phase17/v2_silence_local1
```

For software validation of the severe transport without actual inference:

```bash
python -u scripts/run_phase17_resilience_v2.py run \
  --stage severe --profile replay --team-size 4 --seed 8 \
  --output-dir results/phase17/v2_severe_replay_local1
```

Replay is explicitly labeled and cannot establish an LLM advantage or real-model recovery.

## Evidence and restoration

Top-level `v2_manifest.json` records the stage, profile, fault trigger, telemetry assumptions, source provenance, sizes and per-run outcomes. `diagnostic_checks_passed` reports this small mechanism check; **`eligible_for_final_freeze` remains false** because this runner does not replace full final calibration.

Each case retains its Phase 14 manifest, configuration snapshot, summary, waypoint arrivals, protocol/scenario events, metric record and nine-panel timeline. Most raw events are packed into:

```text
runs/<case>/traces.zip                 # unified events.jsonl
runs/<case>/run/traces.zip             # flight/messages/guardian/actions and agent JSONL
runs/<case>/evidence_archives.json     # archive and original member hashes
```

Phase 15 evaluation reads these archives directly. Older plotting/auditing commands that expect plain files need restoration first:

```bash
python scripts/run_phase17_resilience_v2.py restore \
  --run-dir results/phase17/v2_nominal_pinned_local1/runs/D_n4_nominal_loss_s7
```

Restoration verifies hashes and retains the archives. It refuses to overwrite a different existing file. Restoring increases storage; do it only for cases being inspected. `--no-compress` is available when debugging, but is not recommended for routine pinned batches.

## Verification and limits

```bash
python -m unittest discover -s tests -p 'test_phase17_resilience_v2.py' -v
```

The deterministic offline checks demonstrate the mechanism under the new assumptions; pinned Ollama testing must still be performed on the model host. The guardian remains fail-closed when usable peer observations are absent. There is no live CARLA-Air execution or collision-sensor evidence in these tests, and no claim that the original 24 failed cases have been repaired retroactively.

Any accepted final configuration must be calibrated again, with its source version, fault semantics, telemetry architecture and seed pools recorded. Existing source-hash locks become stale after these implementation changes; do not bypass that protection.

The final offline verification passed 269 tests. Detailed validation findings and generated experiment artifacts are retained locally; they are not included with this implementation-only publication.
