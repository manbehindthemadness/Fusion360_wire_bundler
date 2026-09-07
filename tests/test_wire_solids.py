"""
Mocked Fusion regressions for durable wire generation and replacement safety.
"""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Callable
from dataclasses import replace
from types import ModuleType, SimpleNamespace
from typing import Optional, Protocol, cast
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest

from wire_bundler.domain import (
    HarnessDefinition,
    WireAppearanceReference,
    WireColor,
    WireDefinition,
    WireMaterialSettings,
    WireStripe,
)
from wire_bundler.routing import CubicBezier, RoutePreview, Vector3


class _SolidsModule(Protocol):
    """
    Describe the adapter boundary without importing Fusion during test collection.
    """

    generate_wire_solids: Callable[..., int]
    generated_wire_bodies: Callable[..., tuple[object, ...]]
    clear_wire_solids: Callable[..., int]
    solve_route_centerlines: Callable[..., tuple[RoutePreview, ...]]
    build_wire_sweep: Callable[..., None]
    apply_wire_materials: Callable[..., int]
    GENERATED_STRIPE_GROUP_ID: str
    _replace_stripe_graphics: Callable[..., int]
    _route_from_metadata: Callable[..., Optional[RoutePreview]]
    _route_in_component_space: Callable[..., RoutePreview]
    _route_metadata: Callable[..., list[list[list[float]]]]
    _world_to_harness: Callable[..., object]
    _point: Callable[..., object]
    _wire_appearance: Callable[..., object]


@pytest.fixture
def solids(monkeypatch: pytest.MonkeyPatch) -> _SolidsModule:
    """
    Load the production adapter against isolated host modules.
    """
    core = ModuleType("adsk.core")
    fusion = ModuleType("adsk.fusion")
    adsk = ModuleType("adsk")
    vars(adsk).update(core=core, fusion=fusion)
    vars(core).update(
        Matrix3D=SimpleNamespace(create=lambda: Mock()),
        ObjectCollection=SimpleNamespace(create=lambda: Mock(add=Mock(return_value=True))),
        ValueInput=SimpleNamespace(createByReal=lambda number: number),
        Point3D=SimpleNamespace(
            create=lambda x, y, z: Mock(x=x, y=y, z=z, transformBy=Mock(return_value=True))
        ),
    )
    vars(fusion).update(
        Path=SimpleNamespace(create=Mock(side_effect=RuntimeError("Utils::getObjectPath"))),
        ChainedCurveOptions=SimpleNamespace(noChainedCurves=0),
        SplineDegrees=SimpleNamespace(SplineDegreeThree=3),
        FeatureOperations=SimpleNamespace(NewBodyFeatureOperation=0),
    )
    for name, value in (("adsk", adsk), ("adsk.core", core), ("adsk.fusion", fusion)):
        monkeypatch.setitem(sys.modules, name, value)
    module = importlib.import_module("wire_bundler.fusion.wire_solids")
    monkeypatch.setitem(vars(module), "adsk", adsk)
    return cast(_SolidsModule, cast(object, module))


def _route(wire: WireDefinition) -> RoutePreview:
    """
    Provide one curved cubic and one straight span with exact endpoint continuity.
    """
    a, b, c = Vector3(0, 0, 0), Vector3(2, 0, 2), Vector3(2, 0, 5)
    return RoutePreview(
        wire.wire_id,
        wire.wire_number,
        (a, b, c),
        (
            CubicBezier(a, Vector3(0, 0, 1), Vector3(2, 0, 1), b),
            CubicBezier(b, Vector3(2, 0, 3), Vector3(2, 0, 4), c),
        ),
    )


