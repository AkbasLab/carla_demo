import json
import re
import airsim
import ollama


# These MUST exactly match the vehicle names in AirSim settings.json
DRONES = ["Drone1", "Drone2"]

OLLAMA_MODEL = "llama3.1:latest"
VELOCITY = 5.0


# Convert perceived altitude (+29.18m) to AirSim Local NED frame (-29.18m)
perceived_state = {
    'x_val': -0.05123046785593033,
    'y_val': 0.05228515341877937,
    'z_val': 29.187564849853516
}

def to_ned_frame(state: dict) -> dict:
    """Converts upward-positive Z altitude to NED (North-East-Down) frame."""
    return {
        'x_val': state['x_val'],
        'y_val': state['y_val'],
        'z_val': -abs(state['z_val'])  # Invert altitude for AirSim NED frame
    }

# Apply conversion before feeding to OBA / Controller
ned_state = to_ned_frame(perceived_state)
# ned_state['z_val'] is now -29.18756...

def to_world_frame(state: dict) -> dict:
    """Ensures Z represents positive height above ground level."""
    return {
        'x_val': state['x_val'],
        'y_val': state['y_val'],
        'z_val': abs(state['z_val'])  # Positive height above ground
    }


def parse_llm_response(raw_response: str) -> list[dict]:
    """Extract and parse structured JSON targets from LLM output."""

    cleaned = re.sub(
        r"```(?:json)?\s*(.*?)\s*```",
        r"\1",
        raw_response,
        flags=re.DOTALL,
    ).strip()

    data = json.loads(cleaned)

    if isinstance(data, dict):
        return [data]

    if isinstance(data, list):
        return data

    raise ValueError("LLM response must be a JSON object or array.")


def verify_drones(client):
    """
    Verify that CarlaAir/AirSim actually registered both drones.
    """

    vehicles = client.listVehicles()

    print(f"AirSim vehicles detected: {vehicles}")

    missing = [d for d in DRONES if d not in vehicles]

    if missing:
        raise RuntimeError(
            f"Missing vehicles: {missing}. "
            f"AirSim only reports: {vehicles}\n"
            "Check your AirSim settings.json."
        )

    return vehicles


def setup_drones(client):
    """
    Enable API control and arm EACH drone independently.
    """

    print("\n=== Initializing drones ===")

    for drone in DRONES:
        print(f"[{drone}] Enabling API control...")

        client.enableApiControl(
            True,
            vehicle_name=drone
        )

        print(f"[{drone}] API control enabled.")

        print(f"[{drone}] Arming...")

        client.armDisarm(
            True,
            vehicle_name=drone
        )

        state = client.getMultirotorState(
            vehicle_name=drone
        )

        print(
            f"[{drone}] "
            f"landed={state.landed_state} "
            f"armed={state.kinematics_estimated.position}"
        )


def takeoff_all(client):
    """
    Take off both drones concurrently.
    """

    print("\n=== Taking off both drones ===")

    takeoff_tasks = []

    for drone in DRONES:
        print(f"[{drone}] Takeoff command")

        task = client.takeoffAsync(
            vehicle_name=drone
        )

        takeoff_tasks.append((drone, task))

    # Join only AFTER both asynchronous commands have been sent.
    for drone, task in takeoff_tasks:
        task.join()
        print(f"[{drone}] Takeoff complete.")


def print_positions(client):
    """Print current position of every drone."""

    print("\n=== Drone positions ===")

    for drone in DRONES:
        state = client.getMultirotorState(
            vehicle_name=drone
        )

        p = state.kinematics_estimated.position

        print(
            f"[{drone}] "
            f"X={p.x_val:.2f}, "
            f"Y={p.y_val:.2f}, "
            f"Z={p.z_val:.2f}"
        )


def dispatch_targets(client, targets):
    """
    Dispatch independent movement commands to multiple drones.

    IMPORTANT:
    All async commands are created first.
    Only then do we join them.

    This allows Drone1 and Drone2 to fly their missions concurrently.
    """

    move_tasks = []

    for target in targets:

        d_name = target.get("drone")

        if d_name not in DRONES:
            print(
                f"Warning: ignoring unknown vehicle '{d_name}'. "
                f"Expected one of {DRONES}"
            )
            continue

        try:
            tx = float(target["x"])
            ty = float(target["y"])
            tz = float(target["z"])
        except (KeyError, TypeError, ValueError) as exc:
            print(
                f"[{d_name}] Invalid target: {target} "
                f"({exc})"
            )
            continue

        print(
            f"[{d_name}] "
            f"Mission target -> "
            f"X={tx}, Y={ty}, Z={tz}"
        )

        task = client.moveToPositionAsync(
            tx,
            ty,
            tz,
            VELOCITY,
            vehicle_name=d_name,
        )

        move_tasks.append((d_name, task))

    # IMPORTANT:
    # Do NOT call .join() immediately after each command.
    # Wait until commands for ALL drones have been submitted.
    for d_name, task in move_tasks:
        task.join()
        print(f"[{d_name}] Reached target.")

    print_positions(client)


