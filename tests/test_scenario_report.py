"""
Tests for durable live-scenario reporting.
"""

import json
from pathlib import Path

import pytest

from experiments.scenario_report import ScenarioReport


def test_records_successful_steps_and_final_status(tmp_path: Path) -> None:
    """
    Persist incremental text and structured output for a passing scenario.
    """
    messages: list[str] = []
    report = ScenarioReport("example", tmp_path, messages.append)

    with report.step("Create fixture"):
        pass
    report.finish(True)

    payload = json.loads(report.json_path.read_text(encoding="utf-8"))
    assert payload["status"] == "passed"
    assert payload["steps"][0]["name"] == "Create fixture"
    assert payload["steps"][0]["status"] == "passed"
    assert "PASS Create fixture" in report.log_path.read_text(encoding="utf-8")
    assert messages


def test_records_failure_before_reraising(tmp_path: Path) -> None:
    """
    Preserve the failed operation even when the scenario handles the exception later.
    """
    report = ScenarioReport("example", tmp_path)

    with pytest.raises(RuntimeError, match="fixture failed"):
        with report.step("Create fixture"):
            raise RuntimeError("fixture failed")

    payload = json.loads(report.json_path.read_text(encoding="utf-8"))
    assert payload["status"] == "running"
    assert payload["steps"][0]["status"] == "failed"
    assert payload["steps"][0]["detail"] == "fixture failed"
