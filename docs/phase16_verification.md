# Phase 16: verification and software testing

## Scope

Phase 16 organizes the existing unit/integration tests, adds cross-layer flight regressions and process-level determinism checks, and supplies pull-request CI without CARLA, AirSim, Ollama, a GPU, or external services. It does not equate a mock pass with physical flight evidence.

The executable requirement map is [coverage.json](../configs/phase16/coverage.json). The verification runner checks that every referenced test exists and reports its actual status. An unselected layer is marked `not_run`, not passed. Every full run also executes tests outside the minimum map, including the Phase 12–15 policy, runner and metric suites.

## 16.1 Unit coverage

| Requirement | Existing test module / check |
|---|---|
| Task cost | `test_phase8_allocation`: hand-calculated components, eligibility and role penalty |
| Tie breaking | `test_phase8_allocation`: claim-order invariance, epoch and score/ID ordering |
| Lease expiration | `test_phase8_allocation`: expired ownership, stale/nonowner progress and renewed epochs |
| Message serialization | `test_phase7_protocol`: all 13 envelope types and malformed input |
| Message expiration | `test_phase7_protocol`, `test_phase10_network`: expired messages cannot be received |
| Packet loss | `test_phase10_network`: 10,000 samples, loss tolerance and repeated seeds |
| Latency | `test_phase10_network`: scheduling, expiration, jitter ordering, rate and bandwidth |
| Role transitions | `test_phase9_roles`: scout, relay and reserve changes |
| Belief aging | `test_phase9_roles`, `test_phase11_guardian`: silence vs confirmed failure, stale and missing observations |
| Geofence | `test_phase11_guardian`: every waypoint and connecting segment |
| Battery | `test_phase11_guardian`: reserve, safe fallback and insufficient energy |
| Invalid LLM output | `test_phase12_agents`: malformed JSON, unknown tools, missing/extra parameters and correction/fallback |

The phase reuses these meaningful tests rather than duplicating their assertions under a new phase number.

## 16.2 Mock integration coverage

- Two agents allocate two routes and physically advance through their required waypoints in the kinematic mock.
- Four agents allocate four routes; completion requires observed arrivals and no duplicate task completions.
- An intentionally stopped owner loses its task lease and a survivor completes its unfinished task.
- A four-agent partition permits only within-group receipt during its interval, then permits restored cross-group traffic. Separate existing tests check that a disconnected controller cannot use undelivered state. This is not a claim of general partition consensus or mission completion during arbitrary partitions.
- Delayed competing claims, supported by previously delivered bids, converge to the lower valid bid; the losing claimant logs correction and release.
- Loss of the designated relay causes the reserve to assume its role in the deterministic role-policy scenario. RF improvement is not measured.
- Malformed LLM output receives at most one structured correction before a deterministic, guarded fallback.

The new `test_phase16_verification.py` also checks partial evidence on timeout/adapter errors, accidental live execution prevention, output preservation, and that every adapter effect matches an executed guardian selection.

### Run automated verification

From the repository root, in your test environment:

```bash
python -m pip install -r requirements-test.txt
python scripts/run_phase16_verification.py \
  --output-dir results/phase16/verification_run1
```

Use a fresh output directory. Inspect `summary.json` and `unittest.log`. Exit code is nonzero on test failures/errors. Summary fields include test IDs/statuses, requirement mapping, Python version and Git revision. This is a software-verification report, separate from Phase 14 mission manifests and Phase 15 performance metrics.

For selected layers:

```bash
python scripts/run_phase16_verification.py --layer unit \
  --output-dir results/phase16/unit_run1
python scripts/run_phase16_verification.py --layer integration \
  --output-dir results/phase16/integration_run1
python scripts/run_phase16_verification.py --layer determinism \
  --output-dir results/phase16/determinism_run1
```

## 16.3 Maintained flight regressions

[run_phase16_regression.py](../scripts/run_phase16_regression.py) exposes the same five cases for mock and opt-in AirSim execution:

| Case | Required observed outcome |
|---|---|
| `single_waypoint` | One controlled drone finishes its configured waypoint route |
| `two_nonconflicting` | Two controlled drones finish two calibrated routes |
| `four_search` | Four controlled drones finish four configured search routes |
| `reassignment` | Drone1 stops while owning unfinished work; lease expires and a survivor completes that work |
| `return_home` | After outward work, an injected reserve-level battery state selects a validated `RETURN_HOME` fallback; arrival at airborne home is observed |

These are regression cases, not a fifth comparison architecture. They reuse `AllocationAgent`, `WaypointExecutor`, `MockFlight`/`AirSimFlight`, and `GuardedExecutor`. The test's safety observer reads telemetry for **all four configured physical drones, including a silenced actor**. Policies do not read other agents' private state; they still exchange allocation messages through endpoints. This reliable shared safety observer intentionally differs from the degraded local-belief Phase 13/15 benchmark. Passing reassignment here does not fix or erase the Phase 15 failed-worker result.

