# Experiment B: live CARLA–AirSim pedestrian tracking

Script: `scripts/run_experiment_b_tracking.py`. Run from the repository root with CARLA and AirSim running.

```bash
python scripts/run_experiment_b_tracking.py --scenario rectangle --oba --output-dir results/experiment_b/rectangle_guarded
python scripts/run_experiment_b_tracking.py --scenario rectangle --output-dir results/experiment_b/rectangle_unguarded
python scripts/run_experiment_b_tracking.py --scenario zigzag --oba --output-dir results/experiment_b/zigzag_guarded
python scripts/run_experiment_b_tracking.py --scenario zigzag --output-dir results/experiment_b/zigzag_unguarded
```

Each run outputs `telemetry.csv` and `summary.json`. The script connects to CARLA at localhost:2000 and AirSim's default MultirotorClient, spawns a pedestrian relative to the CARLA spectator, enables CARLA synchronous 20-Hz stepping, and restores the original world settings on exit.

**Interpretation:** Tracking target error is the horizontal distance between actual drone XY and desired offset-follow XY, not drone-to-pedestrian distance. Pedestrian-to-drone XY separation is reported separately. A tracking run is complete if the requested ticks execute; this is not a mission success criterion. The altitude guardian only clamps the target Z when `--oba` is supplied; at default target height 3 m and ceiling 30 m it will not intervene. Therefore guarded/unguarded trajectories should be similar and the experiment **cannot demonstrate obstacle avoidance or generalized OBA efficacy** without further constraints. Altitude violations are sampled from drone telemetry. Guardian timing is a minimal local altitude clamp and not the existing Phase 6 full guardian.

**Limitations:** The CARLA-to-AirSim mapping assumes axes are aligned, using initial positions and displacement only. It does not estimate a frame rotation, so verify alignment before publishing results. CARLA synchronous ticks are not synchronized with AirSim time; 400 ticks represent 20 s of CARLA simulation time, not necessarily 20 s of real flight. No tracking-lag estimate or obstacle-clearance metric is computed. The script does not enforce deterministic simulator reset or seeded repeated trials. Avoid interpreting horizontal pedestrian-to-drone separation as collision clearance because vertical separation is ignored. Review telemetry before making claims.

For publication, run repeated trials with controlled start state, add independent boundary constraints that can actually activate, and independently validate physical collisions and coordinate alignment.
