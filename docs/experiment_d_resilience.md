# Experiment D — live CARLA–AirSim heartbeat-loss prototype

This prototype connects to **both** a running CARLA server and AirSim multirotor. CARLA advances in synchronous mode; AirSim supplies live vehicle state and receives hover recovery commands. Fault injection drops **application-level heartbeat messages**, not CARLA or AirSim network RPC. It uses the repository's `RFPropagationModel` for distance-based connectivity.

Run from the repository root with both simulators started:

```bash
python -u scripts/run_experiment_d_resilience.py --loss 0 --duration 15 --output-dir results/d/loss_0
python -u scripts/run_experiment_d_resilience.py --loss 0.5 --duration 15 --output-dir results/d/loss_50
python -u scripts/run_experiment_d_resilience.py --loss 1 --duration 15 --output-dir results/d/loss_100
python -u scripts/run_experiment_d_resilience.py --loss 1 --recovery none --duration 15 --output-dir results/d/loss_100_no_recovery
```

For repeated trials, change `--seed` and `--output-dir`; do not overwrite runs. Outputs: `telemetry.csv` and `summary.json`.

**Research limitations:** This is a connectivity and recovery **instrumentation prototype**, not yet a rigorous comparison of safe recovery outcomes. The drone takes off and then remains near hover, so a hover command after a timeout may not produce a meaningful change in its trajectory; the low-speed recovery criterion may already hold before injection. Do not interpret a low-speed observation as mission-level recovery success. The script uses a minimal hover-on-timeout policy, not `FailSafeManager`'s RETURN_HOME/LAND implementation. Packet drops are simulated only for heartbeat delivery; no actual transport degradation, stale LLM commands, or RF interference is imposed. The script does not invoke an LLM or exercise a full OBA policy. It records sampled altitude violations only; no collision or horizontal geofence checks. CARLA and AirSim clocks are not synchronized.

**Next research upgrade:** Add an actual moving mission with bounded waypoints, measure progress and stopping distance, distinguish false triggers from legitimate timeout triggers, and validate return/land using vehicle state. Pair seeded fault schedules with and without recovery. Do not claim communication-resilient autonomy based on this prototype alone.
