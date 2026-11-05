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

## Live CARLAAir backend

The runner now accepts `--backend airsim`. Four configured AirSim vehicles execute observed ordered waypoint routes after distributed allocation. No LLM is used. This extends the mock baseline; real flight still requires validation on your scene.

1. Start with all four drones landed at separated, clear spawn positions.
2. Copy `configs/phase8/carlaair.example.json` to `configs/phase8/carlaair.local.json` and calibrate it before running.
3. Set each vehicle's `frame_offset_m` so **shared mission NED position = AirSim API position + offset**. If API telemetry already uses the common mission frame, use `[0,0,0]` for all vehicles. If it is vehicle-local, use the independently established spawn-frame translation. Offsets are not inferred from other agents or assumed from vehicle names; frame rotations are not supported. Verify axes are aligned.
4. Inspect every waypoint route, transit path, and takeoff/landing corridor in the actual scene. Example Z=+25 assumes a suitable common NED reference, matching the earlier -25 m plotted-height setup; do not apply it blindly to another origin.

The example defines four separated, short ordered routes. These are waypoint-search demonstrations, not evidence of area coverage, target detection, or collision avoidance. Shared tasks describe routes and priorities; the mission does not preassign vehicles. Each agent computes bids from its own transformed telemetry and private ledger. The harness reads telemetry for execution/logging, never to supply global task assignments or peer task beliefs.

Normal live run, allowing up to 240 seconds of measurement:

```bash
python -u scripts/run_phase8_allocation.py \
  --backend airsim --mission-config configs/phase8/carlaair.local.json \
  --carla-host localhost --ticks 2400 --dt 0.1 \
  --flight-height 3 --speed 1 --lease-seconds 10 --bid-window 1 \
  --output-dir results/phase8/live_normal
```

For a silent agent during execution, add `--fail-agent Drone1 --fail-at 8` and use a fresh output directory. Verify that time is during an active task using the console/command log. The simulator harness commands the failed vehicle to hover before stopping its allocation/heartbeat/progress loop. Surviving peers receive no explicit failure notification: they infer suspicion and lease expiry from missing messages. The failed vehicle's physical hover is an experimental intervention, not onboard recovery under total RPC failure. Cross-sector takeover routes must also be clear.

An executor starts only when the locally owned version has settled and responsive peers acknowledge the claim. Every task/version change cancels the old movement before a new one is issued. Progress renewal requires a verified waypoint arrival or a reduction in distance to the pending waypoint; elapsed time or motion away from the target cannot complete the task. A stalled agent can lose its lease even while heartbeats continue. TASK_COMPLETE requires observations of all ordered waypoints, including any verified prefix from prior owners. Live arrival checks use independent horizontal `--arrival-tolerance` and vertical `--altitude-tolerance` limits. Reassigned tasks now resume from a verified ordered waypoint prefix received in valid owner progress messages; unknown/unreported progress is conservatively repeated.

Console messages show task/version, waypoint index, movement, holds, and injected failures. `waypoint_arrivals.json` records observed arrival positions/times; `commands.json`, `events.json`, `beliefs.json`, `messages.json`, and `summary.json` capture execution and allocation. Mission completion requires complete task ledgers at all surviving agents; it is separate from cleanup landing. Cleanup polls for landed state with `--landing-confirm-timeout` before disarming, otherwise retaining API control and recording a warning. CARLA asynchronous settings are restored afterward.

The live path has automated mocked-API checks for observed completion, stale-owner stopping, stalled-vehicle behavior, and silent-agent takeover. Passing those tests does not replace a real CARLAAir run. There is no OBA/geofence or live obstacle-avoidance integration in this Phase 8 runner, and no partition/rejoin fencing. Do not report its waypoint completion as full sector coverage without a separately specified coverage metric.

## Larger movements and team overview

