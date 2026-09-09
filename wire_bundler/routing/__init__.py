"""
Host-independent routing geometry and parallel-wire solvers.
"""

from .geometry import CubicBezier
from .parallel import (
    GateCapacityError,
    GateFrame,
    RoutePreview,
    Vector3,
    WireRouteInput,
    solve_parallel_routes,
)
from .smooth import (
    CIRCULAR_SWEEP_BEND_FACTOR,
    BendRadius,
    TransitionAdjustment,
    TransitionLengths,
    TransitionLimits,
    fair_route,
    minimum_circular_bend_radius,
    sample_centerline,
    tightest_bend,
    transition_limits,
)

__all__ = [
    "CubicBezier",
    "BendRadius",
    "CIRCULAR_SWEEP_BEND_FACTOR",
    "GateCapacityError",
    "GateFrame",
    "RoutePreview",
    "Vector3",
    "WireRouteInput",
    "solve_parallel_routes",
    "TransitionLengths",
    "TransitionAdjustment",
    "TransitionLimits",
    "fair_route",
    "minimum_circular_bend_radius",
    "sample_centerline",
    "tightest_bend",
    "transition_limits",
]
