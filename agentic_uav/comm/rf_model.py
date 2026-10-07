import math
from agentic_uav.core.models import Position3D

class RFPropagationModel:
    """Simulates radio frequency attenuation, path loss, and packet drops."""

    def __init__(self, frequency_ghz: float = 2.4, max_range_meters: float = 60.0):
        self.frequency_ghz = frequency_ghz
        self.max_range_meters = max_range_meters

    def calculate_distance(self, pos1: Position3D, pos2: Position3D) -> float:
        return math.sqrt((pos1.x - pos2.x)**2 + (pos1.y - pos2.y)**2 + (pos1.z - pos2.z)**2)

    def is_connected(self, pos1: Position3D, pos2: Position3D) -> bool:
        """Determines if two nodes are within effective RF range."""
        dist = self.calculate_distance(pos1, pos2)
        return dist <= self.max_range_meters

    def calculate_rssi(self, pos1: Position3D, pos2: Position3D, tx_power_dbm: float = 20.0) -> float:
        """Simplified Free-Space Path Loss (FSPL) RSSI calculation in dBm."""
        dist = max(self.calculate_distance(pos1, pos2), 1.0) # Avoid log(0)
        # FSPL = 20*log10(d) + 20*log10(f) + 20*log10(4*pi/c)
        fspl = 20 * math.log10(dist) + 20 * math.log10(self.frequency_ghz * 1e9) - 147.55
        rssi = tx_power_dbm - fspl
        return round(rssi, 2)
