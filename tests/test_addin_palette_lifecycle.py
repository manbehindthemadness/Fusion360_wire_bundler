"""
Regression tests for the Fusion palette launcher lifecycle.
"""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Optional, Protocol, cast
from unittest.mock import Mock
from uuid import UUID

import pytest

from wire_bundler.application import HarnessLoadResult
from wire_bundler.domain import (
    ControlKind,
    ControlStructure,
    HarnessDefinition,
    JunctionDefinition,
    JunctionPathwayRelationship,
    PathwayEndpoint,
    RefineGeometry,
    WireColor,
    WireStripe,
    dumps,
    loads,
)
from wire_bundler.routing import GateFrame, Vector3

REFINE_ID = UUID("30000000-0000-0000-0000-000000000099")


class _RefinePlacementResult(Protocol):
    """
    Describe the placement fields asserted by lifecycle tests.
    """

    insertion_index: int
    geometry: RefineGeometry


class _PaletteLifecycleModule(Protocol):
    """
    Describe the private lifecycle surface exercised by this regression test.
    """

    _handlers: list[object]
    PALETTE_RESOURCE_FILES: tuple[Path, ...]
    JUNCTION_RELATIONSHIP_GEOMETRY_INPUT_ID: str
    JUNCTION_RELATIONSHIP_CHOICE_INPUT_ID: str
    _PaletteIncomingHandler: type
    _PaletteEditExecuteHandler: type
    _PaletteEditDestroyedHandler: type
    _PaletteEditCreatedHandler: type
    _HistoryChangedHandler: type
    _DocumentSavingHandler: type
    _DocumentSavedHandler: type
    _pending_palette_edit: object
    _pending_refine_edit_ids: object
    _damaged_harness_results: dict[str, HarnessLoadResult]
    _graphics_cache_restore_value: Optional[bool]
    _graphics_cache_save_document: Optional[object]
    _last_diagram_qa_observation: Optional[dict[str, object]]
    _open_palette_edit: Callable[[object, str, str], None]
    _apply_palette_edit: Callable[[object, str, str], str]
    _refresh_active_preview: Callable[..., str]
    _apply_generated_materials: Callable[[object, UUID], str]
    _send_palette_state: Callable[[object, str], None]
    reconcile_preview_history: Callable[[object, tuple[HarnessDefinition, ...]], None]
    _ShowPaletteCreatedHandler: type
    _RefineCommandState: type
    _AddJunctionCommandState: type
    _AddJunctionPreSelectHandler: type
    _AddJunctionRelationshipCommandState: type
    _AddJunctionRelationshipInputChangedHandler: type
    _JunctionRelationshipCandidate: type
    _SegmentCommandState: type
    _SegmentPreSelectHandler: type
    _RefinePreSelectHandler: type
    _RefineMouseDragHandler: type
    _RefineActiveSelectionHandler: type
    _EditRefineCommandState: type
    _EditRefineInputChangedHandler: type
    _EditRefineExecutePreviewHandler: type
    _read_refine_placement: Callable[[object, object], _RefinePlacementResult]
    _junction_profile_token: Callable[[object, object], str]
    _read_junction_relationship_candidate: Callable[[object, object], object]
    _update_junction_relationship_choices: Callable[[object, object], None]
    _open_add_junction_command: Callable[[object, str], None]
    _open_add_junction_relationship_command: Callable[[object, str], None]
    _update_refine_placement: Callable[..., None]
    _refine_geometry_transform: Callable[[RefineGeometry], object]
    _add_refine_transform_input: Callable[[object, RefineGeometry], object]
    _read_edited_refine_geometry: Callable[[object], RefineGeometry]
    _preview_edited_refine: Callable[[object, object], None]
    draw_candidate_refine: Callable[[object, RefineGeometry], object]
    draw_refine_editor: Callable[[object, RefineGeometry], object]
    update_candidate_refine: Callable[[object, RefineGeometry], None]
    update_refine_editor: Callable[[object, RefineGeometry], None]
    PathwaySpine: type
    REFINE_SPINE_ENTITY_ID: str
    REFINE_GRAPHICS_GROUP_ID: str
    _show_palette: Callable[[object], None]
    _create_harness_gateway: Callable[[object], object]
    _serialize_palette_state: Callable[[object, str], str]
    _delete_damaged_harness: Callable[[object, str], str]
    _appearance_libraries_payload: Callable[[object], list[dict[str, str]]]
    _library_appearances_payload: Callable[[object, str], list[dict[str, str]]]
    _preview_routes: Callable[[object, str], int]
    _generate_solids: Callable[[object, str], int]
    _clear_preview: Callable[[object], int]
    _clear_highlight: Callable[[object], None]
    _clear_solids: Callable[[object, str], int]
    clear_route_previews: Callable[[object], int]
    clear_wire_solids: Callable[[object], int]
    generated_wire_bodies: Callable[..., tuple[object, ...]]
    has_refine_graphics: Callable[[object], bool]
    has_route_previews: Callable[[object], bool]
    show_route_previews: Callable[..., tuple[object, ...]]
    refresh_route_previews: Callable[..., tuple[str, ...]]
    _log_to_fusion: Callable[[str], None]
    _member_entity_tokens: Callable[[HarnessDefinition, str, UUID], tuple[str, ...]]
    _highlight_member: Callable[[object, str], int]
    _require_active_design: Callable[[object], object]
    highlight_route_preview: Callable[[object, object], int]
    highlight_route_members: Callable[[object, tuple[UUID, ...]], int]
    highlight_refine_graphics: Callable[[object, tuple[UUID, ...]], int]
    load_harnesses: Callable[[object], tuple[HarnessLoadResult, ...]]


@pytest.fixture
def addin_module(monkeypatch: pytest.MonkeyPatch) -> _PaletteLifecycleModule:
    """
    Import the lifecycle module against minimal Fusion handler stubs.
    """
    adsk_module = ModuleType("adsk")
    core_module = ModuleType("adsk.core")
    fusion_module = ModuleType("adsk.fusion")
    handler_names = (
        "CommandEventHandler",
        "ApplicationCommandEventHandler",
        "ActiveSelectionEventHandler",
        "DocumentEventHandler",
        "InputChangedEventHandler",
        "MouseEventHandler",
        "SelectionEventHandler",
        "ValidateInputsEventHandler",
        "CommandCreatedEventHandler",
        "HTMLEventHandler",
        "NavigationEventHandler",
    )
    for handler_name in handler_names:
        setattr(core_module, handler_name, type(handler_name, (), {}))
    core_module.PaletteDockingStates = SimpleNamespace(  # type: ignore[attr-defined]
        PaletteDockStateRight="right"
    )
    core_module.PaletteDockingOptions = SimpleNamespace(  # type: ignore[attr-defined]
        PaletteDockOptionsToVerticalOnly="vertical"
    )
    adsk_module.core = core_module  # type: ignore[attr-defined]
    adsk_module.fusion = fusion_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "adsk", adsk_module)
    monkeypatch.setitem(sys.modules, "adsk.core", core_module)
    monkeypatch.setitem(sys.modules, "adsk.fusion", fusion_module)
    sys.modules.pop("wire_bundler.addin", None)

    module = importlib.import_module("wire_bundler.addin")
    return cast(_PaletteLifecycleModule, cast(object, module))


def _refine_control(radius_mm: float = 10.0) -> ControlStructure:
    """
    Build one deterministic persisted refine for lifecycle-boundary tests.
    """
    return ControlStructure(
        REFINE_ID,
        "Refine Point 01",
        ControlKind.REFINE,
        "",
        refine_geometry=RefineGeometry(
            (1.0, 2.0, 3.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), radius_mm
        ),
    )


def _configure_save_test(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
    has_preview: bool,
) -> tuple[SimpleNamespace, SimpleNamespace]:
    """
    Configure one document save with a controllable live-preview result.
    """
    preview_design = object()
    document = SimpleNamespace(
        products=SimpleNamespace(itemByProductType=lambda _product_type: preview_design)
    )
    compatibility = SimpleNamespace(isCacheGraphicsOnDocumentSave=True)
    application = SimpleNamespace(
        preferences=SimpleNamespace(compatibilityPreferences=compatibility)
    )
    core_module = sys.modules["adsk.core"]
    fusion_module = sys.modules["adsk.fusion"]
    core_module.Application = SimpleNamespace(get=lambda: application)  # type: ignore[attr-defined]
    fusion_module.Design = SimpleNamespace(cast=lambda product: product)  # type: ignore[attr-defined]
    monkeypatch.setattr(addin_module, "has_route_previews", lambda _design: has_preview)
    monkeypatch.setattr(addin_module, "has_refine_graphics", lambda _design: False)
    monkeypatch.setitem(vars(addin_module), "_graphics_cache_restore_value", None)
    monkeypatch.setitem(vars(addin_module), "_graphics_cache_save_document", None)
    return document, compatibility


def _configure_relationship_selector_casts() -> None:
    """
    Make command-input and profile casts transparent for selector tests.
    """
    core_module = sys.modules["adsk.core"]
    fusion_module = sys.modules["adsk.fusion"]
    core_module.SelectionCommandInput = SimpleNamespace(  # type: ignore[attr-defined]
        cast=lambda value: value
    )
    core_module.DropDownCommandInput = SimpleNamespace(  # type: ignore[attr-defined]
        cast=lambda value: value
    )
    fusion_module.Profile = SimpleNamespace(cast=lambda value: value)  # type: ignore[attr-defined]


