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
from .smooth import TransitionLengths, fair_route, sample_centerline

__all__ = [
    "CubicBezier",
    "GateCapacityError",
    "GateFrame",
    "RoutePreview",
    "Vector3",
    "WireRouteInput",
    "solve_parallel_routes",
    "TransitionLengths",
    "fair_route",
    "sample_centerline",
]
