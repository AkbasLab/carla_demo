# Experiment B: live CARLA–AirSim pedestrian tracking

Script: `scripts/run_experiment_b_tracking.py`. Run from the repository root with CARLA and AirSim running.

```bash
python scripts/run_experiment_b_tracking.py --scenario rectangle --oba --output-dir results/experiment_b/rectangle_guarded
python scripts/run_experiment_b_tracking.py --scenario rectangle --output-dir results/experiment_b/rectangle_unguarded
python scripts/run_experiment_b_tracking.py --scenario zigzag --oba --output-dir results/experiment_b/zigzag_guarded
python scripts/run_experiment_b_tracking.py --scenario zigzag --output-dir results/experiment_b/zigzag_unguarded
```

Each run with telemetry outputs `telemetry.csv`, `summary.json`, and `tracking_metrics.png` (requires `matplotlib`). The plot includes XY trajectories, tracking error with RMSE/P95, horizontal pedestrian–drone separation with RMS, and actual/commanded altitude with the ceiling. Partial runs are labeled; plots are saved before simulator cleanup. A blocked loop must return or be interrupted before these outputs are written. Plot failures do not prevent simulator cleanup.

The default horizontal follow distance is **1 m** (previously 2 m); override with `--follow-distance`. Default target height is now -25 m relative to the AirSim origin (AirSim NED Z = +25 m). This changes the desired offset, not a guaranteed physical clearance.

Tracking RMSE is `sqrt(mean((drone_x-target_x)^2 + (drone_y-target_y)^2))`. Lower values mean better tracking. RMS pedestrian–drone XY separation is `sqrt(mean((drone_x-ped_x)^2 + (drone_y-ped_y)^2))`. It measures typical horizontal separation, emphasizes larger distances, and is not tracking error: ideal following at 2 m has tracking RMSE 0 m and RMS separation 2 m. Both use the mapped coordinates described below.

The script connects to CARLA at localhost:2000 and AirSim's default MultirotorClient, spawns a pedestrian relative to the CARLA spectator, enables CARLA synchronous 20-Hz stepping, and restores the original world settings on exit.

**Interpretation:** Tracking target error is the horizontal distance between actual drone XY and desired offset-follow XY, not drone-to-pedestrian distance. Pedestrian-to-drone XY separation is reported separately. A tracking run is complete if the requested ticks execute; this is not a mission success criterion. The altitude guardian only clamps the target Z when `--oba` is supplied; at default target height 3 m and ceiling 30 m it will not intervene. Therefore guarded/unguarded trajectories should be similar and the experiment **cannot demonstrate obstacle avoidance or generalized OBA efficacy** without further constraints. Altitude violations are sampled from drone telemetry. Guardian timing is a minimal local altitude clamp and not the existing Phase 6 full guardian.

**Limitations:** The CARLA-to-AirSim mapping assumes axes are aligned, using initial positions and displacement only. It does not estimate a frame rotation, so verify alignment before publishing results. CARLA synchronous ticks are not synchronized with AirSim time; 400 ticks represent 20 s of CARLA simulation time, not necessarily 20 s of real flight. No tracking-lag estimate or obstacle-clearance metric is computed. The script does not enforce deterministic simulator reset or seeded repeated trials. Avoid interpreting horizontal pedestrian-to-drone separation as collision clearance because vertical separation is ignored. Review telemetry before making claims.

For publication, run repeated trials with controlled start state, add independent boundary constraints that can actually activate, and independently validate physical collisions and coordinate alignment.

## Setup and measurement phases

Takeoff and positioning now run with CARLA asynchronous stepping, before measurement. The pedestrian remains uncontrolled/stationary during setup. The drone must reach the initial mapped follow position and commanded altitude, within 0.3 m in 3D with speed at most 0.3 m/s, continuously for 1 s. Failure to settle aborts the tracking phase rather than scoring startup motion. Configure `--setup-timeout`, `--start-tolerance`, and `--settle-seconds` as needed. AirSim RPCs use `--rpc-timeout` (15 s by default); an RPC in progress can extend a polling deadline by its timeout. Setup does not validate physical coordinate registration or ground clearance.

Defaults are now `--follow-distance 1 --drone-speed 4 --command-interval 0.1`. The pedestrian speed remains 1.4 m/s. CARLA tracking ticks are paced against wall time at 20 Hz; overloaded ticks are not skipped, and this does not synchronize AirSim physics. Telemetry adds `wall_elapsed_s` and `airsim_elapsed_s`; compare them with `carla_sim_time_s` before interpreting results. Summary records setup completion/duration and controller settings. Landing uses asynchronous CARLA stepping, then restores the original world settings.

The original coordinate mapping remains fixed during prepositioning. Horizontal distances are still mapped estimates, not validated physical separation. Rectangle heading changes still cause discontinuous target offsets; reducing the offset reduces these jumps but does not remove them. Compare repeated runs under the same timing, initial state, speed, and distance settings; changing defaults changes the benchmark conditions.

## Continuous path-following target (v3)

Default `--follow-mode path` places the desired drone XY position 1 m behind along the mapped pedestrian's traveled polyline, interpolated between samples. An initial virtual straight segment defines the offset before the pedestrian has traveled that distance. This removes the artificial target teleport at each heading change. At corners the Euclidean XY separation can be less than the requested path distance. Use `--follow-mode heading` to reproduce the old reference definition. The reference definition changes the benchmark; compare runs with the same mode, and keep all measured samples.

Outputs identify `script_version`, a source SHA-256, setup completion, and follow mode. The provisional acceptance settings are `--acceptance-rmse 1 --acceptance-p95 2` (meters); these are configurable engineering goals, not a validated standard. `tracking_criteria_passed` requires a complete run, successful setup, and both limits. It does not certify physical safety, timing alignment, or OBA efficacy. The altitude plot labels the ceiling without forcing the vertical scale to 30 m, making tracking-height changes easier to inspect. Metrics remain computed from unfiltered telemetry.

## Height gate at -25 m (v4)

`--target-height` is a signed height relative to the AirSim origin, matching the plotted `-drone_z` value. The default is now **-25 m**, corresponding to **+25 m AirSim NED Z**. For a plotted starting height of -28 m this requests a 3 m upward change, rather than a climb to +3 m. This is not height above terrain; verify the origin and scene before flight. To command NED Z=-25 m instead, use `--target-height 25`.

The existing setup gate checks the full 3D starting position (including the commanded height) within `--start-tolerance` (0.3 m), with low speed for `--settle-seconds` (1 s), before starting pedestrian movement or collecting samples. Default 400 tracking ticks then measure 20 s of CARLA time, excluding takeoff and settling. Summary adds `measurement_start_height_m` and the height convention. Console and plots identify `experiment-b-height-minus25-v4`. The altitude-only guardian still limits heights above its positive ceiling; it has no terrain or lower-bound check.
