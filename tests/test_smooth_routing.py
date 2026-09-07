"""
Geometric regression tests for ordered, oriented, localized centerline fairing.
"""

from __future__ import annotations

import math
from uuid import UUID

import pytest

from wire_bundler.routing import (
    CubicBezier,
    RoutePreview,
    TransitionAdjustment,
    TransitionLengths,
    Vector3,
    fair_route,
    sample_centerline,
    tightest_bend,
    transition_limits,
)
from wire_bundler.routing.geometry import cross, difference, dot, magnitude, unit


def _route(points: tuple[Vector3, ...]) -> RoutePreview:
    """
    Create a fixed-identity route without a Fusion host.
    """
    return RoutePreview(UUID(int=1), "001", points)


def _assert_parallel(left: Vector3, right: Vector3) -> None:
    """
    Compare directions independently of parameter speed.
    """
    assert magnitude(cross(unit(left), unit(right))) < 1e-10


def test_crossings_normals_and_tangent_continuity() -> None:
    """
    Visit every crossing exactly and preserve continuous tangents at all joins.
    """
    route = _route((Vector3(0, 0, 0), Vector3(10, 0, 20), Vector3(20, 10, 40), Vector3(20, 10, 60)))
    normals = (Vector3(0, 0, 1), Vector3(1, 0, 1), Vector3(0, 1, 2), Vector3(0, 0, 1))
    smooth = fair_route(route, normals)
    assert smooth.wire_id == route.wire_id
    assert smooth.points == route.points
    assert len(smooth.curves) == 9
    for index, normal in enumerate(normals):
        if index < len(normals) - 1:
            assert smooth.curves[index * 3].start == route.points[index]
            _assert_parallel(smooth.curves[index * 3].derivative(0.0), normal)
        if index > 0:
            assert smooth.curves[index * 3 - 1].end == route.points[index]
            _assert_parallel(smooth.curves[index * 3 - 1].derivative(1.0), normal)
    for left, right in zip(smooth.curves, smooth.curves[1:]):
        assert left.end == right.start
        assert dot(unit(left.derivative(1.0)), unit(right.derivative(0.0))) == pytest.approx(1.0)
    assert sample_centerline(smooth)[0] == route.points[0]
    assert sample_centerline(smooth)[-1] == route.points[-1]


def test_default_transitions_leave_straight_middle_half() -> None:
    """
    Localize curvature instead of distributing it across the whole span.
    """
    route = _route((Vector3(0, 0, 0), Vector3(0, 0, 40)))
    smooth = fair_route(route, (Vector3(1, 0, 1), Vector3(-1, 0, 1)))
    middle = smooth.curves[1]
    assert middle.start == Vector3(0, 0, 10)
    assert middle.end == Vector3(0, 0, 30)
    for parameter in (0.0, 0.25, 0.5, 0.75, 1.0):
        assert middle.point(parameter).x == 0.0
        assert middle.point(parameter).y == 0.0


def test_overlapping_explicit_transition_lengths_clamp_proportionally() -> None:
    """
    Project crowded explicit requests into the available span.
    """
    route = _route((Vector3(0, 0, 0), Vector3(0, 0, 12)))
    smooth = fair_route(
        route,
        (Vector3(1, 0, 1), Vector3(0, 1, 1)),
        (
            TransitionLengths(departure_mm=8),
            TransitionLengths(approach_mm=16),
        ),
    )
    assert smooth.curves[0].end.z == pytest.approx(4.0)
    assert smooth.curves[-1].start.z == pytest.approx(4.0)


def test_automatic_distance_contracts_only_to_safe_bend_floor() -> None:
    """
    Yield straight-middle space while retaining the diameter-derived minimum.
    """
    route = _route((Vector3(0, 0, 0), Vector3(0, 0, 10)))
    normals = (Vector3(1, 0, 1), Vector3(0, 0, 1))
    unit_limit = transition_limits(route, normals, 1.0)[0].departure_mm
    required_radius = 8.0 / unit_limit
    limits = transition_limits(route, normals, required_radius)
    smooth = fair_route(route, normals, minimum_bend_radius_mm=required_radius)
    assert limits[0].departure_mm == pytest.approx(8.0)
    assert smooth.curves[0].end.z == pytest.approx(8.0)
    assert smooth.curves[-1].start.z == pytest.approx(8.0)
    bend = tightest_bend(smooth, 1024)
    assert bend is not None and bend.radius_mm >= required_radius - 1e-9


