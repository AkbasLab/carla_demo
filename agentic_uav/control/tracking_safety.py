"""Pure geometry and conservative command checks for Experiment B.

Distances use calibrated XY meters; heights use -AirSim NED Z. This is
a sampled constant-velocity model, not a collision-free flight guarantee.
"""
import math
from dataclasses import dataclass


def map_xy(x, y, yaw_degrees, offset_x, offset_y):
    angle = math.radians(yaw_degrees)
    c, s = math.cos(angle), math.sin(angle)
    return c*x-s*y+offset_x, s*x+c*y+offset_y


def closest_separation(relative_position, relative_velocity, horizon):
    speed_sq = sum(v*v for v in relative_velocity)
    t = 0.0 if speed_sq == 0 else max(0.0, min(
        horizon, -sum(p*v for p, v in zip(relative_position, relative_velocity))/speed_sq))
    return math.hypot(*(p+v*t for p, v in zip(relative_position, relative_velocity)))


def limit_vector(vector, limit):
    magnitude = math.hypot(*vector)
    scale = min(1.0, limit/magnitude) if magnitude else 1.0
    return tuple(v*scale for v in vector)


def tracking_velocity(position, target, pedestrian_velocity, measured_velocity,
                      gain, max_speed, max_acceleration, dt):
    if not all(math.isfinite(v) for v in (*position, *target, *pedestrian_velocity,
                                        *measured_velocity)):
        raise ValueError("Non-finite tracking telemetry")
    desired = limit_vector(tuple(pv+gain*(t-p) for p, t, pv in
                                 zip(position, target, pedestrian_velocity)), max_speed)
    change = limit_vector(tuple(d-v for d, v in zip(desired, measured_velocity)),
                          max_acceleration*dt)
    return limit_vector(tuple(v+dv for v, dv in zip(measured_velocity, change)), max_speed)


@dataclass(frozen=True)
class SafetyEnvelope:
    minimum_separation: float = 3.0
    margin: float = 0.5
    minimum_height: float = 0.0
    maximum_height: float = 30.0
    horizon: float = 0.5
    braking_acceleration: float = 2.0

    def reasons(self, position, measured_velocity, command_velocity,
                pedestrian_position, pedestrian_velocity, height, vertical_velocity):
        if not all(math.isfinite(v) for v in (*position, *measured_velocity,
                *command_velocity, *pedestrian_position, *pedestrian_velocity,
                height, vertical_velocity)):
            return ["invalid_telemetry"]
        relative = tuple(p-q for p, q in zip(position, pedestrian_position))
        distance = math.hypot(*relative)
        reasons = []
        if distance < self.minimum_separation:
            reasons.append("separation_violation")
        if not self.minimum_height <= height <= self.maximum_height:
            reasons.append("height_violation")
        # Check both current momentum and the proposed command. Stopping distance
        # reserves margin even if command execution cannot change velocity instantly.
        for label, velocity in (("measured", measured_velocity), ("command", command_velocity)):
            relative_velocity = tuple(v-pv for v, pv in zip(velocity, pedestrian_velocity))
            closing = max(0.0, -sum(p*v for p, v in zip(relative, relative_velocity))/distance) if distance else math.inf
            reserve = self.margin+closing*closing/(2*self.braking_acceleration)
            if closest_separation(relative, relative_velocity, self.horizon) < self.minimum_separation+reserve:
                reasons.append(label+"_separation_risk")
        predicted_height = height-vertical_velocity*self.horizon
        if not self.minimum_height+self.margin <= predicted_height <= self.maximum_height-self.margin:
            reasons.append("predicted_height_risk")
        return reasons
