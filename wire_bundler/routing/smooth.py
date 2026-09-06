"""
Localized cubic transitions through explicitly ordered, oriented routing profiles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Optional

from .geometry import CubicBezier, Vector3, cross, difference, dot, lerp, magnitude, unit
from .parallel import RoutePreview

CIRCULAR_SWEEP_BEND_FACTOR = 1.05


@dataclass(frozen=True)
class TransitionLengths:
    """
    Request independent approach/departure lengths; None starts at a quarter-span.
    """

    approach_mm: Optional[float] = None
    departure_mm: Optional[float] = None


@dataclass(frozen=True)
class BendRadius:
    """
    Locate the tightest sampled bend on an exact centerline curve.
    """

    curve_index: int
    parameter: float
    radius_mm: float


@dataclass(frozen=True)
class TransitionLimits:
    """
    Store minimum safe interpolation distances at one ordered route crossing.
    """

    approach_mm: float = 0.0
    departure_mm: float = 0.0


@dataclass(frozen=True)
class TransitionAdjustment:
    """
    Describe one geometry-specific transition reduced to fit its route span.
    """

    wire_number: str
    start_profile: int
    end_profile: int
    required_mm: float
    applied_mm: float
    minimum_bend_radius_mm: float


def minimum_circular_bend_radius(diameter_mm: float) -> float:
    """
    Return the guarded geometric radius required by a circular solid Sweep.
    """
    if not math.isfinite(diameter_mm) or diameter_mm <= 0.0:
        raise ValueError("Wire diameter must be finite and positive.")
    return diameter_mm * 0.5 * CIRCULAR_SWEEP_BEND_FACTOR


def fair_route(
    route: RoutePreview,
    normals: tuple[Vector3, ...],
    transitions: tuple[TransitionLengths, ...] = (),
    minimum_bend_radius_mm: float = 0.0,
    adjustments: Optional[list[TransitionAdjustment]] = None,
) -> RoutePreview:
    """
    Preserve crossings and connect them with tangent-continuous local transitions.

    Normal signs follow stored traversal, never reorder points. Automatic
    transitions each occupy a quarter-span, retaining a straight middle half.
    All lengths clamp to the nearest proportional fit above their safe minima
    when a span is crowded.
    """
    points = route.points
    if len(points) < 2 or len(normals) != len(points):
        raise ValueError("Every route crossing needs one profile normal.")
    if any(not math.isfinite(value) for point in points for value in (point.x, point.y, point.z)):
        raise ValueError("Route crossings must have finite coordinates.")
    _validate_route_spans(route)
    if transitions and len(transitions) != len(points):
        raise ValueError("Every crossing needs one pair of transition lengths.")
    if not math.isfinite(minimum_bend_radius_mm) or minimum_bend_radius_mm < 0.0:
        raise ValueError("Minimum bend radius must be finite and non-negative.")
    lengths = transitions or tuple(TransitionLengths() for _ in points)
    for requested in lengths:
        for value in (requested.approach_mm, requested.departure_mm):
            if value is not None and (not math.isfinite(value) or value < 0.0):
                raise ValueError("Transition lengths must be finite and non-negative.")
    tangents = tuple(
        _oriented_normal(points, index, normal) for index, normal in enumerate(normals)
    )
    limits = _transition_limits(route, tangents, minimum_bend_radius_mm)
    curves: list[CubicBezier] = []
    for index, (start, end) in enumerate(zip(points, points[1:])):
        delta = difference(end, start)
        distance = magnitude(delta)
        if not math.isfinite(distance) or distance <= 1e-9:
            raise ValueError(
                f"Wire {route.wire_number}: consecutive profiles {index + 1} and {index + 2} coincide."
            )
        direction = unit(delta)
        minimum_departure = limits[index].departure_mm
        minimum_approach = limits[index + 1].approach_mm
        if minimum_departure + minimum_approach > distance + 1e-9:
            direct = _direct_span_transition(
                start,
                end,
                tangents[index],
                tangents[index + 1],
                minimum_bend_radius_mm,
            )
            if direct is not None:
                curves.append(direct)
                if adjustments is not None:
                    adjustments.append(
                        TransitionAdjustment(
                            route.wire_number,
                            index + 1,
                            index + 2,
                            minimum_departure + minimum_approach,
                            distance,
                            minimum_bend_radius_mm,
                        )
                    )
                continue
        departure, approach = _resolve_span_lengths(
            route.wire_number,
            index,
            distance,
            lengths[index].departure_mm,
            lengths[index + 1].approach_mm,
            minimum_departure,
            minimum_approach,
        )
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


def _direct_span_transition(
    start: Vector3,
    end: Vector3,
    start_tangent: Vector3,
    end_tangent: Vector3,
    minimum_bend_radius_mm: float,
) -> Optional[CubicBezier]:
    """
    Fit one cubic across a crowded span without an artificial middle tangent.

    The localized construction normally turns each profile tangent toward the
    span direction independently. When those two regions do not fit, a direct
    Hermite-style cubic can use the complete span and still retain both profile
    tangents and the circular sweep radius.
    """
    delta = difference(end, start)
    distance = magnitude(delta)
    direction = unit(delta)
    best_curve: Optional[CubicBezier] = None
    best_radius = -1.0
    for step in range(5, 101):
        handle_length = distance * step / 100.0
        candidate = CubicBezier(
            start,
            start.translated(start_tangent, handle_length),
            end.translated(end_tangent, -handle_length),
            end,
        )
        if any(dot(candidate.derivative(sample / 64.0), direction) < -1e-9 for sample in range(65)):
            continue
        radius = _minimum_sampled_radius(candidate, 1024)
        if radius > best_radius:
            best_curve = candidate
            best_radius = radius
    if best_curve is None or best_radius + 1e-9 < minimum_bend_radius_mm:
        return None
    return best_curve


def transition_limits(
    route: RoutePreview,
    normals: tuple[Vector3, ...],
    minimum_bend_radius_mm: float,
) -> tuple[TransitionLimits, ...]:
    """
    Calculate per-crossing interpolation floors for one circular wire route.
    """
    if len(route.points) < 2 or len(normals) != len(route.points):
        raise ValueError("Every route crossing needs one profile normal.")
    if not math.isfinite(minimum_bend_radius_mm) or minimum_bend_radius_mm < 0.0:
        raise ValueError("Minimum bend radius must be finite and non-negative.")
    _validate_route_spans(route)
    tangents = tuple(
        _oriented_normal(route.points, index, normal) for index, normal in enumerate(normals)
    )
    return _transition_limits(route, tangents, minimum_bend_radius_mm)


def _validate_route_spans(route: RoutePreview) -> None:
    """
    Reject non-finite or coincident crossings before tangent-dependent calculations.
    """
    for index, (start, end) in enumerate(zip(route.points, route.points[1:])):
        distance = magnitude(difference(end, start))
        if not math.isfinite(distance) or distance <= 1e-9:
            raise ValueError(
                f"Wire {route.wire_number}: consecutive profiles {index + 1} and "
                f"{index + 2} coincide."
            )


def _transition_limits(
    route: RoutePreview,
    tangents: tuple[Vector3, ...],
    minimum_bend_radius_mm: float,
) -> tuple[TransitionLimits, ...]:
    """
    Resolve minimum approach and departure distances from local tangent changes.
    """
    approaches = [0.0] * len(route.points)
    departures = [0.0] * len(route.points)
    for index, (start, end) in enumerate(zip(route.points, route.points[1:])):
        direction = unit(difference(end, start))
        departures[index] = _minimum_transition_length(
            direction,
            tangents[index],
            direction,
            minimum_bend_radius_mm,
            route.wire_number,
        )
        approaches[index + 1] = _minimum_transition_length(
            direction,
            direction,
            tangents[index + 1],
            minimum_bend_radius_mm,
            route.wire_number,
        )
    return tuple(
        TransitionLimits(approach, departure) for approach, departure in zip(approaches, departures)
    )


def _minimum_transition_length(
    chord_direction: Vector3,
    start_tangent: Vector3,
    end_tangent: Vector3,
    minimum_bend_radius_mm: float,
    wire_number: str,
) -> float:
    """
    Scale the canonical cubic until its sampled minimum radius reaches the target.
    """
    start_alignment = dot(start_tangent, chord_direction)
    end_alignment = dot(end_tangent, chord_direction)
    if minimum_bend_radius_mm == 0.0:
        return 0.0
    if min(start_alignment, end_alignment) <= -1.0 + 1e-9:
        raise ValueError(
            f"Wire {wire_number}: profile order and normals force a reversal; "
            "adjust their order or orientation."
        )
    if min(start_alignment, end_alignment) >= 1.0 - 1e-9:
        return 0.0
    origin = Vector3(0.0, 0.0, 0.0)
    end = chord_direction
    curve = CubicBezier(
        origin,
        origin.translated(start_tangent, 1.0 / 3.0),
        end.translated(end_tangent, -1.0 / 3.0),
        end,
    )
    unit_radius = _minimum_sampled_radius(curve, 1024)
    if not math.isfinite(unit_radius) or unit_radius <= 1e-12:
        raise ValueError(f"Wire {wire_number}: transition curvature cannot be bounded.")
    return minimum_bend_radius_mm / unit_radius


def _resolve_span_lengths(
    wire_number: str,
    span_index: int,
    distance: float,
    requested_departure: Optional[float],
    requested_approach: Optional[float],
    minimum_departure: float,
    minimum_approach: float,
) -> tuple[float, float]:
    """
    Project requested distances into a span without reducing physical safety floors.
    """
    minimum_total = minimum_departure + minimum_approach
    if minimum_total > distance + 1e-9:
        raise ValueError(
            f"Wire {wire_number}: transitions between profiles {span_index + 1} and "
            f"{span_index + 2} require {minimum_total:.3f} mm but only "
            f"{distance:.3f} mm is available."
        )
    requested = (requested_departure, requested_approach)
    minima = (minimum_departure, minimum_approach)
    resolved: list[float] = []
    for value, minimum in zip(requested, minima):
        resolved.append(max(distance * 0.25 if value is None else value, minimum))
    total = sum(resolved)
    if total <= distance + 1e-9:
        return resolved[0], resolved[1]
    excess = total - distance
    reducible = sum(resolved[index] - minima[index] for index in range(2))
    if reducible > 0.0:
        remaining_fraction = max(0.0, (reducible - excess) / reducible)
        for index in range(2):
            extra = resolved[index] - minima[index]
            resolved[index] = minima[index] + extra * remaining_fraction
    return resolved[0], resolved[1]


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


def tightest_bend(route: RoutePreview, samples_per_curve: int = 256) -> Optional[BendRadius]:
    """
    Estimate the minimum spatial radius without invoking the Fusion kernel.

    The diagnostic samples exact cubic derivatives uniformly. It does not certify
    global tube clearance, but it locates local curvature likely to reject a sweep.
    """
    if samples_per_curve < 2:
        raise ValueError("Bend diagnostics require at least two samples per curve.")
    tightest: Optional[BendRadius] = None
    for curve_index, curve in enumerate(route.curves):
        for sample_index in range(samples_per_curve + 1):
            parameter = sample_index / samples_per_curve
            radius = _curvature_radius(curve, parameter)
            candidate = BendRadius(curve_index, parameter, radius)
            if tightest is None or candidate.radius_mm < tightest.radius_mm:
                tightest = candidate
    return tightest


def _minimum_sampled_radius(curve: CubicBezier, samples: int) -> float:
    """
    Return the tightest radius found on one exact cubic, including both endpoints.
    """
    return min(_curvature_radius(curve, index / samples) for index in range(samples + 1))


def _curvature_radius(curve: CubicBezier, parameter: float) -> float:
    """
    Evaluate spatial radius of curvature at one cubic parameter.
    """
    tangent = curve.derivative(parameter)
    speed = magnitude(tangent)
    if speed <= 1e-12:
        return 0.0
    normal = cross(tangent, curve.second_derivative(parameter))
    denominator = magnitude(normal)
    return math.inf if denominator <= 1e-12 else speed * speed * speed / denominator


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
