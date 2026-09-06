"""
Regression tests for incremental Custom Graphics updates without a Fusion host.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, replace
from types import ModuleType, SimpleNamespace
from typing import Callable, Optional, Protocol, cast
from uuid import UUID

import pytest

from wire_bundler.domain import HarnessDefinition
from wire_bundler.domain.model import InterpolationSettings
from wire_bundler.routing import GateFrame, RoutePreview, Vector3, fair_route, sample_centerline
from wire_bundler.routing.geometry import cross, magnitude, unit


class _PreviewModule(Protocol):
    """
    Describe the adapter surface exercised against mocked graphics.
    """

    _preview_states: dict[str, object]
    _PreviewState: Callable[..., object]
    _solve_definition_routes: Callable[..., tuple[RoutePreview, ...]]
    _add_route_graphics: Callable[..., None]
    _gate_frame: Callable[..., GateFrame]
    _profile_frame: Callable[[object, str], tuple[Vector3, Vector3]]
    refresh_route_previews: Callable[[object, HarnessDefinition], tuple[str, ...]]
    clear_route_previews: Callable[[object], None]
    reconcile_preview_history: Callable[[object, tuple[HarnessDefinition, ...]], None]


class _Group:
    """
    Model stable graphics identity and child deletion at the Fusion boundary.
    """

    def __init__(self, identity: str, parent: Optional[_Group] = None) -> None:
        """
        Create a group with no children and an optional owning group.
        """
        self.id = identity
        self.children: list[_Group] = []
        self.parent = parent
        self.deleted = False

    @property
    def count(self) -> int:
        """
        Return the current number of graphics children.
        """
        return len(self.children)

    def item(self, index: int) -> _Group:
        """
        Return one child in graphics collection order.
        """
        return self.children[index]

    # noinspection PyPep8Naming
    def deleteMe(self) -> bool:
        """
        Remove this group while keeping surviving objects intact.
        """
        self.deleted = True
        if self.parent is not None:
            self.parent.children.remove(self)
        return True


@dataclass
class _Scenario:
    """
    Hold controllable solver results and recorded graphics operations.
    """

    module: _PreviewModule
    definition: HarnessDefinition
    design: SimpleNamespace
    group: _Group
    routes: dict[UUID, RoutePreview]
    solves: list[tuple[UUID, ...]]
    draws: list[UUID]
    solve_definition: Callable[[object, HarnessDefinition, float], tuple[RoutePreview, ...]]
    draw_route: Callable[[object, RoutePreview, int], None]


@pytest.fixture
def scenario(monkeypatch: pytest.MonkeyPatch, valid_harness: HarnessDefinition) -> _Scenario:
    """
    Display two wires sharing a bundle and one in an independent bundle.
    """
    adsk = ModuleType("adsk")
    core = ModuleType("adsk.core")
    fusion = ModuleType("adsk.fusion")
    vars(adsk).update(core=core, fusion=fusion)
    vars(fusion)["CustomGraphicsGroup"] = SimpleNamespace(cast=lambda entity: entity)
    for name, stub in (("adsk", adsk), ("adsk.core", core), ("adsk.fusion", fusion)):
        monkeypatch.setitem(sys.modules, name, stub)
    imported = importlib.import_module("wire_bundler.fusion.route_preview")
    monkeypatch.setitem(vars(imported), "adsk", adsk)
    monkeypatch.setitem(vars(imported), "_preview_states", {})
    monkeypatch.setitem(vars(imported), "_preview_history", {})
    module = cast(_PreviewModule, cast(object, imported))
    first = valid_harness.wires[0]
    second = replace(first, wire_id=UUID(int=9002), wire_number="002")
    third = replace(
        first, wire_id=UUID(int=9003), wire_number="003", ordered_control_ids=(UUID(int=9004),)
    )
    definition = replace(valid_harness, wires=(first, second, third))
    group = _Group("kev0.wire_bundler.route_preview:test")
    root = _Group("root")
    root.children.append(group)
    group.parent = root
    routes = {
        wire.wire_id: RoutePreview(
            wire.wire_id, wire.wire_number, (Vector3(0, 0, 0), Vector3(1, 1, 1))
        )
        for wire in definition.wires
    }
    for wire in definition.wires:
        group.children.append(_Group(str(wire.wire_id), group))
    # noinspection PyProtectedMember
    module._preview_states[group.id] = module._PreviewState(
        definition,
        dict(routes),
        {wire.wire_id: index for index, wire in enumerate(definition.wires)},
        0.25,
    )
    # noinspection PyProtectedMember
    state = _Scenario(
        module,
        definition,
        SimpleNamespace(rootComponent=SimpleNamespace(customGraphicsGroups=root)),
        group,
        routes,
        [],
        [],
        module._solve_definition_routes,
        module._add_route_graphics,
    )

    def solve(
        _design: object, updated: HarnessDefinition, clearance: float
    ) -> tuple[RoutePreview, ...]:
        """
        Return configured geometry while recording the scope of recalculation.
        """
        assert clearance == 0.25
        state.solves.append(tuple(wire.wire_id for wire in updated.wires))
        return tuple(state.routes[wire.wire_id] for wire in updated.wires)

    def draw(owner: _Group, route: RoutePreview, _color_index: int) -> None:
        """
        Append replacement graphics without modifying existing objects.
        """
        state.draws.append(route.wire_id)
        owner.children.append(_Group(str(route.wire_id), owner))

    monkeypatch.setattr(module, "_solve_definition_routes", solve)
    monkeypatch.setattr(module, "_add_route_graphics", draw)
    return state


def test_recomputes_affected_bundle_but_redraws_only_changed_wire(scenario: _Scenario) -> None:
    """
    Keep unchanged sibling and unrelated graphics objects alive after an edit.
    """
    original = tuple(scenario.group.children)
    first, second, third = scenario.definition.wires
    new_connection = replace(
        scenario.definition.connections[0], connection_id=UUID(int=9010), entity_token="new-profile"
    )
    updated = replace(
        scenario.definition,
        connections=(*scenario.definition.connections, new_connection),
        wires=(replace(first, start_connection_id=new_connection.connection_id), second, third),
    )
    scenario.routes[first.wire_id] = replace(
        scenario.routes[first.wire_id], points=(Vector3(2, 0, 0),)
    )
    assert scenario.module.refresh_route_previews(scenario.design, updated) == ()
    assert scenario.solves == [(first.wire_id, second.wire_id)]
    assert scenario.draws == [first.wire_id]
    assert original[0].deleted
    assert not original[1].deleted and not original[2].deleted
    scenario.module.refresh_route_previews(scenario.design, updated)
    assert len(scenario.solves) == 1


def test_secondary_member_edits_recompute_but_labels_do_not(scenario: _Scenario) -> None:
    """
    Evaluate secondary members while ignoring display-only changes.
    """
    definition = scenario.definition
    updated = replace(
        definition,
        connections=(
            replace(definition.connections[0], additional_entity_tokens=("extra",)),
            *definition.connections[1:],
        ),
    )
    updated = replace(
        updated, wires=tuple(replace(wire, display_name="Named") for wire in updated.wires)
    )
    assert scenario.module.refresh_route_previews(scenario.design, updated) == ()
    assert len(scenario.solves) == 2
    assert scenario.draws == []
    renamed = replace(
        updated, wires=tuple(replace(wire, display_name="Renamed") for wire in updated.wires)
    )
    scenario.module.refresh_route_previews(scenario.design, renamed)
    assert len(scenario.solves) == 2


def test_deleted_wire_disappears_and_survivors_are_repacked(scenario: _Scenario) -> None:
    """
    Remove stale graphics while leaving the independent bundle unchanged.
    """
    first, second, third = scenario.definition.wires
    old = tuple(scenario.group.children)
    updated = replace(scenario.definition, wires=(second, third))
    scenario.routes[second.wire_id] = replace(
        scenario.routes[second.wire_id], points=(Vector3(3, 0, 0),)
    )
    scenario.module.refresh_route_previews(scenario.design, updated)
    assert scenario.solves == [(second.wire_id,)]
    assert scenario.draws == [second.wire_id]
    assert old[0].deleted and old[1].deleted
    assert not old[2].deleted
    assert all(child.id != str(first.wire_id) for child in scenario.group.children)


def test_failed_bundle_drops_stale_paths_but_retains_unrelated_preview(
    scenario: _Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Report capacity failure without clearing every preview in the design.
    """

    def fail(
        _design: object, _definition: HarnessDefinition, _clearance: float
    ) -> tuple[RoutePreview, ...]:
        """
        Simulate an undersized gate after a wire diameter edit.
        """
        raise ValueError("Gate cannot fit wires")

    monkeypatch.setattr(scenario.module, "_solve_definition_routes", fail)
    first, second, third = scenario.definition.wires
    new_profile = replace(
        scenario.definition.profiles[0], profile_id=UUID(int=9011), diameter_mm=100.0
    )
    updated = replace(
        scenario.definition,
        profiles=(*scenario.definition.profiles, new_profile),
        wires=(replace(first, profile_id=new_profile.profile_id), second, third),
    )
    warnings = scenario.module.refresh_route_previews(scenario.design, updated)
    assert len(warnings) == 1
    assert "cannot fit" in warnings[0]
    assert [child.id for child in scenario.group.children] == [str(third.wire_id)]