@pytest.mark.parametrize("fail_second", [False, True])
def test_builds_all_replacements_before_deleting_old_output(
    solids: _SolidsModule,
    monkeypatch: pytest.MonkeyPatch,
    valid_harness: HarnessDefinition,
    fail_second: bool,
) -> None:
    """
    Preserve original output until every sweep succeeds and clean all staging on failure.
    """
    extra_ends = tuple(
        replace(connection, connection_id=UUID(int=910 + index))
        for index, connection in enumerate(valid_harness.connections)
    )
    definition = replace(
        valid_harness,
        connections=(*valid_harness.connections, *extra_ends),
        wires=(
            valid_harness.wires[0],
            replace(
                valid_harness.wires[0],
                wire_id=UUID(int=900),
                wire_number="002",
                start_connection_id=extra_ends[0].connection_id,
                end_connection_id=extra_ends[1].connection_id,
            ),
        ),
    )
    old = Mock(deleteMe=Mock(return_value=True))
    unrelated = Mock()
    unrelated.component.attributes.itemByName.return_value = None
    created = [Mock(isValid=True, deleteMe=Mock(return_value=True)) for _ in range(2)]
    harness = Mock(occurrences=MagicMock())
    harness.occurrences.__iter__.return_value = iter((old, unrelated))
    harness.occurrences.addNewComponent.side_effect = created
    design = SimpleNamespace(rootComponent=harness)
    monkeypatch.setattr(
        solids,
        "solve_route_centerlines",
        lambda *_args: tuple(_route(wire) for wire in definition.wires),
    )
    builds: list[UUID] = []

    def build(_component: object, wire: WireDefinition, *_args: object) -> None:
        """
        Simulate the kernel succeeding or rejecting the last wire before replacement.
        """
        old.deleteMe.assert_not_called()
        builds.append(wire.wire_id)
        if fail_second and len(builds) == 2:
            raise RuntimeError("sweep rejected")

    monkeypatch.setattr(solids, "build_wire_sweep", build)
    if fail_second:
        with pytest.raises(RuntimeError, match="Wire 002.*sweep rejected"):
            solids.generate_wire_solids(design, harness, definition, True)
        old.deleteMe.assert_not_called()
        for occurrence in created:
            occurrence.deleteMe.assert_called_once()
    else:
        assert solids.generate_wire_solids(design, harness, definition, True) == 2
        old.deleteMe.assert_called_once()
        for occurrence in created:
            occurrence.deleteMe.assert_not_called()
    unrelated.deleteMe.assert_not_called()
    assert builds == [wire.wire_id for wire in definition.wires]


def test_requires_confirmation_before_replacing_output(
    solids: _SolidsModule,
    valid_harness: HarnessDefinition,
) -> None:
    """
    Reject an unconfirmed rebuild before invoking the solver or creating geometry.
    """
    harness = Mock(occurrences=MagicMock())
    harness.occurrences.__iter__.return_value = iter((Mock(),))
    with pytest.raises(ValueError, match="confirm rebuilding"):
        solids.generate_wire_solids(object(), harness, valid_harness)
    harness.occurrences.addNewComponent.assert_not_called()


def test_clears_only_marked_generated_wire_components(solids: _SolidsModule) -> None:
    """
    Delete generated direct children while preserving unrelated harness content.
    """
    generated = [Mock(deleteMe=Mock(return_value=True)) for _ in range(2)]
    unrelated = Mock()
    harness = Mock(occurrences=MagicMock())
    harness.occurrences.__iter__.return_value = iter((*generated, unrelated))
    for occurrence in generated:
        occurrence.component.attributes.itemByName.return_value = object()
    unrelated.component.attributes.itemByName.return_value = None

    assert solids.clear_wire_solids(harness) == 2

    for occurrence in generated:
        occurrence.deleteMe.assert_called_once()
    unrelated.deleteMe.assert_not_called()


def test_clear_solids_raises_when_fusion_rejects_deletion(solids: _SolidsModule) -> None:
    """
    Fail the native transaction when Fusion cannot delete marked output.
    """
    generated = Mock(deleteMe=Mock(return_value=False))
    generated.component.attributes.itemByName.return_value = object()
    harness = Mock(occurrences=MagicMock())
    harness.occurrences.__iter__.return_value = iter((generated,))

    with pytest.raises(RuntimeError, match="could not delete"):
        solids.clear_wire_solids(harness)