def test_crowded_profile_span_uses_direct_dynamic_transition() -> None:
    """
    Fit the reported 1 mm wire case without splitting it at an artificial midpoint.
    """
    distance = 4.563
    angle = math.radians(64)
    normal = Vector3(math.sin(angle), 0, math.cos(angle))
    route = _route((Vector3(0, 0, 0), Vector3(0, 0, distance)))
    minimum_radius = 0.525
    limits = transition_limits(route, (normal, normal), minimum_radius)
    assert limits[0].departure_mm + limits[1].approach_mm == pytest.approx(5.062, abs=0.002)

    adjustments: list[TransitionAdjustment] = []
    smooth = fair_route(
        route,
        (normal, normal),
        minimum_bend_radius_mm=minimum_radius,
        adjustments=adjustments,
    )

    assert len(smooth.curves) == 1
    assert len(adjustments) == 1
    adjustment = adjustments[0]
    assert adjustment.wire_number == "001"
    assert (adjustment.start_profile, adjustment.end_profile) == (1, 2)
    assert adjustment.required_mm == pytest.approx(5.062, abs=0.002)
    assert adjustment.applied_mm == distance
    assert adjustment.minimum_bend_radius_mm == 0.525
    _assert_parallel(smooth.curves[0].derivative(0.0), normal)
    _assert_parallel(smooth.curves[0].derivative(1.0), normal)
    bend = tightest_bend(smooth, 1024)
    assert bend is not None and bend.radius_mm >= minimum_radius - 1e-9


def test_asymmetric_crowded_span_optimizes_endpoint_handles_independently() -> None:
    """
    Fit the reported 1.5 mm wire span when its profile turns are asymmetric.
    """
    distance = 4.912
    departure_angle = math.radians(45)
    approach_angle = math.radians(80)
    approach_azimuth = math.radians(45)
    departure_normal = Vector3(math.sin(departure_angle), 0, math.cos(departure_angle))
    approach_normal = Vector3(
        math.sin(approach_angle) * math.cos(approach_azimuth),
        math.sin(approach_angle) * math.sin(approach_azimuth),
        math.cos(approach_angle),
    )
    route = _route((Vector3(0, 0, 0), Vector3(0, 0, distance)))
    minimum_radius = 0.7875
    limits = transition_limits(route, (departure_normal, approach_normal), minimum_radius)
    assert limits[0].departure_mm + limits[1].approach_mm == pytest.approx(7.956, abs=0.002)

    adjustments: list[TransitionAdjustment] = []
    smooth = fair_route(
        route,
        (departure_normal, approach_normal),
        minimum_bend_radius_mm=minimum_radius,
        adjustments=adjustments,
    )

    assert len(smooth.curves) == 1
    assert len(adjustments) == 1
    curve = smooth.curves[0]
    departure_handle = magnitude(difference(curve.control_a, curve.start))
    approach_handle = magnitude(difference(curve.end, curve.control_b))
    assert departure_handle != pytest.approx(approach_handle)
    bend = tightest_bend(smooth, 1024)
    assert bend is not None and bend.radius_mm >= minimum_radius - 1e-9


