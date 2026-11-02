# Phase 11: independent deterministic runtime-safety guardian

## Scope

`agentic_uav/control/runtime_guardian.py` implements an auditable action gate, independent of an LLM or allocation policy. `GuardedExecutor` evaluates every proposal before calling its wrapped executor. The initial runner uses synthetic commands and mock execution; it does **not** add a safety guarantee to existing live runners or run an LLM. A proposal's `source` records provenance and grants no privilege.

This phase validates the injection exit criterion in a controlled mock harness. Integration into Phase 8/9/10 execution and CARLA–AirSim, real perception, braking dynamics and aircraft battery models remain separate work. Existing experiment-specific OBA checks are retained, not silently replaced.

## Safety checks

| Requirement | Implemented check |
|---|---|
| Altitude bounds | Ground-relative height `ground_z - ned_z`; every route endpoint is checked. LAND can traverse below the flight floor only with a valid surveyed descent corridor. TAKEOFF can start at ground level. |
| Geofence | Finite 3D axis-aligned flight bounds; all endpoints inside imply the straight segment stays inside the convex box. |
| Restricted zones | Exact segment/slab intersection with padded keep-out boxes, including segments crossing a zone when their endpoints lie outside it. |
| Waypoint validity | Strict finite 3D points, supported action kind, correct vehicle, nonempty command ID, required/forbidden waypoint fields. |
| Maximum speed | A positive excessive speed is capped; the resulting action is fully checked again, including duration, energy and separation. Nonpositive/nonfinite speed is rejected. |
| Battery reserve | Configured abstract distance cost plus ordinary reserve; emergency fallbacks use a separately configured landing reserve. This is not a calibrated energy predictor. |
| Command timeout | Creation freshness, absolute command validity, predicted travel duration and a hard active-command duration. A tick-driven watchdog cancels before attempting a fresh fallback. |
| Known-drone separation | Closest approach between each own route segment and constant-velocity peer predictions, including crossing trajectories; additional state-age uncertainty margin. Missing expected peers or stale peer states cause rejection. |
| Landing location | Surveyed-clear configured site, horizontal site tolerance, ground direction, footprint/geofence and keep-out checks through descent. Configuration does not establish physical clearance. |
| Conflicting commands | One active command per vehicle, command-ID replay rejection, command-specific completion acknowledgment and confirmed cancellation before replacement. Concurrent accepted routes are also checked for time-overlapping separation conflicts, including reserved final positions. |

Own telemetry, peer beliefs, membership, communication state and confidence must come from the trusted runtime integration, not from action payloads. Agents cannot authorize themselves by inventing a favorable safety state. The mock runner supplies these inputs directly; production provenance/enforcement is not implemented here. Unknown or stale telemetry does not justify blindly assuming a hold is safe.

## Outcomes

- `APPROVE`: execute the validated proposal.
- `APPROVE_WITH_MODIFICATION`: execute a validated speed-limited copy; preserve the original proposal in the audit.
- `REJECT_AND_REPLAN`: execute no new action and report reasons. If no fallback can be verified, report `no_verified_safe_fallback` rather than dispatching an unchecked action.
- `EXECUTE_SAFE_FALLBACK`: dispatch a separately checked deterministic fallback.

An approval is a policy decision, not proof of completed execution. The audit records executor acknowledgment separately. An execution transport exception leaves the action possibly active and blocks concurrent dispatch; a failed cancellation does not authorize a second command. The gateway cannot physically stop a vehicle if the actuator/control channel is unavailable.

## Context-dependent fallback policy

| Context | Ordered candidates |
|---|---|
| Grounded | HOLD_POSITION; never implicitly take off |
| Critical battery | LAND_AT_SAFE_LOCATION, if already over the surveyed safe site |
| Outside altitude envelope | CLIMB_OR_DESCEND_TO_SAFE_LAYER by a checked vertical segment |
| Low reserve | RETURN_HOME to the airborne home/approach point |
| Degraded communication, sufficient confidence, still-fresh previously approved plan | CONTINUE_LAST_VALID_PLAN after revalidation; do not reset its TTL |
| Lost communication, low confidence, timeout, or remaining candidate | HOLD_POSITION, only if geometry and known-peer prediction permit it |

