"""
Localized cubic transitions through explicitly ordered, oriented routing profiles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Optional

from .geometry import CubicBezier, Vector3, difference, dot, lerp, magnitude, unit
from .parallel import RoutePreview


@dataclass(frozen=True)
class TransitionLengths:
    """
    Request independent approach/departure lengths; None uses a quarter of the span.
    """

    approach_mm: Optional[float] = None
    departure_mm: Optional[float] = None


def fair_route(
    route: RoutePreview,
    normals: tuple[Vector3, ...],
    transitions: tuple[TransitionLengths, ...] = (),
) -> RoutePreview:
    """
    Preserve crossings and connect them with tangent-continuous local transitions.

    Normal signs follow stored traversal, never reorder points. Automatic
    transitions each occupy a quarter-span, retaining a straight middle half.
    Explicit lengths are proportionally clamped when their sum exceeds the span.
    """
    points = route.points
    if len(points) < 2 or len(normals) != len(points):
        raise ValueError("Every route crossing needs one profile normal.")
    if any(not math.isfinite(value) for point in points for value in (point.x, point.y, point.z)):
        raise ValueError("Route crossings must have finite coordinates.")
    if transitions and len(transitions) != len(points):
        raise ValueError("Every crossing needs one pair of transition lengths.")
    lengths = transitions or tuple(TransitionLengths() for _ in points)
    for requested in lengths:
        for value in (requested.approach_mm, requested.departure_mm):
            if value is not None and (not math.isfinite(value) or value < 0.0):
                raise ValueError("Transition lengths must be finite and non-negative.")
    tangents = tuple(
        _oriented_normal(points, index, normal) for index, normal in enumerate(normals)
    )
    curves: list[CubicBezier] = []
    for index, (start, end) in enumerate(zip(points, points[1:])):
        delta = difference(end, start)
        distance = magnitude(delta)
        if not math.isfinite(distance) or distance <= 1e-9:
            raise ValueError(
                f"Wire {route.wire_number}: consecutive profiles {index + 1} and {index + 2} coincide."
            )
        direction = unit(delta)
        departure = lengths[index].departure_mm
        approach = lengths[index + 1].approach_mm
        departure = distance * 0.25 if departure is None else departure
        approach = distance * 0.25 if approach is None else approach
        largest = max(departure, approach)
        if largest > 0.0 and (departure / largest + approach / largest) > distance / largest:
            scale = (distance / largest) / (departure / largest + approach / largest)
            departure *= scale
            approach *= scale
        left = start.translated(direction, departure)
        right = end.translated(direction, -approach)
        if magnitude(difference(right, left)) <= 1e-9:
            right = left
        curves.extend(
            _transition(start, left, tangents[index], direction, departure, route.wire_number)
        )
        if magnitude(difference(right, left)) > 1e-9:
            curves.append(
                CubicBezier(left, lerp(left, right, 1.0 / 3.0), lerp(left, right, 2.0 / 3.0), right)
            )
        curves.extend(
            _transition(right, end, direction, tangents[index + 1], approach, route.wire_number)
        )
    return replace(route, curves=tuple(curves))


def _oriented_normal(points: tuple[Vector3, ...], index: int, normal: Vector3) -> Vector3:
    """
    Choose the normal's sign along the stored local traversal without sorting it.
    """
    direction = unit(normal)
    before = points[max(0, index - 1)]
    after = points[min(len(points) - 1, index + 1)]
    references = (
        difference(after, before),
        difference(after, points[index]),
        difference(points[index], before),
    )
    for reference in references:
        projection = dot(direction, reference)
        if abs(projection) > 1e-9:
            return (
                direction if projection > 0.0 else Vector3(-direction.x, -direction.y, -direction.z)
            )
    for component in (direction.x, direction.y, direction.z):
        if abs(component) > 1e-9:
            return (
                direction if component > 0.0 else Vector3(-direction.x, -direction.y, -direction.z)
            )
    raise ValueError("A route profile has no usable normal.")


def _transition(
    start: Vector3,
    end: Vector3,
    start_tangent: Vector3,
    end_tangent: Vector3,
    length: float,
    wire_number: str,
) -> tuple[CubicBezier, ...]:
    """
    Construct a bounded cubic or reject an unavoidable collinear reversal/cusp.
    """
    if length == 0.0:
        if dot(start_tangent, end_tangent) < 1.0 - 1e-9:
            raise ValueError(
                f"Wire {wire_number}: a direction change needs a positive transition length."
            )
        return ()
    direction = unit(difference(end, start))
    if min(dot(start_tangent, direction), dot(end_tangent, direction)) <= -1.0 + 1e-9:
        raise ValueError(
            f"Wire {wire_number}: profile order and normals force a reversal; adjust their order or orientation."
        )
    curve = CubicBezier(
        start,
        start.translated(start_tangent, length / 3.0),
        end.translated(end_tangent, -length / 3.0),
        end,
    )
    return (curve,)


def sample_centerline(route: RoutePreview, tolerance_mm: float = 0.05) -> tuple[Vector3, ...]:
    """
    Tessellate exact cubics to a bounded chord error for lightweight graphics.
    """
    if not math.isfinite(tolerance_mm) or tolerance_mm <= 0.0:
        raise ValueError("Preview tolerance must be finite and positive.")
    if not route.curves:
        return route.points
    points = [route.curves[0].start]
    for curve in route.curves:
        _sample_curve(curve, tolerance_mm, points, 0)
    return tuple(points)


def _sample_curve(curve: CubicBezier, tolerance: float, points: list[Vector3], depth: int) -> None:
    """
    Subdivide until the control hull lies within tolerance of the chord segment.
    """
    flatness = max(
        _chord_distance(curve.control_a, curve.start, curve.end),
        _chord_distance(curve.control_b, curve.start, curve.end),
    )
    if flatness <= tolerance:
        points.append(curve.end)
        return
    if depth >= 16:
        raise ValueError("Preview curve exceeds the subdivision budget; increase the tolerance.")
    first = lerp(curve.start, curve.control_a, 0.5)
    middle = lerp(curve.control_a, curve.control_b, 0.5)
    last = lerp(curve.control_b, curve.end, 0.5)
    left = lerp(first, middle, 0.5)
    right = lerp(middle, last, 0.5)
    center = lerp(left, right, 0.5)
    _sample_curve(CubicBezier(curve.start, first, left, center), tolerance, points, depth + 1)
    _sample_curve(CubicBezier(center, right, last, curve.end), tolerance, points, depth + 1)


def _chord_distance(point: Vector3, start: Vector3, end: Vector3) -> float:
    """
    Measure distance to the finite chord, including degenerate endpoints.
    """
    delta = difference(end, start)
    length_squared = dot(delta, delta)
    if length_squared <= 1e-24:
        return magnitude(difference(point, start))
    fraction = max(0.0, min(1.0, dot(difference(point, start), delta) / length_squared))
    return magnitude(difference(point, lerp(start, end, fraction)))
