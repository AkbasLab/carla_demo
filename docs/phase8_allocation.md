# Phase 8: deterministic decentralized task allocation

This implements the contract-net baseline over the Phase 7 endpoint API, without an LLM or central assignment. The first validation backend is **mock**. It does not yet satisfy the live four-drone sector-coverage exit criterion.

## Task model and mission

`agentic_uav/coordination/contract_net.py` defines `MissionTask`, `TaskType`, `TaskStatus`, and `Geometry`. Tasks contain all plan fields: ID, type, location/region, priority, capabilities, deadline, status, assigned agent, and lease expiry. Version and mock work units are explicit additional fields. Supported categories are search sector, maintain relay, inspect target, and return to base. The runner supplies a shared team mission of four search sectors A–D, with no assignments. Each agent receives its own copy of that mission and maintains its own task ledger; the harness never chooses task winners.

Geometry currently models a center and radius. Mock work completion accumulates effort and moves the local mock position to the task center. It does not simulate travel time, coverage, target sensing, relay effectiveness, or flight dynamics. Deadline is an admission cutoff for bidding, not a flight scheduler guarantee. The example runs four search tasks; other task types have representation and cost support but no separate execution skills yet.

## Contract net

1. Agents announce the highest-priority available task (ID breaks equal priorities).
2. Idle capable agents exchange deterministic cost bids.
3. After a fixed bidding window the lowest score, then lexical vehicle ID, wins.
4. The winner publishes TASK_AWARD; peers publish TASK_ACCEPT acknowledgments.
5. Work begins only after the current claim has settled and all currently responsive peers acknowledge it.
6. The owner sends progress via INTENT_UPDATE with `intent=task_progress`. Phase 7 has no TASK_PROGRESS enum.
7. Progress renews a lease; missing progress expires it and triggers a higher-version auction.
8. Explicit voluntary release also triggers reannouncement. Losing simultaneous claimants publish TASK_RELEASE.
9. TASK_COMPLETE closes the current owned task on each receiving peer's local ledger.

Inbox consumption is staged before agent decisions in the synchronous mock runner, preventing Python iteration order from selecting winners. Claims are ordered by version (highest), score (lowest), and vehicle ID (lexically lowest). A claim must match a received bid for that owner and version. Old-version, non-owner, or expired-lease progress cannot renew an assignment. The same restrictions apply to completion. Corrections, releases, bids with cost components, renewals, and completions are logged.

The transparent cost is:

```text
1 * distance_m + 5 * (1 - battery_percent/100)
+ 20 * owned_task_count + 5 * communication_risk + 100 * role_mismatch
```

Default mock agents start with full battery and zero communication risk. Missing required capabilities makes an agent ineligible; a capable agent in a nonmatching role receives the role penalty. Busy agents wait until idle before bidding; the workload term remains explicit for extensions. Position, battery, workload, risk, and role are local inputs, not ground-truth reads of other agents. Bid scoring is trusted deterministic behavior, not protection from dishonest peers.

## Run

Normal mission, including an intentionally simultaneous claim race:

```bash
python -u scripts/run_phase8_allocation.py \
  --output-dir results/phase8/normal
```

Stop Drone1's agent loop at 1.5 s to test lease recovery:

```bash
python -u scripts/run_phase8_allocation.py \
  --fail-agent Drone1 --fail-at 1.5 \
  --output-dir results/phase8/silent_drone1
```

Use `--no-conflict-injection` for ordinary best-bid-only claims. By default the first eligible auction forces multiple deterministic self-claims before resolution, so conflicts are actually exercised rather than merely declared supported. No agent is told another has failed: a silent agent stops heartbeats and progress, and peers infer suspicion from heartbeat age. After the heartbeat timeout, it no longer blocks acknowledgment quorum. Network-partition consensus and returning/rejoining failed agents are **not** implemented; these require membership/fencing policies before degraded-network use.

Outputs:

- `tasks.json`: initial shared mission, not an authoritative assignment ledger.
- `beliefs.json`: per-agent task ledgers/positions at each simulated step.
- `messages.json`: Phase 7 recipient-level delivery records and decision-use flags.
- `events.json`: cost bids, claim corrections/releases, progress/renewals, lease expiry, and completion.
- `summary.json`: mission completion across active agents, per-agent completions, duplicate completions, conflict corrections, and lease expirations.

`lease_expirations` counts unique task/version expirations; `local_lease_expiration_events` counts observations across replicas. `conflict_corrections` counts local corrections, not unique global conflicts. Mission completion in a failure test is evaluated across surviving agents; stopped agents retain stale private ledgers. This is a centralized experiment evaluator, not centralized allocation.

## Validation and limits

```bash
python -m unittest discover -s tests -p 'test_phase8_allocation.py' -v
```

Tests cover task serialization, transparent costs/capability exclusion, deterministic claim order, stale/non-owner progress rejection, lease expiry, voluntary release, normal four-agent division, simultaneous claims without duplicate completion, and reassignment following a silent owner. UUID-free Phase 8 message IDs and fixed simulation timing make runs reproducible. These checks establish a mock baseline only. Live sector execution, partition/rejoin behavior, sophisticated geometry, and research-scale repeated trials remain future work.
