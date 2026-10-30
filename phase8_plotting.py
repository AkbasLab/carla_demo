import json
from pathlib import Path
import matplotlib.pyplot as plt

folder = Path("results/phase8/recovery_fixed_run4")
arrivals = json.loads((folder / "waypoint_arrivals.json").read_text())
mission = json.loads((folder / "effective_mission.json").read_text())

fig, (ax, timeline) = plt.subplots(
    1, 2, figsize=(16, 9), constrained_layout=True
)
colors = dict(zip(
    sorted({a["task_id"] for a in arrivals}),
    ["tab:blue", "tab:orange", "tab:green", "tab:red"]
))

for task in mission["tasks"]:
    points = task["waypoints"]
    ax.plot(
        [p[0] for p in points], [p[1] for p in points],
        "--s", color=colors.get(task["task_id"]),
        markerfacecolor="none", alpha=0.6, label=task["task_id"]
    )

groups = sorted({
    (a["agent_id"], a["task_id"], a["version"]) for a in arrivals
})
for row, (drone, task, version) in enumerate(groups):
    points = sorted(
        [a for a in arrivals if
         (a["agent_id"], a["task_id"], a["version"]) ==
         (drone, task, version)],
        key=lambda a: a["time_s"]
    )
    color = colors[task]
    for a in points:
        x, y, _ = a["position"]
        label = f'WP{a["index"] + 1}'
        ax.scatter(x, y, color=color, marker="o" if version == 1 else "D")
        timeline.scatter(a["time_s"], row, color=color)
        timeline.annotate(
            f'{label}\n{a["time_s"]:.1f}s',
            (a["time_s"], row), xytext=(0, 10),
            textcoords="offset points", ha="center", fontsize=8
        )

ax.set(title="Planned routes and observed arrival points",
       xlabel="Shared X (m)", ylabel="Shared Y (m)")
ax.set_aspect("equal", adjustable="datalim")
ax.legend(fontsize=8)
timeline.set_yticks(range(len(groups)), [
    f'{d} · {t.removeprefix("SEARCH_SECTOR_")} · v{v}'
    for d, t, v in groups
])
timeline.set(title="Waypoint arrival timeline", xlabel="Measurement time (s)")
timeline.set_ylim(-0.5, len(groups))
for panel in (ax, timeline):
    panel.grid(alpha=0.2)
fig.suptitle("Phase 8: planned routes and recorded waypoint arrivals")
for extension in ("png", "pdf"):
    fig.savefig(folder / f"waypoint_arrival_graph.{extension}", dpi=200)
print(folder / "waypoint_arrival_graph.png")