Example kinematic run:

```bash
python scripts/run_phase16_regression.py \
  --backend mock --case reassignment \
  --mission-config configs/phase12/mission.example.json \
  --fail-at 1 --duration 120 \
  --output-dir results/phase16/mock_reassignment_run1
```

### Manual AirSim execution

Start CARLAAir, configure all four named multirotors, and copy/calibrate the existing live mission file. Its example assumes ground NED Z=28 and vehicle-local Y offsets; your map and settings may differ. Calibrate **all vehicle offsets, start/home positions, routes, flight bounds and ground height**. The route names do not certify obstacle clearance. The guardian must have at least 5 m of takeoff overhead. All controlled vehicles must begin landed.

```bash
cp configs/phase12/carlaair.example.json configs/phase16/carlaair.local.json
# Edit configs/phase16/carlaair.local.json for the actual scene first.

python scripts/run_phase16_regression.py \
  --backend airsim --execute-live --case single_waypoint \
  --mission-config configs/phase16/carlaair.local.json \
  --host 127.0.0.1 --rpc-timeout 5 --setup-timeout 120 \
  --duration 180 --speed 1 \
  --output-dir results/phase16/airsim_single_run1
```

Reset/land vehicles between cases. Rerun the same command with `--case two_nonconflicting`, `four_search`, `reassignment`, or `return_home` and a separate output directory. For reassignment, start with `--fail-at 1 --lease-seconds 20 --duration 240`; the case fails if no task was owned at injection or takeover completion was not observed. Adjust the injection time to the actual allocation startup if necessary, and retain the unsuccessful attempt.

Each case writes its effective mission/configuration hash, outcome/error summary, waypoint arrivals, allocation and fault events, message log, telemetry, guardian audit and actual effects. `passed` requires observed mission completion, expected waypoint evidence, no duplicate task completions, and confirmed cleanup stops. The return-home battery value is an explicitly injected safety input, not a physical battery measurement. Takeoff/setup time is excluded from the mission-duration budget.

Cleanup requests hover, confirms low speed when possible, and retains API control. It does not automatically land at an unsurveyed location. Manage the vehicles after each test; an unconfirmed stop fails the case. Collision sensing and safe landing are not established by these tests. Live regression outcomes remain `not_run` in automated verification until separately executed; no live simulator was available during implementation.

## 16.4 Determinism

- Existing tests replay identical network traffic/seeds and compare the actual delivery/loss/latency records. Different-seed tests verify the seed changes the trace.
- The same Phase 9 mission is replayed under all four network conditions, including configured target discovery and timed actor silence.
- The new process-level test repeats an observed mock reassignment under `PYTHONHASHSEED=1` and `97`, and compares complete message, policy-event, fault-event, motion, arrival and guardian traces byte-for-byte. Manifests containing run timestamps are excluded from behavioral equality.
- Targets currently use explicit configured positions; repeated loading preserves them exactly. This is not a test of a randomized target generator that does not exist.
- Actual model sampling, model-server scheduling and inference latency are not forced into deterministic assertions. Record their pinned identity, parameters, prompts, responses and timings through Phase 14/15; compare residual variability separately across repeated real-model runs.

## 16.5 Continuous integration

[verification.yml](../.github/workflows/verification.yml) runs the full simulator-free suite on each pull request and push to `main`, plus manual dispatch. It uses Python 3.11 and 3.12, installs only `requirements-test.txt`, and uploads verification evidence even when tests fail. It has read-only repository permissions and needs no model credentials or simulator.

AirSim tests remain manual and never start through the pull-request workflow. The workflow becomes active when these files are pushed; local validation is not evidence of a completed GitHub Actions run.

## Local verification results

| Evidence | Result |
|---|---|
| Full simulator-free suite | 236 tests passed; zero failures, errors or skips |
| New Phase 16 tests | 9 tests, including five observed-flight subcases |
| Requirement mapping | Every mapped unit/integration/determinism topic passed |
| Test source stability | Source hashes unchanged during the final full run |
| Five standalone mock regression commands | All five passed; takeover and return-home evidence retained |
| CARLA / AirSim packages | Neither installed in the validation environment |
| Actual live AirSim runs | Not run |
| Hosted GitHub Actions | Configured; not executed by local validation |

Detailed local artifacts are in [verification_run1](../results/phase16/verification_run1) and [mock_regressions_run1](../results/phase16/mock_regressions_run1). The full summary retains source hashes because the tested working copy includes changes beyond its recorded base Git commit. This evidence must not be described as a clean checkout of that older commit.

## Exit criterion

The minimum coordination/communication requirement map is executable without CARLAAir, backed by unit tests, mock integration, network replay and process-level determinism. This supports the Phase 16 exit criterion in its simulator-free scope. It does not quantify a percentage of all possible defects and does not replace the separate five-case live regression evidence.
