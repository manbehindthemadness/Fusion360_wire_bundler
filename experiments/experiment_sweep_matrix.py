"""
Generate and verify a deterministic matrix of circular wire Sweeps inside Fusion.

Run this through its registered Fusion script bundle, never with standalone Python.
The experiment leaves its unsaved design open and writes reports under artifacts/.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Optional
from uuid import NAMESPACE_URL, uuid5

ADDIN_ROOT = Path(__file__).resolve().parent.parent
if str(ADDIN_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDIN_ROOT))

# noinspection PyUnresolvedReferences
import adsk.core  # noqa: E402

# noinspection PyUnresolvedReferences
import adsk.fusion  # noqa: E402

from experiments.scenario_report import ScenarioReport  # noqa: E402
from experiments.sweep_scenarios import SweepScenario, sweep_scenarios  # noqa: E402
from wire_bundler.domain import WireDefinition  # noqa: E402
from wire_bundler.fusion.wire_solids import build_wire_sweep  # noqa: E402
from wire_bundler.routing import fair_route, tightest_bend  # noqa: E402

SCENARIO_NAME = "sweep_matrix"
ARTIFACT_ROOT = ADDIN_ROOT / "artifacts" / "verification"
HARNESS_ID = uuid5(NAMESPACE_URL, "wire-bundler:sweep-matrix:harness")


def run(_context: object) -> None:
    """
    Run the Sweep matrix and retain its unsaved design for inspection.
    """
    report = ScenarioReport(SCENARIO_NAME, ARTIFACT_ROOT, _log_to_fusion)
    application: Optional[adsk.core.Application] = None
    try:
        application = _require_application()
        verify_sweep_matrix(application, report, retain_document=True)
        report.finish(True)
        application.userInterface.messageBox(
            "Sweep matrix passed.\n\n"
            "The unsaved verification design remains open for inspection.\n"
            f"Log: {report.log_path}\nReport: {report.json_path}",
            "Wire Bundler Sweep Matrix",
        )
    except (AssertionError, AttributeError, OSError, RuntimeError, TypeError, ValueError):
        failure = traceback.format_exc()
        report.finish(False, failure)
        if application is not None and application.userInterface is not None:
            application.userInterface.messageBox(
                "Sweep matrix failed.\n\n"
                f"Log: {report.log_path}\nReport: {report.json_path}\n\n{failure}",
                "Wire Bundler Sweep Matrix",
            )


def verify_sweep_matrix(
    application: adsk.core.Application,
    report: ScenarioReport,
    retain_document: bool = False,
) -> None:
    """
    Execute every Sweep case and optionally retain the isolated design.
    """
    previous_document = application.activeDocument
    document: Optional[adsk.core.Document] = None
    failures: list[str] = []
    try:
        with report.step("Create isolated Hybrid design"):
            document = application.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
            if document is None:
                raise RuntimeError("Fusion did not create the Sweep matrix document.")
            design = adsk.fusion.Design.cast(application.activeProduct)
            if design is None:
                raise RuntimeError("Fusion did not activate the Sweep matrix design.")
            design.designIntent = adsk.fusion.DesignIntentTypes.HybridDesignIntentType

        for scenario in sweep_scenarios():
            try:
                with report.step(f"Sweep case: {scenario.name}"):
                    _run_case(design, scenario)
            except (AssertionError, AttributeError, RuntimeError, TypeError, ValueError):
                failures.append(f"{scenario.name}:\n{traceback.format_exc()}")
        if failures:
            raise AssertionError("\n".join(failures))
    finally:
        if not retain_document and document is not None and document.isValid:
            with report.step("Close isolated Sweep matrix"):
                if not document.close(False):
                    raise RuntimeError("Fusion did not close the Sweep matrix document.")
        if (
            not retain_document
            and previous_document is not None
            and previous_document.isValid
            and application.activeDocument != previous_document
            and not previous_document.activate()
        ):
            raise RuntimeError("Fusion did not restore the previously active document.")


def _run_case(design: adsk.fusion.Design, scenario: SweepScenario) -> None:
    """
    Confirm preflight behavior and build a native Sweep only for feasible geometry.
    """
    try:
        route = fair_route(
            scenario.route(),
            scenario.normals,
            scenario.transitions,
            scenario.minimum_bend_radius_mm,
        )
    except ValueError as error:
        if scenario.expected_feasible:
            raise
        if scenario.expected_error not in str(error):
            raise AssertionError(
                f"Expected error containing {scenario.expected_error!r}, received {error!s}."
            ) from error
        return
    if not scenario.expected_feasible:
        raise AssertionError("Preflight accepted geometry expected to be impossible.")

    bend = tightest_bend(route, 1024)
    if bend is None or bend.radius_mm + 1e-9 < scenario.minimum_bend_radius_mm:
        raise AssertionError("Preflight returned a route below its minimum bend radius.")
    occurrence = design.rootComponent.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    if occurrence is None:
        raise RuntimeError(f"Fusion did not create an occurrence for {scenario.name}.")
    occurrence.component.name = f"Sweep Case - {scenario.name}"
    wire = WireDefinition(
        wire_id=scenario.wire_id,
        wire_number=scenario.name,
        start_connection_id=uuid5(scenario.wire_id, "start"),
        end_connection_id=uuid5(scenario.wire_id, "end"),
        profile_id=uuid5(scenario.wire_id, "profile"),
        ordered_pathway_ids=(),
        ordered_control_ids=(),
    )
    build_wire_sweep(
        occurrence.component,
        wire,
        route,
        scenario.diameter_mm,
        adsk.core.Matrix3D.create(),
        HARNESS_ID,
    )
    component = occurrence.component
    if component.bRepBodies.count != 1 or not component.bRepBodies.item(0).isSolid:
        raise AssertionError("Fusion did not create exactly one valid solid body.")
    if component.features.sweepFeatures.count != 1:
        raise AssertionError("Fusion did not retain exactly one Sweep feature.")
    if component.features.pipeFeatures.count:
        raise AssertionError("The Sweep matrix unexpectedly invoked Pipe geometry.")


def _require_application() -> adsk.core.Application:
    """
    Return the active Fusion application or reject standalone execution.
    """
    application = adsk.core.Application.get()
    if application is None:
        raise RuntimeError("The Sweep matrix must run inside Autodesk Fusion.")
    return application


def _log_to_fusion(message: str) -> None:
    """
    Mirror matrix progress into Fusion's application log.
    """
    adsk.core.Application.log(
        f"Wire Bundler Sweep matrix: {message}",
        adsk.core.LogLevels.InfoLogLevel,
        adsk.core.LogTypes.FileLogType,
    )
