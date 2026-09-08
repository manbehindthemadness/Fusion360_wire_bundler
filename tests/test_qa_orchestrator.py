"""
Tests for the cross-platform local and Fusion QA orchestrator.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from experiments import qa_orchestrator
from experiments.png_oracle import ImageDifference
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


def test_desktop_ui_capture_is_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Never invoke permission-requiring desktop capture in the default suite.
    """
    monkeypatch.setattr(qa_orchestrator, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        qa_orchestrator,
        "_run_local_checks",
        lambda _timeout: [CheckResult("pytest", "passed", 1.0)],
    )
    monkeypatch.setattr(
        qa_orchestrator,
        "_run_fusion_suite",
        lambda _endpoint, _timeout: {"status": "passed", "scenarios": []},
    )
    monkeypatch.setattr(
        qa_orchestrator,
        "_run_desktop_ui_oracle",
        lambda _endpoint, _timeout: pytest.fail("desktop capture must remain opt-in"),
    )

    exit_code, report_path = qa_orchestrator.run_qa()

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["selection"]["desktopUi"] is False


def test_desktop_ui_unavailable_does_not_fail_fusion_suite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Preserve live QA when an opted-in host still lacks desktop permission.
    """
    monkeypatch.setattr(qa_orchestrator, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        qa_orchestrator,
        "_run_fusion_suite",
        lambda _endpoint, _timeout: {"status": "passed", "scenarios": []},
    )
    monkeypatch.setattr(
        qa_orchestrator,
        "_run_desktop_ui_oracle",
        lambda _endpoint, _timeout: {"status": "deferred", "reason": "permission"},
    )

    exit_code, report_path = qa_orchestrator.run_qa(
        run_local=False,
        capture_desktop_ui=True,
    )

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["fusion"]["desktopUiOracle"]["status"] == "deferred"


def test_desktop_ui_oracle_compares_two_ephemeral_stable_captures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Turn opted-in exact-window capture into a rendered stability assertion.
    """
    bounds = qa_orchestrator.PaletteBounds(10, 20, 840, 760)
    captures = [SimpleNamespace(png=b"first"), SimpleNamespace(png=b"second")]
    monkeypatch.setattr(qa_orchestrator, "_read_palette_bounds", lambda *_args: bounds)
    monkeypatch.setattr(
        "experiments.qa_orchestrator.capture_harness_builder_window",
        lambda _bounds: captures.pop(0),
    )
    monkeypatch.setattr(
        "experiments.qa_orchestrator.desktop_capture_observation",
        lambda capture: {"bytesObserved": len(capture.png), "purged": True},
    )
    monkeypatch.setattr(
        "experiments.qa_orchestrator.compare_pngs",
        lambda first, second: ImageDifference(0.001, 0.2, 4),
    )

    result = qa_orchestrator._run_desktop_ui_oracle("local", 1.0)

    assert result["status"] == "passed"
    observations = cast(list[dict[str, object]], result["observations"])
    comparison = cast(dict[str, object], result["comparison"])
    assert len(observations) == 2
    assert comparison["palette_bounds_stable"] is True
    assert comparison["changed_pixel_fraction"] == 0.001
    assert result["capturesPurged"] is True


def test_desktop_ui_oracle_fails_when_stable_palette_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Reject visible instability above the bounded desktop comparison tolerance.
    """
    bounds = qa_orchestrator.PaletteBounds(10, 20, 840, 760)
    captures = [SimpleNamespace(png=b"first"), SimpleNamespace(png=b"second")]
    monkeypatch.setattr(qa_orchestrator, "_read_palette_bounds", lambda *_args: bounds)
    monkeypatch.setattr(
        "experiments.qa_orchestrator.capture_harness_builder_window",
        lambda _bounds: captures.pop(0),
    )
    monkeypatch.setattr(
        "experiments.qa_orchestrator.desktop_capture_observation",
        lambda _capture: {"purged": True},
    )
    monkeypatch.setattr(
        "experiments.qa_orchestrator.compare_pngs",
        lambda first, second: ImageDifference(0.03, 1.0, 20),
    )

    result = qa_orchestrator._run_desktop_ui_oracle("local", 1.0)

    assert result["status"] == "failed"
    assert "changed 3.00%" in result["error"]
    assert result["capturesPurged"] is True


def test_desktop_ui_oracle_fails_when_palette_moves_between_captures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Detect the fullscreen Space regression even when window contents remain stable.
    """
    bounds = [
        qa_orchestrator.PaletteBounds(-840, 20, 840, 760),
        qa_orchestrator.PaletteBounds(0, 30, 840, 760),
    ]
    captures = [SimpleNamespace(png=b"first"), SimpleNamespace(png=b"second")]
    monkeypatch.setattr(
        qa_orchestrator,
        "_read_palette_bounds",
        lambda *_args: bounds.pop(0),
    )
    monkeypatch.setattr(
        "experiments.qa_orchestrator.capture_harness_builder_window",
        lambda _bounds: captures.pop(0),
    )
    monkeypatch.setattr(
        "experiments.qa_orchestrator.desktop_capture_observation",
        lambda _capture: {"purged": True},
    )
    monkeypatch.setattr(
        "experiments.qa_orchestrator.compare_pngs",
        lambda first, second: ImageDifference(0.0, 0.0, 0),
    )

    result = qa_orchestrator._run_desktop_ui_oracle("local", 1.0)

    assert result["status"] == "failed"
    comparison = cast(dict[str, object], result["comparison"])
    assert comparison["palette_bounds_stable"] is False
    assert "moved or resized" in result["error"]
    assert result["capturesPurged"] is True


