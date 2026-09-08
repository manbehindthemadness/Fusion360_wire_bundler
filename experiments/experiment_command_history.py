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
from dataclasses import dataclass
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
from wire_bundler.addin import (  # noqa: E402
    ADD_PATHWAY_COMMAND_ID,
    ADD_WIRES_COMMAND_ID,
    APPEND_GATES_COMMAND_ID,
    DESTINATION_CONNECTIONS_INPUT_ID,
    EDIT_END_COMMAND_ID,
    PALETTE_ID,
    PATHWAY_GATES_INPUT_ID,
    SOURCE_CONNECTIONS_INPUT_ID,
)
from wire_bundler.application import (  # noqa: E402
    add_pathway,
    add_wire_batch,
    append_pathway_gates,
    create_empty_harness,
)
from wire_bundler.application.edit_harness import edit_end_members  # noqa: E402
from wire_bundler.domain import HarnessDefinition, RoutingMode, loads  # noqa: E402
from wire_bundler.fusion import FusionHarnessGateway  # noqa: E402
from wire_bundler.fusion.route_preview import has_route_previews  # noqa: E402
from wire_bundler.fusion.wire_solids import generated_wire_occurrences  # noqa: E402

SCENARIO_NAME = "command_history"
ARTIFACT_ROOT = ADDIN_ROOT / "artifacts" / "verification"
HARNESS_ID = UUID("81000000-0000-0000-0000-000000000001")
PATHWAY_ID = UUID("82000000-0000-0000-0000-000000000001")
CONTROL_ID = UUID("83000000-0000-0000-0000-000000000001")
SECOND_CONTROL_ID = UUID("83000000-0000-0000-0000-000000000002")
WIRE_PROFILE_ID = UUID("84000000-0000-0000-0000-000000000001")
SECOND_WIRE_PROFILE_ID = UUID("84000000-0000-0000-0000-000000000002")
SOURCE_CONNECTION_ID = UUID("85000000-0000-0000-0000-000000000001")
SECOND_SOURCE_CONNECTION_ID = UUID("85000000-0000-0000-0000-000000000002")
DESTINATION_CONNECTION_ID = UUID("86000000-0000-0000-0000-000000000001")
SECOND_DESTINATION_CONNECTION_ID = UUID("86000000-0000-0000-0000-000000000002")
WIRE_ID = UUID("87000000-0000-0000-0000-000000000001")
SECOND_WIRE_ID = UUID("87000000-0000-0000-0000-000000000002")
RENAMED_WIRE = "QA Command History Wire"


@dataclass(frozen=True)
class _PersistentEditCase:
    """
    Describe one palette edit and its expected persisted result.
    """

    name: str
    action: str
    payload: dict[str, object]
    matches_expected: Callable[[HarnessDefinition], bool]
    observe_palette_dom: bool = False


@dataclass(frozen=True)
class _NativeSelectionCase:
    """
    Describe one selection-backed command and its expected persisted result.
    """

    name: str
    command_id: str
    open_command: Callable[[], None]
    configure_inputs: Callable[[adsk.core.CommandInputs], None]
    matches_expected: Callable[[HarnessDefinition], bool]
    palette_changes: bool = True