@pytest.mark.parametrize("sweep_failure", [False, True])
def test_creates_exact_curves_diameter_and_identity(
    solids: _SolidsModule,
    valid_harness: HarnessDefinition,
    sweep_failure: bool,
) -> None:
    """
    Build cubic control geometry and a circular profile using host centimeters, then retain UUIDs.
    """
    component = Mock()
    centerline = Mock(modelToSketchSpace=lambda value: value)
    section = Mock(modelToSketchSpace=lambda value: value)
    component.sketches.add.side_effect = (centerline, section)
    centerline.sketchCurves.sketchControlPointSplines.add.return_value = Mock(length=1.25)
    centerline.sketchCurves.sketchLines.addByTwoPoints.return_value = Mock(length=0.3)
    section.profiles.count = 1
    sweep = component.features.sweepFeatures.add.return_value
    sweep.bodies.count = 1
    sweep.bodies.item.return_value = Mock(isSolid=True, volume=0.025)
    path = Mock()
    component.features.createPath.return_value = path
    wire = valid_harness.wires[0]
    if sweep_failure:
        component.features.sweepFeatures.add.side_effect = RuntimeError("ASM_SELF_INTER")
        with pytest.raises(
            RuntimeError,
            match=r"create solid sweep: ASM_SELF_INTER; route diagnostic: "
            r"tightest sampled bend radius .* wire radius 0\.750 mm",
        ):
            solids.build_wire_sweep(
                component, wire, _route(wire), 1.5, Mock(), valid_harness.harness_id
            )
        component.features.pipeFeatures.add.assert_not_called()
        return
    solids.build_wire_sweep(component, wire, _route(wire), 1.5, Mock(), valid_harness.harness_id)
    controls, degree = centerline.sketchCurves.sketchControlPointSplines.add.call_args.args
    assert degree == 3
    assert [(point.x, point.y, point.z) for point in controls] == [
        (0, 0, 0),
        (0, 0, 0.1),
        (0.2, 0, 0.1),
        (0.2, 0, 0.2),
    ]
    curves, chain = component.features.createPath.call_args.args
    assert chain is False
    vars(sys.modules["adsk.fusion"])["Path"].create.assert_not_called()
    component.constructionPlanes.createInput.return_value.setByDistanceOnPath.assert_called_once_with(
        curves.item(0), 0
    )
    center, radius = section.sketchCurves.sketchCircles.addByCenterRadius.call_args.args
    assert (center.x, center.y, center.z) == (0, 0, 0)
    assert radius == 0.075
    component.features.pipeFeatures.add.assert_not_called()
    assert sweep.name == "Wire Sweep"
    assert sweep.bodies.item.return_value.name == "001_15.50mm"
    assert component.name == "001_15.50mm"
    assert not centerline.isLightBulbOn and not section.isLightBulbOn
    assert not component.constructionPlanes.add.return_value.isLightBulbOn
    metadata = json.loads(component.attributes.add.call_args.args[2])
    assert metadata["wire_id"] == str(wire.wire_id)
    assert metadata["length_mm"] == pytest.approx(15.5)


def test_transforms_points_into_harness_placement(solids: _SolidsModule) -> None:
    """
    Invert the unique placement and apply that matrix after unit conversion.
    """
    transform = Mock(invert=Mock(return_value=True))
    placement = Mock()
    placement.transform2.copy.return_value = transform
    design = Mock()
    design.rootComponent.allOccurrencesByComponent.return_value = Mock(
        count=1, item=lambda _index: placement
    )
    # noinspection PyProtectedMember
    matrix = solids._world_to_harness(design, object())
    # noinspection PyProtectedMember
    point = cast(Mock, solids._point(Vector3(10, 20, 30), matrix))
    assert (point.x, point.y, point.z) == (1, 2, 3)
    point.transformBy.assert_called_once_with(transform)
    transform.invert.assert_called_once()


