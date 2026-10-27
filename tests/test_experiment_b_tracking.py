"""Simulator-free regression tests; no claim of physical flight validation."""
import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from agentic_uav.control.tracking_safety import (
    SafetyEnvelope, closest_separation, map_xy, tracking_velocity)


spec = importlib.util.spec_from_file_location(
    "experiment_b", Path(__file__).resolve().parents[1]/"scripts/run_experiment_b_tracking.py")
experiment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(experiment)


def arguments(tmp_path, *extra):
    return experiment.parse_args(["--scenario", "rectangle", "--output-dir", str(tmp_path), *extra])


def test_frame_rotation_and_origin():
    assert map_xy(2, 1, 90, 10, 20) == pytest.approx((9, 22))


def test_closest_approach_checks_segment_not_just_endpoint():
    assert closest_separation((5, 0), (-10, 0), 1) == 0
    assert closest_separation((5, 0), (0, 0), 1) == 5
    assert closest_separation((5, 0), (10, 0), 1) == 5


def test_velocity_has_feedforward_speed_and_acceleration_limits():
    assert tracking_velocity((0, 0), (0, 0), (1, 0), (1, 0), 1, 3, 2, .05) == (1, 0)
    vx, vy = tracking_velocity((0, 0), (100, 100), (0, 0), (0, 0), 1, 3, 2, .05)
    assert math.hypot(vx, vy) == pytest.approx(.1)


@pytest.mark.parametrize("position,measured,command,ped_velocity,height,vz,reason", [
    ((2, 0), (0, 0), (0, 0), (0, 0), 25, 0, "separation_violation"),
    ((5, 0), (-4, 0), (0, 0), (0, 0), 25, 0, "measured_separation_risk"),
    ((5, 0), (0, 0), (-4, 0), (0, 0), 25, 0, "command_separation_risk"),
    ((5, 0), (0, 0), (0, 0), (4, 0), 25, 0, "measured_separation_risk"),
    ((5, 0), (0, 0), (0, 0), (0, 0), 31, 0, "height_violation"),
    ((5, 0), (0, 0), (0, 0), (0, 0), 29, -3, "predicted_height_risk"),
])
def test_envelope_detects_current_and_predicted_risk(position, measured, command, ped_velocity, height, vz, reason):
    assert reason in SafetyEnvelope().reasons(position, measured, command, (0, 0), ped_velocity, height, vz)


def test_safe_motion_allowed():
    assert not SafetyEnvelope().reasons((5, 0), (1, 0), (1, 0), (0, 0), (1, 0), 25, 0)


def test_nonfinite_telemetry_cannot_produce_approved_command():
    assert SafetyEnvelope().reasons((math.nan, 0), (0, 0), (0, 0), (0, 0), (0, 0), 25, 0) == ["invalid_telemetry"]
    with pytest.raises(ValueError):
        tracking_velocity((math.nan, 0), (0, 0), (0, 0), (0, 0), 1, 3, 2, .05)


@pytest.mark.parametrize("extra", [
    ["--oba"],
    ["--oba", "--frame-offset-x", "0", "--frame-offset-y", "0", "--frame-verified", "--follow-distance", "1"],
    ["--oba", "--frame-offset-x", "0", "--frame-offset-y", "0", "--frame-verified", "--target-height", "-25"],
    ["--max-clock-skew", "nan"], ["--frame-offset-x", "0"],
    ["--prediction-horizon", ".1"], ["--ticks", "0"],
])
def test_invalid_or_unverifiable_config_rejected_before_connection(tmp_path, extra):
    with pytest.raises(SystemExit):
        arguments(tmp_path, *extra)


