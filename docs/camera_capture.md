# Phase 1: AirSim RGB camera capture

Start the CarlaAir simulator and ensure the configured vehicle `Drone1` has a scene camera named `0`.

From the repository root, with the existing AirSim Python environment active:

```bash
python -m scripts.run_phase4_scenario --airsim --capture-images
```

Optional output directory and camera selection:

```bash
python -m scripts.run_phase4_scenario --airsim --capture-images --image-output-dir results/camera --camera-name 0
```

The search mission captures **one RGB image after reaching each search waypoint**, not continuous video. Files are saved as pairs:

```text
results/camera/
  Drone1_0_<timestamp>.png
  Drone1_0_<timestamp>.json
```

JSON metadata includes the vehicle ID, camera name, UTC capture time, simulator timestamp, image dimensions, and estimated vehicle position in AirSim NED coordinates. The position is queried after image retrieval and may differ slightly from the exact camera exposure pose.

This option requires a running AirSim/CarlaAir simulator; the mock adapter does not generate images. The existing ground-truth target detection logic remains unchanged. No object detector or VLM is connected yet.

If the camera returns no image, check the camera name and simulator vehicle configuration. A failed capture causes the search skill to report failure. This feature has not yet been tested against a live simulator.
