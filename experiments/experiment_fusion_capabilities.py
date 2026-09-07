"""
Audit the Fusion host controls available to automated verification.

Run this through its registered Fusion script bundle, never with standalone Python.
The audit creates and closes only its own unsaved design, then writes a structured
report beneath ``artifacts/verification``.
"""

from __future__ import annotations

import platform
import sys
import traceback
from pathlib import Path
from typing import Optional

ADDIN_ROOT = Path(__file__).resolve().parent.parent
if str(ADDIN_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDIN_ROOT))

# noinspection PyUnresolvedReferences
import adsk.core  # noqa: E402

# noinspection PyUnresolvedReferences
import adsk.fusion  # noqa: E402

from experiments.scenario_report import ScenarioReport  # noqa: E402
from wire_bundler.addin import (  # noqa: E402
    ADD_PATHWAY_COMMAND_ID,
    ADD_WIRES_COMMAND_ID,
    APPEND_GATES_COMMAND_ID,
    COMMAND_ID,
    CREATE_COMMAND_ID,
    EDIT_END_COMMAND_ID,
    PALETTE_ID,
)

SCENARIO_NAME = "fusion_capabilities"
ARTIFACT_ROOT = ADDIN_ROOT / "artifacts" / "verification"
EXPECTED_COMMAND_IDS = (
    COMMAND_ID,
    CREATE_COMMAND_ID,
    ADD_PATHWAY_COMMAND_ID,
    APPEND_GATES_COMMAND_ID,
    EDIT_END_COMMAND_ID,
    ADD_WIRES_COMMAND_ID,
    "UndoCommand",
    "RedoCommand",
)


def run(_context: object) -> None:
    """
    Inspect safe Fusion automation surfaces and persist their observed behavior.

    Args:
        _context: Context supplied by the Fusion script host.
    """
    report = ScenarioReport(SCENARIO_NAME, ARTIFACT_ROOT, _log_to_fusion)
    application: Optional[adsk.core.Application] = None
    try:
        application = _require_application()
        audit_fusion_capabilities(application, report)
        report.finish(True)
        application.userInterface.messageBox(
            "Fusion automation capability audit passed.\n\n"
            f"Log: {report.log_path}\n"
            f"Report: {report.json_path}",
            "Wire Bundler QA Capability Audit",
        )
    except (AssertionError, AttributeError, OSError, RuntimeError, TypeError, ValueError):
        failure = traceback.format_exc()
        report.finish(False, failure)
        if application is not None and application.userInterface is not None:
            application.userInterface.messageBox(
                "Fusion automation capability audit failed.\n\n"
                f"Log: {report.log_path}\n"
                f"Report: {report.json_path}\n\n"
                f"{failure}",
                "Wire Bundler QA Capability Audit",
            )


def audit_fusion_capabilities(
    application: adsk.core.Application,
    report: ScenarioReport,
) -> None:
    """
    Execute the capability assertions without catching failures or showing UI.

    Args:
        application: Active Fusion application.
        report: Durable report that receives steps and observations.
    """
    user_interface = application.userInterface
    if user_interface is None:
        raise RuntimeError("Fusion did not expose its user interface.")

    with report.step("Inspect application and API entry points"):
        report.record_observation(
            "fusion.application",
            {
                "version": str(getattr(application, "version", "unknown")),
                "hostPlatform": platform.system(),
                "hostPlatformRelease": platform.release(),
                "hostMachine": platform.machine(),
                "hasActiveDocument": application.activeDocument is not None,
                "hasActiveProduct": application.activeProduct is not None,
                "executeTextCommand": callable(getattr(application, "executeTextCommand", None)),
                "applicationLog": callable(getattr(adsk.core.Application, "log", None)),
            },
        )

    with report.step("Inspect command registry"):
        command_definitions = user_interface.commandDefinitions
        commands = {}
        for command_id in EXPECTED_COMMAND_IDS:
            command_definition = command_definitions.itemById(command_id)
            control_definition = (
                command_definition.controlDefinition if command_definition is not None else None
            )
            commands[command_id] = {
                "registered": command_definition is not None,
                "enabled": bool(getattr(control_definition, "isEnabled", False)),
                "execute": callable(getattr(command_definition, "execute", None))
                if command_definition is not None
                else False,
            }
        report.record_observation("fusion.commands", commands)

    with report.step("Probe isolated document lifecycle"):
        report.record_observation(
            "fusion.documentLifecycle",
            _probe_document_lifecycle(application),
        )

    with report.step("Inspect palette, selection, and design state"):
        active_design = adsk.fusion.Design.cast(application.activeProduct)
        active_palette = user_interface.palettes.itemById(PALETTE_ID)
        report.record_observation(
            "fusion.hostState",
            {
                "activeCommand": str(getattr(user_interface, "activeCommand", "")),
                "activeDesign": active_design is not None,
                "activeSelections": user_interface.activeSelections.count,
                "harnessPaletteRegistered": active_palette is not None,
                "harnessPaletteVisible": bool(active_palette.isVisible)
                if active_palette is not None
                else False,
                "findEntityByToken": callable(getattr(active_design, "findEntityByToken", None))
                if active_design is not None
                else False,
            },
        )

    report.record_observation(
        "fusion.mcp",
        {
            "endpoint": "http://127.0.0.1:27182/mcp",
            "role": "external development orchestration",
            "requiresSeparateProbe": True,
        },
    )


def _probe_document_lifecycle(application: adsk.core.Application) -> dict[str, object]:
    """
    Create and close an isolated unsaved design without modifying the active design.

    Args:
        application: Active Fusion application.

    Returns:
        Structured lifecycle observations.
    """
    previous_document = application.activeDocument
    initial_count = application.documents.count
    probe_document: Optional[adsk.core.Document] = None
    close_result = False
    try:
        probe_document = application.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        if probe_document is None:
            raise RuntimeError("Fusion did not create the isolated capability-probe document.")
        probe_design = adsk.fusion.Design.cast(application.activeProduct)
        if probe_design is None:
            raise RuntimeError("Fusion did not activate a design for the capability probe.")
        probe_design.designIntent = adsk.fusion.DesignIntentTypes.HybridDesignIntentType
    finally:
        if probe_document is not None:
            close_result = bool(probe_document.close(False))

    restored_document = application.activeDocument
    restored_previous = previous_document is None or restored_document == previous_document
    final_count = application.documents.count
    if not close_result:
        raise RuntimeError("Fusion did not close the isolated capability-probe document.")
    if final_count != initial_count:
        raise AssertionError(
            f"Document lifecycle probe leaked a document: before={initial_count}, after={final_count}."
        )
    if not restored_previous:
        raise AssertionError("Fusion did not restore the previously active document.")
    return {
        "createUnsavedDesign": True,
        "setHybridIntent": True,
        "closeWithoutSave": close_result,
        "restoredPreviousDocument": restored_previous,
        "documentCountStable": final_count == initial_count,
    }


def _require_application() -> adsk.core.Application:
    """
    Return the active Fusion application or reject standalone execution.

    Returns:
        Active Fusion application.
    """
    application = adsk.core.Application.get()
    if application is None:
        raise RuntimeError("The capability audit must run inside Autodesk Fusion.")
    return application


def _log_to_fusion(message: str) -> None:
    """
    Mirror capability-audit progress into Fusion's application log.

    Args:
        message: Timestamped scenario log line.
    """
    adsk.core.Application.log(
        f"Wire Bundler QA capability audit: {message}",
        adsk.core.LogLevels.InfoLogLevel,
        adsk.core.LogTypes.FileLogType,
    )