def test_generated_stripes_are_owned_by_wire_component(
    solids: _SolidsModule,
    valid_harness: HarnessDefinition,
) -> None:
    """
    Replace stripe meshes inside the generated component in component-local units.
    """
    wire = valid_harness.wires[0]
    route = _route(wire)
    old_child = Mock(deleteMe=Mock(return_value=True))
    old_group = SimpleNamespace(
        id=solids.GENERATED_STRIPE_GROUP_ID,
        name="Wire 001 Solid Stripes",
        count=1,
        item=lambda _index: old_child,
        deleteMe=Mock(return_value=True),
    )
    meshes: list[SimpleNamespace] = []
    coordinate_calls: list[list[float]] = []

    def add_mesh(*_args: object) -> SimpleNamespace:
        """
        Return one assignable solid-owned stripe mesh.
        """
        mesh = SimpleNamespace()
        meshes.append(mesh)
        return mesh

    new_group = SimpleNamespace(id="", name="", count=0, addMesh=add_mesh)
    groups = SimpleNamespace(count=1, item=lambda _index: old_group, add=lambda: new_group)
    component = SimpleNamespace(customGraphicsGroups=groups)
    core = sys.modules["adsk.core"]
    fusion = sys.modules["adsk.fusion"]
    core.Color = SimpleNamespace(create=lambda *channels: channels)  # type: ignore[attr-defined]
    fusion.CustomGraphicsCoordinates = SimpleNamespace(  # type: ignore[attr-defined]
        create=lambda values: coordinate_calls.append(values) or object()
    )
    fusion.CustomGraphicsSolidColorEffect = SimpleNamespace(  # type: ignore[attr-defined]
        create=lambda color: color
    )
    fusion.CustomGraphicsCullModes = SimpleNamespace(  # type: ignore[attr-defined]
        CustomGraphicsCullNone="none"
    )
    stripe = WireStripe(WireColor("White", 245, 245, 245), 0.3)

    assert solids._replace_stripe_graphics(component, route, (stripe,), 0.75) == 1

    old_child.deleteMe.assert_called_once()
    old_group.deleteMe.assert_called_once()
    assert new_group.id.endswith(str(wire.wire_id))
    assert new_group.name == "Wire 001 Solid Stripes"
    assert coordinate_calls
    assert meshes[0].name == "Wire 001 Stripe 1"
    assert meshes[0].color == (245, 245, 245, 255)
    assert meshes[0].cullMode == "none"


def test_generated_route_metadata_round_trips_component_local_curves(
    solids: _SolidsModule,
    valid_harness: HarnessDefinition,
) -> None:
    """
    Retain the exact solid path so later material edits cannot follow a stale preview.
    """
    wire = valid_harness.wires[0]
    route = _route(wire)
    local_route = solids._route_in_component_space(route, Mock())
    metadata = {"route_curves_mm": solids._route_metadata(local_route)}

    restored = solids._route_from_metadata(wire, metadata)

    assert restored == local_route


