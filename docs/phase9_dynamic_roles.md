# Phase 9: dynamic roles and failure recovery (mock baseline)

The supplied definition is **Phase 9**. Phase 10's degraded-communication simulator remains separate. This baseline extends Phase 8 allocation with local dynamic roles and staged health beliefs, without an LLM or live flight.

## Roles and local decisions

The example team objective is four search tasks. Initial functional roles are Drone1/Drone2 SCOUT, Drone3 RELAY, and Drone4 RESERVE. Those initial roles are mission configuration, not per-task assignments. Subsequent role changes and task claims are autonomous, using only own state and messages delivered by the Phase 7 endpoint.

- SCOUT bids on search/inspection tasks.
- RELAY holds a configured mock relay point and does not bid on search work.
- RESERVE does not bid until activation. It becomes a scout after an unreachable scout, a low-battery scout, or a delivered high-priority target discovery when another healthy relay is available.
- A lost or low-battery relay triggers deterministic replacement. Eligible existing relay is preferred; otherwise reserve, then scout, with distance to relay point and lexical vehicle ID as tie-breaks. An active scout can release work and become relay if no viable reserve exists.
- Own low battery (<25%) causes reserve status, release of owned tasks, and withdrawal of incompatible outstanding bids. This is simulated task/role behavior, not return-to-home or landing.

Agents broadcast STATUS_UPDATE and ROLE_CHANGE. High-priority discovery uses TARGET_FOUND carrying a new inspection task, not a centrally assigned vehicle. A role change does not bypass task capability checks, ownership versions, or leases. Task allocation still uses Phase 8 TASK_ANNOUNCEMENT/BID/AWARD/ACCEPT/RELEASE/COMPLETE plus INTENT_UPDATE progress.

Relay positioning is mock kinematics. The runner does **not** model RF connectivity or prove that a new relay restores reachability. A real topology-aware policy, relay routing, hysteresis under partitions, and live flight integration remain work for later validation.

## Health states

`PeerHealth` supports HEALTHY, SUSPECTED, UNREACHABLE, FAILED, and RECOVERED.

- No heartbeat for 1 s: SUSPECTED.
- No heartbeat for 3 s: UNREACHABLE.
- Silence alone never means confirmed FAILED.
- FAILED requires a `MISSION_UPDATE` confirmed-failure report from an explicitly configured trusted supervisor. The example runner sends no such notification.
- A heartbeat after unreachable/failed status enters RECOVERED. Sustained fresh heartbeats permit HEALTHY after a 1 s dwell.

Health recovery does not authorize a restarted agent to execute old task versions. Automatic vehicle rejoin, snapshot synchronization, and partition fencing are not implemented; the runner deliberately keeps the stopped agent stopped. Do not treat the health state machine as a complete rejoin protocol.

Owned task leases still expire when progress stops; a new version is auctioned and responsive agents rebid. The failed-agent injection changes only which simulated agent loop runs; peers are not given the harness's failed-agent list. Reassignment is decided locally, not by the experiment logger.

If fewer than three peers/self remain responsive, the local objective changes conservatively to CRITICAL_ONLY: low-priority owned tasks are released and future bids prioritize critical work. This is a transparent reduced-team heuristic, not a proof that full completion is mathematically impossible or a general capacity optimizer. Full mission completion remains false if low-priority tasks are deferred. The CLI currently injects one stopped agent; the reduced-team rule has unit-level tests.

## Run

Scout failure and reserve activation:

```bash
python -u scripts/run_phase9_roles.py \
  --fail-agent Drone1 --fail-at 2 \
  --output-dir results/phase9/scout_loss
```

Relay failure and replacement:

```bash
python -u scripts/run_phase9_roles.py \
  --fail-agent Drone3 --fail-at 2 \
  --output-dir results/phase9/relay_loss
```

Battery-driven release and replacement:

```bash
python -u scripts/run_phase9_roles.py \
  --fail-agent none --low-battery-agent Drone1 --low-battery-at 2 \
  --output-dir results/phase9/low_battery
```

High-priority target discovery at 5 seconds:

```bash
python -u scripts/run_phase9_roles.py \
  --fail-agent none --critical-task --target-at 5 \
  --output-dir results/phase9/target_discovery
```

These runs are deterministic mocks with fixed simulation time, no intentional message degradation, and no flight. They write `messages.json`, `events.json`, `beliefs.json`, and `summary.json`. Beliefs include roles, battery, locally received peer status, staged peer health, objective, and private task ledger. Events distinguish role change, health transition, bid withdrawal, lease expiry, and work completion. Summary evaluates final mission outcome across surviving agents; this evaluator does not participate in assignment.

The normal failure case demonstrates reserve-to-scout activation and successful mocked reassignment, while relay loss demonstrates reserve-to-relay election. Task work, battery injection, and relay positions are simulated; neither live radio performance nor physical mission safety is established. Phase 9's full live four-drone exit criterion remains unverified.

## Tests

```bash
python -m unittest discover -s tests -p 'test_phase9_roles.py' -v
```

Coverage includes staged silence detection, short-gap recovery without failure declaration, authenticated confirmed-failure evidence, RECOVERED state, reserve activation, scout-to-relay conversion, low-battery release, target discovery, and reduced-team reprioritization.
