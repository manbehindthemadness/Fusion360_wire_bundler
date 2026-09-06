"""
Run the shared Sweep geometry matrix without an Autodesk Fusion host.
"""

from __future__ import annotations

import re

import pytest

from experiments.sweep_scenarios import SweepScenario, sweep_scenarios
from wire_bundler.routing import fair_route, tightest_bend
from wire_bundler.routing.geometry import difference, dot, magnitude, unit


@pytest.mark.parametrize("scenario", sweep_scenarios(), ids=lambda scenario: scenario.name)
def test_sweep_scenario_preflight(scenario: SweepScenario) -> None:
    """
    Accept safe routes and reject impossible geometry before Fusion sees it.
    """
    if not scenario.expected_feasible:
        with pytest.raises(ValueError, match=re.escape(scenario.expected_error)):
            fair_route(
                scenario.route(),
                scenario.normals,
                scenario.transitions,
                scenario.minimum_bend_radius_mm,
            )
        return

    route = fair_route(
        scenario.route(),
        scenario.normals,
        scenario.transitions,
        scenario.minimum_bend_radius_mm,
    )
    bend = tightest_bend(route, 1024)
    assert bend is not None
    assert bend.radius_mm >= scenario.minimum_bend_radius_mm - 1e-9
    assert route.curves[0].start == scenario.points[0]
    assert route.curves[-1].end == scenario.points[-1]
    if scenario.expects_minimum_expansion:
        first_span = magnitude(difference(scenario.points[1], scenario.points[0]))
        first_transition = magnitude(difference(route.curves[0].end, route.curves[0].start))
        assert first_transition > first_span * 0.25


def test_sweep_scenario_names_and_identities_are_stable() -> None:
    """
    Keep reports addressable and prevent accidental duplicate matrix cases.
    """
    scenarios = sweep_scenarios()
    assert len({scenario.name for scenario in scenarios}) == len(scenarios)
    assert len({scenario.wire_id for scenario in scenarios}) == len(scenarios)
    zigzag = next(scenario for scenario in scenarios if scenario.name == "three_stroke_180_zigzag")
    stroke_directions = tuple(
        unit(difference(zigzag.points[end], zigzag.points[start]))
        for start, end in ((0, 1), (2, 3), (4, 5))
    )
    assert len(stroke_directions) == 3
    assert dot(stroke_directions[0], stroke_directions[1]) == pytest.approx(-1.0)
    assert dot(stroke_directions[1], stroke_directions[2]) == pytest.approx(-1.0)
    assert dot(unit(zigzag.normals[1]), unit(zigzag.normals[2])) == pytest.approx(-1.0)
    assert dot(unit(zigzag.normals[3]), unit(zigzag.normals[4])) == pytest.approx(-1.0)
    pinch = next(
        scenario for scenario in scenarios if scenario.name == "three_adjacent_180_pinches"
    )
    turn_directions = tuple(
        unit(difference(pinch.points[index + 1], pinch.points[index])) for index in range(1, 4)
    )
    assert len(turn_directions) == 3
    assert all(
        dot(left, right) == pytest.approx(1.0)
        for left, right in zip(turn_directions, turn_directions[1:])
    )
    assert all(
        dot(unit(pinch.normals[index]), unit(pinch.normals[index + 1])) == pytest.approx(-1.0)
        for index in range(1, 4)
    )
