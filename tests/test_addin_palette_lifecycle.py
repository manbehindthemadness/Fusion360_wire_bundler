"""
Regression tests for the Fusion palette launcher lifecycle.
"""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Callable
from types import ModuleType, SimpleNamespace
from typing import Protocol, cast
from unittest.mock import Mock

import pytest

from wire_bundler.application import HarnessLoadResult
from wire_bundler.domain import HarnessDefinition


class _PaletteLifecycleModule(Protocol):
    """
    Describe the private lifecycle surface exercised by this regression test.
    """

    _handlers: list[object]
    _PaletteIncomingHandler: type
    _ShowPaletteCreatedHandler: type
    _show_palette: Callable[[object], None]
    _create_harness_gateway: Callable[[object], object]
    _serialize_palette_state: Callable[[object, str], str]
    _preview_routes: Callable[[object, str], int]
    _log_to_fusion: Callable[[str], None]
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
    assert harness["pathways"][0]["orderedControlIds"] == [
        str(valid_harness.controls[0].control_id)
    ]
    assert harness["wires"][0]["wireNumber"] == "001"
    assert harness["wires"][0]["orderedPathwayIds"] == [str(valid_harness.pathways[0].pathway_id)]
    assert harness["wires"][0]["orderedControlIds"] == [str(valid_harness.controls[0].control_id)]


def test_route_capacity_error_is_returned_to_palette(
    addin_module: _PaletteLifecycleModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Keep expected preview rejection actionable without a generic failure dialog.
    """
    application = object()
    logged_messages: list[str] = []
    core_module = sys.modules["adsk.core"]
    core_module.Application = SimpleNamespace(get=lambda: application)  # type: ignore[attr-defined]
    core_module.HTMLEventArgs = SimpleNamespace(cast=lambda args: args)  # type: ignore[attr-defined]
    monkeypatch.setattr(
        addin_module,
        "_preview_routes",
        Mock(side_effect=ValueError("Gate 4 cannot fit 3 wires.")),
    )
    monkeypatch.setattr(addin_module, "_log_to_fusion", logged_messages.append)
    html_args = SimpleNamespace(action="preview_routes", data="{}", returnData="")

    addin_module._PaletteIncomingHandler().notify(html_args)

    assert json.loads(html_args.returnData) == {
        "ok": False,
        "error": "Gate 4 cannot fit 3 wires.",
    }
    assert logged_messages == ["Harness route preview rejected: Gate 4 cannot fit 3 wires."]
