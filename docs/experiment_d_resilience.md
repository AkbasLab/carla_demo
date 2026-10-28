# Experiment D: communication resilience with OBA landing recovery

`scripts/run_experiment_d_resilience.py` now compares `--recovery none`, `hover`, and `oba-land` using the same bounded shuttle mission, heartbeat injection, and output schema. Start CARLA–AirSim and run from the repository root. No LLM is used. This is an application heartbeat fault, not an outage of AirSim RPC or actual RF.

## Calibrate the scene first

Copy `configs/experiments/d_resilience.example.json` to a local configuration and set:

- `flight_bounds`: inclusive XYZ limits in **AirSim NED**, not CARLA coordinates or `-Z` plotted height. Include the landing surface.
- `keepouts`: 3D boxes using the same `x_min`/`x_max`, `y_min`/`y_max`, `z_min`/`z_max` keys. Include obstacles and prohibited landing surfaces.
- `landing_site`: inspected-clear XY location, calibrated NED `ground_z`, and available `radius_m`. Set `surveyed_clear: true` only after verifying that surface and approach in the scene. The example deliberately leaves it false.
- `obstacle_margin_m`: geometric padding. The reserved landing corridor additionally includes the landing-site radius.

The example assumes local ground NED Z=+28 m. A 3 m cruise height above that ground commands Z=+25 m (plotted origin-relative height -25 m). This is an example assumption, not terrain sensing. Calibrate the drone's landed reference offset and use `--ground-tolerance` accordingly. A different site or origin requires different coordinates.

## Run

After saving a calibrated configuration at `configs/experiments/d_resilience.local.json`:

```bash
python -u scripts/run_experiment_d_resilience.py \
  --boundary-config configs/experiments/d_resilience.local.json \
  --recovery oba-land --loss 1 --inject-at 5 --timeout 2 \
  --duration 45 --cruise-height 3 --mission-distance 10 \
  --seed 42 --output-dir results/experiment_d/oba_land_loss100_seed42
```

Use the same parameters with `--recovery none` and `--recovery hover`, changing the output directory for each arm. Set `--loss 0` for a normal-communication control. For the loss sweep use 0, 0.1, 0.3, 0.5, 1 across repeated seeds. Mission length and recovery deadline must fit within the observation duration. Independent Bernoulli packet losses do not necessarily produce timeout-length outages; report actual timeout counts.

## Policy and integration

`agentic_uav/control/oba_recovery.py` extends OBA's deterministic boundary checks with exact **3D segment/AABB** intersection, configured flight limits, and a padded vertical descent corridor. It is a reusable recovery guardian, replacing neither the older Phase 6 midpoint heuristic nor Phase 7's RETURN_HOME/LAND policy globally. Experiment D explicitly invokes it before mission dispatch and during recovery.

The sequence is timeout → brake/hover → approve route → return to the configured landing site at current Z → approve descent corridor → command landing → observe stable touchdown. Recovered heartbeats do not resume the mission automatically. Blocked routes, boundary departures, recorded collisions, descent-corridor departures, and recovery deadlines lead to a latched hold/failure instead of an unchecked landing. This policy cannot guarantee a safe hold from an already unsafe state and does not plan detours.

CARLA runs asynchronously so takeoff and landing can advance without a Python tick deadlock. Output includes both simulator timestamps; clocks are not synchronized. The watchdog executes locally in the Python control client and survives injected heartbeat loss only; this does not demonstrate survival of client failure or RPC loss, or an onboard watchdog.

## Measurements and interpretation

`telemetry.csv` records states, speed, heartbeat delivery, heartbeat age, recovery phase, landing state, collision history, and independently evaluated sampled boundary violations. `summary.json` records configuration, code hash, events, detection latency from the start of the triggering loss streak, recovery duration, and observed success.

Landing success requires a landed-state indication, low speed, configured landing-site proximity and ground-Z tolerance continuously for `--stable-seconds`. Success is false if a collision or recovery-period boundary violation was observed. Hover success requires sustained low speed within boundaries on later samples, rather than counting an issued command as success. Neither criterion proves collision-free motion between samples. Normal flight can collide with unmapped obstacles; no live terrain perception or avoidance planner is present. Estimated states, map assumptions, and sensor reports require independent validation for publication.

The prior `altitude_violation_samples` using `0 <= -Z <= ceiling` is replaced by `boundary_violation_samples` against explicit NED limits. Results from the old origin-relative check are not directly comparable. Mission completion and false failsafe activation remain null until a mission success condition and expected-outage oracle are specified; completed legs and all timeout events are recorded instead. Aggregate recovery success rates across trials that actually triggered recovery, and report blocked, failed, and censored/incomplete recoveries separately.

Results are saved before cleanup. **Cleanup does not perform an unguarded landing or count as recovery.** On completed landing the vehicle is disarmed; otherwise it is commanded to hover and retains API control for operator inspection. Restoring CARLA's previous synchronous settings may pause physics until its original tick owner resumes. These are simulator experiments, not validated real-aircraft landing logic.

## Checks

```bash
python -m unittest discover -s tests -p 'test_experiment_d_recovery.py' -v
```

Tests cover geometry (including intersections missed by midpoint checks), descent clearance, invalid/unapproved sites, ground-coordinate offsets, loss-triggered landing, no-loss controls, disabled recovery, and collision blocking using simulated API responses. Live CARLA–AirSim flight validation is still required.
