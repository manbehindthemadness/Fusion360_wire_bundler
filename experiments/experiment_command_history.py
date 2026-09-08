"""
Verify Wire Bundler command transactions against native Fusion Undo and Redo.

Run this through its registered Fusion script bundle or development MCP orchestration,
never with standalone Python. The scenario creates and closes only its own unsaved
design and restores the previously active document.
"""

from __future__ import annotations

import importlib
import json
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from time import monotonic, sleep
from typing import Optional
from uuid import UUID

ADDIN_ROOT = Path(__file__).resolve().parent.parent
if str(ADDIN_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDIN_ROOT))

# noinspection PyUnresolvedReferences
import adsk  # noqa: E402

# noinspection PyUnresolvedReferences
import adsk.core  # noqa: E402

# noinspection PyUnresolvedReferences
import adsk.fusion  # noqa: E402

from experiments.experiment_reference_harness import _create_circular_profile  # noqa: E402
from experiments.scenario_report import ScenarioReport  # noqa: E402
from wire_bundler.application import add_pathway, add_wire_batch, create_empty_harness  # noqa: E402
from wire_bundler.domain import RoutingMode, loads  # noqa: E402
from wire_bundler.fusion import FusionHarnessGateway  # noqa: E402
from wire_bundler.fusion.route_preview import has_route_previews  # noqa: E402
from wire_bundler.fusion.wire_solids import generated_wire_occurrences  # noqa: E402

SCENARIO_NAME = "command_history"
ARTIFACT_ROOT = ADDIN_ROOT / "artifacts" / "verification"
HARNESS_ID = UUID("81000000-0000-0000-0000-000000000001")
PATHWAY_ID = UUID("82000000-0000-0000-0000-000000000001")
CONTROL_ID = UUID("83000000-0000-0000-0000-000000000001")
WIRE_PROFILE_ID = UUID("84000000-0000-0000-0000-000000000001")
SOURCE_CONNECTION_ID = UUID("85000000-0000-0000-0000-000000000001")
DESTINATION_CONNECTION_ID = UUID("86000000-0000-0000-0000-000000000001")
WIRE_ID = UUID("87000000-0000-0000-0000-000000000001")
RENAMED_WIRE = "QA Command History Wire"


def run(_context: object) -> None:
    """
    Run the command-history scenario and display its result inside Fusion.

    Args:
        _context: Context supplied by the Fusion script host.
    """
    report = ScenarioReport(SCENARIO_NAME, ARTIFACT_ROOT, _log_to_fusion)
    application: Optional[adsk.core.Application] = None
    try:
        application = _require_application()
        verify_command_history(application, report)
        report.finish(True)
        application.userInterface.messageBox(
            "Wire Bundler command-history verification passed.\n\n"
            f"Log: {report.log_path}\n"
            f"Report: {report.json_path}",
            "Wire Bundler Command History",
        )
    except (AssertionError, AttributeError, OSError, RuntimeError, TypeError, ValueError):
        failure = traceback.format_exc()
        report.finish(False, failure)
        if application is not None and application.userInterface is not None:
            application.userInterface.messageBox(
                "Wire Bundler command-history verification failed.\n\n"
                f"Log: {report.log_path}\n"
                f"Report: {report.json_path}\n\n"
                f"{failure}",
                "Wire Bundler Command History",
            )