class _CommandCaptureHandler(adsk.core.CommandCreatedEventHandler):
    """
    Retain the real command created by one production command definition.
    """

    def __init__(self) -> None:
        """
        Initialize an empty capture slot.
        """
        super().__init__()
        self.command: Optional[adsk.core.Command] = None

    def notify(self, args: adsk.core.CommandCreatedEventArgs) -> None:
        """
        Capture the live command after its production creation handlers run.

        Args:
            args: Fusion command-created event arguments.
        """
        self.command = args.command


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
    original_palette_url: Optional[str] = None
    try:
        with report.step("Refresh development palette resources"):
            original_palette_url = _reload_palette_resources(application)
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
            if harness is None:
                raise AssertionError("Command-history harness was not created.")
            if _wire_name(gateway):
                raise AssertionError("Command-history wire unexpectedly started with a name.")
            _augment_command_fixture(design, gateway)

        edit_actions = _verify_persistent_edit_matrix(application, gateway, report)
        selection_actions = _verify_selection_backed_history(
            application,
            design,
            gateway,
            report,
        )

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

        with report.step("Persistent edit history: reorder wire endpoints"):
            _verify_multi_wire_endpoint_history(application, design, gateway)
        edit_actions.append("move_wire_endpoint")

        report.record_observation(
            "fusion.commandHistory",
            {
                "paletteAction": "rename_wire",
                "undoRestoredOriginal": True,
                "redoRestoredEdit": True,
                "persistentEditActions": edit_actions,
                "persistentEditCount": len(edit_actions),
                "selectionBackedActions": selection_actions,
                "selectionBackedCount": len(selection_actions),
                "nativeSelectionInputs": True,
                "paletteProjectionUndoRedo": True,
                "paletteDomUndoRedo": True,
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
        if original_palette_url is not None:
            _restore_palette_url(application, original_palette_url)


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


def _augment_command_fixture(
    design: adsk.fusion.Design,
    gateway: FusionHarnessGateway,
) -> None:
    """
    Add a second gate and endpoint guides for order and removal history cases.

    Args:
        design: Isolated command-history design.
        gateway: Persistence gateway bound to the fixture.
    """
    root = design.rootComponent
    second_gate = _create_circular_profile(root, 7.5, 0.0, 0.0, 0.8, "QA Gate 2")
    start_guide = _create_circular_profile(root, 1.5, 0.0, 0.0, 0.12, "QA Start Guide")
    end_guide = _create_circular_profile(root, 8.5, 0.0, 0.0, 0.12, "QA End Guide")
    append_pathway_gates(
        HARNESS_ID,
        PATHWAY_ID,
        (second_gate.entityToken,),
        gateway,
        id_factory=lambda: SECOND_CONTROL_ID,
    )
    edit_end_members(
        HARNESS_ID,
        WIRE_ID,
        "start",
        "add",
        gateway,
        (start_guide.entityToken,),
        expected_members=1,
    )
    edit_end_members(
        HARNESS_ID,
        WIRE_ID,
        "end",
        "add",
        gateway,
        (end_guide.entityToken,),
        expected_members=1,
    )


def _verify_selection_backed_history(
    application: adsk.core.Application,
    design: adsk.fusion.Design,
    gateway: FusionHarnessGateway,
    report: ScenarioReport,
) -> list[str]:
    """
    Exercise every selection-backed production command through Undo and Redo.

    Args:
        application: Active Fusion application.
        design: Isolated command-history design.
        gateway: Persistence gateway bound to the fixture.
        report: Scenario report receiving named command steps.

    Returns:
        Ordered native command operations exercised by the driver.
    """
    root = design.rootComponent
    pathway_gate = _create_circular_profile(root, 6.0, 1.5, 0.0, 0.7, "QA New Path Gate")
    appended_gate = _create_circular_profile(root, 6.5, -1.5, 0.0, 0.7, "QA Appended Gate")
    added_member = _create_circular_profile(root, 1.0, 1.5, 0.0, 0.12, "QA Added Member")
    replaced_member = _create_circular_profile(
        root,
        1.0,
        -1.5,
        0.0,
        0.12,
        "QA Replacement Member",
    )
    wire_source = _create_circular_profile(root, 0.0, 0.6, 0.0, 0.12, "QA Native Source")
    wire_destination = _create_circular_profile(
        root,
        10.0,
        0.6,
        0.0,
        0.12,
        "QA Native Destination",
    )
    baseline = _read_definition(gateway)
    source_tokens = _connection_member_tokens(baseline, SOURCE_CONNECTION_ID)
    current_addin = importlib.import_module("wire_bundler.addin")
    open_add_pathway = vars(current_addin)["_open_add_pathway_command"]
    open_append_gates = vars(current_addin)["_open_append_gates_command"]
    open_end_edit = vars(current_addin)["_open_end_member_edit"]
    open_add_wires = vars(current_addin)["_open_add_wires_command"]
    harness_payload = json.dumps({"harnessId": str(HARNESS_ID)})
    pathway_payload = json.dumps({"harnessId": str(HARNESS_ID), "pathwayId": str(PATHWAY_ID)})
    cases = (
        _NativeSelectionCase(
            "add pathway",
            ADD_PATHWAY_COMMAND_ID,
            lambda: open_add_pathway(application, harness_payload),
            lambda inputs: _set_profile_selections(
                inputs,
                ((PATHWAY_GATES_INPUT_ID, (pathway_gate,)),),
            ),
            lambda current: _has_distinct_pathway_gate(
                current,
                PATHWAY_ID,
                pathway_gate.entityToken,
            ),
        ),
        _NativeSelectionCase(
            "append pathway gate",
            APPEND_GATES_COMMAND_ID,
            lambda: open_append_gates(application, pathway_payload),
            lambda inputs: _set_profile_selections(
                inputs,
                ((PATHWAY_GATES_INPUT_ID, (appended_gate,)),),
            ),
            lambda current: (
                _pathway_last_gate_token(current, PATHWAY_ID) == appended_gate.entityToken
            ),
        ),
        _NativeSelectionCase(
            "add end member",
            EDIT_END_COMMAND_ID,
            lambda: open_end_edit(
                application,
                json.dumps(
                    {
                        "harnessId": str(HARNESS_ID),
                        "wireId": str(WIRE_ID),
                        "endpoint": "start",
                        "editAction": "add",
                        "memberIndex": 1,
                        "expectedMembers": len(source_tokens),
                        "targetIndex": 2,
                    }
                ),
            ),
            lambda inputs: _set_profile_selections(
                inputs,
                ((PATHWAY_GATES_INPUT_ID, (added_member,)),),
            ),
            lambda current: (
                _connection_member_tokens(current, SOURCE_CONNECTION_ID)
                == (*source_tokens, added_member.entityToken)
            ),
        ),
        _NativeSelectionCase(
            "replace end member",
            EDIT_END_COMMAND_ID,
            lambda: open_end_edit(
                application,
                json.dumps(
                    {
                        "harnessId": str(HARNESS_ID),
                        "wireId": str(WIRE_ID),
                        "endpoint": "start",
                        "editAction": "replace",
                        "memberIndex": 0,
                        "expectedMembers": len(source_tokens),
                        "targetIndex": 0,
                    }
                ),
            ),
            lambda inputs: _set_profile_selections(
                inputs,
                ((PATHWAY_GATES_INPUT_ID, (replaced_member,)),),
            ),
            lambda current: (
                _connection_member_tokens(current, SOURCE_CONNECTION_ID)
                == (replaced_member.entityToken, *source_tokens[1:])
            ),
            False,
        ),
        _NativeSelectionCase(
            "add wire",
            ADD_WIRES_COMMAND_ID,
            lambda: open_add_wires(application, pathway_payload),
            lambda inputs: _set_profile_selections(
                inputs,
                (
                    (SOURCE_CONNECTIONS_INPUT_ID, (wire_source,)),
                    (DESTINATION_CONNECTIONS_INPUT_ID, (wire_destination,)),
                ),
            ),
            lambda current: _has_wire_between_tokens(
                current,
                wire_source.entityToken,
                wire_destination.entityToken,
            ),
        ),
    )
    actions: list[str] = []
    for case in cases:
        with report.step(f"Selection-backed history: {case.name}"):
            _verify_native_selection_case(application, gateway, case)
        actions.append(case.name.replace(" ", "_"))
    return actions


def _verify_native_selection_case(
    application: adsk.core.Application,
    gateway: FusionHarnessGateway,
    case: _NativeSelectionCase,
) -> None:
    """
    Execute one real selection command and verify its complete history cycle.

    Args:
        application: Active Fusion application.
        gateway: Persistence gateway bound to the fixture.
        case: Native command, input population, and expected result.
    """
    _verify_definition_history(
        application,
        gateway,
        case.name,
        lambda: _execute_native_input_command(application, case),
        case.matches_expected,
        palette_must_change=case.palette_changes,
    )


def _execute_native_input_command(
    application: adsk.core.Application,
    case: _NativeSelectionCase,
) -> None:
    """
    Populate and accept one production command after its dialog is active.

    Autodesk permits programmatic selection population after ``commandCreated``;
    the captured command is therefore configured only after the production opener
    returns and Fusion has activated the dialog.

    Args:
        application: Active Fusion application.
        case: Command opener and input configuration.
    """
    user_interface = application.userInterface
    wait_for(
        application,
        lambda: str(user_interface.activeCommand) == "SelectCommand",
        f"Fusion default command before {case.name}",
    )
    definition = user_interface.commandDefinitions.itemById(case.command_id)
    if definition is None:
        raise RuntimeError(f"Native command is unavailable: {case.command_id}")
    capture = _CommandCaptureHandler()
    if not definition.commandCreated.add(capture):
        raise RuntimeError(f"Fusion could not observe native command: {case.command_id}")
    executed = False
    try:
        case.open_command()
        wait_for(
            application,
            lambda: (
                capture.command is not None and str(user_interface.activeCommand) == case.command_id
            ),
            f"open {case.name}",
        )
        command = capture.command
        if command is None:
            raise RuntimeError(f"Fusion did not expose the live command for {case.name}.")
        case.configure_inputs(command.commandInputs)
        for _index in range(3):
            adsk.doEvents()
        if not command.doExecute(True):
            raise RuntimeError(f"Fusion did not accept the configured {case.name} command.")
        executed = True
        wait_for(
            application,
            lambda: str(user_interface.activeCommand) != case.command_id,
            f"terminate {case.name}",
        )
        _restore_default_select_command(application, case.name)
    finally:
        if not executed and str(user_interface.activeCommand) == case.command_id:
            select_definition = user_interface.commandDefinitions.itemById("SelectCommand")
            if select_definition is not None:
                select_definition.execute()
        if not definition.commandCreated.remove(capture):
            raise RuntimeError(f"Fusion could not release the {case.name} command observer.")


def _restore_default_select_command(
    application: adsk.core.Application,
    description: str,
) -> None:
    """
    Restore Fusion's default command after programmatic dialog acceptance.

    Args:
        application: Active Fusion application.
        description: Completed operation used in diagnostics.
    """
    user_interface = application.userInterface
    if str(user_interface.activeCommand) == "SelectCommand":
        return
    select_definition = user_interface.commandDefinitions.itemById("SelectCommand")
    if select_definition is None or not select_definition.execute():
        raise RuntimeError(f"Fusion could not restore selection after {description}.")
    wait_for(
        application,
        lambda: str(user_interface.activeCommand) == "SelectCommand",
        f"restore selection after {description}",
    )


def _set_profile_selections(
    inputs: adsk.core.CommandInputs,
    selections: tuple[tuple[str, tuple[adsk.core.Base, ...]], ...],
) -> None:
    """
    Populate real native selection inputs with deterministic sketch profiles.

    Args:
        inputs: Live production command inputs.
        selections: Input IDs paired with ordered profile entities.
    """
    for input_id, entities in selections:
        selection_input = adsk.core.SelectionCommandInput.cast(inputs.itemById(input_id))
        if selection_input is None:
            raise RuntimeError(f"Fusion command omitted selection input: {input_id}")
        for entity in entities:
            if not selection_input.addSelection(entity):
                raise RuntimeError(f"Fusion rejected a profile for selection input: {input_id}")
        if selection_input.selectionCount != len(entities):
            raise AssertionError(
                f"Fusion retained {selection_input.selectionCount} selections for {input_id}; "
                f"expected {len(entities)}."
            )


def _connection_member_tokens(
    definition: HarnessDefinition,
    connection_id: UUID,
) -> tuple[str, ...]:
    """
    Return the ordered profile tokens for one stable connection identity.
    """
    connection = next(
        (item for item in definition.connections if item.connection_id == connection_id),
        None,
    )
    return connection.member_tokens if connection is not None else ()


def _has_distinct_pathway_gate(
    definition: HarnessDefinition,
    excluded_pathway_id: UUID,
    gate_token: str,
) -> bool:
    """
    Report whether another pathway owns a control linked to the requested profile.
    """
    controls = {control.control_id: control for control in definition.controls}
    return any(
        any(
            control_id in controls and controls[control_id].entity_token == gate_token
            for control_id in pathway.ordered_control_ids
        )
        for pathway in definition.pathways
        if pathway.pathway_id != excluded_pathway_id
    )


def _pathway_last_gate_token(
    definition: HarnessDefinition,
    pathway_id: UUID,
) -> str:
    """
    Return the linked token for the last control on one pathway.
    """
    pathway = next(
        (item for item in definition.pathways if item.pathway_id == pathway_id),
        None,
    )
    if pathway is None or not pathway.ordered_control_ids:
        return ""
    control_id = pathway.ordered_control_ids[-1]
    control = next(
        (item for item in definition.controls if item.control_id == control_id),
        None,
    )
    return control.entity_token if control is not None else ""


def _has_wire_between_tokens(
    definition: HarnessDefinition,
    source_token: str,
    destination_token: str,
) -> bool:
    """
    Report whether one wire connects the requested primary profile tokens.
    """
    connections = {connection.connection_id: connection for connection in definition.connections}
    return any(
        wire.start_connection_id in connections
        and wire.end_connection_id in connections
        and connections[wire.start_connection_id].entity_token == source_token
        and connections[wire.end_connection_id].entity_token == destination_token
        for wire in definition.wires
    )


def _verify_multi_wire_endpoint_history(
    application: adsk.core.Application,
    design: adsk.fusion.Design,
    gateway: FusionHarnessGateway,
) -> None:
    """
    Add a second fixture wire and verify endpoint-sequence history for the first.

    Args:
        application: Active Fusion application.
        design: Isolated command-history design.
        gateway: Persistence gateway bound to the fixture.
    """
    root = design.rootComponent
    source = _create_circular_profile(root, 0.0, 0.3, 0.0, 0.12, "QA Source 2")
    destination = _create_circular_profile(root, 10.0, 0.3, 0.0, 0.12, "QA Destination 2")
    identifiers = iter(
        (
            SECOND_WIRE_PROFILE_ID,
            SECOND_SOURCE_CONNECTION_ID,
            SECOND_DESTINATION_CONNECTION_ID,
            SECOND_WIRE_ID,
        )
    )
    add_wire_batch(
        HARNESS_ID,
        PATHWAY_ID,
        (source.entityToken,),
        (destination.entityToken,),
        1.0,
        gateway,
        id_factory=lambda: next(identifiers),
    )
    case = _PersistentEditCase(
        "reorder wire endpoints",
        "move_wire_endpoint",
        {
            "harnessId": str(HARNESS_ID),
            "wireId": str(WIRE_ID),
            "endpoint": "start",
            "offset": 1,
        },
        lambda current: (
            current.wires[0].start_connection_id == SECOND_SOURCE_CONNECTION_ID
            and current.wires[1].start_connection_id == SOURCE_CONNECTION_ID
        ),
    )
    _verify_persistent_edit_case(application, gateway, case)


def _verify_persistent_edit_matrix(
    application: adsk.core.Application,
    gateway: FusionHarnessGateway,
    report: ScenarioReport,
) -> list[str]:
    """
    Verify one native transaction and palette projection for every matrix edit.

    Args:
        application: Active Fusion application.
        gateway: Persistence gateway bound to the command fixture.
        report: Scenario report receiving named edit steps.

    Returns:
        Ordered palette action names exercised by the matrix.
    """
    actions: list[str] = []
    for case in _persistent_edit_cases(gateway):
        with report.step(f"Persistent edit history: {case.name}"):
            _verify_persistent_edit_case(application, gateway, case)
        actions.append(case.action)
    return actions


def _verify_persistent_edit_case(
    application: adsk.core.Application,
    gateway: FusionHarnessGateway,
    case: _PersistentEditCase,
) -> None:
    """
    Prove one edit, Undo, Redo, and final restoration against data and palette state.

    Args:
        application: Active Fusion application.
        gateway: Persistence gateway bound to the command fixture.
        case: Action payload and expected-state predicate.
    """
    dom_observer: Optional[Callable[[HarnessDefinition, str], None]] = None
    if case.observe_palette_dom:

        def observe_palette_dom(definition: HarnessDefinition, phase: str) -> None:
            """
            Bind the active application to this edit case's DOM assertion.
            """
            _observe_wire_palette_dom(application, definition, phase)

        dom_observer = observe_palette_dom
    _verify_definition_history(
        application,
        gateway,
        case.name,
        lambda: execute_palette_action(application, case.action, json.dumps(case.payload)),
        case.matches_expected,
        dom_observer=dom_observer,
    )


def _verify_definition_history(
    application: adsk.core.Application,
    gateway: FusionHarnessGateway,
    description: str,
    execute: Callable[[], None],
    matches_expected: Callable[[HarnessDefinition], bool],
    palette_must_change: bool = True,
    dom_observer: Optional[Callable[[HarnessDefinition, str], None]] = None,
) -> None:
    """
    Verify edit, Undo, Redo, and restoration against data and palette state.

    Args:
        application: Active Fusion application.
        gateway: Persistence gateway bound to the command fixture.
        description: Operation label used in timeout diagnostics.
        execute: Real production command invocation.
        matches_expected: Predicate identifying the intended edited state.
        palette_must_change: Whether the public projection exposes the changed field.
        dom_observer: Optional live palette assertion after each history phase.
    """
    before = _read_definition(gateway)
    before_palette = _palette_harness_projection(application)
    if dom_observer is not None:
        dom_observer(before, "initial")
    execute()
    wait_for(
        application,
        lambda: _matches_edit(gateway, before, matches_expected),
        description,
    )
    after = _read_definition(gateway)
    after_palette = _palette_harness_projection(application)
    if palette_must_change and after_palette == before_palette:
        raise AssertionError(f"Palette projection did not change after {description}.")
    if dom_observer is not None:
        dom_observer(after, "edited")

    _execute_native_history_command(application, "UndoCommand")
    wait_for(application, lambda: _read_definition(gateway) == before, f"{description} Undo")
    wait_for(
        application,
        lambda: _palette_harness_projection(application) == before_palette,
        f"{description} palette Undo",
    )
    if dom_observer is not None:
        dom_observer(before, "undo")

    _execute_native_history_command(application, "RedoCommand")
    wait_for(application, lambda: _read_definition(gateway) == after, f"{description} Redo")
    wait_for(
        application,
        lambda: _palette_harness_projection(application) == after_palette,
        f"{description} palette Redo",
    )
    if dom_observer is not None:
        dom_observer(after, "redo")

    _execute_native_history_command(application, "UndoCommand")
    wait_for(
        application,
        lambda: _read_definition(gateway) == before,
        f"{description} final restoration",
    )
    wait_for(
        application,
        lambda: _palette_harness_projection(application) == before_palette,
        f"{description} final palette restoration",
    )
    if dom_observer is not None:
        dom_observer(before, "final restoration")


def _observe_wire_palette_dom(
    application: adsk.core.Application,
    definition: HarnessDefinition,
    phase: str,
) -> None:
    """
    Prove that the consent-gated live palette rendered the expected wire label.

    The fixed JavaScript probe clears a known viewport selection only after it
    finds the requested harness and wire in the real DOM with the exact expected
    label. No selector or executable script crosses the palette boundary.

    Args:
        application: Active Fusion application.
        definition: Persisted state expected in the palette.
        phase: History phase used in timeout diagnostics.
    """
    wire = next((item for item in definition.wires if item.wire_id == WIRE_ID), None)
    if wire is None:
        raise AssertionError("Palette DOM probe wire is missing from the definition.")
    connection = next(
        (item for item in definition.connections if item.connection_id == wire.start_connection_id),
        None,
    )
    if connection is None:
        raise AssertionError("Palette DOM probe source connection is missing.")
    design = adsk.fusion.Design.cast(application.activeProduct)
    entities = design.findEntityByToken(connection.entity_token) if design is not None else ()
    profile = adsk.fusion.Profile.cast(entities[0] if entities else None)
    if profile is None:
        raise AssertionError("Palette DOM probe source profile no longer resolves.")
    palette = application.userInterface.palettes.itemById(PALETTE_ID)
    if palette is None or not palette.isVisible:
        raise RuntimeError("Harness Builder palette must be visible for DOM verification.")
    selections = application.userInterface.activeSelections
    if not selections.clear() or not selections.add(profile):
        raise RuntimeError("Fusion could not prepare the palette DOM probe sentinel.")
    expected_label = wire.display_name or f"Wire #{wire.wire_number}"
    payload = json.dumps(
        {
            "operation": "observe_wire",
            "harnessId": str(definition.harness_id),
            "wireId": str(wire.wire_id),
            "expectedLabel": expected_label,
        }
    )
    current_addin = importlib.import_module("wire_bundler.addin")
    vars(current_addin)["_send_palette_state"](application)
    deadline = monotonic() + 5.0
    while monotonic() < deadline:
        palette.sendInfoToHTML("qa_probe", payload)
        for _index in range(3):
            adsk.doEvents()
        if selections.count == 0:
            return
        sleep(0.05)
    selections.clear()
    raise RuntimeError(
        f"Palette DOM did not render {expected_label!r} during {phase}; "
        "Developer mode with current disclosure consent is required."
    )


def _reload_palette_resources(application: adsk.core.Application) -> str:
    """
    Reload local palette files for this development-only live scenario.

    Args:
        application: Active Fusion application.

    Returns:
        Original palette URL restored during scenario cleanup.
    """
    palette = application.userInterface.palettes.itemById(PALETTE_ID)
    if palette is None or not palette.isVisible:
        raise RuntimeError("Harness Builder palette must be visible for DOM verification.")
    original_url = str(palette.htmlFileURL)
    base_url = (ADDIN_ROOT / "palette.html").resolve().as_uri()
    palette.htmlFileURL = f"{base_url}?wire_bundler_qa={int(monotonic() * 1_000_000)}"
    for _index in range(5):
        adsk.doEvents()
        sleep(0.05)
    return original_url


def _restore_palette_url(application: adsk.core.Application, original_url: str) -> None:
    """
    Restore the ordinary palette resource URL after a focused live scenario.

    Args:
        application: Active Fusion application.
        original_url: URL captured before the development refresh.
    """
    palette = application.userInterface.palettes.itemById(PALETTE_ID)
    if palette is None:
        return
    palette.htmlFileURL = original_url
    for _index in range(3):
        adsk.doEvents()


def _matches_edit(
    gateway: FusionHarnessGateway,
    before: HarnessDefinition,
    matches_expected: Callable[[HarnessDefinition], bool],
) -> bool:
    """
    Report whether an edit changed the definition and reached its intended result.
    """
    current = _read_definition(gateway)
    return current != before and matches_expected(current)


def _persistent_edit_cases(gateway: FusionHarnessGateway) -> tuple[_PersistentEditCase, ...]:
    """
    Build deterministic action payloads from the enriched one-wire fixture.
    """
    definition = _read_definition(gateway)
    wire = definition.wires[0]
    pathway = definition.pathways[0]
    source = next(
        item for item in definition.connections if item.connection_id == wire.start_connection_id
    )
    first_member_id = source.member_identities[0]
    harness_id = str(HARNESS_ID)
    wire_id = str(WIRE_ID)
    pathway_id = str(PATHWAY_ID)
    interpolation = {"approach_mm": 2.0, "departure_mm": 3.0}
    material_defaults = {
        "insulationMaterial": "QA ETFE",
        "mainColor": {"name": "QA Blue", "red": 30, "green": 90, "blue": 210},
        "appearance": None,
        "stripes": [],
        "conductorMaterial": "Copper",
        "manufacturer": "Wire Bundler QA",
        "partNumber": "QA-HISTORY-001",
        "notes": "Command history fixture",
    }
    material_overrides = {
        "insulationMaterial": None,
        "mainColor": {"name": "QA Red", "red": 200, "green": 38, "blue": 38},
        "appearance": None,
        "stripes": [],
        "conductorMaterial": None,
        "manufacturer": None,
        "partNumber": "QA-WIRE-HISTORY-001",
        "notes": None,
    }
    return (
        _PersistentEditCase(
            "rename wire",
            "rename_wire",
            {"harnessId": harness_id, "wireId": wire_id, "name": RENAMED_WIRE},
            lambda current: current.wires[0].display_name == RENAMED_WIRE,
            observe_palette_dom=True,
        ),
        _PersistentEditCase(
            "rename pathway",
            "rename_pathway",
            {
                "harnessId": harness_id,
                "pathwayId": pathway_id,
                "field": "name",
                "name": "QA Renamed Pathway",
            },
            lambda current: current.pathways[0].name == "QA Renamed Pathway",
        ),
        _PersistentEditCase(
            "rename pathway start",
            "rename_pathway",
            {
                "harnessId": harness_id,
                "pathwayId": pathway_id,
                "field": "start_name",
                "name": "QA Pathway Start",
            },
            lambda current: current.pathways[0].start_name == "QA Pathway Start",
        ),
        _PersistentEditCase(
            "rename pathway end",
            "rename_pathway",
            {
                "harnessId": harness_id,
                "pathwayId": pathway_id,
                "field": "end_name",
                "name": "QA Pathway End",
            },
            lambda current: current.pathways[0].end_name == "QA Pathway End",
        ),
        _PersistentEditCase(
            "rename wire start",
            "rename_route_end",
            {
                "harnessId": harness_id,
                "wireId": wire_id,
                "endpoint": "start",
                "name": "QA Wire Start",
            },
            lambda current: current.wires[0].start_end_name == "QA Wire Start",
        ),
        _PersistentEditCase(
            "rename wire end",
            "rename_route_end",
            {
                "harnessId": harness_id,
                "wireId": wire_id,
                "endpoint": "end",
                "name": "QA Wire End",
            },
            lambda current: current.wires[0].end_end_name == "QA Wire End",
        ),
        _PersistentEditCase(
            "set wire diameter",
            "set_wire_diameter",
            {"harnessId": harness_id, "wireId": wire_id, "diameterMm": 1.25},
            lambda current: current.profiles[-1].diameter_mm == 1.25,
        ),
        _PersistentEditCase(
            "set gate interpolation",
            "set_interpolation",
            {
                "harnessId": harness_id,
                "target": "gate",
                "targetId": str(CONTROL_ID),
                "settings": interpolation,
            },
            lambda current: current.controls[0].interpolation.approach_mm == 2.0,
        ),
        _PersistentEditCase(
            "set end-member interpolation",
            "set_interpolation",
            {
                "harnessId": harness_id,
                "target": "end",
                "targetId": str(source.connection_id),
                "memberId": str(first_member_id),
                "settings": interpolation,
            },
            lambda current: current.connections[0].member_settings[0].departure_mm == 3.0,
        ),
        _PersistentEditCase(
            "set interpolation defaults",
            "set_interpolation",
            {
                "harnessId": harness_id,
                "target": "defaults",
                "settings": interpolation,
                "endDefaults": {"approach_mm": 4.0, "departure_mm": 5.0},
                "applyExisting": False,
            },
            lambda current: (
                current.gate_defaults.approach_mm == 2.0
                and current.end_defaults.departure_mm == 5.0
            ),
        ),
        _PersistentEditCase(
            "set harness material defaults",
            "set_harness_material_defaults",
            {"harnessId": harness_id, "materials": material_defaults},
            lambda current: current.material_defaults.part_number == "QA-HISTORY-001",
        ),
        _PersistentEditCase(
            "set wire material overrides",
            "set_wire_material_overrides",
            {"harnessId": harness_id, "wireId": wire_id, "overrides": material_overrides},
            lambda current: (
                current.wires[0].material_overrides.part_number == "QA-WIRE-HISTORY-001"
            ),
        ),
        _PersistentEditCase(
            "reorder pathway gates",
            "move_pathway_gate",
            {
                "harnessId": harness_id,
                "pathwayId": pathway_id,
                "controlId": str(pathway.ordered_control_ids[0]),
                "offset": 1,
            },
            lambda current: (
                current.pathways[0].ordered_control_ids
                == tuple(reversed(pathway.ordered_control_ids))
            ),
        ),
        _PersistentEditCase(
            "remove pathway gate",
            "remove_pathway_gate",
            {
                "harnessId": harness_id,
                "pathwayId": pathway_id,
                "controlId": str(SECOND_CONTROL_ID),
            },
            lambda current: current.pathways[0].ordered_control_ids == (CONTROL_ID,),
        ),
        _PersistentEditCase(
            "reorder end members",
            "move_end_member",
            {
                "harnessId": harness_id,
                "wireId": wire_id,
                "endpoint": "start",
                "memberIndex": 1,
                "expectedMembers": 2,
                "targetIndex": 0,
            },
            lambda current: (
                current.connections[0].member_identities[0] == source.member_identities[1]
            ),
        ),
        _PersistentEditCase(
            "remove end member",
            "remove_end_member",
            {
                "harnessId": harness_id,
                "wireId": wire_id,
                "endpoint": "start",
                "memberIndex": 1,
                "expectedMembers": 2,
            },
            lambda current: len(current.connections[0].member_tokens) == 1,
        ),
        _PersistentEditCase(
            "remove wire",
            "remove_wire",
            {"harnessId": harness_id, "wireId": wire_id},
            lambda current: not current.wires,
        ),
    )


def _read_definition(gateway: FusionHarnessGateway) -> HarnessDefinition:
    """
    Read the current command fixture definition.
    """
    return loads(gateway.read_harness_definition(HARNESS_ID))


def _palette_harness_projection(application: adsk.core.Application) -> dict[str, object]:
    """
    Read the serialized palette projection for the command fixture.
    """
    current_addin = importlib.import_module("wire_bundler.addin")
    serialize_palette_state = vars(current_addin)["_serialize_palette_state"]
    serialized = serialize_palette_state(application)
    payload = json.loads(serialized)
    if not isinstance(payload, dict):
        raise AssertionError("Palette state is not an object.")
    harnesses = payload.get("harnesses")
    if not isinstance(harnesses, list):
        raise AssertionError("Palette state omitted its harness collection.")
    projection = next(
        (
            item
            for item in harnesses
            if isinstance(item, dict) and item.get("harnessId") == str(HARNESS_ID)
        ),
        None,
    )
    if projection is None:
        raise AssertionError("Palette state omitted the command-history harness.")
    return projection


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
    current_addin = importlib.import_module("wire_bundler.addin")
    open_palette_edit = vars(current_addin)["_open_palette_edit"]
    open_palette_edit(application, action, payload)


def _clear_transient_preview(application: adsk.core.Application) -> int:
    """
    Exercise the production clear path that intentionally bypasses model history.

    Args:
        application: Active Fusion application.

    Returns:
        Number of removed top-level preview graphics groups.
    """
    current_addin = importlib.import_module("wire_bundler.addin")
    clear_preview = vars(current_addin)["_clear_preview"]
    return clear_preview(application)


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
        current_addin = importlib.import_module("wire_bundler.addin")
        last_command_error = vars(current_addin)["_last_command_error"]
        if last_command_error:
            raise RuntimeError(f"Fusion command failed during {description}: {last_command_error}")
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