`--route-scale 3` multiplies each shared waypoint X and Y by three about the shared mission origin. Z and vehicle frame offsets are unchanged. This expands routes and their spacing; it changes mission distances and may require longer run/waypoint timeouts. The original JSON is not edited. Before takeoff, the runner prints every task's numbered XYZ targets, writes `effective_mission.json`, and generates `mission_routes.png` with labeled routes and four starting positions. The route map shows plans, not proof of obstacle clearance or execution.

To frame the entire mission rather than follow Drone1, use `--overview-camera --carla-frame-origin X Y Z` with `--carla-host`. This sets the **CARLA spectator** to a top-down view of the routes plus starting positions and draws colored waypoint/route labels in the world. `--camera-height 40` sets a minimum height above the routes; the actual height grows to frame wider missions. The previous spectator pose is restored during cleanup.

The transform is `CARLA = (origin_x + mission_x, origin_y + mission_y, origin_z - mission_z)`, assuming aligned horizontal axes. Supply a calibrated origin. For example, origin `0 0 28` is appropriate only if shared NED ground Z=28 maps to CARLA ground Z=0 and horizontal origins coincide. Do not use it blindly; the mission-to-vehicle frame offsets are a separate calibration. Camera rotation/frame yaw calibration is not implemented.

Example additions after calibration:

```text
--route-scale 3 --overview-camera --carla-frame-origin 0 0 28 --camera-height 40
```

The option controls CARLA's spectator actor, not AirSim's selected FPV/chase/onboard camera. If your CARLAAir viewport remains attached to Drone1, select its spectator/free-camera view to see this overview. Camera mode switching depends on the CARLAAir build; this script does not alter your AirSim settings. Larger routes still require scene inspection; there is no collision avoidance.

## Incomplete-recovery fix: separate tolerances, retries, checkpoints

Live arrival acceptance now defaults to XY error <=0.4 m **and** absolute NED Z error <=0.6 m. The old single 3D ball could reject a vehicle that reached XY but held an approximately 0.5 m altitude offset. Both errors and targets are logged in arrivals, commands, and waypoint-arrival events; accepting an arrival does not fix altitude control. Setup uses these same independent position tolerances plus its existing speed gate. Mock allocation behavior remains unchanged.

The executor tracks decreasing distance throughout a long leg, sending progress at most one third of a lease apart when actual approach occurred. A stationary vehicle does not receive unconditional lease renewals. After `--stall-timeout 4` seconds without sufficient distance improvement, it can reissue the current command up to `--max-waypoint-retries 2` times per waypoint/version. A retry remains fenced by valid ownership and does not itself count as progress. The live runner no longer inserts a hover between ordinary consecutive waypoints or a retry of the same valid task/version; it still cancels motion on release, revocation, or assignment changes.

Owner progress messages include the length of the verified ordered waypoint prefix. Receivers accept checkpoints only from the current owner, current version, and a live lease. Checkpoints never decrease; old-owner messages cannot advance them. On reassignment the executor resumes at the next unverified waypoint, instead of repeatedly restarting from WP1. This relies on trusted peers, static shared task routes, and reliable delivery; it is not protection against dishonest completion reports or network partition/rejoin.

Example recovery options:

```text
--arrival-tolerance 0.4 --altitude-tolerance 0.6
--lease-seconds 10 --stall-timeout 4 --max-waypoint-retries 2
--waypoint-timeout 180 --fail-agent Drone1 --fail-at 8
```

Use a new output directory; waypoint arrivals from a resumed version will intentionally omit the already verified prefix. Check `verified_checkpoints`, TASK_COMPLETE events, and mission-complete state rather than requiring a full duplicate waypoint sequence in each version. Summary records tolerances, retries, and checkpoints. Lease-expiration events include their prior deadline and checkpoint count.

Regression tests emulate a 30 m leg with 0.5 m vertical bias, a silent owner at 8 s followed by checkpoint takeover, stalled movement with bounded retries/lease expiry, and rejection of stale-owner checkpoints. They establish software behavior in controlled models, not resolution of scene collisions, frame errors, or live AirSim control issues. Repeat the normal and failure flights to verify end-to-end recovery.
