# Phase 17 V2: matched A/B/C/D development batches

`run_phase17_resilience_v2.py` now accepts `--architectures A B C D`. Each selected architecture contributes a control and an injected policy-failure case. The previous defaults remain C/D for focused/severe and C for smoke, so existing four-case commands do not silently double their cost.

## Architectural differences are preserved

| Architecture | Policy and ownership | After a teammate policy stops |
|---|---|---|
| A | Central fleet controller assigns tasks from delivered state/progress; vehicles execute deterministic rules | Controller can reassign expired work to a policy with a recent heartbeat |
| B | Persistent high-level LLM policies execute their prebriefed tasks; no peer auctions or reassignment | Failed peer's unfinished tasks remain unfinished by design |
| C | Delivered-message decentralized task allocation and deterministic policy | Surviving policies rebid after lease expiry |
| D | Same decentralized task protocol, with persistent LLM decisions | Surviving policies rebid and select structured actions |

The same V2 own-vehicle telemetry service, guarded short-segment execution, alternative-approach helper, survey geometry, task routes, duration and fault predicate are available in all four. For A, telemetry is also delivered to the fleet controller through the same degraded network. That controller recipient adds legitimate centralized communication overhead; it is not a private global-state read.

Vehicle telemetry can survive a policy failure, but policy HEARTBEAT cannot. A's controller now tracks these separately. A physical STATUS_UPDATE never makes an inactive policy eligible for assignment. The controller receives progress/completion through messages and waits for task lease expiry; it does not receive the injected-fault oracle.

A/B retain their fixed/local tool restrictions. In particular, B cannot announce, bid for, claim or inherit another drone's task. Completion of a B fault mission is not a required readiness check when the stopped agent has unfinished work.

## Severe-run crash correction

The `KeyError: 'SEARCH_SECTOR_A'` was caused by a cleared rejection-cache entry. Successful authorization removed `blocked_approaches[task_id]`, but a subsequent rejection within V2's log-throttling interval did not rebuild it. The parent execution path then indexed the absent entry.

V2 now always rebuilds missing or mismatched rejection bookkeeping, independently of logging throttling, and preserves the continuous-blockage timestamp. A focused regression reproduces clearing/rejection within the throttle interval. Severe C control integrations for both team sizes complete without a runtime error in mock/replay verification. This does not establish actual-model severe performance or mission success in every condition.

## Update and verify

```bash
cd /opt/carla_demo
git pull --ff-only
python -m unittest discover -s tests -p test_phase17_recovery_regressions.py -v
python -m unittest discover -s tests -p test_phase17_all_architectures.py -v
```

CARLA-Air is unnecessary. Pinned B/D require the configured Ollama model and exact digest. The config retains the 240-second horizon, 75-second lease, six-second bid window and 30-second inference deadline. Do not change these while comparing the four architectures.

An optional deterministic first check runs only A/C, with two cases each:

```bash
python -u scripts/run_phase17_resilience_v2.py run \
  --config configs/phase17/resilience_v2.json \
  --stage smoke --profile replay --architectures A C \
  --team-size 2 --seed 11 --telemetry alive --fault-trigger owned_motion \
  --output-dir results/phase17/all_architecture_run1/smoke_AC_n2_s11
```

Smoke rejects B/D so replay is never presented as agentic inference in that stage. Focused/severe may use replay for software verification, but the manifest explicitly records it; it is not LLM evidence.

## Your run_check function

Add the explicit architecture selection to the same function. Invoke it from the repository root in the terminal where the function is defined:

```bash
run_check() {
  python -u scripts/run_phase17_resilience_v2.py run \
    --config configs/phase17/resilience_v2.json \
    --stage "$1" \
    --profile pinned \
    --architectures A B C D \
    --team-size "$2" \
    --seed "$3" \
    --telemetry alive \
    --fault-trigger owned_motion \
    --output-dir "results/phase17/all_architecture_run1/${1}_n${2}_s${3}"
}
```

Each command now produces **eight cases**, not four, and has a maximum mission budget of **32 minutes plus warmup/analysis** if all eight reach the horizon. Successful cases may finish earlier. ZIP retention and the per-invocation storage budget remain enabled. All output folders below are prospective new folders, not claimed results.

Run one command and inspect it before continuing:

| Step | Command | Factor changed |
|---|---|---|
| 1 | `run_check focused 2 11` | New implementation reference, all architectures |
| 2 | `run_check focused 2 12` | Development seed |
| 3 | `run_check focused 4 12` | Team size |
| 4 | `run_check severe 4 12` | Network profile |
| 5, later | `run_check severe 2 12` | Team size |
| 6, later | `run_check severe 2 11` | Seed |
| 7, later | `run_check severe 4 11` | Team size |
| 8, later | `run_check focused 4 11` | Network profile |

Do not turn this table into an unattended loop while debugging. For smaller subsets, replace the architecture selection, for example `--architectures A B` (four cases) or `--architectures C` (two cases). Store subsets in distinct output roots to avoid confusing them with an eight-case batch.

Read the first result with:

```bash
cat results/phase17/all_architecture_run1/focused_n2_s11/analysis/REPORT.md
```

Inspect `v2_manifest.json`, `analysis/metrics.json`, per-run summaries and archived decision/protocol traces too. In particular:

- `all_runs_technically_valid` means all selected diagnostic runs finished without recorded runtime or metric-evidence errors. It is not the full Phase 18 decision/provenance exclusion audit.
- `all_missions_complete` is a separate outcome, and may legitimately be false.
- `diagnostic_checks_passed` retains the older all-mission/recovery-success meaning. It will generally be false when B's fault case has uncompleted prebriefed work. Do not classify that as a technical error or rerun it for a better outcome.
- `llm_calls` and productive LLM counters must demonstrate B/D participation; replay or fallback-only completion is insufficient to establish functioning agentic execution.
- A's recovery is controller-mediated, C/D recovery is decentralized, and B's lack of reassignment is intentional. Report these mechanisms separately.

The movement-conditioned fault can occur at different mission times and physical locations across architectures. A can move farther before the five-second eligibility floor than a slower architecture; a stopped vehicle may obstruct a required waypoint. That remains a valid incomplete outcome in this declared diagnostic, not a reason to remove the vehicle from the guardian. Calibrate exposure before using this scenario for final comparisons.

These batches are development evidence. New source hashes invalidate any old lock; no Phase 17 eligibility or Phase 18 replication gate is bypassed.

## Verification scope

Tests cover architecture selection and pairs, equivalent inputs, fixed B ownership/no negotiation, A controller reassignment without a fault oracle, surviving telemetry, policy heartbeat eligibility, the rejection-cache regression, and both severe C team sizes. They use temporary mock/replay fixtures, not a live model server or CARLA-Air. No new pinned experimental outcomes are claimed by the implementation.
