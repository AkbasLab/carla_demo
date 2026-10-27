import json
import numpy as np

pairs = json.load(open("frame_pairs.json"))
assert len(pairs) >= 4, "Use at least three calibration points and one held-out point"

carla = np.array([p["carla"] for p in pairs], dtype=float)
air = np.array([p["airsim"] for p in pairs], dtype=float)

c_mean = carla[:-1].mean(axis=0)
a_mean = air[:-1].mean(axis=0)
c = carla[:-1] - c_mean
a = air[:-1] - a_mean

if np.linalg.matrix_rank(c) < 2:
    raise ValueError("Calibration points must not all lie on one line")

yaw = np.arctan2(
    np.sum(c[:, 0]*a[:, 1] - c[:, 1]*a[:, 0]),
    np.sum(c*a),
)
rotation = np.array([
    [np.cos(yaw), -np.sin(yaw)],
    [np.sin(yaw),  np.cos(yaw)],
])
offset = a_mean - rotation @ c_mean

errors = np.linalg.norm(carla @ rotation.T + offset - air, axis=1)

print("CALIBRATED_YAW_DEG =", np.degrees(yaw))
print("CALIBRATED_OFFSET_X =", offset[0])
print("CALIBRATED_OFFSET_Y =", offset[1])
print("Calibration residuals (m):", errors[:-1])
print("Held-out position error (m):", errors[-1])
