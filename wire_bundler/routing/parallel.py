"""
Deterministic centerline routing through circular passage gates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID

from .geometry import CubicBezier, Vector3


@dataclass(frozen=True)
class GateFrame:
    """
    Describe a circular routing aperture in model coordinates.
    """

    gate_id: UUID
    name: str
    origin: Vector3
    u_direction: Vector3
    v_direction: Vector3
    usable_radius_mm: float


@dataclass(frozen=True)
class WireRouteInput:
    """
    Describe one wire requiring a route through shared gates.

    End guides run from each terminal toward the shared pathway.
    """

    wire_id: UUID
    wire_number: str
    start: Vector3
    end: Vector3
    diameter_mm: float
    start_guides: tuple[Vector3, ...] = ()
    end_guides: tuple[Vector3, ...] = ()


@dataclass(frozen=True)
class RoutePreview:
    """
    Store one lightweight centerline preview.

    Points retain traversal order; fairing may add exact local cubic transitions.
    """

    wire_id: UUID
    wire_number: str
    points: tuple[Vector3, ...]
    curves: tuple[CubicBezier, ...] = ()


class GateCapacityError(ValueError):
    """
    Report a gate that cannot contain every requested wire.
    """

    def __init__(self, gate: GateFrame, wire_count: int) -> None:
        """
        Initialize an actionable capacity error.
        """
        self.gate_id = gate.gate_id
        self.gate_name = gate.name
        self.wire_count = wire_count
        super().__init__(
            f"{gate.name} cannot fit {wire_count} wires inside its "
            f"{gate.usable_radius_mm * 2.0:g} mm usable diameter."
        )


def solve_parallel_routes(
    wires: tuple[WireRouteInput, ...],
    gates: tuple[GateFrame, ...],
    clearance_mm: float = 0.0,
) -> tuple[RoutePreview, ...]:
    """
    Pack wires at each circular gate and connect corresponding crossings.

    This milestone returns piecewise-linear centerlines. Curvature fairing is a
    later solver stage and does not change the persistent wire-to-slot mapping.

    Raises:
        ValueError: If input dimensions or frames are invalid.
        GateCapacityError: If any gate cannot contain the packed wires.
    """
    if not wires:
        raise ValueError("At least one wire is required for route preview.")
    if not gates:
        raise ValueError("At least one routing gate is required for route preview.")
    if not math.isfinite(clearance_mm) or clearance_mm < 0.0:
        raise ValueError("Wire clearance must be a finite non-negative value.")
    for wire in wires:
        if not math.isfinite(wire.diameter_mm) or wire.diameter_mm <= 0.0:
            raise ValueError(f"Wire {wire.wire_number} has an invalid diameter.")

    gate_crossings = tuple(_pack_gate(wires, gate, clearance_mm) for gate in gates)
    previews = tuple(
        RoutePreview(
            wire_id=wire.wire_id,
            wire_number=wire.wire_number,
            points=(
                wire.start,
                *wire.start_guides,
                *(crossings[index] for crossings in gate_crossings),
                *reversed(wire.end_guides),
                wire.end,
            ),
        )
        for index, wire in enumerate(wires)
    )
    return previews


def _pack_gate(
    wires: tuple[WireRouteInput, ...],
    gate: GateFrame,
    clearance_mm: float,
) -> tuple[Vector3, ...]:
    """
    Place input-ordered wire centers on a deterministic hexagonal lattice.
    """
    _validate_gate(gate)
    largest_radius = max(wire.diameter_mm for wire in wires) / 2.0
    spacing = largest_radius * 2.0 + clearance_mm
    offsets = _center_offsets(_hexagonal_offsets(len(wires), spacing))
    crossings: list[Vector3] = []
    for wire, (u_offset, v_offset) in zip(wires, offsets):
        center_distance = math.hypot(u_offset, v_offset)
        if center_distance + wire.diameter_mm / 2.0 > gate.usable_radius_mm + 1e-9:
            raise GateCapacityError(gate, len(wires))
        crossing = gate.origin.translated(gate.u_direction, u_offset).translated(
            gate.v_direction,
            v_offset,
        )
        crossings.append(crossing)
    return tuple(crossings)


def _hexagonal_offsets(count: int, spacing: float) -> tuple[tuple[float, float], ...]:
    """
    Return center-first points on concentric six-position lattice rings.
    """
    offsets: list[tuple[float, float]] = [(0.0, 0.0)]
    ring = 1
    while len(offsets) < count:
        axial_coordinates = (
            (q, r)
            for q in range(-ring, ring + 1)
            for r in range(-ring, ring + 1)
            if max(abs(q), abs(r), abs(-q - r)) == ring
        )
        ring_offsets = [
            (
                spacing * (q + r / 2.0),
                spacing * (math.sqrt(3.0) / 2.0 * r),
            )
            for q, r in axial_coordinates
        ]
        ring_offsets.sort(key=lambda offset: math.atan2(offset[1], offset[0]))
        offsets.extend(ring_offsets)
        ring += 1
    return tuple(offsets[:count])


def _center_offsets(
    offsets: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], ...]:
    """
    Center a partial lattice ring by its smallest enclosing circle.

    Centering preserves every wire-to-wire spacing while making the circular
    aperture test depend on the occupied bundle radius instead of the arbitrary
    center-first insertion origin.
    """
    center_u, center_v, _radius = _smallest_enclosing_circle(offsets)
    return tuple((u_offset - center_u, v_offset - center_v) for u_offset, v_offset in offsets)


def _smallest_enclosing_circle(
    points: tuple[tuple[float, float], ...],
) -> tuple[float, float, float]:
    """
    Return the deterministic minimum circle containing a small ordered point set.
    """
    circle = (0.0, 0.0, -1.0)
    for point_index, point in enumerate(points):
        if _circle_contains(circle, point):
            continue
        circle = (point[0], point[1], 0.0)
        for second_index, second in enumerate(points[:point_index]):
            if _circle_contains(circle, second):
                continue
            circle = _diameter_circle(point, second)
            for third in points[:second_index]:
                if _circle_contains(circle, third):
                    continue
                circle = _three_point_circle(point, second, third)
    return circle


def _diameter_circle(
    first: tuple[float, float], second: tuple[float, float]
) -> tuple[float, float, float]:
    """
    Return the circle whose diameter joins two points.
    """
    center_u = (first[0] + second[0]) / 2.0
    center_v = (first[1] + second[1]) / 2.0
    radius = math.hypot(first[0] - second[0], first[1] - second[1]) / 2.0
    return center_u, center_v, radius


def _three_point_circle(
    first: tuple[float, float],
    second: tuple[float, float],
    third: tuple[float, float],
) -> tuple[float, float, float]:
    """
    Return the circumcircle of three points, including collinear triples.
    """
    determinant = 2.0 * (
        first[0] * (second[1] - third[1])
        + second[0] * (third[1] - first[1])
        + third[0] * (first[1] - second[1])
    )
    if abs(determinant) <= 1e-12:
        candidates = (
            _diameter_circle(first, second),
            _diameter_circle(first, third),
            _diameter_circle(second, third),
        )
        enclosing = (
            candidate
            for candidate in candidates
            if all(_circle_contains(candidate, point) for point in (first, second, third))
        )
        return min(enclosing, key=lambda candidate: candidate[2])
    first_norm = first[0] * first[0] + first[1] * first[1]
    second_norm = second[0] * second[0] + second[1] * second[1]
    third_norm = third[0] * third[0] + third[1] * third[1]
    center_u = (
        first_norm * (second[1] - third[1])
        + second_norm * (third[1] - first[1])
        + third_norm * (first[1] - second[1])
    ) / determinant
    center_v = (
        first_norm * (third[0] - second[0])
        + second_norm * (first[0] - third[0])
        + third_norm * (second[0] - first[0])
    ) / determinant
    radius = math.hypot(center_u - first[0], center_v - first[1])
    return center_u, center_v, radius


def _circle_contains(circle: tuple[float, float, float], point: tuple[float, float]) -> bool:
    """
    Return whether a point lies inside a circle within numeric tolerance.
    """
    center_u, center_v, radius = circle
    return radius >= 0.0 and math.hypot(point[0] - center_u, point[1] - center_v) <= radius + 1e-9


def _validate_gate(gate: GateFrame) -> None:
    """
    Require a finite aperture and orthonormal in-plane directions.
    """
    values = (
        gate.origin.x,
        gate.origin.y,
        gate.origin.z,
        gate.u_direction.x,
        gate.u_direction.y,
        gate.u_direction.z,
        gate.v_direction.x,
        gate.v_direction.y,
        gate.v_direction.z,
        gate.usable_radius_mm,
    )
    if not all(math.isfinite(value) for value in values) or gate.usable_radius_mm <= 0.0:
        raise ValueError(f"{gate.name} has an invalid circular aperture.")
    u_length = _length(gate.u_direction)
    v_length = _length(gate.v_direction)
    dot_product = _dot(gate.u_direction, gate.v_direction)
    if not math.isclose(u_length, 1.0, abs_tol=1e-6):
        raise ValueError(f"{gate.name} has a non-unit U direction.")
    if not math.isclose(v_length, 1.0, abs_tol=1e-6):
        raise ValueError(f"{gate.name} has a non-unit V direction.")
    if not math.isclose(dot_product, 0.0, abs_tol=1e-6):
        raise ValueError(f"{gate.name} has non-orthogonal in-plane directions.")


def _length(vector: Vector3) -> float:
    """
    Return a vector magnitude.
    """
    return math.sqrt(_dot(vector, vector))


def _dot(left: Vector3, right: Vector3) -> float:
    """
    Return the scalar product of two vectors.
    """
    return left.x * right.x + left.y * right.y + left.z * right.z
