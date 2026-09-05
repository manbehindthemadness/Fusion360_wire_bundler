"""
Deterministic centerline routing through circular passage gates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Vector3:
    """
    Store one point or direction in millimeters.

    Args:
        x: X coordinate.
        y: Y coordinate.
        z: Z coordinate.
    """

    x: float
    y: float
    z: float

    def translated(self, direction: Vector3, distance: float) -> Vector3:
        """
        Return this point translated along a direction.

        Args:
            direction: Translation direction.
            distance: Signed translation distance.

        Returns:
            Translated point.
        """
        return Vector3(
            self.x + direction.x * distance,
            self.y + direction.y * distance,
            self.z + direction.z * distance,
        )


@dataclass(frozen=True)
class GateFrame:
    """
    Describe a circular routing aperture in model coordinates.

    Args:
        gate_id: Persistent routing-control identity.
        name: User-facing gate name.
        origin: Aperture center in millimeters.
        u_direction: Unit direction along the local gate X axis.
        v_direction: Unit direction along the local gate Y axis.
        usable_radius_mm: Circular usable aperture radius.
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

    Args:
        wire_id: Persistent conductor identity.
        wire_number: Stable user-facing identifier.
        start: Source-profile center in millimeters.
        end: Destination-profile center in millimeters.
        diameter_mm: Finished wire diameter.
    """

    wire_id: UUID
    wire_number: str
    start: Vector3
    end: Vector3
    diameter_mm: float


@dataclass(frozen=True)
class RoutePreview:
    """
    Store one lightweight centerline preview.

    Args:
        wire_id: Persistent conductor identity.
        wire_number: Stable user-facing identifier.
        points: Source, ordered gate crossings, and destination.
    """

    wire_id: UUID
    wire_number: str
    points: tuple[Vector3, ...]


class GateCapacityError(ValueError):
    """
    Report a gate that cannot contain every requested wire.
    """

    def __init__(self, gate: GateFrame, wire_count: int) -> None:
        """
        Initialize an actionable capacity error.

        Args:
            gate: Gate whose usable circular aperture is too small.
            wire_count: Number of wires requested at the gate.
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

    Args:
        wires: Wires in stable packing order.
        gates: Circular routing gates in traversal order.
        clearance_mm: Additional edge-to-edge separation between wires.

    Returns:
        One ordered point sequence per wire.

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
                *(crossings[index] for crossings in gate_crossings),
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
    Place wire centers on a deterministic hexagonal lattice at one gate.

    Args:
        wires: Wires in stable packing order.
        gate: Circular aperture and local coordinate frame.
        clearance_mm: Additional edge-to-edge wire separation.

    Returns:
        Model-space crossing points corresponding to the input wires.
    """
    _validate_gate(gate)
    largest_radius = max(wire.diameter_mm for wire in wires) / 2.0
    spacing = largest_radius * 2.0 + clearance_mm
    offsets = _hexagonal_offsets(len(wires), spacing)
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

    Args:
        count: Number of offsets required.
        spacing: Center-to-center lattice spacing.

    Returns:
        Local gate-plane offsets in deterministic order.
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


def _validate_gate(gate: GateFrame) -> None:
    """
    Require a finite aperture and orthonormal in-plane directions.

    Args:
        gate: Gate frame to validate.
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

    Args:
        vector: Vector to measure.

    Returns:
        Euclidean magnitude.
    """
    return math.sqrt(_dot(vector, vector))


def _dot(left: Vector3, right: Vector3) -> float:
    """
    Return the scalar product of two vectors.

    Args:
        left: First vector.
        right: Second vector.

    Returns:
        Scalar product.
    """
    return left.x * right.x + left.y * right.y + left.z * right.z