def test_live_offset_equal_tangent_span_uses_s_bend() -> None:
    """
    Fit the complete 1.5 mm VCC route captured from Fusion.
    """
    route = _route(
        (
            Vector3(-16.6122925879, 29.3518725382, -6.0),
            Vector3(-16.6122925879, 29.3518725382, -2.0),
            Vector3(-12.7865552365, 31.984260039, 0.0),
            Vector3(-9.81461301949, 31.984260039, 14.1037396157),
            Vector3(1.34289390301, 35.266768325, 18.9097140137),
            Vector3(2.93184323646, 42.9180665072, 18.9097140137),
            Vector3(2.93184323646, 46.9180665072, 12.9097140137),
            Vector3(2.93184323646, 47.9180665072, -0.0902859863298),
            Vector3(3.23942610649, 47.5214505077, -6.0),
        )
    )
    normals = (
        Vector3(0.0, 0.0, 1.0),
        Vector3(0.0, 0.0, 1.0),
        Vector3(0.0, 0.0, 1.0),
        Vector3(0.573576436351, 0.0, 0.819152044289),
        Vector3(0.707106781187, 0.707106781187, 1.17756934401e-16),
        Vector3(-1.30860675791e-16, 0.906307787037, -0.422618261741),
        Vector3(1.25445795328e-16, 0.173648177667, -0.984807753012),
        Vector3(1.66533453694e-16, -4.99600361081e-16, -1.0),
        Vector3(0.0, 0.0, 1.0),
    )
    transitions = (
        TransitionLengths(1.0, 1.0),
        TransitionLengths(50.0, 50.0),
        TransitionLengths(100.0, 110.0),
        TransitionLengths(20.0, 20.0),
        TransitionLengths(20.0, 20.0),
        TransitionLengths(20.0, 20.0),
        TransitionLengths(20.0, 20.0),
        TransitionLengths(20.0, 20.0),
        TransitionLengths(20.0, 20.0),
    )
    adjustments: list[TransitionAdjustment] = []

    smooth = fair_route(
        route,
        normals,
        transitions,
        minimum_bend_radius_mm=0.7875,
        adjustments=adjustments,
    )

    s_bend = tuple(curve for curve in smooth.curves if curve.start == route.points[1])
    assert len(s_bend) == 1
    second_curve_index = smooth.curves.index(s_bend[0]) + 1
    assert smooth.curves[second_curve_index - 1].end == smooth.curves[second_curve_index].start
    middle_departure = unit(smooth.curves[second_curve_index - 1].derivative(1.0))
    middle_approach = unit(smooth.curves[second_curve_index].derivative(0.0))
    assert dot(middle_departure, middle_approach) == pytest.approx(1.0)
    bend = tightest_bend(smooth, 1024)
    assert bend is not None and bend.radius_mm >= 0.7875 - 1e-9
    assert adjustments


def test_matching_profile_normals_still_respect_off_axis_curvature() -> None:
    """
    Require bend space when equal endpoint normals are not aligned with the span.
    """
    route = _route((Vector3(0, 0, 0), Vector3(0, 0, 20)))
    limits = transition_limits(route, (Vector3(1, 0, 0), Vector3(1, 0, 0)), 1.0)
    assert limits[0].departure_mm > 0.0
    assert limits[1].approach_mm > 0.0


def test_flipping_sketch_normal_does_not_flip_the_route() -> None:
    """
    Resolve normal sign from traversal consistently for reversed sketch frames.
    """
    route = _route((Vector3(0, 0, 0), Vector3(5, 0, 10), Vector3(0, 0, 20)))
    positive = (Vector3(0, 0, 1),) * 3
    negative = (Vector3(0, 0, -1),) * 3
    assert fair_route(route, positive) == fair_route(route, negative)


def test_backtracking_order_is_preserved_when_geometry_allows_it() -> None:
    """
    Never choose the terminal or reorder guides using distance to a gate.
    """
    route = _route((Vector3(0, 0, 9), Vector3(0, 0, 1), Vector3(0, 0, 5), Vector3(0, 0, 10)))
    smooth = fair_route(route, (Vector3(1, 0, 0),) * 4)
    assert tuple(smooth.curves[index * 3].start for index in range(3)) == route.points[:-1]
    assert smooth.curves[-1].end == route.points[-1]


def test_impossible_collinear_reversal_is_reported_without_reordering() -> None:
    """
    Reject a one-dimensional cusp rather than manufacturing a silent loop.
    """
    route = _route((Vector3(0, 0, 9), Vector3(0, 0, 1), Vector3(0, 0, 5)))
    with pytest.raises(ValueError, match="reversal"):
        fair_route(route, (Vector3(0, 0, 1),) * 3)


