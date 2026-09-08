"""
Verify deleted linked geometry remains isolated and repairable after reload.

The scenario creates and deletes one disposable cloud DataFile during mandatory cleanup.
Run it only inside Fusion through its registered runner or the development QA suite.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Optional
from uuid import uuid4

ADDIN_ROOT = Path(__file__).resolve().parent.parent
if str(ADDIN_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDIN_ROOT))

# noinspection PyUnresolvedReferences
import adsk.core  # noqa: E402

# noinspection PyUnresolvedReferences
import adsk.fusion  # noqa: E402

from experiments.experiment_command_history import (  # noqa: E402
    HARNESS_ID,
    build_single_wire_fixture,
)
from experiments.experiment_preview_reload import (  # noqa: E402
    _delete_temporary_data_file,
    _wait_for_cloud_processing,
)
from experiments.scenario_report import ScenarioReport  # noqa: E402
from wire_bundler import addin  # noqa: E402
from wire_bundler.domain import loads  # noqa: E402
from wire_bundler.fusion import FusionHarnessGateway  # noqa: E402

SCENARIO_NAME = "linked_geometry"
ARTIFACT_ROOT = ADDIN_ROOT / "artifacts" / "verification"


def run(_context: object) -> None:
    """
    Run the disposable linked-geometry scenario and display its result.

    Args:
        _context: Context supplied by the Fusion script host.
    """
    report = ScenarioReport(SCENARIO_NAME, ARTIFACT_ROOT, _log_to_fusion)
    application: Optional[adsk.core.Application] = None
    try:
        application = _require_application()
        verify_linked_geometry(application, report)
        report.finish(True)
        application.userInterface.messageBox(
            "Linked-geometry verification passed.\n\n"
            "The disposable cloud document was deleted.\n"
            f"Log: {report.log_path}\nReport: {report.json_path}",
            "Wire Bundler Linked Geometry",
        )
    except (AssertionError, AttributeError, OSError, RuntimeError, TypeError, ValueError):
        failure = traceback.format_exc()
        report.finish(False, failure)
        if application is not None and application.userInterface is not None:
            application.userInterface.messageBox(
                "Linked-geometry verification failed.\n\n"
                f"Log: {report.log_path}\nReport: {report.json_path}\n\n{failure}",
                "Wire Bundler Linked Geometry",
            )


def verify_linked_geometry(
    application: adsk.core.Application,
    report: ScenarioReport,
) -> None:
    """
    Delete one endpoint, reload, and verify the damage remains isolated.

    Args:
        application: Active Fusion application.
        report: Durable scenario report.
    """
    previous_document = application.activeDocument
    initial_document_count = application.documents.count
    document: Optional[adsk.core.Document] = None
    temporary_data_file: Optional[adsk.core.DataFile] = None
    fixture_name = f"WB_QA_Linked_Geometry_{uuid4().hex[:12]}"
    try:
        with report.step("Create linked-geometry fixture"):
            active_folder = application.data.activeFolder
            if active_folder is None:
                raise RuntimeError("Fusion has no active cloud folder for disposable QA data.")
            document = application.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
            if document is None:
                raise RuntimeError("Fusion did not create the linked-geometry fixture.")
            design = adsk.fusion.Design.cast(application.activeProduct)
            if design is None:
                raise RuntimeError("Fusion did not activate the linked-geometry fixture.")
            design.designIntent = adsk.fusion.DesignIntentTypes.HybridDesignIntentType
            gateway = build_single_wire_fixture(application, design)
            definition = loads(gateway.read_harness_definition(HARNESS_ID))
            if len(definition.connections) != 2 or len(definition.controls) != 1:
                raise AssertionError("Linked-geometry fixture has an unexpected topology.")
            source_token = definition.connections[0].entity_token
            healthy_tokens = (
                definition.connections[1].entity_token,
                definition.controls[0].entity_token,
            )
            if not all(
                gateway.is_entity_token_resolvable(token)
                for token in (source_token, *healthy_tokens)
            ):
                raise AssertionError("Fixture geometry was not initially resolvable.")

        with report.step("Delete one linked endpoint sketch"):
            source_sketch = design.rootComponent.sketches.itemByName("QA Source")
            if source_sketch is None or not source_sketch.deleteMe():
                raise RuntimeError("Fusion did not delete the selected endpoint sketch.")
            if gateway.is_entity_token_resolvable(source_token):
                raise AssertionError("Deleted endpoint token remained resolvable.")
            if not all(gateway.is_entity_token_resolvable(token) for token in healthy_tokens):
                raise AssertionError("Deleting one endpoint damaged healthy linked geometry.")

        with report.step("Save, close, and reopen damaged fixture"):
            if not document.saveAs(
                fixture_name,
                active_folder,
                "Wire Bundler automated linked-geometry verification",
                "wire-bundler-qa",
            ):
                raise RuntimeError("Fusion declined to save the linked-geometry fixture.")
            fusion_document = adsk.fusion.FusionDocument.cast(document)
            if fusion_document is None or fusion_document.dataFile is None:
                raise RuntimeError("Saved linked-geometry fixture has no cloud DataFile.")
            temporary_data_file = fusion_document.dataFile
            _wait_for_cloud_processing(temporary_data_file)
            if not document.close(False):
                raise RuntimeError("Fusion did not close the linked-geometry fixture.")
            document = None
            reopened_document = application.documents.open(temporary_data_file, True)
            if reopened_document is None:
                raise RuntimeError("Fusion did not reopen the linked-geometry fixture.")
            document = reopened_document
            reopened_design = adsk.fusion.Design.cast(application.activeProduct)
            if reopened_design is None:
                raise RuntimeError("Reopened linked-geometry item is not a Fusion design.")

        with report.step("Inspect repairable palette state after reload"):
            reopened_gateway = FusionHarnessGateway(reopened_design, active_folder)
            reopened_definition = loads(reopened_gateway.read_harness_definition(HARNESS_ID))
            if reopened_definition != definition:
                raise AssertionError("Deleting linked geometry changed the stored definition.")
            if reopened_gateway.is_entity_token_resolvable(source_token):
                raise AssertionError("Deleted endpoint token recovered unexpectedly after reload.")
            if not all(
                reopened_gateway.is_entity_token_resolvable(token) for token in healthy_tokens
            ):
                raise AssertionError("Healthy linked geometry did not survive reload.")

            palette_state = json.loads(addin._serialize_palette_state(application))  # noqa: SLF001
            harnesses = palette_state.get("harnesses")
            if not isinstance(harnesses, list) or len(harnesses) != 1:
                raise AssertionError("Palette did not expose exactly one damaged fixture.")
            connections = harnesses[0].get("connections")
            controls = harnesses[0].get("controls")
            if not isinstance(connections, list) or not isinstance(controls, list):
                raise AssertionError("Palette state omitted linked-geometry collections.")
            connection_health = tuple(
                bool(connection.get("hasLinkedGeometry")) for connection in connections
            )
            control_health = tuple(bool(control.get("hasLinkedGeometry")) for control in controls)
            if connection_health != (False, True) or control_health != (True,):
                raise AssertionError(
                    "Palette did not isolate the missing endpoint: "
                    f"connections={connection_health}, controls={control_health}."
                )

        report.record_observation(
            "fusion.linkedGeometry",
            {
                "storedDefinitionUnchanged": True,
                "deletedEndpointRepairable": True,
                "connectionHealth": list(connection_health),
                "controlHealth": list(control_health),
                "healthyReferencesPreserved": True,
            },
        )
    finally:
        if document is not None and document.isValid:
            with report.step("Close disposable linked-geometry document"):
                if not document.close(False):
                    raise RuntimeError("Fusion did not close the disposable cloud document.")
        if temporary_data_file is not None and temporary_data_file.isValid:
            with report.step("Delete disposable linked-geometry DataFile"):
                _delete_temporary_data_file(temporary_data_file)
        if (
            previous_document is not None
            and previous_document.isValid
            and application.activeDocument != previous_document
            and not previous_document.activate()
        ):
            raise RuntimeError("Fusion did not restore the previously active document.")
        if application.documents.count != initial_document_count:
            raise AssertionError(
                "Linked-geometry scenario changed the open document count: "
                f"before={initial_document_count}, after={application.documents.count}."
            )


def _require_application() -> adsk.core.Application:
    """
    Return the active Fusion application or reject standalone execution.
    """
    application = adsk.core.Application.get()
    if application is None:
        raise RuntimeError("Linked-geometry verification must run inside Autodesk Fusion.")
    return application


def _log_to_fusion(message: str) -> None:
    """
    Mirror linked-geometry progress into Fusion's application log.

    Args:
        message: Timestamped scenario log line.
    """
    adsk.core.Application.log(
        f"Wire Bundler linked geometry: {message}",
        adsk.core.LogLevels.InfoLogLevel,
        adsk.core.LogTypes.FileLogType,
    )
