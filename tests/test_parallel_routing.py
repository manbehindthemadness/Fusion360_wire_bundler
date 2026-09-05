"""
Tests for deterministic parallel-wire route previews.
"""

from __future__ import annotations

import math
from uuid import UUID

import pytest

from wire_bundler.routing import (
    GateCapacityError,
    GateFrame,
    Vector3,
    WireRouteInput,
    solve_parallel_routes,
)


def _wire(index: int, diameter_mm: float = 1.5) -> WireRouteInput:
    """
    Create one deterministic routing input.
    """
    return WireRouteInput(
        wire_id=UUID(f"10000000-0000-0000-0000-{index:012d}"),
        wire_number=f"{index:03d}",
        start=Vector3(float(index), 0.0, 0.0),
        end=Vector3(float(index), 0.0, 30.0),
        diameter_mm=diameter_mm,
    )


def _gate(index: int, radius_mm: float = 8.0) -> GateFrame:
    """
    Create one XY-plane routing gate.
    """
    return GateFrame(
        gate_id=UUID(f"20000000-0000-0000-0000-{index:012d}"),
        name=f"Gate {index}",
        origin=Vector3(0.0, 0.0, float(index * 10)),
        u_direction=Vector3(1.0, 0.0, 0.0),
        v_direction=Vector3(0.0, 1.0, 0.0),
        usable_radius_mm=radius_mm,
    )


def test_preserves_wire_and_gate_order_in_preview() -> None:
    """
    Keep endpoint pairing and corresponding packed slots stable through every gate.
    """
    wires = tuple(_wire(index) for index in range(1, 4))
    gates = (_gate(1), _gate(2))

    routes = solve_parallel_routes(wires, gates)

    assert [route.wire_id for route in routes] == [wire.wire_id for wire in wires]
    assert all(len(route.points) == 4 for route in routes)
    assert [route.points[0] for route in routes] == [wire.start for wire in wires]
    assert [route.points[-1] for route in routes] == [wire.end for wire in wires]
    for wire_index in range(len(wires)):
        first_offset = routes[wire_index].points[1]
        second_offset = routes[wire_index].points[2]
        assert first_offset.x == pytest.approx(second_offset.x)
        assert first_offset.y == pytest.approx(second_offset.y)


def test_maintains_required_wire_clearance_at_gate() -> None:
    """
    Keep every pair of swept circular envelopes separated at a gate.
    """
    wires = tuple(_wire(index, 2.0) for index in range(1, 8))
    clearance_mm = 0.5

    routes = solve_parallel_routes(wires, (_gate(1, 6.0),), clearance_mm)

    crossings = [route.points[1] for route in routes]
    for left_index, left in enumerate(crossings):
        for right in crossings[left_index + 1 :]:
            distance = math.hypot(left.x - right.x, left.y - right.y)
            assert distance >= 2.0 + clearance_mm - 1e-9


def test_reports_gate_that_cannot_fit_bundle() -> None:
    """
    Stop before generating a preview when a gate aperture is undersized.
    """
    gate = _gate(4, 1.0)

    with pytest.raises(GateCapacityError, match="Gate 4 cannot fit 3 wires") as error_info:
        solve_parallel_routes(tuple(_wire(index, 1.5) for index in range(1, 4)), (gate,))

    assert error_info.value.gate_id == gate.gate_id


@pytest.mark.parametrize(
    ("gates", "clearance", "message"),
    [
        ((), 0.0, "routing gate"),
        ((_gate(1),), -0.1, "non-negative"),
    ],
)
def test_rejects_invalid_solver_inputs(
    gates: tuple[GateFrame, ...],
    clearance: float,
    message: str,
) -> None:
    """
    Reject incomplete or physically invalid routing inputs.
    """
    with pytest.raises(ValueError, match=message):
        solve_parallel_routes((_wire(1),), gates, clearance)