def test_clear_preview_disables_automatic_refresh(scenario: _Scenario) -> None:
    """
    Never recreate previews after the user explicitly clears them.
    """
    scenario.module.clear_route_previews(scenario.design)
    scenario.module.refresh_route_previews(scenario.design, scenario.definition)
    assert scenario.module._preview_states == {}
    assert scenario.solves == []


def test_missing_end_hides_only_its_wire_and_restores_after_repair(scenario: _Scenario) -> None:
    """
    Keep complete neighbors visible while an edited connection is absent.
    """
    first, second, third = scenario.definition.wires
    original = tuple(scenario.group.children)
    incomplete = replace(
        scenario.definition,
        wires=(replace(first, start_connection_id=UUID(int=9999)), second, third),
    )
    scenario.module.refresh_route_previews(scenario.design, incomplete)
    assert original[0].deleted
    assert not original[1].deleted and not original[2].deleted
    assert scenario.solves == [(second.wire_id,)]
    scenario.module.refresh_route_previews(scenario.design, scenario.definition)
    assert scenario.draws == [first.wire_id]
    assert scenario.solves[-1] == (first.wire_id, second.wire_id)


def test_redraw_failure_cleans_partial_graphics_and_retains_neighbors(
    scenario: _Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Remove a failed replacement without leaving stale or duplicate wire geometry.
    """
    first, second, third = scenario.definition.wires
    scenario.routes[first.wire_id] = replace(
        scenario.routes[first.wire_id], points=(Vector3(7, 0, 0),)
    )
    updated = replace(scenario.definition, wires=(replace(first, wire_number="004"), second, third))

    def fail_draw(owner: _Group, route: RoutePreview, _color: int) -> None:
        """
        Simulate failure after Fusion has already created a partial child group.
        """
        owner.children.append(_Group(str(route.wire_id), owner))
        raise RuntimeError("Graphics allocation failed")

    monkeypatch.setattr(scenario.module, "_add_route_graphics", fail_draw)
    warnings = scenario.module.refresh_route_previews(scenario.design, updated)
    assert len(warnings) == 1
    assert [child.id for child in scenario.group.children] == [
        str(second.wire_id),
        str(third.wire_id),
    ]


def test_other_harness_does_not_modify_active_preview(scenario: _Scenario) -> None:
    """
    Scope incremental updates to the owner of the displayed preview.
    """
    other_harness = replace(scenario.definition, harness_id=UUID(int=9999))
    assert scenario.module.refresh_route_previews(scenario.design, other_harness) == ()
    assert scenario.solves == []
    assert scenario.draws == []


def test_promoting_end_member_refreshes_preview(scenario: _Scenario) -> None:
    """
    Reordering an end refreshes its route when a different profile becomes first.
    """
    definition = scenario.definition
    first = definition.wires[0]
    connection = definition.connections[0]
    updated = replace(
        definition,
        connections=(
            replace(
                connection,
                entity_token="promoted",
                additional_entity_tokens=(connection.entity_token,),
            ),
            *definition.connections[1:],
        ),
    )
    scenario.routes[first.wire_id] = replace(
        scenario.routes[first.wire_id], points=(Vector3(2, 0, 0),)
    )
    assert scenario.module.refresh_route_previews(scenario.design, updated) == ()
    assert scenario.solves
    assert scenario.draws == [first.wire_id]


def test_history_reconciliation_restores_cache_without_graphics_writes(scenario: _Scenario) -> None:
    """
    Let Fusion own geometry restoration while Python adopts matching undo/redo caches.
    """
    original = scenario.definition
    updated = replace(
        original, wires=tuple(replace(wire, display_name="Renamed") for wire in original.wires)
    )
    scenario.module.refresh_route_previews(scenario.design, updated)
    children = tuple(scenario.group.children)
    scenario.module.reconcile_preview_history(scenario.design, (original,))
    scenario.module.refresh_route_previews(scenario.design, original)
    assert scenario.solves == []
    assert scenario.draws == []
    assert tuple(scenario.group.children) == children
    scenario.module.reconcile_preview_history(scenario.design, (updated,))
    scenario.module.refresh_route_previews(scenario.design, updated)
    assert scenario.solves == []
    assert scenario.draws == []


def test_undo_clear_preview_recovers_cache(scenario: _Scenario) -> None:
    """
    Recover a cleared preview cache when Fusion restores its graphics group.
    """
    root = scenario.group.parent
    assert root is not None
    scenario.module.clear_route_previews(scenario.design)
    root.children.append(scenario.group)
    scenario.group.deleted = False
    scenario.module.reconcile_preview_history(scenario.design, (scenario.definition,))
    scenario.module.refresh_route_previews(scenario.design, scenario.definition)
    assert scenario.solves == []
    assert scenario.draws == []


@pytest.mark.parametrize("explicit", [False, True])
def test_adapter_fairs_all_end_members_in_stored_order(
    scenario: _Scenario,
    monkeypatch: pytest.MonkeyPatch,
    valid_harness: HarnessDefinition,
    explicit: bool,
) -> None:
    """
    Translate every profile normal and retain reversed end-B traversal through fairing.
    """
    definition = replace(
        valid_harness,
        connections=(
            replace(valid_harness.connections[0], additional_entity_tokens=("a-guide",)),
            replace(valid_harness.connections[1], additional_entity_tokens=("b-guide",)),
        ),
    )
    if explicit:
        definition = replace(
            definition,
            connections=(
                replace(
                    definition.connections[0],
                    member_interpolations=(
                        InterpolationSettings(0.4, 0.8),
                        InterpolationSettings(0.5, 0.9),
                    ),
                ),
                replace(
                    definition.connections[1],
                    member_interpolations=(
                        InterpolationSettings(0.6, 1.2),
                        InterpolationSettings(0.7, 1.3),
                    ),
                ),
            ),
            controls=(replace(definition.controls[0], interpolation=InterpolationSettings(1, 2)),),
        )
    frames = {
        definition.connections[0].entity_token: (Vector3(0, 0, 0), Vector3(1, 0, 1)),
        "a-guide": (Vector3(0, 0, 4), Vector3(0, 1, 1)),
        "b-guide": (Vector3(0, 0, 16), Vector3(0, 1, 1)),
        definition.connections[1].entity_token: (Vector3(0, 0, 20), Vector3(1, 0, 1)),
    }
    calls: list[str] = []

    def profile_frame(_design: object, token: str) -> tuple[Vector3, Vector3]:
        """
        Resolve an explicitly identified profile without proximity inference.
        """
        calls.append(token)
        return frames[token]

    gate = GateFrame(UUID(int=4), "Gate", Vector3(0, 0, 10), Vector3(1, 0, 0), Vector3(0, 1, 0), 10)
    monkeypatch.setattr(scenario.module, "_gate_frame", lambda *_args: gate)
    monkeypatch.setattr(scenario.module, "_profile_frame", profile_frame)
    route = scenario.solve_definition(scenario.design, definition, 0.0)[0]
    assert [point.z for point in route.points] == [0, 4, 10, 16, 20]
    assert set(calls) == set(frames)
    assert len(calls) == 4
    assert len(route.curves) == 12
    if explicit:
        assert [curve.end.z for curve in route.curves[::3]] == pytest.approx([0.8, 4.9, 12, 16.7])
        assert [curve.start.z for curve in route.curves[2::3]] == pytest.approx(
            [3.5, 9, 14.7, 18.8]
        )
    expected_normals = (Vector3(1, 0, 1), Vector3(0, 1, 1), Vector3(0, 0, 1), Vector3(0, 1, 1))
    for index, normal in enumerate(expected_normals):
        tangent = route.curves[index * 3].derivative(0.0)
        assert magnitude(cross(unit(tangent), unit(normal))) < 1e-10


def test_graphics_use_sampled_curves_in_fusion_units(scenario: _Scenario) -> None:
    """
    Send curved samples, rather than just crossings, to the host line renderer.
    """
    route = fair_route(
        RoutePreview(UUID(int=1), "001", (Vector3(0, 0, 0), Vector3(0, 0, 100))),
        (Vector3(1, 0, 1), Vector3(0, 1, 1)),
    )
    coordinates: list[float] = []
    lines = SimpleNamespace()

    def capture(values: list[float]) -> object:
        """
        Record the coordinates passed across the millimeter/centimeter boundary.
        """
        coordinates.extend(values)
        return object()

    core = sys.modules["adsk.core"]
    fusion = sys.modules["adsk.fusion"]
    vars(core)["Color"] = SimpleNamespace(create=lambda *_args: object())
    vars(fusion)["CustomGraphicsCoordinates"] = SimpleNamespace(create=capture)
    vars(fusion)["CustomGraphicsSolidColorEffect"] = SimpleNamespace(create=lambda _color: object())
    wire_group = SimpleNamespace(addLines=lambda *_args: lines)
    owner = SimpleNamespace(addGroup=lambda: wire_group)
    scenario.draw_route(owner, route, 0)
    expected = [
        value / 10 for point in sample_centerline(route) for value in (point.x, point.y, point.z)
    ]
    assert coordinates == expected
    assert len(coordinates) > 6
    assert wire_group.id == str(route.wire_id)
    assert lines.weight == 1.0


@pytest.mark.parametrize("target", ["gate", "end", "defaults"])
def test_interpolation_refresh_scope(scenario: _Scenario, target: str) -> None:
    """
    Recompute the affected bundle for section edits; defaults leave existing previews intact.
    """
    definition = scenario.definition
    settings = InterpolationSettings(3, 5)
    if target == "gate":
        updated = replace(
            definition,
            controls=(
                replace(definition.controls[0], interpolation=settings),
                *definition.controls[1:],
            ),
        )
    elif target == "end":
        updated = replace(
            definition,
            connections=(
                replace(definition.connections[0], interpolation=settings),
                *definition.connections[1:],
            ),
        )
    else:
        updated = replace(definition, gate_defaults=settings, end_defaults=settings)
    scenario.module.refresh_route_previews(scenario.design, updated)
    expected = (
        [] if target == "defaults" else [tuple(wire.wire_id for wire in definition.wires[:2])]
    )
    if target == "end":
        expected.append((definition.wires[2].wire_id,))
    assert set(scenario.solves) == set(expected)
