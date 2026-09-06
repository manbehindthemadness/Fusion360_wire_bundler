"""
Regression tests for the Fusion palette launcher lifecycle.
"""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Callable
from dataclasses import replace
from types import ModuleType, SimpleNamespace
from typing import Protocol, cast
from unittest.mock import Mock
from uuid import UUID

import pytest

from wire_bundler.application import HarnessLoadResult
from wire_bundler.domain import HarnessDefinition, dumps


class _PaletteLifecycleModule(Protocol):
    """
    Describe the private lifecycle surface exercised by this regression test.
    """

    _handlers: list[object]
    _PaletteIncomingHandler: type
    _PaletteEditExecuteHandler: type
    _PaletteEditCreatedHandler: type
    _HistoryChangedHandler: type
    _pending_palette_edit: object
    _open_palette_edit: Callable[[object, str, str], None]
    _apply_palette_edit: Callable[[object, str, str], str]
    _refresh_active_preview: Callable[[object, UUID], str]
    _send_palette_state: Callable[[object, str], None]
    reconcile_preview_history: Callable[[object, tuple[HarnessDefinition, ...]], None]
    _ShowPaletteCreatedHandler: type
    _show_palette: Callable[[object], None]
    _create_harness_gateway: Callable[[object], object]
    _serialize_palette_state: Callable[[object, str], str]
    _preview_routes: Callable[[object, str], int]
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
        "ValidateInputsEventHandler",
        "CommandCreatedEventHandler",
        "HTMLEventHandler",
        "NavigationEventHandler",
    )
    for handler_name in handler_names:
        setattr(core_module, handler_name, type(handler_name, (), {}))
    adsk_module.core = core_module  # type: ignore[attr-defined]
    adsk_module.fusion = fusion_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "adsk", adsk_module)
    monkeypatch.setitem(sys.modules, "adsk.core", core_module)
    monkeypatch.setitem(sys.modules, "adsk.fusion", fusion_module)
    sys.modules.pop("wire_bundler.addin", None)

    module = importlib.import_module("wire_bundler.addin")
    return cast(_PaletteLifecycleModule, cast(object, module))


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
    assert logged_messages == ["Harness command failed: Gate 4 cannot fit 3 wires."]


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
    Replace the active Fusion selection with both profiles linked to a wire.
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
    application = SimpleNamespace(
        userInterface=SimpleNamespace(activeSelections=selections),
        activeViewport=viewport,
    )
    gateway = SimpleNamespace(
        read_harness_definition=lambda _harness_id: dumps(valid_harness),
    )
    fusion_module = sys.modules["adsk.fusion"]
    fusion_module.Profile = SimpleNamespace(cast=lambda entity: entity)  # type: ignore[attr-defined]
    monkeypatch.setattr(addin_module, "_require_active_design", lambda _application: design)
    monkeypatch.setattr(addin_module, "_create_harness_gateway", lambda _application: gateway)
    payload = json.dumps(
        {
            "harnessId": str(valid_harness.harness_id),
            "memberType": "wire",
            "memberId": str(valid_harness.wires[0].wire_id),
        }
    )

    count = addin_module._highlight_member(application, payload)

    assert count == 2
    selections.clear.assert_called_once_with()
    assert [call.args[0] for call in selections.add.call_args_list] == [
        start_profile,
        end_profile,
    ]
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


def test_palette_edit_waits_for_execute_and_releases_handlers(
    addin_module: _PaletteLifecycleModule, monkeypatch: pytest.MonkeyPatch
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
    addin_module._open_palette_edit(application, "rename_wire", payload)
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
    applied.assert_called_once_with(application, "rename_wire", payload)
    refreshed.assert_called_once_with(application, UUID(int=1))
    assert not args.executeFailed
    cast(Mock, cleanup[0]).notify(SimpleNamespace())
    assert handlers[0] not in addin_module._handlers
    assert cleanup[0] not in addin_module._handlers


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
