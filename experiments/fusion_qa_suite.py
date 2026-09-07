"""
Run the cleanup-safe Fusion scenarios used by the external QA orchestrator.
"""

from __future__ import annotations

import platform
import traceback
from collections.abc import Callable
from pathlib import Path

# noinspection PyUnresolvedReferences
import adsk.core

from experiments.experiment_command_history import verify_command_history
from experiments.experiment_fusion_capabilities import audit_fusion_capabilities
from experiments.experiment_preview_reload import verify_preview_reload
from experiments.experiment_reference_harness import verify_reference_harness
from experiments.experiment_sweep_matrix import verify_sweep_matrix
from experiments.scenario_report import ScenarioReport

ADDIN_ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_ROOT = ADDIN_ROOT / "artifacts" / "verification"
Scenario = Callable[[adsk.core.Application, ScenarioReport], None]


def run_automated_fusion_suite(application: adsk.core.Application) -> dict[str, object]:
    """
    Run every cleanup-safe live scenario and return one JSON-safe result.

    The suite catches failures at the scenario boundary so later independent scenarios
    still run and produce evidence. Each scenario core owns its fixture cleanup.

    Args:
        application: Active Fusion application.

    Returns:
        Aggregate live-suite result including each durable scenario report path.
    """
    scenarios: tuple[tuple[str, Scenario], ...] = (
        ("fusion_capabilities", audit_fusion_capabilities),
        ("command_history", verify_command_history),
        ("sweep_matrix", verify_sweep_matrix),
        ("reference_harness", verify_reference_harness),
        ("preview_reload", verify_preview_reload),
    )
    initial_document = application.activeDocument
    initial_document_count = application.documents.count
    results = []
    for scenario_name, scenario in scenarios:
        report = ScenarioReport(
            f"{scenario_name}_automated",
            ARTIFACT_ROOT,
            _log_to_fusion,
        )
        try:
            scenario(application, report)
        except (
            AssertionError,
            AttributeError,
            KeyError,
            OSError,
            RuntimeError,
            StopIteration,
            TypeError,
            ValueError,
        ):
            # This is the deliberate suite boundary: record one failed scenario and
            # continue collecting independent evidence from the remaining scenarios.
            failure = traceback.format_exc()
            report.finish(False, failure)
        else:
            report.finish(True)
        results.append(
            {
                "scenario": scenario_name,
                "status": report.status,
                "report": str(report.json_path),
                "log": str(report.log_path),
                "error": report.error,
            }
        )

    final_document = application.activeDocument
    document_count_stable = application.documents.count == initial_document_count
    active_document_restored = initial_document is None or final_document == initial_document
    cleanup_passed = document_count_stable and active_document_restored
    return {
        "status": "passed"
        if cleanup_passed and all(result["status"] == "passed" for result in results)
        else "failed",
        "host": {
            "platform": platform.system(),
            "machine": platform.machine(),
            "fusionVersion": str(application.version),
        },
        "cleanup": {
            "documentCountStable": document_count_stable,
            "activeDocumentRestored": active_document_restored,
        },
        "scenarios": results,
    }


def _log_to_fusion(message: str) -> None:
    """
    Mirror automated-suite progress into Fusion's application log.

    Args:
        message: Timestamped scenario log line.
    """
    adsk.core.Application.log(
        f"Wire Bundler automated QA: {message}",
        adsk.core.LogLevels.InfoLogLevel,
        adsk.core.LogTypes.FileLogType,
    )
