"""
Tests for deterministic bounded local junction transitions.
"""

from uuid import UUID

import pytest

from wire_bundler.routing import JunctionRouteInput, Vector3, route_junction_members


def _member(identity: int, y_start: float, y_end: float) -> JunctionRouteInput:
    """
    Build one left-to-right junction member for focused geometry tests.
    """
    return JunctionRouteInput(
        UUID(int=identity),
        f"00{identity}",
        Vector3(0.0, y_start, 0.0),
        Vector3(20.0, y_end, 0.0),
        Vector3(1.0, 0.0, 0.0),
        Vector3(1.0, 0.0, 0.0),
        1.0,
    )


def test_junction_router_preserves_member_order_and_identity() -> None:
    """
    Keep selected source-to-destination correspondence without permutation.
    """
    members = (_member(2, 2.0, 3.0), _member(1, -2.0, -3.0))

    routes = route_junction_members(members, clearance_mm=0.25)

    assert tuple(route.wire_id for route in routes) == tuple(
        member.physical_wire_id for member in members
    )
    assert all(route.curves for route in routes)


def test_junction_router_rejects_crossing_member_envelopes() -> None:
    """
    Fail explicitly when simple order-preserving transitions cross.
    """
    with pytest.raises(ValueError, match="collide"):
        route_junction_members((_member(1, -2.0, 2.0), _member(2, 2.0, -2.0)))


def test_junction_router_rejects_departure_from_bounded_region() -> None:
    """
    Report a transition whose tube cannot stay inside its local envelope.
    """
    with pytest.raises(ValueError, match="bounded junction envelope"):
        route_junction_members(
            (_member(1, 0.0, 0.0),),
            envelope_center=Vector3(10.0, 0.0, 0.0),
            envelope_radius_mm=5.0,
        )
