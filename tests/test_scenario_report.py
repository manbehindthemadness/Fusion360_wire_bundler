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


def test_records_structured_observations(tmp_path: Path) -> None:
    """
    Preserve JSON-safe capability observations beside scenario steps.
    """
    report = ScenarioReport("capabilities", tmp_path)

    report.record_observation("fusion.commands", {"available": True, "count": 3})

    payload = json.loads(report.json_path.read_text(encoding="utf-8"))
    assert payload["observations"] == {"fusion.commands": {"available": True, "count": 3}}
    assert "OBSERVE fusion.commands" in report.log_path.read_text(encoding="utf-8")


def test_rejects_invalid_or_duplicate_observations(tmp_path: Path) -> None:
    """
    Reject ambiguous observation names and values before corrupting a report.
    """
    report = ScenarioReport("capabilities", tmp_path)
    report.record_observation("fusion.commands", True)

    with pytest.raises(ValueError, match="already recorded"):
        report.record_observation("fusion.commands", False)
    with pytest.raises(ValueError, match="must not be empty"):
        report.record_observation(" ", True)
    with pytest.raises(TypeError):
        report.record_observation("fusion.invalid", object())