def test_fusion_bootstrap_refreshes_dependencies_before_importing_suite() -> None:
    """
    Prevent Fusion's cached experiment modules from hiding newly added scenario cores.
    """
    script = qa_orchestrator._fusion_suite_script()

    history_reload = script.index("importlib.reload(history_module)")
    preview_import = script.index("import experiments.experiment_preview_reload")
    assembly_import = script.index("import experiments.experiment_assembly_placement")
    linked_geometry_import = script.index("import experiments.experiment_linked_geometry")
    generated_solids_import = script.index("import experiments.experiment_generated_solids")
    suite_import = script.index("import experiments.fusion_qa_suite")

    assert (
        history_reload
        < preview_import
        < assembly_import
        < linked_geometry_import
        < generated_solids_import
        < suite_import
    )


def test_extracts_png_from_mcp_json_text_screenshot_envelope() -> None:
    """
    Decode the screenshot shape advertised by the local Fusion MCP server.
    """
    png = qa_orchestrator.PNG_SIGNATURE + b"fixture"
    screenshot = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "type": "image",
                        "mimeType": "image/png",
                        "base64Data": base64.b64encode(png).decode("ascii"),
                    }
                ),
            }
        ]
    }

    assert qa_orchestrator._extract_screenshot_png(screenshot) == png


def test_visual_phase_script_dispatches_requested_action() -> None:
    """
    Keep the external checkpoint bootstrap small and deterministic.
    """
    script = qa_orchestrator._visual_phase_script("show-preview", reload_module=True)

    assert "module = importlib.reload(module)" in script
    assert 'module.dispatch("show-preview")' in script


def test_generated_visual_phase_script_dispatches_requested_action() -> None:
    """
    Keep the generated-wire checkpoint bootstrap small and deterministic.
    """
    script = qa_orchestrator._generated_visual_phase_script(
        "hide-stripes",
        reload_module=True,
    )

    assert "module = importlib.reload(module)" in script
    assert "import experiments.experiment_generated_visual as module" in script
    assert 'module.dispatch("hide-stripes")' in script


def test_generated_visual_difference_contract_accepts_expected_states() -> None:
    """
    Accept visible presentation changes and stable generated lifecycle comparisons.
    """
    differences = {
        "baselineToStriped": {"changed_pixel_fraction": 0.08},
        "stripedToPlain": {"changed_pixel_fraction": 0.01},
        "stripedIsoToTop": {"changed_pixel_fraction": 0.06},
        "stripedToRebuilt": {"changed_pixel_fraction": 0.0},
        "stripedToMoved": {"changed_pixel_fraction": 0.08},
        "stripedToCleared": {"changed_pixel_fraction": 0.08},
        "stripedToRestored": {"changed_pixel_fraction": 0.01},
    }

    qa_orchestrator._assert_generated_visual_differences(differences)


def test_generated_visual_difference_contract_rejects_missing_stripes() -> None:
    """
    Fail when hiding stripe graphics makes no rendered difference.
    """
    differences = {
        "baselineToStriped": {"changed_pixel_fraction": 0.08},
        "stripedToPlain": {"changed_pixel_fraction": 0.0},
        "stripedIsoToTop": {"changed_pixel_fraction": 0.06},
        "stripedToRebuilt": {"changed_pixel_fraction": 0.0},
        "stripedToMoved": {"changed_pixel_fraction": 0.08},
        "stripedToCleared": {"changed_pixel_fraction": 0.08},
        "stripedToRestored": {"changed_pixel_fraction": 0.0},
    }

    with pytest.raises(RuntimeError, match="stripedToPlain"):
        qa_orchestrator._assert_generated_visual_differences(differences)
