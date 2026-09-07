"""
Tests for the machine-readable QA automation coverage ledger.
"""

import json
from pathlib import Path

import pytest

from experiments.qa_coverage import LEDGER_PATH, load_coverage_ledger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MCP_CAPABILITIES_PATH = PROJECT_ROOT / "experiments" / "fusion_mcp_capabilities.json"


def test_repository_coverage_ledger_is_valid_and_references_existing_evidence() -> None:
    """
    Keep the checked-in M0 inventory structurally valid and reviewable.
    """
    ledger = load_coverage_ledger()

    assert ledger.milestone == "M0"
    assert set(ledger.required_platforms) == {"macos", "windows"}
    assert len(ledger.targets) >= 15
    assert ledger.counts_by_status()["automated"] >= 5
    for target in ledger.targets:
        for evidence in target.evidence:
            assert (PROJECT_ROOT / evidence).is_file(), f"Missing evidence for {target.target_id}"


def test_rejects_duplicate_target_ids(tmp_path: Path) -> None:
    """
    Prevent multiple acceptance targets from sharing one audit identity.
    """
    payload = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    payload["targets"].append(payload["targets"][0])
    ledger_path = tmp_path / "coverage.json"
    ledger_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="must be unique"):
        load_coverage_ledger(ledger_path)


def test_manual_target_requires_reason_and_review_trigger(tmp_path: Path) -> None:
    """
    Keep residual manual QA explicit and scheduled for reconsideration.
    """
    payload = {
        "schemaVersion": 1,
        "milestone": "M0",
        "requiredPlatforms": ["macos", "windows"],
        "targets": [
            {
                "id": "M0-MANUAL-001",
                "area": "visual",
                "behavior": "Inspect a rendered result.",
                "status": "manual",
                "layers": ["manual"],
                "evidence": [],
                "capabilities": ["render-oracle"],
            }
        ],
    }
    ledger_path = tmp_path / "coverage.json"
    ledger_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="requires a reason and review trigger"):
        load_coverage_ledger(ledger_path)


def test_mcp_capability_snapshot_records_required_automation_surfaces() -> None:
    """
    Preserve the verified MCP inventory that informs the M0 automation plan.
    """
    payload = json.loads(MCP_CAPABILITIES_PATH.read_text(encoding="utf-8"))
    tools = {tool["name"]: tool for tool in payload["tools"]}

    assert payload["transport"] == "streamable-http"
    assert payload["observedHost"]["platform"] == "macos"
    assert "script" in tools["fusion_mcp_execute"]["verifiedCapabilities"]
    assert {"undo", "redo"} <= set(tools["fusion_mcp_update"]["advertisedCapabilities"])
    assert "screenshot" in tools["fusion_mcp_read"]["advertisedCapabilities"]
    history = payload["commandHistoryAudit"]
    assert history["status"] == "passed"
    assert {
        "preview-undo-redo",
        "generate-undo-redo",
        "rebuild-undo-redo",
        "clear-solids-undo-redo",
    } <= set(history["verifiedCapabilities"])
    orchestrated = payload["orchestratedSuiteAudit"]
    assert orchestrated["status"] == "passed"
    assert set(orchestrated["verifiedScenarios"]) == {
        "fusion_capabilities",
        "command_history",
        "sweep_matrix",
        "reference_harness",
        "preview_reload",
    }
