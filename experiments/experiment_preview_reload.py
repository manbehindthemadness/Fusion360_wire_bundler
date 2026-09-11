"""
Verify preview creation and clearing across a real Fusion save and reopen cycle.

The scenario creates a uniquely named cloud document in Fusion's active data folder,
closes and reopens it, then deletes the temporary DataFile during mandatory cleanup.
Run it only inside Fusion through its registered runner or the development QA suite.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from time import monotonic, sleep
from typing import Optional
from uuid import uuid4

ADDIN_ROOT = Path(__file__).resolve().parent.parent
if str(ADDIN_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDIN_ROOT))

# noinspection PyUnresolvedReferences
import adsk  # noqa: E402

# noinspection PyUnresolvedReferences
import adsk.core  # noqa: E402

# noinspection PyUnresolvedReferences
import adsk.fusion  # noqa: E402

from experiments.experiment_command_history import (  # noqa: E402
    HARNESS_ID,
    build_single_wire_fixture,
    execute_palette_action,
    wait_for,
)
from experiments.scenario_report import ScenarioReport  # noqa: E402
from wire_bundler.fusion import FusionHarnessGateway  # noqa: E402
from wire_bundler.fusion.route_preview import (  # noqa: E402
    clear_route_previews,
    has_route_previews,
)

SCENARIO_NAME = "preview_reload"
ARTIFACT_ROOT = ADDIN_ROOT / "artifacts" / "verification"
CLOUD_TIMEOUT_SECONDS = 120.0


def run(_context: object) -> None:
    """
    Run the disposable cloud lifecycle scenario and display its result.
    """
    report = ScenarioReport(SCENARIO_NAME, ARTIFACT_ROOT, _log_to_fusion)
    application: Optional[adsk.core.Application] = None
    try:
        application = _require_application()
        verify_preview_reload(application, report)
        report.finish(True)
        application.userInterface.messageBox(
            "Preview save/reload verification passed.\n\n"
            "The disposable cloud document was deleted.\n"
            f"Log: {report.log_path}\nReport: {report.json_path}",
            "Wire Bundler Preview Reload",
        )
    except (AssertionError, AttributeError, OSError, RuntimeError, TypeError, ValueError):
        failure = traceback.format_exc()
        report.finish(False, failure)
        if application is not None and application.userInterface is not None:
            application.userInterface.messageBox(
                "Preview save/reload verification failed.\n\n"
                f"Log: {report.log_path}\nReport: {report.json_path}\n\n{failure}",
                "Wire Bundler Preview Reload",
            )


def verify_preview_reload(
    application: adsk.core.Application,
    report: ScenarioReport,
) -> None:
    """
    Save, reopen, inspect, and delete one disposable preview fixture.
    """
    previous_document = application.activeDocument
    initial_document_count = application.documents.count
    document: Optional[adsk.core.Document] = None
    temporary_data_file: Optional[adsk.core.DataFile] = None
    fixture_name = f"WB_QA_Preview_Reload_{uuid4().hex[:12]}"
    try:
        with report.step("Create disposable preview fixture"):
            active_folder = application.data.activeFolder
            if active_folder is None:
                raise RuntimeError("Fusion has no active cloud folder for disposable QA data.")
            document = application.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
            if document is None:
                raise RuntimeError("Fusion did not create the preview-reload document.")
            design = adsk.fusion.Design.cast(application.activeProduct)
            if design is None:
                raise RuntimeError("Fusion did not activate the preview-reload design.")
            design.designIntent = adsk.fusion.DesignIntentTypes.HybridDesignIntentType
            gateway = build_single_wire_fixture(application, design)
            if gateway.harness_component(HARNESS_ID) is None:
                raise AssertionError("Preview-reload harness was not created.")

        with report.step("Create preview before initial save"):
            payload = json.dumps({"harnessId": str(HARNESS_ID)})
            execute_palette_action(application, "preview_routes", payload)
            wait_for(application, lambda: has_route_previews(design), "pre-save preview")

        with report.step("Save disposable document with active preview"):
            compatibility = application.preferences.compatibilityPreferences
            initial_cache_setting = compatibility.isCacheGraphicsOnDocumentSave
            if not document.saveAs(
                fixture_name,
                active_folder,
                "Wire Bundler automated preview reload verification",
                "wire-bundler-qa",
            ):
                raise RuntimeError("Fusion declined to save the preview-reload fixture.")
            fusion_document = adsk.fusion.FusionDocument.cast(document)
            if fusion_document is None or fusion_document.dataFile is None:
                raise RuntimeError("Saved preview-reload document has no cloud DataFile.")
            temporary_data_file = fusion_document.dataFile
            _wait_for_cloud_processing(temporary_data_file)
            wait_for(
                application,
                lambda: compatibility.isCacheGraphicsOnDocumentSave == initial_cache_setting,
                "preview graphics-cache preference restoration",
            )

        with report.step("Close and reopen saved document"):
            if not document.close(False):
                raise RuntimeError("Fusion did not close the saved preview-reload fixture.")
            document = None
            reopened_document = application.documents.open(temporary_data_file, True)
            if reopened_document is None:
                raise RuntimeError("Fusion did not reopen the preview-reload fixture.")
            document = reopened_document
            reopened_design = adsk.fusion.Design.cast(application.activeProduct)
            if reopened_design is None:
                raise RuntimeError("Reopened preview-reload item is not a Fusion design.")

        with report.step("Inspect and clear preview state after reload"):
            reopened_gateway = FusionHarnessGateway(
                reopened_design,
                application.data.activeFolder,
            )
            definitions = reopened_gateway.list_stored_harnesses()
            if len(definitions) != 1:
                raise AssertionError(f"Expected one reopened harness, found {len(definitions)}.")
            if has_route_previews(reopened_design):
                raise AssertionError("Saved preview graphics remained API-visible after reload.")
            if clear_route_previews(reopened_design) != 0:
                raise AssertionError("Reload clear found an unexpected serialized preview group.")

        with report.step("Create and clear a fresh preview after reload"):
            execute_palette_action(application, "preview_routes", payload)
            wait_for(
                application,
                lambda: has_route_previews(reopened_design),
                "post-reload preview",
            )
            if clear_route_previews(reopened_design) != 1:
                raise AssertionError("Post-reload clear did not remove one fresh preview group.")
            application.activeViewport.refresh()
            if has_route_previews(reopened_design):
                raise AssertionError("Post-reload preview remained after explicit clear.")

        report.record_observation(
            "fusion.previewReload",
            {
                "savedWithActivePreview": True,
                "serializedPreviewGroups": 0,
                "freshPreviewClearedAfterReload": True,
                "graphicsCachePreferenceRestored": True,
            },
        )
    finally:
        if document is not None and document.isValid:
            with report.step("Close disposable preview-reload document"):
                if not document.close(False):
                    raise RuntimeError("Fusion did not close the disposable cloud document.")
        if temporary_data_file is not None and temporary_data_file.isValid:
            with report.step("Delete disposable preview-reload DataFile"):
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
                "Preview-reload scenario changed the open document count: "
                f"before={initial_document_count}, after={application.documents.count}."
            )


def _wait_for_cloud_processing(
    data_file: adsk.core.DataFile,
) -> None:
    """
    Pump Fusion events until a newly saved DataFile is fully processed.
    """
    deadline = monotonic() + CLOUD_TIMEOUT_SECONDS
    while monotonic() < deadline:
        adsk.doEvents()
        if data_file.isComplete:
            return
        sleep(0.05)
    raise RuntimeError("Timed out waiting for Fusion cloud processing to complete.")


def _delete_temporary_data_file(
    data_file: adsk.core.DataFile,
) -> None:
    """
    Delete the scenario-owned cloud file after all documents release it.
    """
    deadline = monotonic() + CLOUD_TIMEOUT_SECONDS
    while monotonic() < deadline:
        adsk.doEvents()
        if data_file.deleteMe():
            return
        sleep(0.1)
    raise RuntimeError("Fusion could not delete the disposable preview-reload DataFile.")


def _require_application() -> adsk.core.Application:
    """
    Return the active Fusion application or reject standalone execution.
    """
    application = adsk.core.Application.get()
    if application is None:
        raise RuntimeError("Preview-reload verification must run inside Autodesk Fusion.")
    return application


def _log_to_fusion(message: str) -> None:
    """
    Mirror preview-reload progress into Fusion's application log.
    """
    adsk.core.Application.log(
        f"Wire Bundler preview reload: {message}",
        adsk.core.LogLevels.InfoLogLevel,
        adsk.core.LogTypes.FileLogType,
    )