def verify_command_history(
    application: adsk.core.Application,
    report: ScenarioReport,
) -> None:
    """
    Exercise production lifecycle commands through native Undo and Redo.

    Args:
        application: Active Fusion application.
        report: Durable scenario report.
    """
    previous_document = application.activeDocument
    test_document: Optional[adsk.core.Document] = None
    try:
        with report.step("Create isolated one-wire command fixture"):
            test_document = application.documents.add(
                adsk.core.DocumentTypes.FusionDesignDocumentType
            )
            if test_document is None:
                raise RuntimeError("Fusion did not create the command-history document.")
            design = adsk.fusion.Design.cast(application.activeProduct)
            if design is None:
                raise RuntimeError("Fusion did not activate the command-history design.")
            design.designIntent = adsk.fusion.DesignIntentTypes.HybridDesignIntentType
            gateway = build_single_wire_fixture(application, design)
            harness = gateway.harness_component(HARNESS_ID)
            if _wire_name(gateway):
                raise AssertionError("Command-history wire unexpectedly started with a name.")

        with report.step("Rename wire through palette command transaction"):
            payload = json.dumps(
                {
                    "harnessId": str(HARNESS_ID),
                    "wireId": str(WIRE_ID),
                    "name": RENAMED_WIRE,
                }
            )
            execute_palette_action(application, "rename_wire", payload)
            wait_for(application, lambda: _wire_name(gateway) == RENAMED_WIRE, "wire rename")

        with report.step("Undo restores original harness definition"):
            _execute_native_history_command(application, "UndoCommand")
            wait_for(application, lambda: _wire_name(gateway) == "", "wire rename Undo")

        with report.step("Redo restores renamed harness definition"):
            _execute_native_history_command(application, "RedoCommand")
            wait_for(application, lambda: _wire_name(gateway) == RENAMED_WIRE, "wire rename Redo")

        harness_payload = json.dumps({"harnessId": str(HARNESS_ID)})
        with report.step("Preview participates in native Undo and Redo"):
            execute_palette_action(application, "preview_routes", harness_payload)
            wait_for(application, lambda: has_route_previews(design), "route preview")
            _execute_native_history_command(application, "UndoCommand")
            wait_for(
                application,
                lambda: not has_route_previews(design),
                "route preview Undo",
            )
            _execute_native_history_command(application, "RedoCommand")
            wait_for(application, lambda: has_route_previews(design), "route preview Redo")

        with report.step("Explicit preview clear removes transient graphics"):
            if _clear_transient_preview(application) != 1:
                raise AssertionError("Explicit preview clear did not remove exactly one group.")
            wait_for(
                application,
                lambda: not has_route_previews(design),
                "explicit route preview clear",
            )

        with report.step("Generate participates in native Undo and Redo"):
            execute_palette_action(application, "preview_routes", harness_payload)
            wait_for(application, lambda: has_route_previews(design), "pre-generation preview")
            generate_payload = json.dumps({"harnessId": str(HARNESS_ID), "replaceExisting": False})
            execute_palette_action(application, "generate_solids", generate_payload)
            wait_for(
                application,
                lambda: _generated_wire_count(harness) == 1 and not has_route_previews(design),
                "wire solid generation and preview cleanup",
            )
            _execute_native_history_command(application, "UndoCommand")
            wait_for(
                application,
                lambda: _generated_wire_count(harness) == 0,
                "wire solid generation Undo",
            )
            _execute_native_history_command(application, "RedoCommand")
            wait_for(
                application,
                lambda: _generated_wire_count(harness) == 1,
                "wire solid generation Redo",
            )

        with report.step("Rebuild participates in native Undo and Redo"):
            original_occurrence = generated_wire_occurrences(harness)[0]
            original_token = _root_occurrence_token(design, original_occurrence)
            rebuild_payload = json.dumps({"harnessId": str(HARNESS_ID), "replaceExisting": True})
            execute_palette_action(application, "generate_solids", rebuild_payload)
            wait_for(
                application,
                lambda: _generated_wire_replaced(harness, original_occurrence),
                "wire solid rebuild",
            )
            rebuilt_occurrence = generated_wire_occurrences(harness)[0]
            rebuilt_token = _root_occurrence_token(design, rebuilt_occurrence)
            _execute_native_history_command(application, "UndoCommand")
            wait_for(
                application,
                lambda: _generated_wire_matches_token(
                    design,
                    harness,
                    original_token,
                ),
                "wire solid rebuild Undo",
            )
            _execute_native_history_command(application, "RedoCommand")
            wait_for(
                application,
                lambda: _generated_wire_matches_token(
                    design,
                    harness,
                    rebuilt_token,
                ),
                "wire solid rebuild Redo",
            )

        with report.step("Clear Solids participates in native Undo and Redo"):
            execute_palette_action(application, "clear_solids", harness_payload)
            wait_for(
                application,
                lambda: _generated_wire_count(harness) == 0,
                "wire solid clear",
            )
            _execute_native_history_command(application, "UndoCommand")
            wait_for(
                application,
                lambda: _generated_wire_count(harness) == 1,
                "wire solid clear Undo",
            )
            _execute_native_history_command(application, "RedoCommand")
            wait_for(
                application,
                lambda: _generated_wire_count(harness) == 0,
                "wire solid clear Redo",
            )

        report.record_observation(
            "fusion.commandHistory",
            {
                "paletteAction": "rename_wire",
                "undoRestoredOriginal": True,
                "redoRestoredEdit": True,
                "previewUndoRedo": True,
                "generateUndoRedo": True,
                "rebuildUndoRedo": True,
                "clearSolidsUndoRedo": True,
                "explicitPreviewClear": True,
                "wireIdStable": str(WIRE_ID),
            },
        )
    finally:
        if test_document is not None and test_document.isValid:
            with report.step("Close isolated command fixture"):
                if not test_document.close(False):
                    raise RuntimeError("Fusion did not close the command-history document.")
        if previous_document is not None and previous_document.isValid:
            if application.activeDocument != previous_document and not previous_document.activate():
                raise RuntimeError("Fusion did not restore the previously active document.")


