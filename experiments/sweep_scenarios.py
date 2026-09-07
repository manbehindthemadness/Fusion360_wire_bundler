"""
Reusable round-wire geometry cases for local and live Fusion verification.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from wire_bundler.routing import (
    RoutePreview,
    TransitionLengths,
    Vector3,
    minimum_circular_bend_radius,
)


@dataclass(frozen=True)
class SweepScenario:
    """
    Describe one deterministic centerline fairing and Sweep expectation.
    """

    name: str
    points: tuple[Vector3, ...]
    normals: tuple[Vector3, ...]
    diameter_mm: float
    expected_feasible: bool
    transitions: tuple[TransitionLengths, ...] = ()
    expected_error: str = ""
    expects_minimum_expansion: bool = False

    @property
    def wire_id(self) -> UUID:
        """
        Return a stable identity shared by local and Fusion-hosted runs.
        """
        return uuid5(NAMESPACE_URL, f"wire-bundler:sweep-scenario:{self.name}")

    @property
    def minimum_bend_radius_mm(self) -> float:
        """
        Include a small geometric margin above the circular profile radius.
        """
        return minimum_circular_bend_radius(self.diameter_mm)

    def route(self) -> RoutePreview:
        """
        Build the unsmoothed route consumed by the production fairer.
        """
        return RoutePreview(self.wire_id, self.name, self.points)


def sweep_scenarios() -> tuple[SweepScenario, ...]:
    """
    Return the common deterministic matrix in stable execution order.
    """
    return (
        SweepScenario(
            "straight",
            (Vector3(0, 0, 0), Vector3(0, 0, 30)),
            (Vector3(0, 0, 1), Vector3(0, 0, 1)),
            1.5,
            True,
        ),
        SweepScenario(
            "gentle_spatial",
            (
                Vector3(0, 0, 0),
                Vector3(5, 2, 15),
                Vector3(-3, 7, 32),
            ),
            (
                Vector3(0, 0, 1),
                Vector3(1, 1, 3),
                Vector3(0, 0, 1),
            ),
            1.5,
            True,
        ),
        SweepScenario(
            "three_stroke_180_zigzag",
            (
                Vector3(0, 0, 0),
                Vector3(0, 0, 40),
                Vector3(20, 0, 40),
                Vector3(20, 0, 0),
                Vector3(40, 0, 0),
                Vector3(40, 0, 40),
            ),
            (
                Vector3(0, 0, 1),
                Vector3(0, 0, 1),
                Vector3(0, 0, -1),
                Vector3(0, 0, -1),
                Vector3(0, 0, 1),
                Vector3(0, 0, 1),
            ),
            1.5,
            True,
        ),
        SweepScenario(
            "three_adjacent_180_pinches",
            (
                Vector3(0, 0, 0),
                Vector3(0, 0, 40),
                Vector3(15, 0, 40),
                Vector3(30, 0, 40),
                Vector3(45, 0, 40),
                Vector3(45, 0, 0),
            ),
            (
                Vector3(0, 0, 1),
                Vector3(0, 0, 1),
                Vector3(0, 0, -1),
                Vector3(0, 0, 1),
                Vector3(0, 0, -1),
                Vector3(0, 0, -1),
            ),
            1.5,
            True,
        ),
        SweepScenario(
            "asymmetric_crowded_span_1_5_mm",
            (Vector3(0, 0, 0), Vector3(0, 0, 4.912)),
            (
                Vector3(math.sin(math.radians(45)), 0, math.cos(math.radians(45))),
                Vector3(
                    math.sin(math.radians(80)) * math.cos(math.radians(45)),
                    math.sin(math.radians(80)) * math.sin(math.radians(45)),
                    math.cos(math.radians(80)),
                ),
            ),
            1.5,
            True,
        ),
        SweepScenario(
            "equal_tangent_offset_s_bend_1_5_mm",
            (
                Vector3(0, 0, 0),
                Vector3(3.8257373514, 2.6323875008, 2.0),
            ),
            (Vector3(0, 0, 1), Vector3(0, 0, 1)),
            1.5,
            True,
            transitions=(
                TransitionLengths(50.0, 50.0),
                TransitionLengths(100.0, 110.0),
            ),
        ),
        SweepScenario(
            "diameter_expands_auto",
            (Vector3(0, 0, 0), Vector3(0, 0, 10)),
            (Vector3(1, 0, 1), Vector3(0, 0, 1)),
            4.0,
            True,
            expects_minimum_expansion=True,
        ),
        SweepScenario(
            "explicit_below_minimum_clamps",
            (Vector3(0, 0, 0), Vector3(0, 0, 10)),
            (Vector3(1, 0, 1), Vector3(0, 0, 1)),
            4.0,
            True,
            transitions=(
                TransitionLengths(departure_mm=0.5),
                TransitionLengths(),
            ),
            expects_minimum_expansion=True,
        ),
        SweepScenario(
            "short_span_impossible",
            (Vector3(0, 0, 0), Vector3(0, 0, 3)),
            (Vector3(1, 0, 1), Vector3(0, 1, 1)),
            4.0,
            False,
            expected_error="but only 3.000 mm is available",
        ),
    )
