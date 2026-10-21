import json

# Example logging during simulation loop
trajectory_log = {
    "time": [],
    "x": [],
    "y": [],
    "z": [],
    "intervention_points": []  # Mark where OBA intervened
}

# In your flight control loop:
pos = drone_client.getMultirotorState().kinematics_estimated.position
trajectory_log["x"].append(pos.x_val)
trajectory_log["y"].append(pos.y_val)
trajectory_log["z"].append(pos.z_val) # Note: AirSim/Carla z is negative for altitude
