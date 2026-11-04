# Phase 12: bidding deadlines and blocked-task recovery

## Observed failure

The real Ollama `easy_run3` completed A, B and C through three LLM search authorizations (six observed arrivals), without duplicate completion. Sector D remained unfinished. Its auction opened at 90.8 s and closed around 120.8 s. Drone4 waited 22.2 s for admission, started inference at 113.0 s and returned its bid at 122.8 s, too late. Drone1 claimed D instead, then encountered repeated separation rejections as other drones occupied their final positions. The run logged 14 policy errors for separation, seven motion fallbacks and no D arrivals. These are mock-flight observations, not physical collisions.

## Implemented changes

### 1. Deadline-aware bidding

Each agent estimates required response time as its shared-server admission-delay estimate plus its recent inference-time estimate plus a configurable response margin. The admission service exposes scheduling metadata only; it does not choose task winners or read peer beliefs. Initial estimates use the configured inference timeout; later estimates adapt to locally observed latency, bounded by that timeout.

Before an open auction closes, an idle eligible scout submits a **deterministically calculated bid** if the remaining window is insufficient for that response budget. Fresh local/peer state, route feasibility, battery, capabilities, task epoch and the current deadline still constrain the bid. The score and vehicle-ID tie breaker are unchanged. This is a bid-protection guard, not invented LLM output or guaranteed server throughput. It may submit early when initial estimates are conservative. Agents never extend an already closed auction to accept a late result.

Explicitly declined epochs are not automatically rebid. The same agent can reevaluate a new task version. Submitted bids are idempotent, and the existing ownership/epoch checks continue to reject stale responses.

`deadline_bid_submitted` logs deadline, remaining time, admission estimate, inference estimate and `source: deterministic_deadline_guard`. `deadline_bids_by_agent` reports the count independently of accepted LLM decisions and motion fallbacks. Therefore, zero `fallbacks_by_agent` does not imply zero deterministic assistance.

### 2. Fresh approach checks

The next approach is evaluated with current own telemetry and delivered peer beliefs when building the decision context, immediately before search/waypoint authorization, and before an idle executor resumes a segment. Actual dispatch still passes through the independent guardian, including concurrent-command checks. An earlier feasible bid cannot authorize a later unsafe approach.

The context includes `approach_validation` with task/version, target, timestamp, feasibility and reasons. Known blocked approaches do not offer `start_search` or `go_to_waypoint` in the next tool schema. `approach_revalidated` and `approach_blocked` preserve the evidence separately from the guardian dispatch audit. A rejected preview does not count as an executed action or productive policy decision.

### 3. Bounded blocked-task recovery

Repeated identical rejection sets are counted per task, version and waypoint index. The default `--safety-rejection-limit 2` bounds repeated attempts. A compliant policy can release the task after the first rejection. If it continues to fail, deterministic recovery cancels any active own command, requires cancellation acknowledgment, releases the task and reannounces it with an incremented version. If cancellation is unconfirmed, the assignment is retained and the deferred release is logged.

The former owner waits one bid window before rebidding, and fresh feasibility checks must still pass. Peers learn of the release and new epoch only through delivered protocol messages. Existing completed-waypoint checkpoints survive a handoff. Rejections never create artificial progress or authorize bypassing the guardian. This implementation chooses release/reauction; it does not add an unvalidated detour planner.

`blocked_task_released` distinguishes LLM/replay releases from `deterministic_safety_recovery`; `blocked_task_releases_by_agent` summarizes releases. Successful motion authorization clears the relevant rejection history.

### 4. Recovery-specific correction

For a blocked owned route, the example is now `release_task` with `SAFETY_ROUTE_BLOCKED`, rather than the previously rejected search command. The correction explicitly says not to repeat that search or waypoint request. Unknown/stale telemetry instead produces a HOLD example. The prompt exposes current approach reasons, valid task versions and remaining bid time. All five structured decision fields and strict tool validation remain required.

## Validation

The repository suite passes 139 tests, including 49 Phase 12 tests. Thirteen new regressions cover deadline budgets, stale/closed auctions, explicit declines, queue hints, changed peer geometry, recovery-specific examples, repeated/stubborn proposals, cancellation acknowledgment and peer takeover through delivered messages.

A complete four-drone **replay fixture** also simulates one inference slot and nine-second responses, with 30-second auctions and 180-second leases. It completes all four routes in 167.6 simulated seconds, with one productive fixture authorization per drone, no duplicates and no motion fallbacks. Deadline-protected bid counts are 3, 3, 2, 2. All dispatches are guarded. Both LLM and live exit flags remain false because this is synthetic replay timing, not an Ollama or AirSim measurement. The compact summary and fixture manifest are in `results/phase12/recovery_validation`; raw formal runs must retain their complete traces.

```bash
python -m unittest discover -s tests -p 'test_phase12*.py' -v
```

## Next real-model run

Use the same model, seed, mission and timings as `easy_run3`, with a new output directory. The new safeguards default on for Ollama. This is a hybrid allocation/policy experiment: deterministic deadline bids must be reported as support, while useful LLM search authorizations remain separately measured.

```bash
python -u scripts/run_phase12_agents.py \
  --backend mock --provider ollama \
  --model phase12-agent:pinned \
  --model-digest 46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e \
  --seed 42 --ticks 1500 --dt 0.2 \
  --inference-timeout 30 --max-context-age 35 \
  --inference-parallelism 1 --progress-timeout 60 \
  --lease-seconds 180 --bid-window 30 \
  --bid-response-margin 1 --safety-rejection-limit 2 \
  --output-dir results/phase12/easy_run4
```

Check task completion, productive LLM decisions for every drone, duplicate completions, guardian coverage, deadline-bid counts, safety releases and all policy errors. Preserve all request, response, telemetry, protocol and guardian logs. Do not infer real-model success from the replay regression; the new Ollama test is still required, followed by separately validated live-flight testing for the literal flight exit criterion.
