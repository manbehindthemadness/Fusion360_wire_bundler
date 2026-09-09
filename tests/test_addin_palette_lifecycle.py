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
from wire_bundler.domain import HarnessDefinition, WireColor, WireStripe, dumps, loads


class _PaletteLifecycleModule(Protocol):
    """
    Describe the private lifecycle surface exercised by this regression test.
    """

    _handlers: list[object]
    PALETTE_RESOURCE_FILES: tuple[Path, ...]
    _PaletteIncomingHandler: type
    _PaletteEditExecuteHandler: type
    _PaletteEditDestroyedHandler: type
    _PaletteEditCreatedHandler: type
    _HistoryChangedHandler: type
    _DocumentSavingHandler: type
    _DocumentSavedHandler: type
    _pending_palette_edit: object
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
    has_route_previews: Callable[[object], bool]
    show_route_previews: Callable[..., tuple[object, ...]]
    refresh_route_previews: Callable[..., tuple[str, ...]]
    _log_to_fusion: Callable[[str], None]
    _member_entity_tokens: Callable[[HarnessDefinition, str, UUID], tuple[str, ...]]
    _highlight_member: Callable[[object, str], int]
    _require_active_design: Callable[[object], object]
    highlight_route_preview: Callable[[object, object], int]
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
        "DocumentEventHandler",
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
    monkeypatch.setitem(vars(addin_module), "_graphics_cache_restore_value", None)
    monkeypatch.setitem(vars(addin_module), "_graphics_cache_save_document", None)
    return document, compatibility


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
                "contractVersion": "1",
                "layout": "measured-pathway-stack",
            }
        ),
        returnData="",
    )

    addin_module._PaletteIncomingHandler().notify(args)

    assert addin_module._last_diagram_qa_observation == {
        "status": "passed",
        "connectorCount": 4,
        "maximumEndpointGap": 0.0,
        "contractVersion": "1",
        "layout": "measured-pathway-stack",
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