def parse_direct_command(user_input):
    """
    Parse:

        Drone1: 10, 5, -5

    or:

        Drone2: -10, 20, -8
    """

    if ":" not in user_input:
        return None

    drone_part, coords_part = user_input.split(":", 1)

    target_drone = drone_part.strip()

    if target_drone not in DRONES:
        return None

    coords = [
        float(c.strip())
        for c in coords_part.split(",")
    ]

    if len(coords) != 3:
        raise ValueError(
            "Direct command requires exactly 3 coordinates: x, y, z"
        )

    return [{
        "drone": target_drone,
        "x": coords[0],
        "y": coords[1],
        "z": coords[2],
    }]


def llm_parse_command(user_input):
    """
    Convert natural language into independent drone missions.
    """

    system_prompt = """
You are a multi-UAV flight task parser.

There are exactly two available drones:

- Drone1
- Drone2

Convert the user's instruction into independent target coordinates.

Coordinate system:
AirSim NED:
  X = North
  Y = East
  Z = Down

Therefore altitude above the origin is normally represented by a NEGATIVE Z.

Return ONLY valid JSON.

The response MUST be a JSON array.

Each object MUST contain exactly:

{
  "drone": "Drone1" or "Drone2",
  "x": number,
  "y": number,
  "z": number
}

Examples:

User:
Send Drone1 to 10, 0, -10

Output:
[
  {
    "drone": "Drone1",
    "x": 10,
    "y": 0,
    "z": -10
  }
]

User:
Send Drone1 to 10, 0, -10 and Drone2 to -10, 20, -8

Output:
[
  {
    "drone": "Drone1",
    "x": 10,
    "y": 0,
    "z": -10
  },
  {
    "drone": "Drone2",
    "x": -10,
    "y": 20,
    "z": -8
  }
]

Never invent a third drone.
Never rename a drone.
Return JSON only.
"""

    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_input,
            },
        ],
    )

    raw_output = response["message"]["content"].strip()

    print(f"\nLLM output:\n{raw_output}\n")

    return parse_llm_response(raw_output)


def continuous_drone_control():

    client = airsim.MultirotorClient()

    print("Connecting to CarlaAir / AirSim...")
    client.confirmConnection()

    # ---------------------------------------------------------
    # 1. Verify vehicles
    # ---------------------------------------------------------

    verify_drones(client)

    # ---------------------------------------------------------
    # 2. API control + arm EACH drone
    # ---------------------------------------------------------

    setup_drones(client)

    # ---------------------------------------------------------
    # 3. Takeoff concurrently
    # ---------------------------------------------------------

    takeoff_all(client)

    print_positions(client)

    print("\n========================================")
    print(" Dual Drone Control Active")
    print("========================================")
    print()
    print("Direct command:")
    print("  Drone1: 10, 5, -5")
    print()
    print("Multi-drone command:")
    print(
        "  Send Drone1 to 10, 0, -10 "
        "and Drone2 to -10, 20, -8"
    )
    print()
    print("Commands:")
    print("  land")
    print("  exit")
    print()

    try:

        while True:

            user_input = input(
                "Target / Command > "
            ).strip()

            if not user_input:
                continue

            if user_input.lower() in [
                "land",
                "exit",
                "quit",
            ]:
                break

            try:

                # -------------------------------------------------
                # Direct command
                # -------------------------------------------------

                targets = parse_direct_command(
                    user_input
                )

                # -------------------------------------------------
                # LLM command
                # -------------------------------------------------

                if targets is None:

                    targets = llm_parse_command(
                        user_input
                    )

                # -------------------------------------------------
                # Dispatch all drone missions concurrently
                # -------------------------------------------------

                dispatch_targets(
                    client,
                    targets
                )

                print(
                    "\nAll submitted missions completed."
                )

            except json.JSONDecodeError as exc:

                print(
                    f"LLM returned invalid JSON: {exc}"
                )

            except Exception as exc:

                print(
                    f"Error executing command: {exc}"
                )

    finally:

        print("\n=== Landing drones ===")

        land_tasks = []

        for drone in DRONES:

            try:

                print(
                    f"[{drone}] Landing..."
                )

                task = client.landAsync(
                    vehicle_name=drone
                )

                land_tasks.append(
                    (drone, task)
                )

            except Exception as exc:

                print(
                    f"[{drone}] Landing command failed: "
                    f"{exc}"
                )

        for drone, task in land_tasks:

            try:

                task.join()

                print(
                    f"[{drone}] Landed."
                )

            except Exception as exc:

                print(
                    f"[{drone}] Landing wait failed: "
                    f"{exc}"
                )

        # ---------------------------------------------------------
        # Disarm + release API control independently
        # ---------------------------------------------------------

        for drone in DRONES:

            try:

                client.armDisarm(
                    False,
                    vehicle_name=drone
                )

                client.enableApiControl(
                    False,
                    vehicle_name=drone
                )

                print(
                    f"[{drone}] API control released."
                )

            except Exception as exc:

                print(
                    f"[{drone}] Cleanup failed: {exc}"
                )

        print("\nSession closed safely.")


if __name__ == "__main__":
    continuous_drone_control()

