"""Deterministic unbounded 2D square-grid mob positions, shared by both simulators.

The 20-yard spacing is Euclidean nearest-neighbour distance, not a one-
dimensional row. Geometry by itself does not simulate aggro, multi-enemy
swing schedules, or area damage; consumers must disclose those limitations.
"""
from __future__ import annotations
from dataclasses import dataclass
from functools import cached_property
from math import atan2, hypot, isfinite


@dataclass(frozen=True)
class SpacedPullLayout:
    mob_count: int
    spacing_yards: float = 20.0
    movement_speed_yards_s: float = 7.0
    melee_radius_yards: float = 5.0

    def __post_init__(self):
        if type(self.mob_count) is not int or self.mob_count < 1:
            raise ValueError('MOB_COUNT_MUST_BE_POSITIVE')
        for n in ('spacing_yards', 'movement_speed_yards_s', 'melee_radius_yards'):
            x = float(getattr(self, n))
            if not isfinite(x) or x < 0 or (n == 'movement_speed_yards_s' and x <= 0):
                raise ValueError('INVALID_SPACED_PULL_GEOMETRY_' + n.upper())

    @cached_property
    def positions_yards(self) -> tuple[tuple[float, float], ...]:
        """Square lattice at exactly `spacing_yards` pitch, expanding without a cap.

        Enumerate deterministic Chebyshev rings. The player starts next to
        (0,0); mobs outside aggro range are idle until approached or tagged.
        """
        points = [(0.0, 0.0)]
        side = float(self.spacing_yards)
        radius = 1
        while len(points) < self.mob_count:
            ring = [(side * q, side * r) for q in range(-radius, radius+1)
                    for r in range(-radius, radius+1)
                    if max(abs(q), abs(r)) == radius]
            ring.sort(key=lambda xy: (atan2(xy[1], xy[0]) % (2 * 3.141592653589793), xy))
            points.extend(ring[:self.mob_count-len(points)])
            radius += 1
        return tuple(points)

    def distance_yards(self, i: int, j: int) -> float:
        p = self.positions_yards
        return hypot(p[i][0] - p[j][0], p[i][1] - p[j][1])

    def targets_in_melee(self, actor_position: tuple[float, float] = (0., 0.)) -> tuple[int, ...]:
        if len(actor_position) != 2 or not all(isfinite(float(v)) for v in actor_position):
            raise ValueError('INVALID_ACTOR_POSITION')
        return tuple(i for i, (x, y) in enumerate(self.positions_yards)
                     if hypot(x - float(actor_position[0]), y - float(actor_position[1]))
                     <= float(self.melee_radius_yards) + 1e-9)

    def initial_melee_targets(self) -> tuple[int, ...]:
        return self.targets_in_melee()

    @cached_property
    def path_indices(self) -> tuple[int, ...]:
        """Greedy nearest-unvisited route from the first mob; deterministic ties."""
        route = [0]
        remaining = set(range(1, self.mob_count))
        while remaining:
            here = route[-1]
            nxt = min(remaining, key=lambda i: (self.distance_yards(here, i), i))
            route.append(nxt)
            remaining.remove(nxt)
        return tuple(route)

    @cached_property
    def segment_distances_yards(self) -> tuple[float, ...]:
        route = self.path_indices
        return tuple(self.distance_yards(i, j) for i, j in zip(route, route[1:]))

    @property
    def between_mob_travel_s(self) -> float:
        if self.mob_count < 2:
            return 0.0
        return self.segment_distances_yards[0] / float(self.movement_speed_yards_s)

    @property
    def sequential_travel_total_s(self) -> float:
        return sum(self.segment_distances_yards) / float(self.movement_speed_yards_s)

    @property
    def minimum_walk_to_tag_farthest_s(self) -> float:
        """Approach each mob within melee radius, optimistic path estimate.

        This is NOT a simultaneous pack assembly or threat model.
        """
        return sum(max(0., d - float(self.melee_radius_yards))
                   for d in self.segment_distances_yards) / float(self.movement_speed_yards_s)

    def as_dict(self) -> dict:
        return {'mob_positions_yards': self.positions_yards,
                'coordinate_system': '2D_EUCLIDEAN_SQUARE_LATTICE',
                'spacing_yards': self.spacing_yards,
                'movement_speed_yards_s': self.movement_speed_yards_s,
                'pull_route_indices': self.path_indices,
                'initial_melee_target_indices': self.initial_melee_targets(),
                'initial_max_melee_targets': len(self.initial_melee_targets()),
                'sequential_travel_total_s': self.sequential_travel_total_s,
                'minimum_walk_to_tag_farthest_s': self.minimum_walk_to_tag_farthest_s,
                'simultaneous_pack_assembled': False}