@pytest.mark.parametrize("length", [-1.0, math.nan, math.inf])
def test_rejects_invalid_transition_lengths(length: float) -> None:
    """
    Reject invalid settings before constructing curves.
    """
    with pytest.raises(ValueError, match="Transition lengths"):
        fair_route(
            _route((Vector3(0, 0, 0), Vector3(0, 0, 10))),
            (Vector3(0, 0, 1),) * 2,
            (TransitionLengths(departure_mm=length), TransitionLengths()),
        )


def test_rejects_missing_normals_coincident_points_and_invalid_coordinates() -> None:
    """
    Give deterministic diagnostics instead of division errors or missing members.
    """
    route = _route((Vector3(0, 0, 0), Vector3(0, 0, 10)))
    with pytest.raises(ValueError, match="one profile normal"):
        fair_route(route, ())
    with pytest.raises(ValueError, match="nonzero"):
        fair_route(route, (Vector3(0, 0, 0), Vector3(0, 0, 1)))
    with pytest.raises(ValueError, match="coincide"):
        fair_route(_route((Vector3(0, 0, 0),) * 2), (Vector3(0, 0, 1),) * 2)
    with pytest.raises(ValueError, match="finite coordinates"):
        fair_route(_route((Vector3(math.nan, 0, 0), Vector3(0, 0, 10))), (Vector3(0, 0, 1),) * 2)


def _segment_distance(point: Vector3, left: Vector3, right: Vector3) -> float:
    """
    Measure a sample's distance to one rendered chord.
    """
    delta = difference(right, left)
    fraction = max(0.0, min(1.0, dot(difference(point, left), delta) / dot(delta, delta)))
    closest = left.translated(delta, fraction)
    return magnitude(difference(point, closest))


def test_adaptive_sampling_bounds_display_error_and_keeps_crossings() -> None:
    """
    Check dense analytic samples against the rendered polyline independently.
    """
    route = _route((Vector3(0, 0, 0), Vector3(0, 0, 100)))
    smooth = fair_route(route, (Vector3(1, 0, 0), Vector3(-1, 0, 1)))
    tolerance = 0.02
    sampled = sample_centerline(smooth, tolerance)
    assert len(sampled) > len(route.points)
    assert sampled == sample_centerline(smooth, tolerance)
    assert all(magnitude(difference(a, b)) > 0.0 for a, b in zip(sampled, sampled[1:]))
    for curve in smooth.curves:
        assert curve.start in sampled
        assert curve.end in sampled
        for index in range(101):
            point = curve.point(index / 100.0)
            error = min(_segment_distance(point, a, b) for a, b in zip(sampled, sampled[1:]))
            assert error <= tolerance


def test_tightest_bend_reports_exact_cubic_curvature_location() -> None:
    """
    Locate a symmetric cubic's tightest sampled radius at its midpoint.
    """
    route = _route((Vector3(0, 0, 0), Vector3(1, 0, 0)))
    route = RoutePreview(
        route.wire_id,
        route.wire_number,
        route.points,
        (
            CubicBezier(
                Vector3(0, 0, 0),
                Vector3(0, 1, 0),
                Vector3(1, 1, 0),
                Vector3(1, 0, 0),
            ),
        ),
    )
    bend = tightest_bend(route)
    assert bend is not None
    assert bend.curve_index == 0
    assert bend.parameter == pytest.approx(0.5)
    assert bend.radius_mm == pytest.approx(0.375)


def test_tightest_bend_handles_straight_curves_and_invalid_sampling() -> None:
    """
    Report infinite radius for a straight path and reject unusable sampling.
    """
    route = RoutePreview(
        UUID(int=1),
        "001",
        (Vector3(0, 0, 0), Vector3(3, 0, 0)),
        (
            CubicBezier(
                Vector3(0, 0, 0),
                Vector3(1, 0, 0),
                Vector3(2, 0, 0),
                Vector3(3, 0, 0),
            ),
        ),
    )
    bend = tightest_bend(route)
    assert bend is not None and math.isinf(bend.radius_mm)
    with pytest.raises(ValueError, match="at least two"):
        tightest_bend(route, 1)
