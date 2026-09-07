"""
Tests for the cross-platform local and Fusion QA orchestrator.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments import qa_orchestrator
from experiments.qa_orchestrator import CheckResult, HttpResponse, McpClient


def test_mcp_client_negotiates_uses_and_closes_session() -> None:
    """
    Preserve the Streamable HTTP handshake and session-header lifecycle.
    """
    requests: list[tuple[str, dict[str, str], object]] = []

    def transport(
        _endpoint: str,
        method: str,
        headers: dict[str, str],
        body: bytes | None,
        _timeout_seconds: float,
    ) -> HttpResponse:
        decoded: dict[str, object] | None = None
        if body:
            raw_decoded = json.loads(body)
            if isinstance(raw_decoded, dict):
                decoded = raw_decoded
        requests.append((method, headers, decoded))
        if decoded and decoded.get("method") == "initialize":
            return HttpResponse(
                200,
                {"mcp-session-id": "qa-session"},
                json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {}}}),
            )
        if decoded and decoded.get("method") == "tools/call":
            return HttpResponse(
                200,
                {},
                json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"content": []}}),
            )
        return HttpResponse(202, {}, "")

    client = McpClient("http://127.0.0.1:27182/mcp", 5.0, transport)

    client.initialize()
    result = client.call_tool("fusion_mcp_execute", {"featureType": "script"})
    client.close()

    assert result == {"content": []}
    assert [request[0] for request in requests] == ["POST", "POST", "POST", "DELETE"]
    assert "MCP-Session-Id" not in requests[0][1]
    assert all(request[1].get("MCP-Session-Id") == "qa-session" for request in requests[1:])
    assert client.session_id == ""


def test_extracts_fusion_suite_result_from_execute_envelope() -> None:
    """
    Decode Fusion MCP's nested execute payload and the suite sentinel.
    """
    expected = {"status": "passed", "scenarios": [{"scenario": "history"}]}
    execution = {
        "success": True,
        "message": f"host output\n{qa_orchestrator.FUSION_RESULT_PREFIX}{json.dumps(expected)}\n",
    }
    tool_result = {"content": [{"type": "text", "text": json.dumps(execution)}]}

    assert qa_orchestrator._parse_fusion_tool_result(tool_result) == expected


def test_aggregate_report_returns_failure_for_failed_selected_layer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Return a failing exit code while retaining local and Fusion evidence.
    """
    monkeypatch.setattr(qa_orchestrator, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        qa_orchestrator,
        "_run_local_checks",
        lambda _timeout: [CheckResult("pytest", "failed", 1.0, "failure")],
    )
    monkeypatch.setattr(
        qa_orchestrator,
        "_run_fusion_suite",
        lambda _endpoint, _timeout: {"status": "passed", "scenarios": []},
    )

    exit_code, report_path = qa_orchestrator.run_qa()

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert payload["status"] == "failed"
    assert payload["local"][0]["detail"] == "failure"
    assert payload["fusion"]["status"] == "passed"
    assert payload["coverage"]["requiredPlatforms"] == ["macos", "windows"]


def test_local_only_report_marks_fusion_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Support useful local runs when Fusion or its MCP server is unavailable.
    """
    monkeypatch.setattr(qa_orchestrator, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        qa_orchestrator,
        "_run_local_checks",
        lambda _timeout: [CheckResult("pytest", "passed", 1.0)],
    )

    exit_code, report_path = qa_orchestrator.run_qa(run_fusion=False)

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "passed"
    assert payload["fusion"]["status"] == "skipped"