@pytest.mark.parametrize("fault", ["stale", "separation"])
def test_runner_command_dispatch_abort_and_cleanup(tmp_path, monkeypatch, fault):
    """Fake APIs exercise the real orchestration, including a stale timestamp run."""
    class Vec:
        def __init__(self, x=0., y=0., z=0.):
            self.x, self.y, self.z = x, y, z
        def __mul__(self, n):
            return Vec(self.x*n, self.y*n, self.z*n)
        def __add__(self, other):
            return Vec(self.x+other.x, self.y+other.y, self.z+other.z)

    now = [0.]
    stale = [False]
    unsafe = [False]
    ped = Vec(10, 0, 0)
    walker = Mock(id=7)
    walker.get_location.return_value = ped
    snapshot = lambda: NS(timestamp=NS(elapsed_seconds=now[0]),
        find=lambda _: NS(get_transform=lambda: NS(location=ped)))
    original = NS(synchronous_mode=False, fixed_delta_seconds=None)
    world = Mock()
    world.get_settings.side_effect = lambda: NS(**vars(original))
    world.get_snapshot.side_effect = snapshot
    world.tick.side_effect = lambda: now.__setitem__(0, now[0]+.05)
    world.get_blueprint_library.return_value.filter.return_value = [object()]
    world.get_spectator.return_value.get_transform.return_value = NS(
        location=Vec(), get_forward_vector=lambda: Vec(1, 0), get_right_vector=lambda: Vec(0, 1))
    world.try_spawn_actor.return_value = walker
    client = Mock()
    client.get_world.return_value = world
    drone = Mock()
    position = NS(x_val=0., y_val=0., z_val=0.)
    drone.moveToPositionAsync.side_effect = lambda x, y, z, **kw: (
        setattr(position, "x_val", x), setattr(position, "y_val", y), setattr(position, "z_val", z))
    drone.getMultirotorState.side_effect = lambda: NS(
        timestamp=int((1+(0 if stale[0] else now[0]))*1e9),
        kinematics_estimated=NS(position=NS(x_val=9.,y_val=0.,z_val=-25.) if unsafe[0] and now[0]>0 else position,
                               linear_velocity=NS(x_val=0., y_val=0., z_val=0.)))
    import sys
    monkeypatch.setitem(sys.modules, "carla", NS(Client=lambda *a: client,
        WalkerControl=lambda: NS(speed=0.), Vector3D=Vec, Transform=lambda x: x))
    monkeypatch.setitem(sys.modules, "airsim", NS(MultirotorClient=lambda **kw: drone))
    monkeypatch.setattr(experiment, "wait_until_settled", lambda *a: None)
    monkeypatch.setattr(experiment, "plot_metrics", lambda *a: None)
    common = ["--oba", "--frame-offset-x", "0", "--frame-offset-y", "0", "--frame-verified", "--ticks", "2"]
    assert experiment.run(arguments(tmp_path, *common))
    summary = json.loads((tmp_path/"summary.json").read_text())
    assert summary["sampled_boundary_compliance"]
    assert drone.moveByVelocityAsync.call_count == 2
    drone.hoverAsync.assert_called_once()
    walker.destroy.assert_called_once()
    # Frozen AirSim timestamp must stop tracking and return failure, never dispatch.
    drone.reset_mock()
    now[0] = 0.
    stale[0] = fault == "stale"
    unsafe[0] = fault == "separation"
    assert not experiment.run(arguments(tmp_path/"stale", *common))
    summary = json.loads((tmp_path/"stale"/"summary.json").read_text())
    assert not summary["sampled_boundary_compliance"]
    assert ("invalid_timing" if fault == "stale" else "separation_violation") in summary["abort_reason"]
    drone.moveByVelocityAsync.assert_not_called()
    drone.cancelLastTask.assert_called_once()


def test_existing_results_preserved_before_simulator_connection(tmp_path, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "carla", NS())
    monkeypatch.setitem(sys.modules, "airsim", NS())
    summary = tmp_path/"summary.json"
    summary.write_text("existing research result")
    with pytest.raises(FileExistsError):
        experiment.run(arguments(tmp_path))
    assert summary.read_text() == "existing research result"


def setup_clock(monkeypatch):
    clock = [0.]
    monkeypatch.setattr(experiment, "time", NS(monotonic=lambda: clock[0],
        sleep=lambda duration: clock.__setitem__(0, clock[0]+duration)))
    return clock


def setup_state(x=0., z=0., vx=0.):
    return NS(kinematics_estimated=NS(position=NS(x_val=x,y_val=0.,z_val=z),
              linear_velocity=NS(x_val=vx,y_val=0.,z_val=0.)))


@pytest.mark.parametrize("state,expected", [
    (setup_state(x=2), "last XY error=2.000 m"),
    (setup_state(z=.5), "height error=0.500 m"),
    (setup_state(vx=.6), "speed=0.600 m/s"),
])
def test_setup_timeout_reports_which_requirement_failed(monkeypatch, capsys, state, expected):
    setup_clock(monkeypatch)
    drone=Mock()
    drone.getMultirotorState.return_value=state
    samples=[]
    with pytest.raises(TimeoutError, match=expected):
        experiment.wait_until_settled(drone,(0.,0.,0.),.2,.1,.3,False,samples.append)
    assert samples
    assert "target NED XYZ=" in capsys.readouterr().out


def test_setup_requires_continuous_settling_and_retains_samples(monkeypatch):
    setup_clock(monkeypatch)
    drone=Mock()
    states=iter([setup_state(),setup_state(vx=1.),setup_state()])
    drone.getMultirotorState.side_effect=lambda: next(states,setup_state())
    samples=[]
    experiment.wait_until_settled(drone,(0.,0.,0.),1.,.1,.3,False,samples.append)
    assert samples[-1]["setup_elapsed_s"] >= .2
    assert len(samples) >= 5


def test_setup_rejects_nonfinite_pose(monkeypatch):
    setup_clock(monkeypatch)
    drone=Mock()
    drone.getMultirotorState.return_value=setup_state(x=math.nan)
    with pytest.raises(RuntimeError, match="Non-finite setup telemetry"):
        experiment.wait_until_settled(drone,(0.,0.,0.),1.,.1,.3)
