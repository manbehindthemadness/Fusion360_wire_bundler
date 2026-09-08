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
            if harness is None:
                raise AssertionError("Command-history harness was not created.")
            if _wire_name(gateway):
                raise AssertionError("Command-history wire unexpectedly started with a name.")
            _augment_command_fixture(design, gateway)

        edit_actions = _verify_persistent_edit_matrix(application, gateway, report)

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
                "paletteProjectionUndoRedo": True,
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
    before = _read_definition(gateway)
    before_palette = _palette_harness_projection(application)
    execute_palette_action(application, case.action, json.dumps(case.payload))
    wait_for(
        application,
        lambda: _matches_edit(gateway, before, case.matches_expected),
        case.name,
    )
    after = _read_definition(gateway)
    after_palette = _palette_harness_projection(application)
    if after_palette == before_palette:
        raise AssertionError(f"Palette projection did not change after {case.name}.")

    _execute_native_history_command(application, "UndoCommand")
    wait_for(application, lambda: _read_definition(gateway) == before, f"{case.name} Undo")
    wait_for(
        application,
        lambda: _palette_harness_projection(application) == before_palette,
        f"{case.name} palette Undo",
    )

    _execute_native_history_command(application, "RedoCommand")
    wait_for(application, lambda: _read_definition(gateway) == after, f"{case.name} Redo")
    wait_for(
        application,
        lambda: _palette_harness_projection(application) == after_palette,
        f"{case.name} palette Redo",
    )

    _execute_native_history_command(application, "UndoCommand")
    wait_for(
        application,
        lambda: _read_definition(gateway) == before,
        f"{case.name} final restoration",
    )
    wait_for(
        application,
        lambda: _palette_harness_projection(application) == before_palette,
        f"{case.name} final palette restoration",
    )


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
