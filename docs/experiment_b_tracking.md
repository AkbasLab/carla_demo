# Experiment B: live CARLA–AirSim pedestrian tracking

Script: `scripts/run_experiment_b_tracking.py`. Run from the repository root with CARLA and AirSim running.

```bash
python scripts/run_experiment_b_tracking.py --scenario rectangle --oba --output-dir results/experiment_b/rectangle_guarded
python scripts/run_experiment_b_tracking.py --scenario rectangle --output-dir results/experiment_b/rectangle_unguarded
python scripts/run_experiment_b_tracking.py --scenario zigzag --oba --output-dir results/experiment_b/zigzag_guarded
python scripts/run_experiment_b_tracking.py --scenario zigzag --output-dir results/experiment_b/zigzag_unguarded
```

Each run with telemetry outputs `telemetry.csv`, `summary.json`, and `tracking_metrics.png` (requires `matplotlib`). The plot includes XY trajectories, tracking error with RMSE/P95, horizontal pedestrian–drone separation with RMS, and actual/commanded altitude with the ceiling. Partial runs are labeled; plots are saved before simulator cleanup. A blocked loop must return or be interrupted before these outputs are written. Plot failures do not prevent simulator cleanup.

The default horizontal follow distance is **2 m** (previously 3.5 m); override with `--follow-distance`. Target height remains 3 m in the AirSim frame. This changes the desired offset, not a guaranteed physical clearance.

Tracking RMSE is `sqrt(mean((drone_x-target_x)^2 + (drone_y-target_y)^2))`. Lower values mean better tracking. RMS pedestrian–drone XY separation is `sqrt(mean((drone_x-ped_x)^2 + (drone_y-ped_y)^2))`. It measures typical horizontal separation, emphasizes larger distances, and is not tracking error: ideal following at 2 m has tracking RMSE 0 m and RMS separation 2 m. Both use the mapped coordinates described below.

The script connects to CARLA at localhost:2000 and AirSim's default MultirotorClient, spawns a pedestrian relative to the CARLA spectator, enables CARLA synchronous 20-Hz stepping, and restores the original world settings on exit.

**Interpretation:** Tracking target error is the horizontal distance between actual drone XY and desired offset-follow XY, not drone-to-pedestrian distance. Pedestrian-to-drone XY separation is reported separately. A tracking run is complete if the requested ticks execute; this is not a mission success criterion. The altitude guardian only clamps the target Z when `--oba` is supplied; at default target height 3 m and ceiling 30 m it will not intervene. Therefore guarded/unguarded trajectories should be similar and the experiment **cannot demonstrate obstacle avoidance or generalized OBA efficacy** without further constraints. Altitude violations are sampled from drone telemetry. Guardian timing is a minimal local altitude clamp and not the existing Phase 6 full guardian.

**Limitations:** The CARLA-to-AirSim mapping assumes axes are aligned, using initial positions and displacement only. It does not estimate a frame rotation, so verify alignment before publishing results. CARLA synchronous ticks are not synchronized with AirSim time; 400 ticks represent 20 s of CARLA simulation time, not necessarily 20 s of real flight. No tracking-lag estimate or obstacle-clearance metric is computed. The script does not enforce deterministic simulator reset or seeded repeated trials. Avoid interpreting horizontal pedestrian-to-drone separation as collision clearance because vertical separation is ignored. Review telemetry before making claims.

For publication, run repeated trials with controlled start state, add independent boundary constraints that can actually activate, and independently validate physical collisions and coordinate alignment.