def build_single_wire_fixture(
    application: adsk.core.Application,
    design: adsk.fusion.Design,
) -> FusionHarnessGateway:
    """
    Create a deterministic one-wire harness for history verification.

    Args:
        application: Active Fusion application.
        design: Isolated design receiving the fixture.

    Returns:
        Gateway bound to the completed fixture.
    """
    root_component = design.rootComponent
    source = _create_circular_profile(root_component, 0.0, 0.0, 0.0, 0.12, "QA Source")
    gate = _create_circular_profile(root_component, 5.0, 0.0, 0.0, 0.8, "QA Gate")
    destination = _create_circular_profile(
        root_component,
        10.0,
        0.0,
        0.0,
        0.12,
        "QA Destination",
    )
    gateway = FusionHarnessGateway(design, application.data.activeFolder)
    create_empty_harness(
        "WB_Command_History",
        RoutingMode.ROUTING_GATES,
        gateway,
        id_factory=lambda: HARNESS_ID,
    )
    pathway_identifiers = iter((CONTROL_ID, PATHWAY_ID))
    add_pathway(
        HARNESS_ID,
        "QA Pathway",
        RoutingMode.ROUTING_GATES,
        (gate.entityToken,),
        gateway,
        id_factory=lambda: next(pathway_identifiers),
    )
    wire_identifiers = iter(
        (WIRE_PROFILE_ID, SOURCE_CONNECTION_ID, DESTINATION_CONNECTION_ID, WIRE_ID)
    )
    add_wire_batch(
        HARNESS_ID,
        PATHWAY_ID,
        (source.entityToken,),
        (destination.entityToken,),
        1.0,
        gateway,
        id_factory=lambda: next(wire_identifiers),
    )
    return gateway


def _wire_name(gateway: FusionHarnessGateway) -> str:
    """
    Read the command-history wire's current persisted display name.
    """
    definition = loads(gateway.read_harness_definition(HARNESS_ID))
    wire = next((item for item in definition.wires if item.wire_id == WIRE_ID), None)
    if wire is None:
        raise AssertionError("Command-history wire disappeared from the definition.")
    return wire.display_name


def _generated_wire_count(harness: adsk.fusion.Component) -> int:
    """
    Count generated wire occurrences owned by the command-history harness.

    Args:
        harness: Harness component that owns generated wire occurrences.
    """
    return len(generated_wire_occurrences(harness))


def _generated_wire_replaced(
    harness: adsk.fusion.Component,
    original_occurrence: adsk.fusion.Occurrence,
) -> bool:
    """
    Report whether rebuild replaced the one original generated occurrence.

    Args:
        harness: Harness component that owns generated wire occurrences.
        original_occurrence: Occurrence present before rebuild.
    """
    occurrences = generated_wire_occurrences(harness)
    return len(occurrences) == 1 and occurrences[0] != original_occurrence


def _generated_wire_matches_token(
    design: adsk.fusion.Design,
    harness: adsk.fusion.Component,
    entity_token: str,
) -> bool:
    """
    Match the generated occurrence through Fusion's persistent token resolver.

    Args:
        design: Active design used to resolve the stored entity token.
        harness: Harness component that owns generated wire occurrences.
        entity_token: Token captured from the expected occurrence state.
    """
    occurrences = generated_wire_occurrences(harness)
    resolved = design.findEntityByToken(entity_token)
    return (
        len(occurrences) == 1
        and bool(resolved)
        and occurrences[0].component == resolved[0].component
    )


