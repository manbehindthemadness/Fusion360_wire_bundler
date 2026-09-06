"""
Geometric regression tests for ordered, oriented, localized centerline fairing.
"""

from __future__ import annotations

import math
from uuid import UUID

import pytest

from wire_bundler.routing import (
    RoutePreview,
    TransitionLengths,
    Vector3,
    fair_route,
    sample_centerline,
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


def test_independent_transition_lengths_clamp_without_overlap() -> None:
    """
    Fit asymmetric requested lengths into the span while retaining their ratio.
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
    assert len(smooth.curves) == 2
    assert smooth.curves[0].end == Vector3(0, 0, 4)
    assert smooth.curves[0].end == smooth.curves[1].start
    _assert_parallel(smooth.curves[0].derivative(1.0), smooth.curves[1].derivative(0.0))


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
