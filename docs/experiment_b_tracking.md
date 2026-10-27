# Experiment B: tracking and sampled boundary monitoring (v6)

Run `scripts/run_experiment_b_tracking.py` from the repository root with a compatible
CARLA/AirSim pair in a clear test area. This version changes the reference, control,
setup gate, and validity criteria; do not pool its results with the archived v5 runs.
Existing results are retained unchanged.

## Coordinate registration is a prerequisite

The old runner mapped the initial pedestrian XY directly onto the initial drone XY.
That displacement mapping supports relative trajectory comparisons but cannot establish
physical pedestrian clearance. Guarded runs now require an independently verified
static registration:

```
airsim_x = cos(yaw)*carla_x - sin(yaw)*carla_y + offset_x
airsim_y = sin(yaw)*carla_x + cos(yaw)*carla_y + offset_y
```

Angles are degrees, coordinates are meters. Determine rotation/translation from known
corresponding landmarks or simulator transforms and check additional landmarks not used
for calibration. `--frame-verified` records the operator's verification; the script cannot
perform it or detect incorrect calibration. A reflected or differently scaled frame must
be corrected before using this rotation/translation model. Never copy zero offsets unless
independently verified. Unguarded runs without calibration retain the legacy relative
mapping, but cannot pass tracking validity or sampled boundary compliance.

Height is **-AirSim NED Z relative to the AirSim origin**, not terrain clearance.
The default target is now **+25 m** (NED Z=-25), replacing the old signed -25 m
(NED Z=+25). The default floor/ceiling are 0/30 m in that same origin-relative frame.
Verify the origin against the scene and set `--height-min`, `--z-max`, and
`--target-height` accordingly. This runner does not observe terrain or obstacles.

## Define a consistent envelope

Defaults conservatively interpret pedestrian clearance as **horizontal separation**:

- `--minimum-separation 3`: minimum XY distance, distinct from tracking accuracy.
- `--safety-margin 0.5`: reserve outside the boundary.
- `--follow-distance 5`: desired path distance; a guarded 1 m request is rejected.
- `--prediction-horizon 0.5`: seconds of constant-velocity lookahead.
- `--max-acceleration 2`: horizontal command slew limit and assumed braking acceleration.

These are engineering settings, not a validated interpretation of every threshold in the
paper. If the research definition is vertical or 3D clearance, implement that definition
explicitly before making equivalent claims. Verify braking assumptions experimentally;
command slew limits do not prove physical braking performance. At corners, the path target
is projected outside the minimum-plus-margin disk when needed. This changes the reference
and is logged as an intervention. There is no maximum separation safety constraint here.

## Example guarded run

After supplying your actual calibration, use:

```bash
python scripts/run_experiment_b_tracking.py \
  --scenario rectangle --oba \
  --frame-offset-x "$CALIBRATED_OFFSET_X" \
  --frame-offset-y "$CALIBRATED_OFFSET_Y" \
  --frame-yaw-deg "$CALIBRATED_YAW_DEG" --frame-verified \
  --minimum-separation 3 --safety-margin 0.5 --follow-distance 5 \
  --height-min 0 --z-max 30 --target-height 25 \
  --output-dir results/experiment_b/rectangle_v6_trial1
```

These shell variables are local non-secret calibration values, not automatically supplied
by the environment. The script requires CARLA's Python client and AirSim; no live simulator
validation is implied by the example. Remove `--oba` for a controlled unguarded comparison,
retaining calibration, controller, reference, timing settings, and initial scene. Unguarded
runs deliberately do not enforce the safety envelope; use an isolated simulation only.

## Setup, control, and recovery

Before arming, guarded runs reject a straight setup segment intersecting the stationary
pedestrian's protected disk. Full XYZ settling within 0.3 m and speed <=0.3 m/s for 1 s
is required before measurement; startup acquisition errors are excluded explicitly.

During tracking, CARLA is stepped at 20 Hz. A proportional position controller plus
measured pedestrian-velocity feedforward issues short-lived AirSim velocity commands.
Horizontal speed and changes from measured velocity are bounded; vertical velocity has
a separate proportional gain and speed limit. Defaults: XY speed 3 m/s, gains 0.8/s,
vertical speed 1 m/s, command duration 0.15 s. These replace asynchronous position-command
refreshes/deadbands; the old `--command-interval` setting is no longer used.

