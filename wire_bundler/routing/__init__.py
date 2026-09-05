"""
Host-independent routing geometry and parallel-wire solvers.
"""

from .parallel import (
    GateCapacityError,
    GateFrame,
    RoutePreview,
    Vector3,
    WireRouteInput,
    solve_parallel_routes,
)

__all__ = [
    "GateCapacityError",
    "GateFrame",
    "RoutePreview",
    "Vector3",
    "WireRouteInput",
    "solve_parallel_routes",
]