Candidates can fail. An invalid descent site is not replaced with arbitrary landing; return-home does not implicitly land. Insufficient confidence prevents moving fallbacks, while stale/missing peer beliefs reject all newly proposed execution. If the current position violates both geofence and altitude bounds, a vertical recovery is not allowed to bypass the geofence. Returning to a safe layer is a narrowly checked altitude recovery, not general escape-path planning.

Every fallback uses the same route, battery, deadline and separation checks as normal motion, with explicit emergency reserve and safe-layer-entry exceptions. These exceptions are recorded via the fallback identity and rejected-candidate reasons.

## Runtime integration contract

```python
config = Config(**json_config)
guardian = RuntimeGuardian(config)
gateway = GuardedExecutor(guardian, execute=adapter_execute, cancel=adapter_cancel)

# Trusted state builder supplies fresh own telemetry and local peer beliefs.
gateway.watchdog(state, simulation_time)  # Call on every control tick.
decision = gateway.dispatch(proposed_action, state, simulation_time)

# Only an actual executor acknowledgment may complete an asynchronous command.
gateway.confirm_completion(vehicle_id, command_id)
```

`adapter_execute(Action)` returns a dictionary with `executed`, `completed`, status and observed effects. An in-progress/possibly-active action stays registered. `adapter_cancel(vehicle_id)` must return literal `True` only after cancellation is confirmed. Do not route unguarded commands around the gateway. The current implementation is single-threaded; adapters must serialize tick/dispatch/completion calls. It is an API boundary, not a sandbox against malicious code with adapter access.

## Run and inspect

From the repository root:

```bash
python -u scripts/run_phase11_guardian.py \
  --config configs/phase11/guardian.example.json \
  --output-dir results/phase11/guardian_run1

python -m unittest discover -s tests -p 'test_phase11_guardian.py' -v
```

The example uses ground Z = 0 and negative airborne NED Z, independent of the earlier CARLAAir map's ground Z = 28. Do not copy its geometry or `surveyed_clear: true` into a live scene without calibration and site inspection.

Outputs:

- `guardian_audit.json`: proposed action, supplied local safety state, outcome, reasons, selected modification/fallback, rejected fallback candidates and executor-reported mission effect. Invalid/nonfinite proposals are retained as representations so the audit remains valid finite JSON.
- `mission_effects.json`: per-scenario executor effects and replan outcomes, including continuation and watchdog acknowledgments.
- `injection_cases.json`: labelled scenarios and decisions.
- `effective_config.json`: thresholds and geometry used.
- `summary.json`: unsafe proposal interception and outcome counts.

## Initial mock results

The example run in `results/phase11/guardian_baseline` injected **36 unsafe proposals** (rule-policy and synthetic LLM-labelled cases, continuation timeout and simultaneous-command cases). **Zero unsafe original proposals reached execution.** Valid controls, modified-speed controls and all five fallback kinds were exercised. The combined audit contains:

| Outcome | Count |
|---|---:|
| APPROVE | 6 |
| APPROVE_WITH_MODIFICATION | 2 |
| REJECT_AND_REPLAN | 19 |
| EXECUTE_SAFE_FALLBACK | 16 |

Counts include valid control actions and the separate asynchronous watchdog sequence; they are not a success-rate sample. The watchdog recorded one confirmed cancellation before fallback. Seventeen focused tests cover geometry, swept peer separation, invalid/stale inputs, landing corridors, battery/fallback refusal, plan TTL preservation, concurrency, replay, lost communication, failed cancellation, unconfirmed executor results and active-command hard timeout.

The full repository regression suite passed **90 tests**, including the 17 Phase 11 checks.

## Limits of the claim

The exit criterion is demonstrated **for injected actions routed through this mock gateway**. Source labels do not imply LLM inference. Peer motion is extrapolated at constant velocity; future turns, unobserved drones, perception errors, vehicle acceleration and stopping distance are not modeled. Minimum separation is not a formal multi-vehicle collision-avoidance guarantee. A surveyed static site is an assumption, not terrain sensing. Battery accounting is abstract and return-home is not guaranteed to preserve real flight energy. No full search mission, live landing, or real-world safety certification is established by these tests.