def test_creates_and_reuses_document_insulation_appearance(
    solids: _SolidsModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Copy Fusion's released generic appearance once and update its opaque color.
    """
    color = WireColor("Blue", 35, 94, 190)
    color_property = SimpleNamespace(value=None)
    created = SimpleNamespace(
        appearanceProperties=SimpleNamespace(itemById=lambda identity: color_property)
    )
    appearances = Mock()
    appearances.itemByName.side_effect = (None, created)
    appearances.addByCopy.return_value = created
    generic = object()
    library = SimpleNamespace(
        appearances=SimpleNamespace(
            itemById=lambda identity: generic if identity == "Prism-129" else None
        )
    )
    application = SimpleNamespace(
        materialLibraries=SimpleNamespace(
            itemById=lambda identity: (
                library if identity == "BA5EE55E-9982-449B-9D66-9F036540E140" else None
            )
        )
    )
    core = sys.modules["adsk.core"]
    core.Application = SimpleNamespace(get=lambda: application)  # type: ignore[attr-defined]
    core.Color = SimpleNamespace(create=lambda *channels: channels)  # type: ignore[attr-defined]
    design = SimpleNamespace(appearances=appearances)

    assert solids._wire_appearance(design, color) is created
    assert color_property.value == (35, 94, 190, 255)
    appearances.addByCopy.assert_called_once_with(generic, "Wire Bundler Insulation #235EBE")
    assert solids._wire_appearance(design, color) is created
    appearances.addByCopy.assert_called_once()


def test_copies_selected_fusion_library_appearance(
    solids: _SolidsModule,
) -> None:
    """
    Preserve a user's library appearance without replacing it with a flat color.
    """
    reference = WireAppearanceReference(
        "custom-library", "My Appearances", "rubber-blue", "Rubber - Blue"
    )
    source = object()
    library = SimpleNamespace(
        appearances=SimpleNamespace(
            itemById=lambda identity: source if identity == "rubber-blue" else None
        )
    )
    application = SimpleNamespace(
        materialLibraries=SimpleNamespace(
            itemById=lambda identity: library if identity == "custom-library" else None
        )
    )
    core = sys.modules["adsk.core"]
    core.Application = SimpleNamespace(get=lambda: application)  # type: ignore[attr-defined]
    created = object()
    appearances = Mock(itemByName=Mock(return_value=None), addByCopy=Mock(return_value=created))
    design = SimpleNamespace(appearances=appearances)

    result = solids._wire_appearance(design, WireColor("Blue", 35, 94, 190), reference)

    assert result is created
    appearances.addByCopy.assert_called_once()
    assert appearances.addByCopy.call_args.args[0] is source
    assert "Rubber - Blue" in appearances.addByCopy.call_args.args[1]


def test_applies_saved_materials_to_existing_generated_body(
    solids: _SolidsModule,
    monkeypatch: pytest.MonkeyPatch,
    valid_harness: HarnessDefinition,
) -> None:
    """
    Recolor generated output and refresh its resolved material metadata in place.
    """
    blue = WireColor("Blue", 35, 94, 190)
    stripe = WireStripe(WireColor("White", 245, 245, 245), 0.3)
    definition = replace(
        valid_harness,
        material_defaults=WireMaterialSettings(
            insulation_material="ETFE",
            main_color=blue,
            stripes=(stripe,),
            part_number="WB-001",
        ),
    )
    route = _route(definition.wires[0])
    metadata = {
        "wire_id": str(definition.wires[0].wire_id),
        "length_mm": 42.0,
        "route_curves_mm": solids._route_metadata(route),
    }
    attribute = SimpleNamespace(value=json.dumps(metadata))
    body = SimpleNamespace(appearance=None)
    bodies = SimpleNamespace(count=1, item=lambda _index: body)
    component = SimpleNamespace(
        attributes=SimpleNamespace(itemByName=lambda *_args: attribute),
        bRepBodies=bodies,
    )
    occurrence = SimpleNamespace(component=component)
    harness = SimpleNamespace(occurrences=(occurrence,))
    appearance = object()
    monkeypatch.setattr(
        solids, "_wire_appearance", lambda _design, _color, _reference=None: appearance
    )
    stripe_updates: list[tuple[object, RoutePreview, tuple[WireStripe, ...], float]] = []

    def replace_stripes(
        owner: object,
        saved_route: RoutePreview,
        stripes: tuple[WireStripe, ...],
        radius: float,
    ) -> int:
        """
        Record the component-local stripe refresh performed during material Apply.
        """
        stripe_updates.append((owner, saved_route, stripes, radius))
        return len(stripes)

    monkeypatch.setattr(
        solids,
        "_replace_stripe_graphics",
        replace_stripes,
    )

    assert solids.apply_wire_materials(object(), harness, definition) == 1
    assert body.appearance is appearance
    expected_radius = definition.profiles[0].diameter_mm / 2.0
    assert stripe_updates == [(component, route, (stripe,), expected_radius)]
    stored = json.loads(attribute.value)
    assert stored["length_mm"] == 42.0
    assert stored["main_color"] == "#235EBE"
    assert stored["insulation_material"] == "ETFE"
    assert stored["part_number"] == "WB-001"


def test_resolves_generated_bodies_by_persistent_wire_identity(
    solids: _SolidsModule,
    valid_harness: HarnessDefinition,
) -> None:
    """
    Return every body owned by the requested generated wire components.
    """
    selected_wire = valid_harness.wires[0]
    selected_body = object()
    other_body = object()

    def occurrence(
        wire_id: UUID,
        body: object,
    ) -> tuple[SimpleNamespace, SimpleNamespace]:
        """
        Build one marked generated occurrence with identity metadata.
        """
        attribute = SimpleNamespace(value=json.dumps({"wire_id": str(wire_id)}))
        component = SimpleNamespace(
            attributes=SimpleNamespace(itemByName=lambda *_args: attribute),
        )
        root_occurrence = SimpleNamespace(
            bRepBodies=SimpleNamespace(count=1, item=lambda _index: body)
        )
        return SimpleNamespace(component=component), root_occurrence

    other_wire_id = UUID(int=999)
    selected_native, selected_root = occurrence(selected_wire.wire_id, selected_body)
    other_native, other_root = occurrence(other_wire_id, other_body)
    harness = SimpleNamespace(
        occurrences=(selected_native, other_native),
    )
    root_occurrences = {
        id(selected_native.component): selected_root,
        id(other_native.component): other_root,
    }
    root = SimpleNamespace(
        allOccurrencesByComponent=lambda component: SimpleNamespace(
            count=1,
            item=lambda _index: root_occurrences[id(component)],
        )
    )

    assert solids.generated_wire_bodies(root, harness, (selected_wire.wire_id,)) == (selected_body,)