def _root_occurrence_token(
    design: adsk.fusion.Design,
    occurrence: adsk.fusion.Occurrence,
) -> str:
    """
    Capture a token from the generated occurrence's required root context.

    Args:
        design: Active design containing the nested occurrence.
        occurrence: Harness-local generated wire occurrence.

    Returns:
        Persistent token for the corresponding root-context occurrence.
    """
    root_occurrences = design.rootComponent.allOccurrencesByComponent(occurrence.component)
    if root_occurrences.count != 1:
        raise AssertionError(
            "Expected one root-context occurrence for the generated wire, "
            f"found {root_occurrences.count}."
        )
    root_occurrence = root_occurrences.item(0)
    if root_occurrence is None:
        raise RuntimeError("Fusion did not expose the generated root occurrence.")
    return root_occurrence.entityToken


def execute_palette_action(
    application: adsk.core.Application,
    action: str,
    payload: str,
) -> None:
    """
    Enter one production palette action through its real Fusion command boundary.

    Args:
        application: Active Fusion application.
        action: Production palette action identifier.
        payload: Serialized action payload.
    """
    wait_for(
        application,
        lambda: str(application.userInterface.activeCommand) == "SelectCommand",
        f"Fusion default command before {action}",
    )
    # The experiment intentionally verifies this internal production boundary.
    # noinspection PyProtectedMember
    current_addin = importlib.import_module("wire_bundler.addin")
    current_addin._open_palette_edit(application, action, payload)


def _clear_transient_preview(application: adsk.core.Application) -> int:
    """
    Exercise the production clear path that intentionally bypasses model history.

    Args:
        application: Active Fusion application.

    Returns:
        Number of removed top-level preview graphics groups.
    """
    # The experiment intentionally verifies this internal production boundary.
    # noinspection PyProtectedMember
    current_addin = importlib.import_module("wire_bundler.addin")
    return current_addin._clear_preview(application)


def _execute_native_history_command(
    application: adsk.core.Application,
    command_id: str,
) -> None:
    """
    Execute one enabled native history command.

    Args:
        application: Active Fusion application.
        command_id: Native Undo or Redo command identity.
    """
    command_definition = application.userInterface.commandDefinitions.itemById(command_id)
    if command_definition is None:
        raise RuntimeError(f"Fusion command is not registered: {command_id}")
    wait_for(
        application,
        lambda: _command_is_enabled(command_definition),
        f"{command_id} to become enabled",
    )
    if not command_definition.execute():
        raise RuntimeError(f"Fusion declined to execute: {command_id}")


def _command_is_enabled(command_definition: adsk.core.CommandDefinition) -> bool:
    """
    Report whether a native command currently has an enabled control definition.

    Args:
        command_definition: Fusion command inspected after event processing.
    """
    control_definition = command_definition.controlDefinition
    return control_definition is not None and control_definition.isEnabled


def wait_for(
    application: adsk.core.Application,
    condition: Callable[[], bool],
    description: str,
    timeout_seconds: float = 10.0,
) -> None:
    """
    Pump Fusion events until an asynchronous command reaches its observable result.

    Args:
        application: Active Fusion application.
        condition: Result predicate evaluated after each event cycle.
        description: Operation named in timeout diagnostics.
        timeout_seconds: Maximum wait duration.
    """
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        adsk.doEvents()
        if condition():
            return
        # The scenario intentionally observes the running add-in's command boundary.
        # noinspection PyProtectedMember
        current_addin = importlib.import_module("wire_bundler.addin")
        if current_addin._last_command_error:
            # noinspection PyProtectedMember
            raise RuntimeError(
                f"Fusion command failed during {description}: {current_addin._last_command_error}"
            )
        sleep(0.01)
    active_command = application.userInterface.activeCommand
    raise RuntimeError(
        f"Timed out waiting for {description}; active Fusion command is {active_command!r}."
    )


def _require_application() -> adsk.core.Application:
    """
    Return the active Fusion application or reject standalone execution.
    """
    application = adsk.core.Application.get()
    if application is None:
        raise RuntimeError("Command-history verification must run inside Autodesk Fusion.")
    return application


def _log_to_fusion(message: str) -> None:
    """
    Mirror command-history progress into Fusion's application log.

    Args:
        message: Timestamped scenario log line.
    """
    adsk.core.Application.log(
        f"Wire Bundler command history: {message}",
        adsk.core.LogLevels.InfoLogLevel,
        adsk.core.LogTypes.FileLogType,
    )
