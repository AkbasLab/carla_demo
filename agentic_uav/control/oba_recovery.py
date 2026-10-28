"""Deterministic OBA recovery geometry in a calibrated AirSim NED frame.

A configuration is a scene model, not evidence that a landing surface is clear.
"""
import math
from dataclasses import dataclass


def segment_hits_box(start, end, box, margin=0.0):
    """Exact closed segment/slab intersection, including tangencies."""
    lo, hi = 0.0, 1.0
    for i, axis in enumerate('xyz'):
        low, high = box[axis + '_min'] - margin, box[axis + '_max'] + margin
        delta = end[i] - start[i]
        if abs(delta) < 1e-12:
            if not low <= start[i] <= high:
                return False
        else:
            a, b = (low - start[i]) / delta, (high - start[i]) / delta
            lo, hi = max(lo, min(a, b)), min(hi, max(a, b))
            if lo > hi:
                return False
    return True


@dataclass
class RecoveryGuardian:
    bounds: dict
    keepouts: list
    site: dict
    margin: float = 0.5

    @classmethod
    def from_config(cls, config):
        guardian = cls(config['flight_bounds'], config.get('keepouts', []),
                       config['landing_site'], float(config.get('obstacle_margin_m', 0.5)))
        for box in [guardian.bounds] + guardian.keepouts:
            for axis in 'xyz':
                low, high = box[axis + '_min'], box[axis + '_max']
                if not all(math.isfinite(v) for v in (low, high)) or low >= high:
                    raise ValueError('Invalid boundary box')
        site = guardian.site
        if not all(math.isfinite(site[k]) for k in ('x', 'y', 'ground_z', 'radius_m')):
            raise ValueError('Landing coordinates must be finite')
        if site['radius_m'] <= 0 or not math.isfinite(guardian.margin) or guardian.margin < 0:
            raise ValueError('Invalid site radius or obstacle margin')
        return guardian

    def inside(self, position):
        return all(math.isfinite(v) for v in position) and all(
            self.bounds[a + '_min'] <= position[i] <= self.bounds[a + '_max']
            for i, a in enumerate('xyz'))

    def violations(self, position):
        reasons = []
        if not self.inside(position):
            reasons.append('outside_flight_bounds')
        if any(segment_hits_box(position, position, b, self.margin) for b in self.keepouts):
            reasons.append('inside_keepout_margin')
        return reasons

    def check_segment(self, start, end):
        if not self.inside(start) or not self.inside(end):
            return False, 'segment_outside_flight_bounds'
        if any(segment_hits_box(start, end, b, self.margin) for b in self.keepouts):
            return False, 'segment_intersects_keepout_margin'
        return True, 'accepted'

    def approach(self, cruise_z):
        return (self.site['x'], self.site['y'], cruise_z)

    def approve_landing(self, position, tolerance):
        if self.site.get('surveyed_clear') is not True:
            return False, 'landing_site_not_surveyed_clear'
        if math.hypot(position[0] - self.site['x'], position[1] - self.site['y']) > tolerance:
            return False, 'not_over_landing_site'
        if tolerance >= self.site['radius_m']:
            return False, 'landing_tolerance_exceeds_site_radius'
        ground = (position[0], position[1], self.site['ground_z'])
        if ground[2] < position[2]:
            return False, 'ground_above_vehicle_in_NED_frame'
        # Reserve a footprint as wide as the configured landing site throughout descent.
        radius = self.site['radius_m']
        for dx, dy in ((-radius, -radius), (-radius, radius), (radius, -radius), (radius, radius)):
            a = (position[0] + dx, position[1] + dy, position[2])
            b = (a[0], a[1], ground[2])
            if not self.inside(a) or not self.inside(b):
                return False, 'landing_corridor_outside_flight_bounds'
        for box in self.keepouts:
            padded = dict(box)
            for axis in 'xy':
                padded[axis + '_min'] -= radius
                padded[axis + '_max'] += radius
            if segment_hits_box(position, ground, padded, self.margin):
                return False, 'landing_corridor_intersects_keepout_margin'
        return True, 'accepted'