def test_save_with_active_preview_temporarily_disables_graphics_cache(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Keep Custom Graphics out of the saved OGS cache and restore user settings.
    """
    document, compatibility = _configure_save_test(addin_module, monkeypatch, True)

    args = SimpleNamespace(document=document)
    addin_module._DocumentSavingHandler().notify(args)
    assert not compatibility.isCacheGraphicsOnDocumentSave

    addin_module._DocumentSavedHandler().notify(args)
    assert compatibility.isCacheGraphicsOnDocumentSave
    assert addin_module._graphics_cache_restore_value is None


def test_save_without_active_preview_preserves_graphics_cache_setting(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Leave unrelated document saves and the user's cache preference untouched.
    """
    document, compatibility = _configure_save_test(addin_module, monkeypatch, False)

    addin_module._DocumentSavingHandler().notify(SimpleNamespace(document=document))

    assert compatibility.isCacheGraphicsOnDocumentSave
    assert addin_module._graphics_cache_restore_value is None


def test_palette_is_shown_during_command_creation(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Show the palette immediately when Fusion creates the input-free command.
    """
    shown_applications: list[object] = []
    application = object()
    core_module = sys.modules["adsk.core"]
    core_module.Application = SimpleNamespace(get=lambda: application)  # type: ignore[attr-defined]
    monkeypatch.setattr(
        addin_module,
        "_show_palette",
        shown_applications.append,
    )

    created_handler = addin_module._ShowPaletteCreatedHandler()
    created_handler.notify(SimpleNamespace(command=object()))

    assert shown_applications == [application]


def test_junction_selector_rejects_registered_profiles(
    addin_module: _PaletteLifecycleModule,
) -> None:
    """
    Filter registered native geometry and read one unused profile token.
    """
    registered = SimpleNamespace(entityToken="registered", nativeObject=None)
    unused = SimpleNamespace(entityToken="unused", nativeObject=None)
    selection_input = SimpleNamespace(
        selectionCount=1,
        selection=lambda _index: SimpleNamespace(entity=unused),
    )
    inputs = SimpleNamespace(itemById=lambda _identity: selection_input)
    core_module = sys.modules["adsk.core"]
    fusion_module = sys.modules["adsk.fusion"]
    core_module.SelectionCommandInput = SimpleNamespace(  # type: ignore[attr-defined]
        cast=lambda value: value
    )
    fusion_module.Profile = SimpleNamespace(cast=lambda value: value)  # type: ignore[attr-defined]
    state = addin_module._AddJunctionCommandState(UUID(int=1), (registered,))

    assert addin_module._junction_profile_token(inputs, state) == "unused"
    unused_args = SimpleNamespace(selection=SimpleNamespace(entity=unused), isSelectable=False)
    registered_args = SimpleNamespace(
        selection=SimpleNamespace(entity=registered), isSelectable=True
    )
    handler = addin_module._AddJunctionPreSelectHandler(state)
    handler.notify(unused_args)
    handler.notify(registered_args)
    assert unused_args.isSelectable is True
    assert registered_args.isSelectable is False

    selection_input.selection = lambda _index: SimpleNamespace(entity=registered)
    with pytest.raises(ValueError, match="already registered"):
        addin_module._junction_profile_token(inputs, state)


def test_relationship_selector_narrows_ambiguous_geometry_to_endpoint_choice(
    addin_module: _PaletteLifecycleModule,
) -> None:
    """
    Require an explicit End A/End B choice when one profile represents both.
    """
    profile = SimpleNamespace(nativeObject=None)
    first = JunctionPathwayRelationship(UUID(int=10), PathwayEndpoint.START)
    second = JunctionPathwayRelationship(UUID(int=10), PathwayEndpoint.END)
    candidates = (
        addin_module._JunctionRelationshipCandidate(
            first,
            "Pathway_001 · End A",
            UUID(int=20),
            profile,
        ),
        addin_module._JunctionRelationshipCandidate(
            second,
            "Pathway_001 · End B",
            UUID(int=20),
            profile,
        ),
    )
    state = addin_module._AddJunctionRelationshipCommandState(
        UUID(int=1),
        UUID(int=2),
        candidates,
    )
    selection_input = SimpleNamespace(
        selectionCount=1,
        selection=lambda _index: SimpleNamespace(entity=profile),
    )
    choice_input = SimpleNamespace(selectedItem=SimpleNamespace(name="Pathway_001 · End B"))
    inputs = SimpleNamespace(
        itemById=lambda identity: (
            selection_input
            if identity == addin_module.JUNCTION_RELATIONSHIP_GEOMETRY_INPUT_ID
            else choice_input
        )
    )
    _configure_relationship_selector_casts()

    selected = addin_module._read_junction_relationship_candidate(inputs, state)

    assert selected.relationship == second


def test_relationship_selector_refreshes_choices_as_a_collection(
    addin_module: _PaletteLifecycleModule,
) -> None:
    """
    Clear an active drop-down safely before adding current geometry matches.
    """
    profile = SimpleNamespace(nativeObject=None)
    candidates = tuple(
        addin_module._JunctionRelationshipCandidate(
            JunctionPathwayRelationship(UUID(int=10), endpoint),
            f"Pathway_001 · {label}",
            UUID(int=20),
            profile,
        )
        for endpoint, label in (
            (PathwayEndpoint.START, "End A"),
            (PathwayEndpoint.END, "End B"),
        )
    )
    state = addin_module._AddJunctionRelationshipCommandState(
        UUID(int=1),
        UUID(int=2),
        candidates,
    )
    selection_input = SimpleNamespace(
        selectionCount=1,
        selection=lambda _index: SimpleNamespace(entity=profile),
    )
    list_items = SimpleNamespace(clear=Mock(), add=Mock(side_effect=lambda *_args: object()))
    choice_input = SimpleNamespace(listItems=list_items, isVisible=False)
    inputs = SimpleNamespace(
        itemById=lambda identity: (
            selection_input
            if identity == addin_module.JUNCTION_RELATIONSHIP_GEOMETRY_INPUT_ID
            else choice_input
        )
    )
    _configure_relationship_selector_casts()

    addin_module._update_junction_relationship_choices(inputs, state)

    list_items.clear.assert_called_once_with()
    assert [record.args for record in list_items.add.call_args_list] == [
        ("Pathway_001 · End A", True),
        ("Pathway_001 · End B", False),
    ]
    assert choice_input.isVisible is True


def test_relationship_selector_refreshes_only_for_geometry_input_changes(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Preserve an active choice while continuing to respond to geometry changes.
    """
    state = addin_module._AddJunctionRelationshipCommandState(
        UUID(int=1),
        UUID(int=2),
        (),
    )
    update_choices = Mock()
    monkeypatch.setattr(
        addin_module,
        "_update_junction_relationship_choices",
        update_choices,
    )

    addin_module._AddJunctionRelationshipInputChangedHandler(state).notify(
        SimpleNamespace(
            input=SimpleNamespace(id=addin_module.JUNCTION_RELATIONSHIP_CHOICE_INPUT_ID),
            inputs=object(),
        )
    )

    update_choices.assert_not_called()

    inputs = object()
    addin_module._AddJunctionRelationshipInputChangedHandler(state).notify(
        SimpleNamespace(
            input=SimpleNamespace(id=addin_module.JUNCTION_RELATIONSHIP_GEOMETRY_INPUT_ID),
            inputs=inputs,
        )
    )

    update_choices.assert_called_once_with(inputs, state)


def test_refine_selection_accepts_only_command_spine(
    addin_module: _PaletteLifecycleModule,
) -> None:
    """
    Exclude persistent markers and unrelated Custom Graphics from placement.
    """
    handler = addin_module._RefinePreSelectHandler()
    accepted = SimpleNamespace(
        selection=SimpleNamespace(entity=SimpleNamespace(id=addin_module.REFINE_SPINE_ENTITY_ID)),
        isSelectable=False,
    )
    rejected = SimpleNamespace(
        selection=SimpleNamespace(entity=SimpleNamespace(id="another-graphic")),
        isSelectable=True,
    )
    profile = SimpleNamespace(
        selection=SimpleNamespace(entity=SimpleNamespace()),
        isSelectable=True,
    )

    handler.notify(accepted)
    handler.notify(rejected)
    handler.notify(profile)

    assert accepted.isSelectable
    assert not rejected.isSelectable
    assert not profile.isSelectable


def test_segment_selection_normalizes_profiles_and_accepts_refine_marker(
    addin_module: _PaletteLifecycleModule,
) -> None:
    """
    Match eligible native geometry without relying on unstable entity-token strings.
    """
    fusion_module = sys.modules["adsk.fusion"]
    native_profile = object()
    eligible_profile = SimpleNamespace(nativeObject=native_profile, is_profile=True)
    selected_proxy = SimpleNamespace(nativeObject=native_profile, is_profile=True)
    unrelated = SimpleNamespace(nativeObject=object(), is_profile=True)
    fusion_module.Profile = SimpleNamespace(  # type: ignore[attr-defined]
        cast=lambda entity: entity if getattr(entity, "is_profile", False) else None
    )
    refine_id = UUID(int=22)
    state = addin_module._SegmentCommandState(
        UUID(int=1),
        UUID(int=2),
        ((UUID(int=21), eligible_profile),),
        frozenset((refine_id,)),
    )
    handler = addin_module._SegmentPreSelectHandler(state)
    profile_args = SimpleNamespace(
        selection=SimpleNamespace(entity=selected_proxy), isSelectable=False
    )
    refine_args = SimpleNamespace(
        selection=SimpleNamespace(entity=SimpleNamespace(id=str(refine_id))),
        isSelectable=False,
    )
    unrelated_args = SimpleNamespace(selection=SimpleNamespace(entity=unrelated), isSelectable=True)

    handler.notify(profile_args)
    handler.notify(refine_args)
    handler.notify(unrelated_args)

    assert profile_args.isSelectable
    assert refine_args.isSelectable
    assert not unrelated_args.isSelectable


def test_refine_selection_uses_click_point_and_centimeter_radius(
    addin_module: _PaletteLifecycleModule,
) -> None:
    """
    Project Fusion's root-space click while converting database units to millimeters.
    """
    core_module = sys.modules["adsk.core"]
    core_module.SelectionCommandInput = SimpleNamespace(cast=lambda value: value)  # type: ignore[attr-defined]
    core_module.DistanceValueCommandInput = SimpleNamespace(cast=lambda value: value)  # type: ignore[attr-defined]
    selection_input = SimpleNamespace(
        selectionCount=1,
        selection=lambda _index: SimpleNamespace(
            entity=SimpleNamespace(id=addin_module.REFINE_SPINE_ENTITY_ID),
            point=SimpleNamespace(x=0.0, y=0.0, z=1.5),
        ),
    )
    radius_input = SimpleNamespace(isValidExpression=True, value=1.0)
    inputs = SimpleNamespace(
        itemById=lambda identity: selection_input if identity == "refine_spine" else radius_input
    )
    frame = GateFrame(
        UUID(int=1),
        "Gate",
        Vector3(0.0, 0.0, 10.0),
        Vector3(1.0, 0.0, 0.0),
        Vector3(0.0, 1.0, 0.0),
        5.0,
    )
    spine = addin_module.PathwaySpine(
        (Vector3(0.0, 0.0, 0.0), Vector3(0.0, 0.0, 20.0)),
        (frame,),
    )

    placement = addin_module._read_refine_placement(inputs, spine)

    assert placement.insertion_index == 1
    assert placement.geometry.origin_mm == (0.0, 0.0, 15.0)
    assert placement.geometry.display_radius_mm == 10.0


def test_refine_placement_rejects_selected_entity_without_graphics_id(
    addin_module: _PaletteLifecycleModule,
) -> None:
    """
    Reject an underlying Fusion profile without leaking an AttributeError.
    """
    core_module = sys.modules["adsk.core"]
    core_module.SelectionCommandInput = SimpleNamespace(cast=lambda value: value)  # type: ignore[attr-defined]
    core_module.DistanceValueCommandInput = SimpleNamespace(cast=lambda value: value)  # type: ignore[attr-defined]
    selection_input = SimpleNamespace(
        selectionCount=1,
        selection=lambda _index: SimpleNamespace(
            entity=SimpleNamespace(),
            point=SimpleNamespace(x=0.0, y=0.0, z=1.5),
        ),
    )
    radius_input = SimpleNamespace(isValidExpression=True, value=1.0)
    inputs = SimpleNamespace(
        itemById=lambda identity: selection_input if identity == "refine_spine" else radius_input
    )

    with pytest.raises(ValueError, match="displayed pathway spine"):
        addin_module._read_refine_placement(inputs, SimpleNamespace())


def test_refine_placement_drag_updates_existing_candidate_in_place(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Resize the initial-placement marker without replacing its graphics entity.
    """
    geometry = _refine_control(18.0).refine_geometry
    assert geometry is not None
    placement = SimpleNamespace(insertion_index=1, geometry=geometry)
    candidate = SimpleNamespace(isValid=True)
    state = addin_module._RefineCommandState(
        UUID(int=1),
        UUID(int=2),
        object(),
        object(),
        candidate=candidate,
    )
    radius = SimpleNamespace(
        isEnabled=False,
        isVisible=False,
        setManipulator=Mock(return_value=True),
    )
    inputs = SimpleNamespace(itemById=lambda _identity: radius)
    viewport = SimpleNamespace(refresh=Mock())
    application = SimpleNamespace(activeViewport=viewport)
    core_module = sys.modules["adsk.core"]
    core_module.Application = SimpleNamespace(get=lambda: application)  # type: ignore[attr-defined]
    core_module.DistanceValueCommandInput = SimpleNamespace(cast=lambda value: value)  # type: ignore[attr-defined]
    update_candidate = Mock()
    monkeypatch.setattr(addin_module, "_read_refine_placement", lambda *_args: placement)
    monkeypatch.setattr(addin_module, "update_candidate_refine", update_candidate)

    addin_module._update_refine_placement(
        state,
        inputs,
        position_manipulator=False,
    )

    assert state.placement is placement
    assert radius.isEnabled
    assert radius.isVisible
    radius.setManipulator.assert_not_called()
    update_candidate.assert_called_once_with(candidate, geometry)
    viewport.refresh.assert_called_once()


def test_refine_mouse_drag_reads_live_command_inputs(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Poll the distance manipulator throughout a click-drag gesture.
    """
    state = addin_module._RefineCommandState(
        UUID(int=1),
        UUID(int=2),
        object(),
        object(),
    )
    inputs = object()
    update_placement = Mock()
    monkeypatch.setattr(addin_module, "_update_refine_placement", update_placement)

    addin_module._RefineMouseDragHandler(state, inputs).notify(SimpleNamespace())

    update_placement.assert_called_once_with(
        state,
        inputs,
        position_manipulator=False,
    )


def test_refine_placement_replaces_invalidated_candidate_before_redraw(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Never update a Custom Graphics handle Fusion has already invalidated.
    """
    geometry = _refine_control().refine_geometry
    assert geometry is not None
    placement = SimpleNamespace(insertion_index=1, geometry=geometry)
    group = object()
    invalid_candidate = SimpleNamespace(isValid=False)
    replacement = SimpleNamespace(isValid=True)
    state = addin_module._RefineCommandState(
        UUID(int=1),
        UUID(int=2),
        object(),
        group,
        candidate=invalid_candidate,
    )
    radius = SimpleNamespace(isEnabled=False, isVisible=False)
    inputs = SimpleNamespace(itemById=lambda _identity: radius)
    application = SimpleNamespace(activeViewport=SimpleNamespace(refresh=Mock()))
    core_module = sys.modules["adsk.core"]
    core_module.Application = SimpleNamespace(get=lambda: application)  # type: ignore[attr-defined]
    core_module.DistanceValueCommandInput = SimpleNamespace(cast=lambda value: value)  # type: ignore[attr-defined]
    draw_candidate = Mock(return_value=replacement)
    update_candidate = Mock()
    monkeypatch.setattr(addin_module, "_read_refine_placement", lambda *_args: placement)
    monkeypatch.setattr(addin_module, "draw_candidate_refine", draw_candidate)
    monkeypatch.setattr(addin_module, "update_candidate_refine", update_candidate)

    addin_module._update_refine_placement(
        state,
        inputs,
        position_manipulator=False,
    )

    assert state.candidate is replacement
    draw_candidate.assert_called_once_with(group, geometry)
    update_candidate.assert_not_called()


def test_edited_refine_geometry_reads_triad_and_resized_radius(
    addin_module: _PaletteLifecycleModule,
) -> None:
    """
    Convert the live triad frame and radius from centimeters to millimeters.
    """
    core_module = sys.modules["adsk.core"]
    triad = SimpleNamespace(
        isValidExpressions=True,
        transform=SimpleNamespace(
            getAsCoordinateSystem=lambda: (
                SimpleNamespace(x=1.0, y=2.0, z=3.0),
                SimpleNamespace(x=0.0, y=1.0, z=0.0),
                SimpleNamespace(x=0.0, y=0.0, z=1.0),
                SimpleNamespace(x=1.0, y=0.0, z=0.0),
            )
        ),
    )
    radius = SimpleNamespace(isValidExpression=True, value=1.8)
    core_module.TriadCommandInput = SimpleNamespace(cast=lambda value: value)  # type: ignore[attr-defined]
    core_module.DistanceValueCommandInput = SimpleNamespace(cast=lambda value: value)  # type: ignore[attr-defined]
    inputs = SimpleNamespace(
        itemById=lambda identity: triad if identity == "refine_transform" else radius
    )

    geometry = addin_module._read_edited_refine_geometry(inputs)

    assert geometry == RefineGeometry((10.0, 20.0, 30.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), 18.0)


def test_refine_triad_reapplies_initial_world_transform(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Work around Fusion ignoring the matrix passed during triad creation.
    """
    geometry = _refine_control().refine_geometry
    assert geometry is not None
    transform = object()
    triad = SimpleNamespace(transform=None)
    inputs = SimpleNamespace(addTriadCommandInput=Mock(return_value=triad))
    monkeypatch.setattr(addin_module, "_refine_geometry_transform", lambda _geometry: transform)

    result = addin_module._add_refine_transform_input(inputs, geometry)

    assert result is triad
    inputs.addTriadCommandInput.assert_called_once_with("refine_transform", transform)
    assert triad.transform is transform


def test_edit_refine_preview_redraws_current_triad_geometry(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Rebuild the command-local marker during Fusion's preview event.
    """
    initial = _refine_control().refine_geometry
    assert initial is not None
    changed = replace(initial, origin_mm=(10.0, 20.0, 30.0))
    group = object()
    state = addin_module._EditRefineCommandState(UUID(int=1), REFINE_ID, group, initial)
    read_geometry = Mock(return_value=changed)
    update_editor = Mock()
    viewport = SimpleNamespace(refresh=Mock())
    application = SimpleNamespace(activeViewport=viewport)
    core_module = sys.modules["adsk.core"]
    core_module.Application = SimpleNamespace(get=lambda: application)  # type: ignore[attr-defined]
    monkeypatch.setattr(addin_module, "_read_edited_refine_geometry", read_geometry)
    monkeypatch.setattr(addin_module, "update_refine_editor", update_editor)
    command_inputs = object()

    addin_module._EditRefineExecutePreviewHandler(state).notify(
        SimpleNamespace(command=SimpleNamespace(commandInputs=command_inputs))
    )

    assert state.geometry == changed
    read_geometry.assert_called_once_with(command_inputs)
    update_editor.assert_called_once_with(group, changed)
    viewport.refresh.assert_called_once()


def test_edit_refine_input_change_updates_existing_marker(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Apply drag and dialog edits through the immediate input-change event.
    """
    geometry = _refine_control().refine_geometry
    assert geometry is not None
    state = addin_module._EditRefineCommandState(UUID(int=1), REFINE_ID, object(), geometry)
    preview = Mock()
    monkeypatch.setattr(addin_module, "_preview_edited_refine", preview)
    command_inputs = object()

    addin_module._EditRefineInputChangedHandler(state).notify(
        SimpleNamespace(inputs=command_inputs)
    )

    preview.assert_called_once_with(state, command_inputs)


def test_refine_editor_updates_one_graphics_transform_in_place(
    addin_module: _PaletteLifecycleModule,
) -> None:
    """
    Encode world position, orientation, and radius in the live graphics transform.
    """
    from wire_bundler.fusion import refine_graphics

    core_module = refine_graphics.adsk.core
    transform = SimpleNamespace(setCell=Mock(return_value=True))
    core_module.Matrix3D = SimpleNamespace(create=lambda: transform)  # type: ignore[attr-defined]
    geometry = RefineGeometry(
        (10.0, 20.0, 30.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        20.0,
    )
    group = SimpleNamespace(isValid=True, transform=None)

    addin_module.update_refine_editor(group, geometry)

    assert [item.args for item in transform.setCell.call_args_list] == [
        (0, 0, 0.0),
        (1, 0, 2.0),
        (2, 0, 0.0),
        (0, 1, 0.0),
        (1, 1, 0.0),
        (2, 1, 2.0),
        (0, 2, 1.0),
        (1, 2, 0.0),
        (2, 2, 0.0),
        (0, 3, 1.0),
        (1, 3, 2.0),
        (2, 3, 3.0),
    ]
    assert group.transform is transform


def test_selecting_persistent_refine_opens_transform_editor(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
    valid_harness: HarnessDefinition,
) -> None:
    """
    Turn a normal viewport selection of a refine marker into an edit command.
    """
    refine_id = REFINE_ID
    refine = _refine_control()
    definition = replace(valid_harness, controls=(*valid_harness.controls, refine))
    command_definition = SimpleNamespace(execute=Mock(return_value=True))
    selections = SimpleNamespace(clear=Mock(return_value=True))
    application = SimpleNamespace(
        userInterface=SimpleNamespace(
            activeSelections=selections,
            commandDefinitions=SimpleNamespace(itemById=lambda _identity: command_definition),
        )
    )
    core_module = sys.modules["adsk.core"]
    core_module.Application = SimpleNamespace(get=lambda: application)  # type: ignore[attr-defined]
    monkeypatch.setattr(
        addin_module,
        "load_harnesses",
        lambda _gateway: (SimpleNamespace(definition=definition),),
    )
    monkeypatch.setattr(addin_module, "_create_harness_gateway", lambda _application: object())
    marker = SimpleNamespace(
        id=str(refine_id),
        parent=SimpleNamespace(id=addin_module.REFINE_GRAPHICS_GROUP_ID),
    )

    addin_module._RefineActiveSelectionHandler().notify(
        SimpleNamespace(currentSelection=[SimpleNamespace(entity=marker)])
    )

    selections.clear.assert_called_once_with()
    command_definition.execute.assert_called_once_with()
    assert addin_module._pending_refine_edit_ids == (definition.harness_id, refine_id)


def test_refine_reconciliation_redraws_changed_geometry_with_same_identity(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
    valid_harness: HarnessDefinition,
) -> None:
    """
    Rebuild a marker even when a resize preserves its persistent control UUID.
    """
    from wire_bundler.fusion import refine_graphics

    refine_id = REFINE_ID
    refine = _refine_control(18.0)
    definition = replace(valid_harness, controls=(*valid_harness.controls, refine))
    existing = SimpleNamespace(count=1, item=lambda _index: SimpleNamespace(id=str(refine_id)))
    marker = SimpleNamespace()
    created_group = SimpleNamespace()
    groups = SimpleNamespace(add=Mock(return_value=created_group))
    design = SimpleNamespace(rootComponent=SimpleNamespace(customGraphicsGroups=groups))
    clear = Mock()
    add_polyline = Mock(return_value=marker)
    monkeypatch.setattr(refine_graphics, "_find_group", lambda _design, _identity: existing)
    monkeypatch.setattr(refine_graphics, "clear_refine_graphics", clear)
    monkeypatch.setattr(refine_graphics, "_add_polyline", add_polyline)

    refine_graphics.reconcile_refine_graphics(design, (definition,))

    clear.assert_called_once_with(design)
    groups.add.assert_called_once_with()
    add_polyline.assert_called_once()
    assert marker.id == str(refine_id)


def test_palette_opens_at_relationship_graphic_working_size(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Give the editor enough initial room for its connection-map labels and controls.
    """
    palette = SimpleNamespace(
        incomingFromHTML=SimpleNamespace(add=Mock(return_value=True)),
        navigatingURL=SimpleNamespace(add=Mock(return_value=True)),
        htmlFileURL="palette.html",
    )
    palettes = SimpleNamespace(
        itemById=Mock(return_value=None),
        add=Mock(return_value=palette),
    )
    application = SimpleNamespace(userInterface=SimpleNamespace(palettes=palettes))
    monkeypatch.setattr(addin_module, "_send_palette_state", lambda _application: None)
    monkeypatch.setattr(addin_module, "_log_to_fusion", lambda _message: None)

    addin_module._show_palette(application)

    assert palettes.add.call_args.args[6:8] == (840, 760)
    assert palettes.add.call_args.args[3] is False
    assert palette.dockingOption == "vertical"
    assert palette.dockingState == "right"
    assert palette.isVisible is True


def test_existing_palette_is_redocked_and_revealed(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Recover a floating palette that macOS moved outside Fusion's fullscreen Space.
    """
    palette = SimpleNamespace(dockingState="floating", isVisible=True)
    palettes = SimpleNamespace(itemById=Mock(return_value=palette))
    application = SimpleNamespace(userInterface=SimpleNamespace(palettes=palettes))
    monkeypatch.setattr(addin_module, "_send_palette_state", lambda _application: None)

    addin_module._show_palette(application)

    assert palette.dockingState == "right"
    assert palette.dockingOption == "vertical"
    assert palette.isVisible is True


def test_palette_remains_usable_when_fusion_rejects_redocking(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Reveal and refresh an existing palette when Fusion rejects area placement.
    """

    class _Palette:
        """
        Reproduce Fusion's docking-state assignment failure.
        """

        def __init__(self) -> None:
            """
            Start hidden with no docking option assigned.
            """
            self.dockingOption = None
            self.isVisible = False

        # noinspection PyPep8Naming
        @property
        def dockingState(self) -> str:
            """
            Return the current floating state.
            """
            return "floating"

        # noinspection PyPep8Naming
        @dockingState.setter
        def dockingState(self, _value: str) -> None:
            """
            Reproduce Fusion's internal area-placement rejection.
            """
            raise RuntimeError("InternalValidationError: setAreaPlacement")

    palette = _Palette()
    application = SimpleNamespace(
        userInterface=SimpleNamespace(palettes=SimpleNamespace(itemById=Mock(return_value=palette)))
    )
    sent = Mock()
    logged: list[str] = []
    monkeypatch.setattr(addin_module, "_send_palette_state", sent)
    monkeypatch.setattr(addin_module, "_log_to_fusion", logged.append)

    addin_module._show_palette(application)

    assert palette.isVisible
    sent.assert_called_once_with(application)
    assert logged == [
        "Harness Builder could not restore right docking: InternalValidationError: setAreaPlacement"
    ]


def test_all_palette_resources_are_packaged(addin_module: _PaletteLifecycleModule) -> None:
    """
    Keep every stylesheet and ordered script beside the palette entry point.
    """
    assert all(path.is_file() for path in addin_module.PALETTE_RESOURCE_FILES)


def test_palette_state_contains_complete_editor_definition(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
    valid_harness: HarnessDefinition,
) -> None:
    """
    Include stable identities and ordered relationships needed by the editor.
    """
    gateway = SimpleNamespace(
        is_entity_token_resolvable=lambda entity_token: entity_token == "fusion-gate-token"
    )
    valid_harness = replace(
        valid_harness,
        pathways=(replace(valid_harness.pathways[0], start_name="Sensor", end_name="Controller"),),
        wires=(replace(valid_harness.wires[0], display_name="Signal", start_end_name="O2"),),
    )
    result = HarnessLoadResult(
        component_name="Harness_001",
        definition=valid_harness,
        error=None,
        validation_messages=(),
    )
    monkeypatch.setattr(addin_module, "_create_harness_gateway", lambda _application: gateway)
    monkeypatch.setattr(addin_module, "load_harnesses", lambda _gateway: (result,))

    payload = json.loads(addin_module._serialize_palette_state(object(), "Ready"))

    harness = payload["harnesses"][0]
    assert payload["notice"] == "Ready"
    assert "ETFE" in payload["catalog"]["insulationMaterials"]
    assert harness["materialDefaults"]["mainColor"]["hex"] == "#202020"
    assert harness["wires"][0]["materials"] == harness["materialDefaults"]
    assert harness["wires"][0]["materialOverrides"]["mainColor"] is None
    assert harness["gateDefaults"] == {"approach_mm": None, "departure_mm": None}
    assert harness["connections"][0]["interpolation"] == harness["endDefaults"]
    assert harness["controls"][0]["interpolation"] == harness["gateDefaults"]
    monkeypatch.setitem(
        vars(addin_module), "_last_command_error", "Wire 001: create cross-section plane failed"
    )
    refreshed = json.loads(addin_module._serialize_palette_state(object(), ""))
    assert refreshed["notice"] == "Wire 001: create cross-section plane failed"
    assert harness["schemaVersion"] == valid_harness.schema_version
    assert harness["profiles"][0]["name"] == "Primary wire"
    assert harness["connections"][0]["name"] == "J1 / Pin 1"
    assert harness["controls"][0]["kind"] == "routing_gate"
    assert harness["controls"][0]["hasLinkedGeometry"]
    assert not harness["connections"][0]["hasLinkedGeometry"]
    assert harness["pathways"][0]["name"] == "Main Pathway"
    assert harness["pathways"][0]["startName"] == "Sensor"
    assert harness["pathways"][0]["endName"] == "Controller"
    assert harness["wires"][0]["displayName"] == "Signal"
    assert harness["wires"][0]["startEndName"] == "O2"
    assert harness["pathways"][0]["orderedControlIds"] == [
        str(valid_harness.controls[0].control_id)
    ]
    assert harness["wires"][0]["wireNumber"] == "001"
    assert harness["wires"][0]["orderedPathwayIds"] == [str(valid_harness.pathways[0].pathway_id)]
    assert harness["wires"][0]["orderedControlIds"] == [str(valid_harness.controls[0].control_id)]
    relationship_map = harness["relationshipMap"]
    assert relationship_map["routes"][0]["nodeIds"] == [
        f"connection:{valid_harness.connections[0].connection_id}",
        f"pathway:{valid_harness.pathways[0].pathway_id}",
        f"connection:{valid_harness.connections[1].connection_id}",
    ]
    assert relationship_map["pathwayOccupancy"][0]["wireIds"] == [
        str(valid_harness.wires[0].wire_id)
    ]
    assert relationship_map["auditIssues"] == []


def test_damaged_palette_entry_can_delete_its_exact_component(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Give an unreadable entry a short-lived token that resolves to its component.
    """
    component = object()
    result = HarnessLoadResult(
        component_name="Broken Harness",
        definition=None,
        error="Stored definition is malformed.",
        validation_messages=(),
        component_handle=component,
    )
    deleted_components: list[object] = []
    gateway = SimpleNamespace(
        delete_stored_harness_component=deleted_components.append,
    )
    monkeypatch.setattr(addin_module, "_create_harness_gateway", lambda _application: gateway)
    monkeypatch.setattr(addin_module, "load_harnesses", lambda _gateway: (result,))

    state = json.loads(addin_module._serialize_palette_state(object(), ""))
    deletion_token = state["harnesses"][0]["deletionToken"]
    refreshed = json.loads(addin_module._serialize_palette_state(object(), ""))
    notice = addin_module._delete_damaged_harness(
        object(),
        json.dumps({"deletionToken": deletion_token}),
    )

    assert isinstance(deletion_token, str)
    assert refreshed["harnesses"][0]["deletionToken"] == deletion_token
    assert deleted_components == [component]
    assert notice == "Deleted damaged harness Broken Harness."
    assert deletion_token not in addin_module._damaged_harness_results


def test_route_capacity_error_fails_preview_command(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Keep expected preview rejection actionable through Fusion's command failure.
    """
    document = object()
    application = SimpleNamespace(activeDocument=document)
    logged_messages: list[str] = []
    core_module = sys.modules["adsk.core"]
    core_module.Application = SimpleNamespace(get=lambda: application)  # type: ignore[attr-defined]
    monkeypatch.setattr(
        addin_module,
        "_preview_routes",
        Mock(side_effect=ValueError("Gate 4 cannot fit 3 wires.")),
    )
    monkeypatch.setattr(addin_module, "_log_to_fusion", logged_messages.append)
    args = SimpleNamespace(executeFailed=False, executeFailedMessage="")
    addin_module._PaletteEditExecuteHandler(("preview_routes", "{}", document)).notify(args)
    assert args.executeFailed
    assert args.executeFailedMessage == "Gate 4 cannot fit 3 wires."
    assert len(logged_messages) == 1
    assert logged_messages[0].startswith("Harness command failed: Gate 4 cannot fit 3 wires.")
    assert "Traceback (most recent call last)" in logged_messages[0]


def test_damaged_deletion_runs_inside_palette_command(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Delete and refresh palette state within the native Fusion transaction.
    """
    document = object()
    application = SimpleNamespace(activeDocument=document, activeViewport=Mock())
    core_module = sys.modules["adsk.core"]
    core_module.Application = SimpleNamespace(get=lambda: application)  # type: ignore[attr-defined]
    delete = Mock(return_value="Deleted damaged harness Broken Harness.")
    sent = Mock()
    monkeypatch.setattr(addin_module, "_delete_damaged_harness", delete)
    monkeypatch.setattr(addin_module, "_send_palette_state", sent)
    payload = json.dumps({"deletionToken": "current-token"})
    args = SimpleNamespace(executeFailed=False, executeFailedMessage="")

    addin_module._PaletteEditExecuteHandler(("delete_damaged_harness", payload, document)).notify(
        args
    )

    delete.assert_called_once_with(application, payload)
    application.activeViewport.refresh.assert_called_once_with()
    sent.assert_called_once_with(application, "Deleted damaged harness Broken Harness.")
    assert not args.executeFailed


@pytest.mark.parametrize(
    ("member_type", "identity_attribute", "expected_tokens"),
    [
        ("control", "control_id", ("fusion-gate-token",)),
        ("connection", "connection_id", ("fusion-start-token",)),
        ("wire", "wire_id", ("fusion-start-token", "fusion-end-token")),
    ],
)
def test_resolves_palette_members_to_linked_geometry_tokens(
    addin_module: _PaletteLifecycleModule,
    valid_harness: HarnessDefinition,
    member_type: str,
    identity_attribute: str,
    expected_tokens: tuple[str, ...],
) -> None:
    """
    Resolve stable UI identities without exposing opaque Fusion tokens to HTML.
    """
    collections = {
        "control": valid_harness.controls,
        "connection": valid_harness.connections,
        "wire": valid_harness.wires,
    }
    member_id = getattr(collections[member_type][0], identity_attribute)

    tokens = addin_module._member_entity_tokens(valid_harness, member_type, member_id)

    assert tokens == expected_tokens


def test_highlights_both_wire_endpoint_profiles(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
    valid_harness: HarnessDefinition,
) -> None:
    """
    Highlight a wire's generated body together with both endpoint profiles.
    """
    start_profile = object()
    end_profile = object()
    profiles_by_token = {
        "fusion-start-token": [start_profile],
        "fusion-end-token": [end_profile],
    }
    design = SimpleNamespace(
        findEntityByToken=profiles_by_token.get,
        rootComponent=SimpleNamespace(customGraphicsGroups=SimpleNamespace(count=0)),
    )
    selections = SimpleNamespace(clear=Mock(return_value=True), add=Mock(return_value=True))
    viewport = SimpleNamespace(refresh=Mock())
    generated_body = object()
    harness_component = object()
    application = SimpleNamespace(
        userInterface=SimpleNamespace(activeSelections=selections),
        activeViewport=viewport,
    )
    gateway = SimpleNamespace(
        read_harness_definition=lambda _harness_id: dumps(valid_harness),
        harness_component=Mock(return_value=harness_component),
    )
    fusion_module = sys.modules["adsk.fusion"]
    fusion_module.Profile = SimpleNamespace(cast=lambda entity: entity)  # type: ignore[attr-defined]
    monkeypatch.setattr(addin_module, "_require_active_design", lambda _application: design)
    monkeypatch.setattr(addin_module, "_create_harness_gateway", lambda _application: gateway)
    generated_bodies = Mock(return_value=(generated_body,))
    monkeypatch.setattr(addin_module, "generated_wire_bodies", generated_bodies)
    payload = json.dumps(
        {
            "harnessId": str(valid_harness.harness_id),
            "memberType": "wire",
            "memberId": str(valid_harness.wires[0].wire_id),
        }
    )

    count = addin_module._highlight_member(application, payload)

    assert count == 3
    selections.clear.assert_called_once_with()
    assert [call.args[0] for call in selections.add.call_args_list] == [
        start_profile,
        end_profile,
        generated_body,
    ]
    generated_bodies.assert_called_once_with(
        design.rootComponent,
        harness_component,
        (valid_harness.wires[0].wire_id,),
    )
    viewport.refresh.assert_called_once_with()


def test_refine_control_hover_highlights_persistent_marker(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
    valid_harness: HarnessDefinition,
) -> None:
    """
    Route a refine-row hover to Custom Graphics without requiring a profile token.
    """
    refine_id = REFINE_ID
    refine = _refine_control()
    definition = replace(valid_harness, controls=(*valid_harness.controls, refine))
    design = SimpleNamespace(rootComponent=object())
    selections = SimpleNamespace(clear=Mock(return_value=True), add=Mock(return_value=True))
    application = SimpleNamespace(
        userInterface=SimpleNamespace(activeSelections=selections),
        activeViewport=SimpleNamespace(refresh=Mock()),
    )
    gateway = SimpleNamespace(
        read_harness_definition=lambda _harness_id: dumps(definition),
        harness_component=lambda _harness_id: object(),
    )
    marker_highlight = Mock(return_value=1)
    monkeypatch.setattr(addin_module, "_require_active_design", lambda _application: design)
    monkeypatch.setattr(addin_module, "_create_harness_gateway", lambda _application: gateway)
    monkeypatch.setattr(addin_module, "highlight_refine_graphics", marker_highlight)
    monkeypatch.setattr(addin_module, "highlight_route_members", lambda _design, _ids: 0)
    monkeypatch.setattr(addin_module, "generated_wire_bodies", lambda *_args: ())
    payload = json.dumps(
        {
            "harnessId": str(definition.harness_id),
            "memberType": "control",
            "memberId": str(refine_id),
        }
    )

    count = addin_module._highlight_member(application, payload)

    assert count == 1
    marker_highlight.assert_called_once_with(design, (refine_id,))
    assert not selections.add.called


def test_preview_hover_emphasizes_only_matching_centerline(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
    valid_harness: HarnessDefinition,
) -> None:
    """
    Emphasize an existing wire preview and clear it without selecting sketch profiles.
    """
    from wire_bundler.fusion import route_preview

    monkeypatch.setitem(vars(route_preview), "adsk", sys.modules["adsk"])
    fusion_module = sys.modules["adsk.fusion"]
    monkeypatch.setitem(
        vars(fusion_module), "CustomGraphicsGroup", SimpleNamespace(cast=lambda item: item)
    )
    monkeypatch.setitem(
        vars(fusion_module), "CustomGraphicsLines", SimpleNamespace(cast=lambda item: item)
    )
    selected = SimpleNamespace(weight=1.0)
    other = SimpleNamespace(weight=1.0)
    child_groups = [
        SimpleNamespace(id=str(valid_harness.wires[0].wire_id), count=1, item=lambda _i: selected),
        SimpleNamespace(id="other-wire", count=1, item=lambda _i: other),
    ]
    group = SimpleNamespace(
        id=route_preview.PREVIEW_GROUP_ID, count=2, item=child_groups.__getitem__
    )
    design = SimpleNamespace(
        rootComponent=SimpleNamespace(
            customGraphicsGroups=SimpleNamespace(count=1, item=lambda _i: group)
        )
    )
    count = addin_module.highlight_route_preview(design, valid_harness.wires[0].wire_id)
    assert count == 1
    assert selected.weight == 5.0
    assert other.weight == 1.0
    assert addin_module.highlight_route_preview(design, None) == 0
    assert selected.weight == 1.0
    design.rootComponent.customGraphicsGroups.count = 0
    assert addin_module.highlight_route_preview(design, valid_harness.wires[0].wire_id) == 0


@pytest.mark.parametrize("action", ["rename_wire", "set_interpolation"])
def test_palette_edit_waits_for_execute_and_releases_handlers(
    addin_module: _PaletteLifecycleModule, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    """
    Queue without changing data, then group persistence and preview in execute.
    """
    document = object()
    definition = Mock(execute=Mock(return_value=True))
    application = SimpleNamespace(
        activeDocument=document,
        activeViewport=Mock(),
        userInterface=SimpleNamespace(
            commandDefinitions=Mock(itemById=Mock(return_value=definition))
        ),
    )
    core_module = sys.modules["adsk.core"]
    core_module.Application = SimpleNamespace(get=lambda: application)  # type: ignore[attr-defined]
    applied = Mock(return_value="Renamed wire.")
    refreshed = Mock(return_value="")
    sent = Mock()
    monkeypatch.setattr(addin_module, "_apply_palette_edit", applied)
    monkeypatch.setattr(addin_module, "_refresh_active_preview", refreshed)
    monkeypatch.setattr(addin_module, "_send_palette_state", sent)
    payload = json.dumps({"harnessId": str(UUID(int=1))})
    addin_module._open_palette_edit(application, action, payload)
    applied.assert_not_called()
    handlers: list[object] = []
    cleanup: list[object] = []
    command = SimpleNamespace(
        execute=Mock(add=Mock(side_effect=lambda handler: handlers.append(handler) or True)),
        destroy=Mock(add=Mock(side_effect=lambda handler: cleanup.append(handler) or True)),
    )
    addin_module._PaletteEditCreatedHandler().notify(SimpleNamespace(command=command))
    applied.assert_not_called()
    args = SimpleNamespace(executeFailed=False)
    cast(Mock, handlers[0]).notify(args)
    applied.assert_called_once_with(application, action, payload)
    refreshed.assert_called_once_with(application, UUID(int=1), ensure_visible=False)
    assert not args.executeFailed
    cast(Mock, cleanup[0]).notify(SimpleNamespace())
    assert handlers[0] not in addin_module._handlers
    assert cleanup[0] not in addin_module._handlers


def test_material_save_applies_existing_bodies_and_preview(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Apply saved material settings to persistent solids and active graphics together.
    """
    document = object()
    application = SimpleNamespace(activeDocument=document, activeViewport=Mock())
    core_module = sys.modules["adsk.core"]
    core_module.Application = SimpleNamespace(get=lambda: application)  # type: ignore[attr-defined]
    harness_id = UUID(int=1)
    applied = Mock(return_value="Saved harness wire-material defaults.")
    applied_bodies = Mock(return_value="Applied materials to 2 generated wires.")
    refreshed = Mock(return_value="")
    sent = Mock()
    monkeypatch.setattr(addin_module, "_apply_palette_edit", applied)
    monkeypatch.setattr(addin_module, "_apply_generated_materials", applied_bodies)
    monkeypatch.setattr(addin_module, "_refresh_active_preview", refreshed)
    monkeypatch.setattr(addin_module, "_send_palette_state", sent)
    payload = json.dumps({"harnessId": str(harness_id)})
    args = SimpleNamespace(executeFailed=False, executeFailedMessage="")

    addin_module._PaletteEditExecuteHandler(
        ("set_harness_material_defaults", payload, document)
    ).notify(args)

    applied_bodies.assert_called_once_with(application, harness_id)
    refreshed.assert_called_once_with(application, harness_id, ensure_visible=True)
    sent.assert_called_once_with(
        application,
        "Saved harness wire-material defaults. Applied materials to 2 generated wires.",
    )
    assert not args.executeFailed


def test_material_refresh_shows_striped_preview_when_none_is_active(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
    valid_harness: HarnessDefinition,
) -> None:
    """
    Create visible stripe graphics as direct feedback for Apply and Save.
    """
    stripe = WireStripe(WireColor("White", 245, 245, 245), 0.2)
    definition = replace(
        valid_harness,
        material_defaults=replace(valid_harness.material_defaults, stripes=(stripe,)),
    )
    design = object()
    application = SimpleNamespace(activeProduct=design)
    gateway = SimpleNamespace(read_harness_definition=lambda _identity: dumps(definition))
    fusion_module = sys.modules["adsk.fusion"]
    fusion_module.Design = SimpleNamespace(cast=lambda product: product)  # type: ignore[attr-defined]
    show = Mock(return_value=(object(),))
    refresh = Mock()
    monkeypatch.setattr(addin_module, "_create_harness_gateway", lambda _application: gateway)
    monkeypatch.setattr(addin_module, "show_route_previews", show)
    monkeypatch.setattr(addin_module, "refresh_route_previews", refresh)

    assert (
        addin_module._refresh_active_preview(
            application,
            definition.harness_id,
            ensure_visible=True,
        )
        == ""
    )

    show.assert_called_once_with(design, definition)
    refresh.assert_not_called()


def test_palette_edit_rejects_document_switch(
    addin_module: _PaletteLifecycleModule, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Do not apply delayed palette requests to a different active document.
    """
    application = SimpleNamespace(activeDocument=object())
    core_module = sys.modules["adsk.core"]
    core_module.Application = SimpleNamespace(get=lambda: application)  # type: ignore[attr-defined]
    applied = Mock()
    monkeypatch.setattr(addin_module, "_apply_palette_edit", applied)
    monkeypatch.setattr(addin_module, "_log_to_fusion", Mock())
    args = SimpleNamespace(executeFailed=False, executeFailedMessage="")
    addin_module._PaletteEditExecuteHandler(("remove_wire", "{}", object())).notify(args)
    assert args.executeFailed
    assert "document changed" in args.executeFailedMessage
    applied.assert_not_called()


def test_history_sync_does_not_edit_model_or_redraw(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
    valid_harness: HarnessDefinition,
) -> None:
    """
    Reconcile restored caches and palette without starting an edit that clears Redo.
    """
    design = object()
    application = SimpleNamespace(activeProduct=design)
    core_module = sys.modules["adsk.core"]
    core_module.Application = SimpleNamespace(get=lambda: application)  # type: ignore[attr-defined]
    fusion_module = sys.modules["adsk.fusion"]
    fusion_module.Design = SimpleNamespace(cast=lambda value: value)  # type: ignore[attr-defined]
    gateway = Mock()
    reconcile = Mock()
    sent = Mock()
    refreshed = Mock()
    monkeypatch.setattr(addin_module, "_create_harness_gateway", lambda _application: gateway)
    monkeypatch.setattr(
        addin_module,
        "load_harnesses",
        Mock(return_value=(SimpleNamespace(definition=valid_harness),)),
    )
    monkeypatch.setattr(addin_module, "reconcile_preview_history", reconcile)
    monkeypatch.setattr(addin_module, "_send_palette_state", sent)
    monkeypatch.setattr(addin_module, "_refresh_active_preview", refreshed)
    addin_module._HistoryChangedHandler().notify(SimpleNamespace(commandId="UndoCommand"))
    reconcile.assert_called_once_with(design, (valid_harness,))
    sent.assert_called_once_with(application)
    refreshed.assert_not_called()
    assert gateway.mock_calls == []


def test_palette_command_launch_failure_releases_request(
    addin_module: _PaletteLifecycleModule, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Allow a retry after Fusion declines to launch a queued edit.
    """
    definition = Mock(execute=Mock(return_value=False))
    application = SimpleNamespace(
        activeDocument=object(),
        userInterface=SimpleNamespace(
            commandDefinitions=Mock(itemById=Mock(return_value=definition))
        ),
    )
    monkeypatch.setattr(addin_module, "_pending_palette_edit", None)
    with pytest.raises(RuntimeError, match="could not execute"):
        addin_module._open_palette_edit(application, "rename_wire", "{}")
    assert addin_module._pending_palette_edit is None


@pytest.mark.parametrize("target", ["gate", "end", "defaults"])
def test_interpolation_bridge_persists_selected_target(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
    valid_harness: HarnessDefinition,
    target: str,
) -> None:
    """
    Translate popup distances into one complete metadata write with stable target identity.
    """
    gateway = Mock(read_harness_definition=Mock(return_value=dumps(valid_harness)))
    monkeypatch.setattr(addin_module, "_create_harness_gateway", lambda _application: gateway)
    target_id = (
        valid_harness.controls[0].control_id
        if target == "gate"
        else valid_harness.connections[0].connection_id
    )
    request = {
        "harnessId": str(valid_harness.harness_id),
        "target": target,
        "targetId": str(target_id),
        "memberId": str(valid_harness.connections[0].member_identities[0]),
        "settings": {"approach_mm": 2, "departure_mm": None},
        "endDefaults": {"approach_mm": 1, "departure_mm": 3},
    }
    addin_module._apply_palette_edit(object(), "set_interpolation", json.dumps(request))
    gateway.replace_harness_definition.assert_called_once()
    saved = loads(gateway.replace_harness_definition.call_args.args[1])
    actual = (
        saved.gate_defaults
        if target == "defaults"
        else saved.controls[0].interpolation
        if target == "gate"
        else saved.connections[0].member_settings[0]
    )
    assert actual.approach_mm == 2
    assert actual.departure_mm is None
    assert saved.wires == valid_harness.wires
    if target == "defaults":
        assert saved.end_defaults.departure_mm == 3
        assert saved.connections == valid_harness.connections
        assert saved.controls == valid_harness.controls


def test_junction_relationship_bridge_persists_endpoint_list(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
    valid_harness: HarnessDefinition,
) -> None:
    """
    Translate palette endpoint selections into the typed application edit.
    """
    control = ControlStructure(
        UUID("37000000-0000-0000-0000-000000000001"),
        "Junction Gate",
        ControlKind.ROUTING_GATE,
        "junction-token",
    )
    junction = JunctionDefinition(
        UUID("38000000-0000-0000-0000-000000000001"),
        "Junction 01",
        control.control_id,
    )
    definition = replace(
        valid_harness,
        controls=(*valid_harness.controls, control),
        junctions=(junction,),
    )
    gateway = Mock(read_harness_definition=Mock(return_value=dumps(definition)))
    monkeypatch.setattr(addin_module, "_create_harness_gateway", lambda _application: gateway)
    request = {
        "harnessId": str(definition.harness_id),
        "junctionId": str(junction.junction_id),
        "pathwayRelationships": [
            {
                "pathwayId": str(definition.pathways[0].pathway_id),
                "endpoint": "end",
            }
        ],
    }

    notice = addin_module._apply_palette_edit(
        object(),
        "update_junction_relationships",
        json.dumps(request),
    )

    saved = loads(gateway.replace_harness_definition.call_args.args[1])
    assert notice == "Saved junction relationships."
    assert saved.junctions[0].pathway_relationships[0].endpoint is PathwayEndpoint.END


def test_junction_rename_bridge_persists_name(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
    valid_harness: HarnessDefinition,
) -> None:
    """
    Translate a palette junction rename into one transactional metadata edit.
    """
    control = ControlStructure(
        UUID("37000000-0000-0000-0000-000000000011"),
        "Junction Gate",
        ControlKind.ROUTING_GATE,
        "junction-token",
    )
    junction = JunctionDefinition(
        UUID("38000000-0000-0000-0000-000000000011"),
        "Junction 01",
        control.control_id,
    )
    definition = replace(
        valid_harness,
        controls=(*valid_harness.controls, control),
        junctions=(junction,),
    )
    gateway = Mock(read_harness_definition=Mock(return_value=dumps(definition)))
    monkeypatch.setattr(addin_module, "_create_harness_gateway", lambda _application: gateway)

    notice = addin_module._apply_palette_edit(
        object(),
        "rename_junction",
        json.dumps(
            {
                "harnessId": str(definition.harness_id),
                "junctionId": str(junction.junction_id),
                "name": "Main Splice",
            }
        ),
    )

    saved = loads(gateway.replace_harness_definition.call_args.args[1])
    assert notice == "Saved name."
    assert saved.junctions[0] == replace(junction, name="Main Splice")


def test_junction_relationship_bridge_removes_one_endpoint(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
    valid_harness: HarnessDefinition,
) -> None:
    """
    Translate one palette row removal into the atomic application edit.
    """
    control = ControlStructure(
        UUID("37000000-0000-0000-0000-000000000001"),
        "Junction Gate",
        ControlKind.ROUTING_GATE,
        "junction-token",
    )
    relationship = JunctionPathwayRelationship(
        valid_harness.pathways[0].pathway_id,
        PathwayEndpoint.END,
    )
    junction = JunctionDefinition(
        UUID("38000000-0000-0000-0000-000000000001"),
        "Junction 01",
        control.control_id,
        (relationship,),
    )
    definition = replace(
        valid_harness,
        controls=(*valid_harness.controls, control),
        junctions=(junction,),
    )
    gateway = Mock(read_harness_definition=Mock(return_value=dumps(definition)))
    monkeypatch.setattr(addin_module, "_create_harness_gateway", lambda _application: gateway)
    request = {
        "harnessId": str(definition.harness_id),
        "junctionId": str(junction.junction_id),
        "pathwayId": str(relationship.pathway_id),
        "endpoint": relationship.endpoint.value,
    }

    notice = addin_module._apply_palette_edit(
        object(),
        "remove_junction_relationship",
        json.dumps(request),
    )

    saved = loads(gateway.replace_harness_definition.call_args.args[1])
    assert notice == "Removed junction relationship."
    assert saved.junctions[0].pathway_relationships == ()


def test_solid_generation_fails_native_transaction_on_kernel_error(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Abort the native command if solid generation fails, preserving Undo/Redo semantics.
    """
    document = object()
    application = SimpleNamespace(activeDocument=document)
    core_module = sys.modules["adsk.core"]
    vars(core_module)["Application"] = SimpleNamespace(get=lambda: application)
    monkeypatch.setitem(
        vars(addin_module), "_generate_solids", Mock(side_effect=RuntimeError("Wire 002 failed"))
    )
    monkeypatch.setattr(addin_module, "_log_to_fusion", Mock())
    args = SimpleNamespace(executeFailed=False)
    handler = addin_module._PaletteEditExecuteHandler(("generate_solids", "{}", document))
    handler.notify(args)
    assert args.executeFailed
    assert args.executeFailedMessage == "Wire 002 failed"
    assert not handler.clear_preview_after_destroy


def test_successful_solid_generation_clears_preview_after_command_destroy(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Remove transient graphics only after Fusion closes the successful transaction.
    """
    document = object()
    application = SimpleNamespace(activeDocument=document)
    core_module = sys.modules["adsk.core"]
    vars(core_module)["Application"] = SimpleNamespace(get=lambda: application)
    generate = Mock(return_value=3)
    clear = Mock(return_value=1)
    monkeypatch.setattr(addin_module, "_generate_solids", generate)
    monkeypatch.setattr(addin_module, "_clear_preview", clear)
    execute = addin_module._PaletteEditExecuteHandler(("generate_solids", "{}", document))
    destroyed = addin_module._PaletteEditDestroyedHandler(execute)
    args = SimpleNamespace(executeFailed=False)

    execute.notify(args)

    assert execute.clear_preview_after_destroy
    clear.assert_not_called()
    destroyed.notify(SimpleNamespace())
    clear.assert_called_once_with(application)


def test_clear_preview_deletes_graphics_outside_edit_transaction(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Refresh Fusion after deleting transient graphics so they disappear immediately.
    """
    design = object()
    viewport = Mock()
    application = SimpleNamespace(activeViewport=viewport)
    clear = Mock(return_value=1)
    monkeypatch.setattr(addin_module, "_require_active_design", lambda _application: design)
    monkeypatch.setattr(addin_module, "_clear_highlight", Mock())
    monkeypatch.setattr(addin_module, "clear_route_previews", clear)

    assert addin_module._clear_preview(application) == 1

    clear.assert_called_once_with(design)
    viewport.refresh.assert_called_once()


def test_clear_preview_palette_event_bypasses_model_edit_command(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Complete transient cleanup synchronously before returning to the palette.
    """
    application = object()
    core_module = sys.modules["adsk.core"]
    vars(core_module)["Application"] = SimpleNamespace(get=lambda: application)
    vars(core_module)["HTMLEventArgs"] = SimpleNamespace(cast=lambda value: value)
    clear = Mock(return_value=2)
    open_edit = Mock()
    monkeypatch.setattr(addin_module, "_clear_preview", clear)
    monkeypatch.setattr(addin_module, "_open_palette_edit", open_edit)
    args = SimpleNamespace(action="clear_preview", data="{}", returnData="")

    addin_module._PaletteIncomingHandler().notify(args)

    clear.assert_called_once_with(application)
    open_edit.assert_not_called()
    assert json.loads(args.returnData) == {
        "ok": True,
        "notice": "Cleared 2 route-preview graphics groups.",
    }


def test_add_junction_palette_event_opens_native_selector(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Route the background-menu action through the dedicated Fusion command.
    """
    application = object()
    core_module = sys.modules["adsk.core"]
    vars(core_module)["Application"] = SimpleNamespace(get=lambda: application)
    vars(core_module)["HTMLEventArgs"] = SimpleNamespace(cast=lambda value: value)
    opened = Mock()
    monkeypatch.setattr(addin_module, "_open_add_junction_command", opened)
    data = json.dumps({"harnessId": str(UUID(int=1))})
    args = SimpleNamespace(action="add_junction", data=data, returnData="")

    addin_module._PaletteIncomingHandler().notify(args)

    opened.assert_called_once_with(application, data)
    assert json.loads(args.returnData) == {"ok": True}


def test_add_junction_relationship_palette_event_opens_native_selector(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Route the popup action through the pathway-ending geometry command.
    """
    application = object()
    core_module = sys.modules["adsk.core"]
    vars(core_module)["Application"] = SimpleNamespace(get=lambda: application)
    vars(core_module)["HTMLEventArgs"] = SimpleNamespace(cast=lambda value: value)
    opened = Mock()
    monkeypatch.setattr(
        addin_module,
        "_open_add_junction_relationship_command",
        opened,
    )
    data = json.dumps({"harnessId": str(UUID(int=1)), "junctionId": str(UUID(int=2))})
    args = SimpleNamespace(action="add_junction_relationship", data=data, returnData="")

    addin_module._PaletteIncomingHandler().notify(args)

    opened.assert_called_once_with(application, data)
    assert json.loads(args.returnData) == {"ok": True}


def test_palette_records_bounded_relationship_diagram_observation(
    addin_module: _PaletteLifecycleModule,
) -> None:
    """
    Retain only report-safe continuity metrics from the visual QA probe.
    """
    application = object()
    core_module = sys.modules["adsk.core"]
    vars(core_module)["Application"] = SimpleNamespace(get=lambda: application)
    vars(core_module)["HTMLEventArgs"] = SimpleNamespace(cast=lambda value: value)
    args = SimpleNamespace(
        action="qa_diagram_observation",
        data=json.dumps(
            {
                "status": "passed",
                "connectorCount": 4,
                "maximumEndpointGap": 0.0,
                "contractVersion": "2",
                "layout": "endpoint-junction-forest",
            }
        ),
        returnData="",
    )

    addin_module._PaletteIncomingHandler().notify(args)

    assert addin_module._last_diagram_qa_observation == {
        "status": "passed",
        "connectorCount": 4,
        "maximumEndpointGap": 0.0,
        "contractVersion": "2",
        "layout": "endpoint-junction-forest",
    }
    assert json.loads(args.returnData) == {"ok": True}


def test_lists_installed_fusion_appearance_libraries_and_contents(
    addin_module: _PaletteLifecycleModule,
) -> None:
    """
    Load appearance names only for the library selected in the palette.
    """
    appearances = SimpleNamespace(
        count=2,
        item=lambda index: (
            SimpleNamespace(id="blue-id", name="Rubber - Blue"),
            SimpleNamespace(id="black-id", name="Rubber - Black"),
        )[index],
    )
    library = SimpleNamespace(id="custom-id", name="My Library", appearances=appearances)
    libraries = SimpleNamespace(
        count=1,
        item=lambda _index: library,
        itemById=lambda identity: library if identity == "custom-id" else None,
    )
    application = SimpleNamespace(materialLibraries=libraries)

    assert addin_module._appearance_libraries_payload(application) == [
        {"id": "custom-id", "name": "My Library"}
    ]
    assert addin_module._library_appearances_payload(application, "custom-id") == [
        {"id": "black-id", "name": "Rubber - Black"},
        {"id": "blue-id", "name": "Rubber - Blue"},
    ]


def test_preview_reports_dynamic_transition_adjustment_as_information(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
    valid_harness: HarnessDefinition,
) -> None:
    """
    Continue preview creation and publish a crowded-span adjustment to the palette.
    """
    design = object()
    viewport = Mock()
    application = SimpleNamespace(activeViewport=viewport)
    gateway = SimpleNamespace(read_harness_definition=Mock(return_value=dumps(valid_harness)))
    send_state = Mock()

    def show(
        _design: object, _definition: HarnessDefinition, **kwargs: object
    ) -> tuple[object, ...]:
        """
        Simulate a successful solve that dynamically corrects one transition.
        """
        notices = cast(list[str], kwargs["notices"])
        notices.append(
            "Wire 001: dynamically adjusted transitions between profiles 2 and 3 "
            "from 5.063 mm to 4.563 mm; the 0.525 mm sweep radius is preserved."
        )
        return object(), object(), object()

    monkeypatch.setattr(addin_module, "_require_active_design", lambda _application: design)
    monkeypatch.setattr(addin_module, "_create_harness_gateway", lambda _application: gateway)
    monkeypatch.setattr(addin_module, "show_route_previews", show)
    monkeypatch.setattr(addin_module, "_send_palette_state", send_state)
    payload = json.dumps({"harnessId": str(valid_harness.harness_id)})

    assert addin_module._preview_routes(application, payload) == 3

    viewport.refresh.assert_called_once()
    notice = send_state.call_args.args[1]
    assert notice.startswith("Previewing 3 wire routes.\nWire 001:")
    assert "from 5.063 mm to 4.563 mm" in notice


def test_clear_solids_targets_selected_harness_and_refreshes_viewport(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
    valid_harness: HarnessDefinition,
) -> None:
    """
    Delete marked output for one harness and report the affected wire count.
    """
    component = object()
    viewport = Mock()
    application = SimpleNamespace(activeViewport=viewport)
    gateway = SimpleNamespace(harness_component=Mock(return_value=component))
    clear = Mock(return_value=3)
    send_state = Mock()
    monkeypatch.setattr(addin_module, "_create_harness_gateway", lambda _application: gateway)
    monkeypatch.setattr(addin_module, "clear_wire_solids", clear)
    monkeypatch.setattr(addin_module, "_send_palette_state", send_state)
    payload = json.dumps({"harnessId": str(valid_harness.harness_id)})

    assert addin_module._clear_solids(application, payload) == 3

    gateway.harness_component.assert_called_once_with(valid_harness.harness_id)
    clear.assert_called_once_with(component)
    viewport.refresh.assert_called_once()
    send_state.assert_called_once_with(application, "Cleared 3 wire solids.")
