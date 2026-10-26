import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d import Axes3D
from matplotlib.patches import Rectangle
import mpl_toolkits.mplot3d.art3d as art3d

# Set publication style
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.size'] = 10
plt.style.use('seaborn-v0_8-paper' if 'seaborn-v0_8-paper' in plt.style.available else 'default')

fig = plt.figure(figsize=(12, 5), dpi=300)

# ==========================================
# SUBPLOT 1: 2D Overhead Top-Down View (X-Y)
# ==========================================
ax1 = fig.add_subplot(121)

# Start and Target Points
start = (0, 0)
target = (100, 80)

# Obstacle / Building Bounds (X: 35 to 65, Y: 25 to 55)
obstacle_x = [35, 65, 65, 35, 35]
obstacle_y = [25, 25, 55, 55, 25]
ax1.fill(obstacle_x, obstacle_y, color='gray', alpha=0.5, label='Geometric Blocker (Building)')

# Unguarded Trajectory (Direct path cutting through obstacle)
x_unguarded = np.linspace(0, 100, 50)
y_unguarded = np.linspace(0, 80, 50)
ax1.plot(x_unguarded, y_unguarded, 'r--', linewidth=2, label='Unguarded LLM (Collision & Breach)')
ax1.scatter([50], [40], color='red', marker='X', s=100, zorder=5, label='Collision / Breach Event')

# Guardrailed Trajectory (Rerouted around obstacle)
x_guardrailed = np.array([0, 30, 30, 70, 70, 100])
y_guardrailed = np.array([0, 20, 60, 60, 80, 80])
ax1.plot(x_guardrailed, y_guardrailed, 'g-', linewidth=2.5, label='LLM + OBA Guardrail (Safe)')

# Markers
ax1.scatter(*start, color='blue', marker='o', s=80, label='Start')
ax1.scatter(*target, color='purple', marker='*', s=120, label='Target Waypoint')

ax1.set_title('(a) 2D Flight Path & Spatial Obstacle Avoidance', fontsize=7, fontweight='bold')
ax1.set_xlabel('X Position (m)')
ax1.set_ylabel('Y Position (m)')
ax1.grid(True, linestyle=':', alpha=0.6)
ax1.legend(loc='upper left', fontsize=4)

# ==========================================
# SUBPLOT 2: Altitude Profile & Ceilings (X-Z)
# ==========================================
ax2 = fig.add_subplot(122)

# Altitude (Z) profiles (Note: In flight dynamics, z_max ceiling = 30m altitude)
z_ceiling = 30.0  # Max altitude limit

# Unguarded breaches altitude up to 55m
x_prof = np.linspace(0, 100, 50)
z_unguarded = 15 + 40 * np.sin(np.pi * x_prof / 100) # Breaches 30m ceiling
ax2.plot(x_prof, z_unguarded, 'r--', linewidth=2, label='Unguarded LLM (Ceiling Violation)')

# Guardrailed clamps altitude strictly at z_max = 30m
z_guardrailed = np.minimum(z_unguarded, z_ceiling)
ax2.plot(x_prof, z_guardrailed, 'g-', linewidth=2.5, label='LLM + OBA Guardrail (Clamped at $z_{max}$)')

# Draw Geofence Ceiling Line
ax2.axhline(y=z_ceiling, color='darkred', linestyle='-', linewidth=1.5, label='Max Altitude Ceiling ($z_{max} = 30m$)')
ax2.fill_between([0, 100], z_ceiling, 60, color='red', alpha=0.15, label='Unauthorized Airspace Zone')

ax2.set_title('(b) Vertical Profile & Kinematic Ceiling Enforcement', fontsize=7, fontweight='bold')
ax2.set_xlabel('X Position (m)')
ax2.set_ylabel('Altitude Z (m)')
ax2.set_ylim(0, 60)
ax2.grid(True, linestyle=':', alpha=0.6)
ax2.legend(loc='lower right', fontsize=4)

plt.tight_layout()
plt.savefig('trajectory_comparison_carlaair.pdf', format='pdf', bbox_inches='tight')
plt.savefig('trajectory_comparison_carlaair.png', format='png', dpi=300, bbox_inches='tight')
plt.show()
