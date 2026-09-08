"""
Deterministic bounded local routing for physical members leaving a junction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from .geometry import Vector3, difference, dot, magnitude
from .parallel import RoutePreview
from .smooth import fair_route, minimum_circular_bend_radius, sample_centerline


@dataclass(frozen=True)
class JunctionRouteInput:
    """
    Describe one identity-preserving source-to-destination junction transition.
    """

    physical_wire_id: UUID
    wire_number: str
    source: Vector3
    destination: Vector3
    source_tangent: Vector3
    destination_tangent: Vector3
    diameter_mm: float


def route_junction_members(
    members: tuple[JunctionRouteInput, ...],
    clearance_mm: float = 0.0,
    envelope_center: Optional[Vector3] = None,
    envelope_radius_mm: Optional[float] = None,
) -> tuple[RoutePreview, ...]:
    """
    Route members in supplied order and reject simple transitions that collide.

    This intentionally performs no permutation or global weaving. Each member uses
    the established local cubic fairing primitive, after which sampled segments are
    checked for self-intersection, pairwise envelope collision, and optional bounded
    junction-envelope departure.
    """
    if not math.isfinite(clearance_mm) or clearance_mm < 0:
        raise ValueError("Junction clearance must be finite and nonnegative.")
    if (envelope_center is None) != (envelope_radius_mm is None):
        raise ValueError("Junction envelope requires both a center and radius.")
    if envelope_radius_mm is not None and (
        not math.isfinite(envelope_radius_mm) or envelope_radius_mm <= 0
    ):
        raise ValueError("Junction envelope radius must be finite and positive.")
    identities: set[UUID] = set()
    routes: list[RoutePreview] = []
    samples: list[tuple[Vector3, ...]] = []
    for member in members:
        if member.physical_wire_id in identities:
            raise ValueError("A junction member physical identity may appear only once.")
        identities.add(member.physical_wire_id)
        if not math.isfinite(member.diameter_mm) or member.diameter_mm <= 0:
            raise ValueError("Junction member diameter must be finite and positive.")
        base = RoutePreview(
            member.physical_wire_id,
            member.wire_number,
            (member.source, member.destination),
        )
        route = fair_route(
            base,
            (member.source_tangent, member.destination_tangent),
            minimum_bend_radius_mm=minimum_circular_bend_radius(member.diameter_mm),
        )
        route_samples = sample_centerline(route, tolerance_mm=0.02)
        _validate_self_intersection(route_samples)
        if envelope_center is not None and envelope_radius_mm is not None:
            usable_radius = envelope_radius_mm - member.diameter_mm / 2.0
            if usable_radius < 0 or any(
                magnitude(difference(point, envelope_center)) > usable_radius + 1e-9
                for point in route_samples
            ):
                raise ValueError(f"Wire {member.wire_number} leaves the bounded junction envelope.")
        routes.append(route)
        samples.append(route_samples)

    for first_index, first in enumerate(members):
        for second_index in range(first_index + 1, len(members)):
            second = members[second_index]
            required = (first.diameter_mm + second.diameter_mm) / 2.0 + clearance_mm
            if _polyline_distance(samples[first_index], samples[second_index]) < required - 1e-9:
                raise ValueError(
                    f"Junction routes for wires {first.wire_number} and "
                    f"{second.wire_number} collide."
                )
    return tuple(routes)


def _validate_self_intersection(points: tuple[Vector3, ...]) -> None:
    """
    Reject nonadjacent segments that fold back through the same wire envelope.
    """
    for first_index in range(len(points) - 1):
        for second_index in range(first_index + 2, len(points) - 1):
            if second_index == first_index + 1:
                continue
            distance = _segment_distance(
                points[first_index],
                points[first_index + 1],
                points[second_index],
                points[second_index + 1],
            )
            if distance < 1e-7:
                raise ValueError("A junction transition self-intersects.")


def _polyline_distance(
    first: tuple[Vector3, ...],
    second: tuple[Vector3, ...],
) -> float:
    """
    Return the minimum distance between two sampled centerline polylines.
    """
    return min(
        _segment_distance(first[index], first[index + 1], second[other], second[other + 1])
        for index in range(len(first) - 1)
        for other in range(len(second) - 1)
    )


def _segment_distance(
    first_start: Vector3,
    first_end: Vector3,
    second_start: Vector3,
    second_end: Vector3,
) -> float:
    """
    Return the closest distance between two finite three-dimensional segments.
    """
    first_direction = difference(first_end, first_start)
    second_direction = difference(second_end, second_start)
    offset = difference(first_start, second_start)
    first_length = dot(first_direction, first_direction)
    second_length = dot(second_direction, second_direction)
    cross_term = dot(first_direction, second_direction)
    first_offset = dot(first_direction, offset)
    second_offset = dot(second_direction, offset)
    denominator = first_length * second_length - cross_term * cross_term
    first_parameter = 0.0
    second_parameter = 0.0
    if first_length <= 1e-12 and second_length <= 1e-12:
        return magnitude(offset)
    if first_length <= 1e-12:
        second_parameter = min(1.0, max(0.0, second_offset / second_length))
    elif second_length <= 1e-12:
        first_parameter = min(1.0, max(0.0, -first_offset / first_length))
    elif denominator > 1e-12:
        first_parameter = min(
            1.0,
            max(0.0, (cross_term * second_offset - second_length * first_offset) / denominator),
        )
        second_parameter = (cross_term * first_parameter + second_offset) / second_length
        if second_parameter < 0.0:
            second_parameter = 0.0
            first_parameter = min(1.0, max(0.0, -first_offset / first_length))
        elif second_parameter > 1.0:
            second_parameter = 1.0
            first_parameter = min(
                1.0,
                max(0.0, (cross_term - first_offset) / first_length),
            )
    else:
        first_parameter = min(1.0, max(0.0, -first_offset / first_length))
        second_parameter = min(
            1.0,
            max(0.0, (cross_term * first_parameter + second_offset) / second_length),
        )
    first_point = first_start.translated(first_direction, first_parameter)
    second_point = second_start.translated(second_direction, second_parameter)
    return magnitude(difference(first_point, second_point))