Every update checks measured height/separation and closest predicted XY approach under
both measured velocity and the proposed command. Closing-speed stopping distance adds to
the configured reserve. Predicted height is checked for current and commanded vertical
velocity. Risk, invalid telemetry, or timing failure aborts a guarded trial with nonzero
exit status. The runner stops the pedestrian, cancels the last flight task, and requests
hover, then restores CARLA settings. It **leaves API control active for operator recovery**
instead of automatically landing on unknown terrain. Recovery is best effort, not a proof
of safety; a target that can independently move into the drone needs a validated evasive
controller. The simulated pedestrian is destroyed after output generation.

## Timing and output interpretation

Pedestrian poses come from the tick's CARLA snapshot. Telemetry includes actual CARLA
simulation elapsed time, AirSim elapsed time, their relative drift, and host acquisition
latency. Guarded runs reject nonadvancing AirSim timestamps, drift >0.1 s, or acquisition
latency >0.1 s by default. Configure `--max-clock-skew` and `--max-telemetry-latency` from
validated measurement tolerances, not merely to obtain a passing run. This gates uncertain
comparisons; it does **not** synchronize clocks or reconstruct exact simultaneous poses.
Hardware/physics synchronization and interpolation require additional simulator support.

### Diagnosing a setup timeout

Tracking starts only after position error is <= `--start-tolerance` (default 0.3 m)
and total speed is <=0.3 m/s continuously for `--settle-seconds` (default 1 s).
Console output now prints the requested NED XYZ/height, initial travel distance,
and one progress sample per second. `setup_telemetry.csv` retains all setup polling
samples even when no tracking samples are collected. `summary.json` includes
`setup_last_sample` and a detailed `abort_reason`.

- Large or increasing XY error: verify the actual target, frame registration,
  spectator placement, and unobstructed setup path.
- Large height error: check the signed target and scene origin. A +25 m height
  requests NED Z=-25; this differs from older -25 m-height experiments.
- Error steadily decreasing with insufficient travel time: after checking the target,
  increase `--setup-timeout` to cover travel and settling.
- Position inside tolerance but speed too high: inspect control/physics stability
  and competing API clients. Increasing the timeout alone may not help.
- Persistent nonzero position error with near-zero speed: investigate the simulator's
  position-controller stopping tolerance or obstructions before changing the gate.

Do not bypass settling or widen tracking/safety thresholds to hide setup failure.
Retry in a new output directory; existing results are preserved.

Each run saves raw `telemetry.csv`, `summary.json`, and (with matplotlib)
`tracking_metrics.png`. Outputs distinguish:

- `completed`: requested measurement ticks executed.
- `tracking_criteria_passed`: completed, settled, verified calibration, valid timing,
  XY target RMSE <=1 m and P95 <=2 m (configurable).
- `sampled_boundary_compliance`: completed with valid timing/calibration, no abort,
  no sampled separation or height violations. This is not a formal safety certificate.
- Violation counts, sample-interval-based violation duration, reasons for abort/intervention,
  max clock skew/acquisition latency, guardian computation time, and controller settings.

RMS pedestrian separation is not tracking RMSE. Plots show the configured minimum
horizontal distance, height bounds, and distinct timing/tracking/boundary outcomes.
No between-sample collision, obstacle, terrain, maximum following-distance, or moving-target
safety guarantee is evaluated. Continuous checks here mean checks on each sampled control
update, not continuous-time verification.

## Validation and research protocol

Run simulator-free tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_experiment_b_tracking.py
```

Tests cover geometry, braking lookahead, command limits, configuration rejection,
non-finite data, command dispatch, stale-clock abort, and cleanup using fake simulator APIs.
They do not verify real physics or control stability. For publication, use live repeated
trials with fixed scene initialization, verified frames/time tolerances, deliberate boundary
challenges, and independent trajectory-based violation checks. Compare unguarded,
pre-dispatch-only, and sampled runtime monitoring under matching conditions. Retain failures
and interrupted trials; do not retune acceptance thresholds after observing results.
