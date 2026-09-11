"""
Run the cleanup-safe Fusion scenarios used by the external QA orchestrator.
"""

from __future__ import annotations

import platform
import traceback
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Optional

# noinspection PyUnresolvedReferences
import adsk.core

from experiments.experiment_assembly_placement import verify_assembly_placement
from experiments.experiment_command_history import verify_command_history
from experiments.experiment_fusion_capabilities import audit_fusion_capabilities
from experiments.experiment_generated_solids import verify_generated_solids
from experiments.experiment_linked_geometry import verify_linked_geometry
from experiments.experiment_preview_reload import verify_preview_reload
from experiments.experiment_reference_harness import verify_reference_harness
from experiments.experiment_sweep_matrix import verify_sweep_matrix
from experiments.scenario_report import ScenarioReport

ADDIN_ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_ROOT = ADDIN_ROOT / "artifacts" / "verification"
Scenario = Callable[[adsk.core.Application, ScenarioReport], None]
FUSION_SCENARIOS: tuple[tuple[str, Scenario], ...] = (
    ("fusion_capabilities", audit_fusion_capabilities),
    ("command_history", verify_command_history),
    ("sweep_matrix", verify_sweep_matrix),
    ("reference_harness", verify_reference_harness),
    ("preview_reload", verify_preview_reload),
    ("assembly_placement", verify_assembly_placement),
    ("linked_geometry", verify_linked_geometry),
    ("generated_solids", verify_generated_solids),
)
FUSION_SCENARIO_NAMES = tuple(name for name, _scenario in FUSION_SCENARIOS)


def run_automated_fusion_suite(
    application: adsk.core.Application,
    scenario_names: Optional[Sequence[str]] = None,
) -> dict[str, object]:
    """
    Run every cleanup-safe live scenario and return one JSON-safe result.

    The suite catches failures at the scenario boundary so later independent scenarios
    still run and produce evidence. Each scenario core owns its fixture cleanup.
    """
    scenarios_by_name = dict(FUSION_SCENARIOS)
    selected_names = tuple(scenario_names) if scenario_names is not None else FUSION_SCENARIO_NAMES
    unknown_names = tuple(name for name in selected_names if name not in scenarios_by_name)
    if unknown_names:
        raise ValueError(f"Unknown Fusion QA scenarios: {', '.join(unknown_names)}")
    scenarios = tuple((name, scenarios_by_name[name]) for name in selected_names)
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
        "selection": {"scenarios": list(selected_names)},
        "scenarios": results,
    }


def _log_to_fusion(message: str) -> None:
    """
    Mirror automated-suite progress into Fusion's application log.
    """
    adsk.core.Application.log(
        f"Wire Bundler automated QA: {message}",
        adsk.core.LogLevels.InfoLogLevel,
        adsk.core.LogTypes.FileLogType,
    )
