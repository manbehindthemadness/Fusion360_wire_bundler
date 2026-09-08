# =============================================================================
# DEVELOPMENT-ONLY EXTERNAL UI CAPTURE — OPT-IN CALL SITE
#
# OS-level capture is reachable only through the explicit --desktop-ui command-line
# flag. The default end-to-end QA procedure does not invoke it. The capture adapter
# enforces Fusion identity and exact-window ownership for the fixed palette and main
# application frame, never accepts an arbitrary target or rectangle, and purges all
# pixel and handshake files before this orchestrator reports.
# =============================================================================

"""
Orchestrate local checks and cleanup-safe Fusion scenarios into one QA report.
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, perf_counter, sleep
from typing import Optional
from urllib.parse import urlparse
from uuid import uuid4

from experiments.desktop_ui_capture import (
    DesktopCapture,
    DesktopCaptureSafetyError,
    DesktopCaptureUnavailable,
    PaletteBounds,
    capture_fusion_main_window,
    capture_harness_builder_window,
    desktop_capture_observation,
)
from experiments.png_oracle import PNG_SIGNATURE, compare_pngs
from experiments.qa_coverage import load_coverage_ledger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "verification"
DEFAULT_MCP_URL = "http://127.0.0.1:27182/mcp"
MAXIMUM_STABLE_DESKTOP_CHANGE = 0.02
MCP_PROTOCOL_VERSION = "2025-03-26"
FUSION_RESULT_PREFIX = "WIRE_BUNDLER_QA_RESULT="
VISUAL_RESULT_PREFIX = "WIRE_BUNDLER_VISUAL_RESULT="
GENERATED_VISUAL_RESULT_PREFIX = "WIRE_BUNDLER_GENERATED_VISUAL_RESULT="
PALETTE_BOUNDS_RESULT_PREFIX = "WIRE_BUNDLER_PALETTE_BOUNDS_RESULT="
NATIVE_DIALOG_RESULT_PREFIX = "WIRE_BUNDLER_NATIVE_DIALOG_RESULT="
NATIVE_DIALOG_HANDSHAKE_ROOT = PROJECT_ROOT / "artifacts" / "native_dialog_handshake"
MINIMUM_NATIVE_DIALOG_CHANGE = 0.00001
VISUAL_WIDTH = 640
VISUAL_HEIGHT = 480
LOCAL_CHECK_NAMES = ("pytest", "palette", "ruff-lint", "ruff-format", "diff-check")
FUSION_SCENARIO_NAMES = (
    "fusion_capabilities",
    "command_history",
    "sweep_matrix",
    "reference_harness",
    "preview_reload",
    "assembly_placement",
    "linked_geometry",
    "generated_solids",
)


@dataclass(frozen=True)
class CheckResult:
    """
    Describe one local or live QA operation.

    Args:
        name: Stable operation identifier.
        status: Passed, failed, skipped, or deferred.
        elapsed_ms: Wall-clock operation duration.
        detail: Concise diagnostic or output tail.
    """

    name: str
    status: str
    elapsed_ms: float
    detail: str = ""


@dataclass(frozen=True)
class HttpResponse:
    """
    Retain the relevant result of one MCP HTTP request.

    Args:
        status: HTTP response status.
        headers: Case-normalized response headers.
        body: Decoded response body.
    """

    status: int
    headers: dict[str, str]
    body: str


Transport = Callable[[str, str, dict[str, str], Optional[bytes], float], HttpResponse]


class McpClient:
    """
    Minimal Streamable HTTP MCP client for the local Fusion development server.
    """

    def __init__(
        self,
        endpoint: str,
        timeout_seconds: float,
        transport: Optional[Transport] = None,
    ) -> None:
        """
        Configure the endpoint and injectable HTTP transport.

        Args:
            endpoint: Streamable HTTP MCP endpoint.
            timeout_seconds: Timeout for each MCP request.
            transport: Optional transport used by unit tests.
        """
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.transport = transport or _http_request
        self.session_id = ""
        self._next_id = 1

    def initialize(self) -> dict[str, object]:
        """
        Negotiate an MCP session and send the initialized notification.

        Returns:
            MCP initialize result.
        """
        response = self._request(
            "POST",
            {
                "jsonrpc": "2.0",
                "id": self._allocate_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "wire-bundler-qa", "version": "0.1.0"},
                },
                "session": False,
            },
        )
        self.session_id = response.headers.get("mcp-session-id", "")
        if not self.session_id:
            raise RuntimeError("Fusion MCP initialize response omitted MCP-Session-Id.")
        payload = _decode_json_response(response)
        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"Fusion MCP initialize failed: {payload!r}")
        self._request(
            "POST",
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
                "session": True,
            },
            allow_empty=True,
        )
        return result

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        """
        Invoke one MCP tool in the initialized session.

        Args:
            name: Advertised MCP tool name.
            arguments: Tool arguments matching its input schema.

        Returns:
            Tool call result object.
        """
        if not self.session_id:
            raise RuntimeError("Fusion MCP client is not initialized.")
        response = self._request(
            "POST",
            {
                "jsonrpc": "2.0",
                "id": self._allocate_id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
                "session": True,
            },
        )
        payload = _decode_json_response(response)
        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"Fusion MCP tool call failed: {payload!r}")
        return result

    def close(self) -> None:
        """
        Delete the current MCP session when one was established.
        """
        if not self.session_id:
            return
        try:
            self._request("DELETE", None, allow_empty=True)
        finally:
            self.session_id = ""

    def _request(
        self,
        method: str,
        payload: Optional[dict[str, object]],
        allow_empty: bool = False,
    ) -> HttpResponse:
        """
        Send one JSON request with the active MCP session header.
        """
        request_payload = dict(payload) if payload is not None else None
        use_session = bool(request_payload and request_payload.pop("session", False))
        headers = {"Accept": "application/json, text/event-stream"}
        body = None
        if request_payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(request_payload).encode("utf-8")
        if use_session or method == "DELETE":
            headers["MCP-Session-Id"] = self.session_id
        response = self.transport(
            self.endpoint,
            method,
            headers,
            body,
            self.timeout_seconds,
        )
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(
                f"Fusion MCP returned HTTP {response.status}: {response.body.strip()}"
            )
        if not allow_empty and not response.body.strip():
            raise RuntimeError("Fusion MCP returned an empty response.")
        return response

    def _allocate_id(self) -> int:
        """
        Return the next JSON-RPC request identity.
        """
        request_id = self._next_id
        self._next_id += 1
        return request_id


def run_qa(
    run_local: bool = True,
    run_fusion: bool = True,
    mcp_url: str = DEFAULT_MCP_URL,
    command_timeout_seconds: float = 180.0,
    fusion_timeout_seconds: float = 600.0,
    capture_desktop_ui: bool = False,
    local_checks: Optional[Sequence[str]] = None,
    fusion_scenarios: Optional[Sequence[str]] = None,
) -> tuple[int, Path]:
    """
    Run the selected QA layers and write one aggregate report.

    Args:
        run_local: Execute pytest, palette, Ruff, formatting, and diff checks.
        run_fusion: Execute the cleanup-safe in-host Fusion suite through MCP.
        mcp_url: Local Fusion MCP endpoint.
        command_timeout_seconds: Timeout for each local subprocess.
        fusion_timeout_seconds: Timeout for each MCP request.
        capture_desktop_ui: Opt into permission-requiring Fusion-window capture.
        local_checks: Optional ordered subset of local check names.
        fusion_scenarios: Optional ordered subset of structural Fusion scenarios.

    Returns:
        Process exit code and aggregate JSON report path.
    """
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc)
    local_results = (
        _run_local_checks(command_timeout_seconds, local_checks)
        if run_local
        else [CheckResult("local", "skipped", 0.0, "Disabled by command option.")]
    )
    fusion_result: dict[str, object]
    if run_fusion:
        fusion_result = _run_fusion_suite(mcp_url, fusion_timeout_seconds, fusion_scenarios)
        if capture_desktop_ui:
            desktop_result = _run_desktop_ui_oracle(mcp_url, fusion_timeout_seconds)
            fusion_result["desktopUiOracle"] = desktop_result
            if desktop_result.get("status") == "failed":
                fusion_result["status"] = "failed"
            elif desktop_result.get("status") == "passed":
                native_result = _run_native_dialog_ui_oracle(
                    mcp_url,
                    fusion_timeout_seconds,
                )
                fusion_result["nativeDialogUiOracle"] = native_result
                if native_result.get("status") == "failed":
                    fusion_result["status"] = "failed"
    else:
        fusion_result = {"status": "skipped", "detail": "Disabled by command option."}

    ledger = load_coverage_ledger()
    local_passed = all(result.status in {"passed", "skipped"} for result in local_results)
    fusion_passed = fusion_result.get("status") in {"passed", "skipped"}
    status = "passed" if local_passed and fusion_passed else "failed"
    finished_at = datetime.now(timezone.utc)
    payload = {
        "schemaVersion": 1,
        "status": status,
        "startedAt": started_at.isoformat(),
        "finishedAt": finished_at.isoformat(),
        "host": {"platform": platform.system(), "machine": platform.machine()},
        "selection": {
            "local": run_local,
            "fusion": run_fusion,
            "desktopUi": capture_desktop_ui,
            "localChecks": list(local_checks) if local_checks is not None else None,
            "fusionScenarios": list(fusion_scenarios) if fusion_scenarios is not None else None,
        },
        "local": [asdict(result) for result in local_results],
        "fusion": fusion_result,
        "coverage": {
            "milestone": ledger.milestone,
            "requiredPlatforms": list(ledger.required_platforms),
            "counts": ledger.counts_by_status(),
            "manualOrDeferred": [
                {
                    "id": target.target_id,
                    "status": target.status,
                    "reason": target.manual_reason,
                    "reviewTrigger": target.review_trigger,
                }
                for target in ledger.targets
                if target.status == "manual"
            ],
        },
    }
    timestamp = started_at.strftime("%Y%m%dT%H%M%S.%fZ")
    report_path = ARTIFACT_ROOT / f"qa_suite_{timestamp}.json"
    report_path.write_text(f"{json.dumps(payload, indent=2, sort_keys=True)}\n", encoding="utf-8")
    return (0 if status == "passed" else 1), report_path


def main(arguments: Optional[Sequence[str]] = None) -> int:
    """
    Parse command-line options, run QA, and print the final report location.

    Args:
        arguments: Optional argument sequence for tests; defaults to ``sys.argv``.

    Returns:
        Zero only when every selected automated layer passes.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--local-only", action="store_true", help="Skip live Fusion checks.")
    mode.add_argument("--fusion-only", action="store_true", help="Skip local checks.")
    parser.add_argument("--mcp-url", default=DEFAULT_MCP_URL)
    parser.add_argument("--command-timeout", type=float, default=180.0)
    parser.add_argument("--fusion-timeout", type=float, default=600.0)
    parser.add_argument(
        "--local-check",
        action="append",
        choices=LOCAL_CHECK_NAMES,
        dest="local_checks",
        help="Run only this local check; repeat to select more than one.",
    )
    parser.add_argument(
        "--fusion-scenario",
        action="append",
        choices=FUSION_SCENARIO_NAMES,
        dest="fusion_scenarios",
        help=(
            "Run only this structural Fusion scenario and skip viewport visual oracles; "
            "repeat to select more than one."
        ),
    )
    parser.add_argument(
        "--desktop-ui",
        action="store_true",
        help=(
            "Opt into Fusion-only desktop window capture; requires development-mode "
            "Screen Recording permission."
        ),
    )
    options = parser.parse_args(arguments)
    if options.local_only and options.desktop_ui:
        parser.error("--desktop-ui requires the live Fusion layer.")
    if options.fusion_only and options.local_checks:
        parser.error("--local-check cannot be used with --fusion-only.")
    if options.local_only and options.fusion_scenarios:
        parser.error("--fusion-scenario cannot be used with --local-only.")
    exit_code, report_path = run_qa(
        run_local=not options.fusion_only,
        run_fusion=not options.local_only,
        mcp_url=options.mcp_url,
        command_timeout_seconds=options.command_timeout,
        fusion_timeout_seconds=options.fusion_timeout,
        capture_desktop_ui=options.desktop_ui,
        local_checks=options.local_checks,
        fusion_scenarios=options.fusion_scenarios,
    )
    print(f"Wire Bundler QA: {'PASS' if exit_code == 0 else 'FAIL'}")
    print(f"Report: {report_path}")
    return exit_code


def _run_local_checks(
    timeout_seconds: float,
    selected_checks: Optional[Sequence[str]] = None,
) -> list[CheckResult]:
    """
    Execute every host-independent repository check.
    """
    commands = (
        ("pytest", (sys.executable, "-m", "pytest", "-q")),
        ("palette", ("node", "tests/test_palette.cjs")),
        (
            "ruff-lint",
            (
                sys.executable,
                "-m",
                "ruff",
                "check",
                "Fusion360_wire_bundler.py",
                "wire_bundler",
                "tests",
                "experiments",
            ),
        ),
        (
            "ruff-format",
            (
                sys.executable,
                "-m",
                "ruff",
                "format",
                "--check",
                "Fusion360_wire_bundler.py",
                "wire_bundler",
                "tests",
                "experiments",
            ),
        ),
        ("diff-check", ("git", "diff", "--check")),
    )
    commands_by_name = dict(commands)
    selected_names = tuple(selected_checks) if selected_checks is not None else LOCAL_CHECK_NAMES
    unknown_names = tuple(name for name in selected_names if name not in commands_by_name)
    if unknown_names:
        raise ValueError(f"Unknown local QA checks: {', '.join(unknown_names)}")
    return [_run_command(name, commands_by_name[name], timeout_seconds) for name in selected_names]


def _run_command(name: str, command: Sequence[str], timeout_seconds: float) -> CheckResult:
    """
    Run one local command and retain a bounded output tail.
    """
    started = perf_counter()
    try:
        completed = subprocess.run(
            tuple(command),
            cwd=PROJECT_ROOT,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_seconds,
        )
        status = "passed" if completed.returncode == 0 else "failed"
        detail = completed.stdout[-8000:].strip()
    except FileNotFoundError as error:
        status = "failed"
        detail = str(error)
    except subprocess.TimeoutExpired as error:
        status = "failed"
        output = error.stdout or ""
        detail = f"Timed out after {timeout_seconds:.1f} seconds.\n{output}"[-8000:].strip()
    elapsed_ms = (perf_counter() - started) * 1000
    print(f"[{status.upper():7}] {name} ({elapsed_ms:.0f} ms)")
    return CheckResult(name, status, elapsed_ms, detail)


def _run_fusion_suite(
    endpoint: str,
    timeout_seconds: float,
    selected_scenarios: Optional[Sequence[str]] = None,
) -> dict[str, object]:
    """
    Execute the in-host suite through one temporary MCP session.
    """
    started = perf_counter()
    client = McpClient(endpoint, timeout_seconds)
    suite_result: dict[str, object] = {"status": "failed"}
    try:
        server = client.initialize()
        tool_result = client.call_tool(
            "fusion_mcp_execute",
            {
                "featureType": "script",
                "object": {"script": _fusion_suite_script(selected_scenarios)},
            },
        )
        suite_result = _parse_fusion_tool_result(tool_result)
        suite_result["server"] = server
        if selected_scenarios is None:
            visual_result = _run_preview_visual_oracle(client)
            suite_result["visualOracle"] = visual_result
            if visual_result.get("status") != "passed":
                suite_result["status"] = "failed"
            generated_visual_result = _run_generated_visual_oracle(client)
            suite_result["generatedVisualOracle"] = generated_visual_result
            if generated_visual_result.get("status") != "passed":
                suite_result["status"] = "failed"
        else:
            skipped = {
                "status": "skipped",
                "detail": "Focused structural Fusion scenario selection.",
            }
            suite_result["visualOracle"] = skipped
            suite_result["generatedVisualOracle"] = skipped
    except (ConnectionError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        suite_result = {"status": "failed", "error": str(error)}
    finally:
        try:
            client.close()
        except (ConnectionError, OSError, RuntimeError):
            pass
    elapsed_ms = (perf_counter() - started) * 1000
    suite_result["elapsed_ms"] = elapsed_ms
    raw_status = suite_result.get("status", "failed")
    display_status = raw_status.upper() if isinstance(raw_status, str) else "FAILED"
    print(f"[{display_status:7}] fusion ({elapsed_ms:.0f} ms)")
    return suite_result


def _run_desktop_ui_oracle(endpoint: str, timeout_seconds: float) -> dict[str, object]:
    """
    Compare two verified captures of the stable Fusion palette when explicitly requested.

    Returns:
        Passed metadata, a non-failing unavailable result, or a safety failure.
    """
    try:
        first_bounds = _read_palette_bounds(endpoint, timeout_seconds)
        first_capture = capture_harness_builder_window(first_bounds)
        second_bounds = _read_palette_bounds(endpoint, timeout_seconds)
        second_capture = capture_harness_builder_window(second_bounds)
        observations = [
            desktop_capture_observation(first_capture),
            desktop_capture_observation(second_capture),
        ]
    except DesktopCaptureSafetyError as error:
        return {"status": "failed", "error": str(error), "capturesPurged": True}
    except (
        ConnectionError,
        DesktopCaptureUnavailable,
        OSError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        return {"status": "deferred", "reason": str(error), "capturesPurged": True}
    try:
        difference = asdict(compare_pngs(first_capture.png, second_capture.png))
    except ValueError as error:
        return {"status": "failed", "error": str(error), "capturesPurged": True}
    changed_fraction = float(difference["changed_pixel_fraction"])
    palette_bounds_stable = first_bounds == second_bounds
    comparison = {
        **difference,
        "maximum_changed_pixel_fraction": MAXIMUM_STABLE_DESKTOP_CHANGE,
        "palette_bounds_stable": palette_bounds_stable,
    }
    result = {
        "status": "passed",
        "observations": observations,
        "comparison": comparison,
        "capturesPurged": True,
    }
    if not palette_bounds_stable:
        result["status"] = "failed"
        result["error"] = "Stable desktop palette moved or resized between captures."
    elif changed_fraction > MAXIMUM_STABLE_DESKTOP_CHANGE:
        result["status"] = "failed"
        result["error"] = (
            f"Stable desktop palette changed {changed_fraction:.2%}; maximum is "
            f"{MAXIMUM_STABLE_DESKTOP_CHANGE:.2%}."
        )
    return result


def _run_native_dialog_ui_oracle(
    endpoint: str,
    timeout_seconds: float,
) -> dict[str, object]:
    """
    Compare Fusion's main window before and during one safely bounded native dialog.

    The external capture worker and Fusion coordinate through two private, token-scoped
    acknowledgements while a single MCP request owns the command from open through
    termination.
    """
    token = uuid4().hex
    handshake_directory = NATIVE_DIALOG_HANDSHAKE_ROOT / token
    handshake_directory.mkdir(parents=True)
    os.chmod(handshake_directory, 0o700)
    captures: list[DesktopCapture] = []
    worker_errors: list[BaseException] = []
    stop_requested = threading.Event()
    worker = threading.Thread(
        target=_capture_native_dialog_phases,
        args=(handshake_directory, token, captures, worker_errors, stop_requested),
        name="wire-bundler-native-dialog-capture",
        daemon=True,
    )
    client = McpClient(endpoint, timeout_seconds)
    host_result: dict[str, object] = {}
    host_error: Optional[BaseException] = None
    try:
        client.initialize()
        worker.start()
        tool_result = client.call_tool(
            "fusion_mcp_execute",
            {
                "featureType": "script",
                "object": {"script": _native_dialog_capture_script(token)},
            },
        )
        host_result = _parse_execute_result(tool_result, NATIVE_DIALOG_RESULT_PREFIX)
    except (
        ConnectionError,
        OSError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        host_error = error
    finally:
        try:
            client.close()
        except (ConnectionError, OSError, RuntimeError):
            pass
        if worker.ident is not None:
            worker.join(timeout=32.0)
        if worker.is_alive():
            stop_requested.set()
            worker.join(timeout=3.0)
        shutil.rmtree(handshake_directory, ignore_errors=True)

    if worker.is_alive():
        return {
            "status": "failed",
            "error": "Native-dialog capture worker did not terminate.",
            "capturesPurged": True,
        }
    if worker_errors:
        error = worker_errors[0]
        status = "failed" if isinstance(error, DesktopCaptureSafetyError) else "deferred"
        key = "error" if status == "failed" else "reason"
        return {"status": status, key: str(error), "capturesPurged": True}
    if host_error is not None:
        return {"status": "failed", "error": str(host_error), "capturesPurged": True}
    if len(captures) != 2:
        return {
            "status": "failed",
            "error": f"Expected two native-dialog captures, received {len(captures)}.",
            "capturesPurged": True,
        }
    baseline = captures[0]
    dialog = captures[1]
    try:
        difference = asdict(compare_pngs(baseline.png, dialog.png))
    except (AttributeError, ValueError) as error:
        return {"status": "failed", "error": str(error), "capturesPurged": True}
    window_stable = _same_desktop_window(baseline.window, dialog.window)
    changed_fraction = float(difference["changed_pixel_fraction"])
    result = {
        "status": "passed",
        "host": host_result,
        "observations": [
            desktop_capture_observation(baseline),
            desktop_capture_observation(dialog),
        ],
        "comparison": {
            **difference,
            "minimum_changed_pixel_fraction": MINIMUM_NATIVE_DIALOG_CHANGE,
            "window_stable": window_stable,
        },
        "capturesPurged": True,
    }
    if host_result.get("terminated") is not True or host_result.get("documentRestored") is not True:
        result["status"] = "failed"
        result["error"] = "Fusion did not confirm native-command and document cleanup."
    elif not window_stable:
        result["status"] = "failed"
        result["error"] = "Fusion's main window moved, resized, or changed identity during capture."
    elif changed_fraction < MINIMUM_NATIVE_DIALOG_CHANGE:
        result["status"] = "failed"
        result["error"] = (
            f"Native dialog changed only {changed_fraction:.4%} of pixels; minimum is "
            f"{MINIMUM_NATIVE_DIALOG_CHANGE:.4%}."
        )
    return result


def _capture_native_dialog_phases(
    directory: Path,
    token: str,
    captures: list[DesktopCapture],
    errors: list[BaseException],
    stop_requested: threading.Event,
) -> None:
    """
    Capture the fixed Fusion main window at both in-host handshake checkpoints.
    """
    for phase in ("baseline", "dialog"):
        try:
            _wait_for_capture_phase(
                directory / f"{phase}-ready.json",
                token,
                phase,
                stop_requested,
            )
            capture = capture_fusion_main_window()
            captures.append(capture)
            _write_capture_ack(directory, token, phase, "captured")
        except (
            DesktopCaptureSafetyError,
            DesktopCaptureUnavailable,
            OSError,
            RuntimeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            errors.append(error)
            _write_capture_ack(directory, token, phase, "error", str(error))
            return


def _wait_for_capture_phase(
    path: Path,
    token: str,
    phase: str,
    stop_requested: threading.Event,
) -> None:
    """
    Wait for one exact token and phase announcement from the in-host script.
    """
    deadline = monotonic() + 35.0
    while monotonic() < deadline:
        if stop_requested.is_set():
            raise RuntimeError(f"Native-dialog {phase} capture was cancelled.")
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            expected_phase = f"{phase}-ready"
            if (
                not isinstance(payload, dict)
                or payload.get("token") != token
                or payload.get("phase") != expected_phase
            ):
                raise RuntimeError(f"Invalid native-dialog {phase} checkpoint.")
            return
        sleep(0.01)
    raise RuntimeError(f"Timed out waiting for native-dialog {phase} checkpoint.")


def _write_capture_ack(
    directory: Path,
    token: str,
    phase: str,
    status: str,
    error: str = "",
) -> None:
    """
    Atomically acknowledge one capture so Fusion can continue or clean up.
    """
    destination = directory / f"{phase}-ack.json"
    temporary = directory / f".{phase}-ack.tmp"
    payload = {"token": token, "phase": phase, "status": status}
    if error:
        payload["error"] = error
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(destination)


def _same_desktop_window(first: object, second: object) -> bool:
    """
    Require stable identity, ownership, and bounds across both main-window captures.
    """
    fields = ("window_id", "owner_pid", "owner_name", "x", "y", "width", "height")
    return all(getattr(first, field, None) == getattr(second, field, None) for field in fields)


def _read_palette_bounds(endpoint: str, timeout_seconds: float) -> PaletteBounds:
    """
    Read the fixed Harness Builder palette geometry through Fusion's API.

    Args:
        endpoint: Local Fusion MCP endpoint.
        timeout_seconds: Timeout for each MCP operation.

    Returns:
        Validated visible palette bounds used only to select a Fusion-owned window.
    """
    client = McpClient(endpoint, timeout_seconds)
    payload: dict[str, object] = {}
    try:
        client.initialize()
        tool_result = client.call_tool(
            "fusion_mcp_execute",
            {"featureType": "script", "object": {"script": _palette_bounds_script()}},
        )
        payload = _parse_execute_result(tool_result, PALETTE_BOUNDS_RESULT_PREFIX)
    finally:
        try:
            client.close()
        except (ConnectionError, OSError, RuntimeError):
            pass
    if (
        payload.get("id") != "kev0_wire_bundler_harness_builder_palette"
        or payload.get("name") != "Harness Builder"
    ):
        raise DesktopCaptureSafetyError("Fusion returned an unexpected palette identity.")
    if payload.get("valid") is not True or payload.get("visible") is not True:
        raise DesktopCaptureUnavailable("Harness Builder is not a valid visible Fusion palette.")
    left = _finite_number(payload.get("left"), "left")
    top = _finite_number(payload.get("top"), "top")
    width = _finite_number(payload.get("width"), "width")
    height = _finite_number(payload.get("height"), "height")
    if width <= 0 or height <= 0:
        raise DesktopCaptureUnavailable("Harness Builder reported invalid palette dimensions.")
    return PaletteBounds(left, top, width, height)


def _palette_bounds_script() -> str:
    """
    Build a fixed in-host query for the Harness Builder palette only.
    """
    return f'''import json

import adsk.core


def run(_context: str):
    application = adsk.core.Application.get()
    palette = application.userInterface.palettes.itemById(
        "kev0_wire_bundler_harness_builder_palette"
    )
    if palette is None:
        raise RuntimeError("Harness Builder palette is not registered.")
    result = {{
        "id": palette.id,
        "name": palette.name,
        "valid": palette.isValid,
        "visible": palette.isVisible,
        "left": palette.left,
        "top": palette.top,
        "width": palette.width,
        "height": palette.height,
    }}
    print("{PALETTE_BOUNDS_RESULT_PREFIX}" + json.dumps(result, sort_keys=True))
'''


def _finite_number(value: object, label: str) -> float:
    """
    Validate one numeric Palette API coordinate or dimension.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DesktopCaptureUnavailable(f"Harness Builder {label} is not numeric.")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise DesktopCaptureUnavailable(f"Harness Builder {label} is not finite.")
    return parsed


def _run_preview_visual_oracle(client: McpClient) -> dict[str, object]:
    """
    Advance the preview lifecycle around normalized MCP screenshots.

    Args:
        client: Initialized MCP client shared with the structural Fusion suite.

    Returns:
        JSON-safe comparison metrics, phase state, and status.
    """
    images: dict[str, bytes] = {}
    phases: list[dict[str, object]] = []
    differences: dict[str, dict[str, object]] = {}
    error = ""
    try:
        phases.append(_call_visual_phase(client, "begin", reload_module=True))
        images["baseline"] = _capture_normalized_viewport(client, phases)
        phases.append(_call_visual_phase(client, "show-preview"))
        images["preview"] = _capture_normalized_viewport(client, phases)
        phases.append(_call_visual_phase(client, "save-reload"))
        images["reloaded"] = _capture_normalized_viewport(client, phases)
        phases.append(_call_visual_phase(client, "show-fresh"))
        images["freshPreview"] = _capture_normalized_viewport(client, phases)
        phases.append(_call_visual_phase(client, "clear"))
        images["cleared"] = _capture_normalized_viewport(client, phases)

        differences = {
            "baselineToPreview": asdict(compare_pngs(images["baseline"], images["preview"])),
            "baselineToReloaded": asdict(compare_pngs(images["baseline"], images["reloaded"])),
            "previewToFreshPreview": asdict(
                compare_pngs(images["preview"], images["freshPreview"])
            ),
            "baselineToCleared": asdict(compare_pngs(images["baseline"], images["cleared"])),
        }
        _assert_visual_differences(differences)
        status = "passed"
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as failure:
        status = "failed"
        error = str(failure)
    finally:
        try:
            cleanup = _call_visual_phase(client, "cleanup")
        except (RuntimeError, ValueError, json.JSONDecodeError) as failure:
            cleanup = {"clean": False, "error": str(failure)}
            status = "failed"
            error = f"{error} Cleanup failed: {failure}".strip()
    return {
        "status": status,
        "dimensions": {"width": VISUAL_WIDTH, "height": VISUAL_HEIGHT},
        "camera": "iso-top-right",
        "captures": {"count": len(images), "storage": "memory-only", "purged": True},
        "differences": differences,
        "phases": phases,
        "cleanup": cleanup,
        "error": error,
    }


def _run_generated_visual_oracle(client: McpClient) -> dict[str, object]:
    """
    Compare striped-wire presentation across visibility, viewpoint, and lifecycle phases.

    Args:
        client: Initialized MCP client shared with the structural Fusion suite.

    Returns:
        JSON-safe comparison metrics, phase state, and status.
    """
    images: dict[str, bytes] = {}
    phases: list[dict[str, object]] = []
    differences: dict[str, dict[str, object]] = {}
    error = ""
    try:
        phases.append(_call_generated_visual_phase(client, "begin", reload_module=True))
        images["baseline"] = _capture_generated_viewport(client, phases, "iso-top-right")
        phases.append(_call_generated_visual_phase(client, "generate"))
        images["stripedIso"] = _capture_generated_viewport(client, phases, "iso-top-right")
        phases.append(_call_generated_visual_phase(client, "hide-stripes"))
        images["plainIso"] = _capture_generated_viewport(client, phases, "iso-top-right")
        phases.append(_call_generated_visual_phase(client, "show-stripes"))
        images["stripedTop"] = _capture_generated_viewport(client, phases, "top")
        phases.append(_call_generated_visual_phase(client, "rebuild"))
        images["rebuiltIso"] = _capture_generated_viewport(client, phases, "iso-top-right")
        phases.append(_call_generated_visual_phase(client, "move"))
        images["movedIso"] = _capture_generated_viewport(client, phases, "iso-top-right")
        phases.append(_call_generated_visual_phase(client, "reset-position"))
        images["restoredIso"] = _capture_generated_viewport(client, phases, "iso-top-right")
        phases.append(_call_generated_visual_phase(client, "clear"))
        images["cleared"] = _capture_generated_viewport(client, phases, "iso-top-right")

        differences = {
            "baselineToStriped": asdict(compare_pngs(images["baseline"], images["stripedIso"])),
            "stripedToPlain": asdict(compare_pngs(images["stripedIso"], images["plainIso"])),
            "stripedIsoToTop": asdict(compare_pngs(images["stripedIso"], images["stripedTop"])),
            "stripedToRebuilt": asdict(compare_pngs(images["stripedIso"], images["rebuiltIso"])),
            "stripedToMoved": asdict(compare_pngs(images["stripedIso"], images["movedIso"])),
            "stripedToRestored": asdict(compare_pngs(images["stripedIso"], images["restoredIso"])),
            "stripedToCleared": asdict(compare_pngs(images["stripedIso"], images["cleared"])),
        }
        _assert_generated_visual_differences(differences)
        status = "passed"
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as failure:
        status = "failed"
        error = str(failure)
    finally:
        try:
            cleanup = _call_generated_visual_phase(client, "cleanup")
        except (RuntimeError, ValueError, json.JSONDecodeError) as failure:
            cleanup = {"clean": False, "error": str(failure)}
            status = "failed"
            error = f"{error} Cleanup failed: {failure}".strip()
    return {
        "status": status,
        "dimensions": {"width": VISUAL_WIDTH, "height": VISUAL_HEIGHT},
        "cameras": ["iso-top-right", "top"],
        "captures": {"count": len(images), "storage": "memory-only", "purged": True},
        "differences": differences,
        "phases": phases,
        "cleanup": cleanup,
        "error": error,
    }


def _capture_generated_viewport(
    client: McpClient,
    phases: list[dict[str, object]],
    direction: str,
) -> bytes:
    """
    Establish a requested camera, fit the generated fixture, and capture its viewport.
    """
    screenshot_arguments: dict[str, object] = {
        "queryType": "screenshot",
        "width": VISUAL_WIDTH,
        "height": VISUAL_HEIGHT,
        "antiAliasing": True,
        "transparentBackground": False,
    }
    phases.append(_call_generated_visual_phase(client, "normalize"))
    tool_result = client.call_tool(
        "fusion_mcp_read",
        {**screenshot_arguments, "direction": direction},
    )
    return _extract_screenshot_png(tool_result)


def _call_generated_visual_phase(
    client: McpClient,
    action: str,
    reload_module: bool = False,
) -> dict[str, object]:
    """
    Execute one generated-wire visual fixture phase inside Fusion.
    """
    tool_result = client.call_tool(
        "fusion_mcp_execute",
        {
            "featureType": "script",
            "object": {"script": _generated_visual_phase_script(action, reload_module)},
        },
    )
    return _parse_execute_result(tool_result, GENERATED_VISUAL_RESULT_PREFIX)


def _generated_visual_phase_script(action: str, reload_module: bool = False) -> str:
    """
    Build the in-host bootstrap for one generated-wire visual fixture phase.
    """
    root = json.dumps(str(PROJECT_ROOT))
    encoded_action = json.dumps(action)
    reload_statement = "module = importlib.reload(module)" if reload_module else ""
    return f'''import importlib
import json
import sys


def run(_context: str):
    root = {root}
    if root not in sys.path:
        sys.path.insert(0, root)
    import experiments.experiment_generated_visual as module

    {reload_statement}
    result = module.dispatch({encoded_action})
    print("{GENERATED_VISUAL_RESULT_PREFIX}" + json.dumps(result, sort_keys=True))
'''


def _assert_generated_visual_differences(
    differences: dict[str, dict[str, object]],
) -> None:
    """
    Enforce visible stripes/view changes and stable regenerated or cleared states.
    """
    minimum_visible_change = 0.0001
    maximum_stable_change = 0.02
    for name in (
        "baselineToStriped",
        "stripedToPlain",
        "stripedIsoToTop",
        "stripedToMoved",
        "stripedToCleared",
    ):
        changed = _difference_fraction(differences, name)
        if changed < minimum_visible_change:
            raise RuntimeError(f"Generated visual comparison {name} changed only {changed:.6f}.")
    for name in ("stripedToRebuilt", "stripedToRestored"):
        changed = _difference_fraction(differences, name)
        if changed > maximum_stable_change:
            raise RuntimeError(
                f"Generated visual comparison {name} changed {changed:.2%}; "
                f"maximum is {maximum_stable_change:.2%}."
            )


def _difference_fraction(
    differences: dict[str, dict[str, object]],
    name: str,
) -> float:
    """
    Validate and return one changed-pixel fraction from a comparison mapping.
    """
    value = differences[name].get("changed_pixel_fraction")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"Visual comparison {name} has no numeric changed-pixel fraction.")
    fraction = float(value)
    if not math.isfinite(fraction):
        raise RuntimeError(f"Visual comparison {name} has a non-finite changed-pixel fraction.")
    return fraction


def _capture_normalized_viewport(
    client: McpClient,
    phases: list[dict[str, object]],
) -> bytes:
    """
    Establish a standard camera, fit the model, and capture the active viewport.
    """
    screenshot_arguments: dict[str, object] = {
        "queryType": "screenshot",
        "width": VISUAL_WIDTH,
        "height": VISUAL_HEIGHT,
        "antiAliasing": True,
        "transparentBackground": False,
    }
    phases.append(_call_visual_phase(client, "normalize"))
    tool_result = client.call_tool(
        "fusion_mcp_read",
        {**screenshot_arguments, "direction": "iso-top-right"},
    )
    return _extract_screenshot_png(tool_result)


def _call_visual_phase(
    client: McpClient,
    action: str,
    reload_module: bool = False,
) -> dict[str, object]:
    """
    Execute one visual-fixture phase inside Fusion.
    """
    tool_result = client.call_tool(
        "fusion_mcp_execute",
        {
            "featureType": "script",
            "object": {"script": _visual_phase_script(action, reload_module)},
        },
    )
    return _parse_execute_result(tool_result, VISUAL_RESULT_PREFIX)


def _visual_phase_script(action: str, reload_module: bool = False) -> str:
    """
    Build the in-host bootstrap for one visual-fixture phase.
    """
    root = json.dumps(str(PROJECT_ROOT))
    encoded_action = json.dumps(action)
    reload_statement = "module = importlib.reload(module)" if reload_module else ""
    return f'''import importlib
import json
import sys


def run(_context: str):
    root = {root}
    if root not in sys.path:
        sys.path.insert(0, root)
    import experiments.experiment_preview_visual as module

    {reload_statement}
    result = module.dispatch({encoded_action})
    print("{VISUAL_RESULT_PREFIX}" + json.dumps(result, sort_keys=True))
'''


def _extract_screenshot_png(tool_result: dict[str, object]) -> bytes:
    """
    Extract and validate PNG bytes from supported MCP content envelopes.
    """
    encoded = _find_encoded_png(tool_result)
    if encoded is None:
        raise RuntimeError("Fusion MCP screenshot result omitted PNG image data.")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise RuntimeError("Fusion MCP screenshot returned invalid base64 data.") from error
    if not payload.startswith(PNG_SIGNATURE):
        raise RuntimeError("Fusion MCP screenshot did not return a PNG file.")
    return payload


def _find_encoded_png(value: object) -> Optional[str]:
    """
    Find base64 PNG data in native image blocks or JSON text blocks.
    """
    if isinstance(value, dict):
        mime_type = value.get("mimeType") or value.get("mime_type")
        if mime_type == "image/png":
            for key in ("base64Data", "data"):
                encoded = value.get(key)
                if isinstance(encoded, str):
                    return encoded
        for nested in value.values():
            found = _find_encoded_png(nested)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_encoded_png(nested)
            if found is not None:
                return found
    elif isinstance(value, str) and value.startswith(("{", "[")):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return None
        return _find_encoded_png(decoded)
    return None


def _assert_visual_differences(differences: dict[str, dict[str, object]]) -> None:
    """
    Enforce tolerant preview visibility and cleared-state equivalence.
    """
    minimum_visible_change = 0.0001
    maximum_stable_change = 0.02
    for name in ("baselineToPreview",):
        changed = _difference_fraction(differences, name)
        if changed < minimum_visible_change:
            raise RuntimeError(f"Visual oracle did not detect the route preview: {changed:.6f}.")
    for name in ("baselineToReloaded", "previewToFreshPreview", "baselineToCleared"):
        changed = _difference_fraction(differences, name)
        if changed > maximum_stable_change:
            raise RuntimeError(
                f"Visual oracle comparison {name} changed {changed:.2%}; "
                f"maximum is {maximum_stable_change:.2%}."
            )


def _fusion_suite_script(selected_scenarios: Optional[Sequence[str]] = None) -> str:
    """
    Build the small in-host bootstrap submitted to ``fusion_mcp_execute``.
    """
    root = json.dumps(str(PROJECT_ROOT))
    scenario_selection = (
        json.dumps(list(selected_scenarios)) if selected_scenarios is not None else "None"
    )
    return f'''import importlib
import json
import sys

import adsk.core


def run(_context: str):
    root = {root}
    if root not in sys.path:
        sys.path.insert(0, root)
    import experiments.scenario_report as scenario_report_module
    import experiments.experiment_fusion_capabilities as capabilities_module
    import experiments.experiment_command_history as history_module
    import experiments.experiment_sweep_matrix as sweep_module
    import experiments.experiment_reference_harness as reference_module

    importlib.reload(scenario_report_module)
    importlib.reload(capabilities_module)
    importlib.reload(history_module)
    importlib.reload(sweep_module)
    importlib.reload(reference_module)
    import experiments.experiment_preview_reload as preview_reload_module

    importlib.reload(preview_reload_module)
    import experiments.experiment_assembly_placement as assembly_module

    importlib.reload(assembly_module)
    import experiments.experiment_linked_geometry as linked_geometry_module

    importlib.reload(linked_geometry_module)
    import experiments.experiment_generated_solids as generated_solids_module

    importlib.reload(generated_solids_module)
    import experiments.fusion_qa_suite as suite_module

    suite_module = importlib.reload(suite_module)
    result = suite_module.run_automated_fusion_suite(
        adsk.core.Application.get(),
        {scenario_selection},
    )
    print("{FUSION_RESULT_PREFIX}" + json.dumps(result, sort_keys=True))
'''


def _native_dialog_capture_script(token: str) -> str:
    """
    Build the single-request native-dialog capture and cleanup bootstrap.
    """
    root = json.dumps(str(PROJECT_ROOT))
    encoded_token = json.dumps(token)
    return f'''import importlib
import json
import sys

import adsk.core


def run(_context: str):
    root = {root}
    if root not in sys.path:
        sys.path.insert(0, root)
    import experiments.experiment_native_dialog_capture as module

    module = importlib.reload(module)
    result = module.run_capture_handshake(adsk.core.Application.get(), {encoded_token})
    print("{NATIVE_DIALOG_RESULT_PREFIX}" + json.dumps(result, sort_keys=True))
'''


def _parse_fusion_tool_result(tool_result: dict[str, object]) -> dict[str, object]:
    """
    Extract the suite sentinel from Fusion MCP's nested execute result.
    """
    return _parse_execute_result(tool_result, FUSION_RESULT_PREFIX)


def _parse_execute_result(
    tool_result: dict[str, object],
    result_prefix: str,
) -> dict[str, object]:
    """
    Extract one prefixed JSON object from Fusion MCP's nested execute result.

    Args:
        tool_result: Raw MCP tool result.
        result_prefix: Sentinel prefix written by the submitted in-host script.

    Returns:
        Decoded JSON object following the final matching sentinel.
    """
    content = tool_result.get("content")
    if not isinstance(content, list):
        raise RuntimeError("Fusion MCP tool result omitted content.")
    text_blocks = [
        item.get("text", "")
        for item in content
        if isinstance(item, dict) and item.get("type") == "text"
    ]
    if not text_blocks:
        raise RuntimeError("Fusion MCP execute returned no text result.")
    execution_payload = json.loads("\n".join(text_blocks))
    if not isinstance(execution_payload, dict):
        raise RuntimeError("Fusion MCP execute result was not an object.")
    if not execution_payload.get("success"):
        raise RuntimeError(str(execution_payload.get("error", "Fusion script failed.")))
    message = execution_payload.get("message")
    if not isinstance(message, str):
        raise RuntimeError("Fusion MCP execute result omitted script output.")
    for line in reversed(message.splitlines()):
        if line.startswith(result_prefix):
            result = json.loads(line[len(result_prefix) :])
            if not isinstance(result, dict):
                raise RuntimeError("Fusion suite result was not an object.")
            return result
    raise RuntimeError("Fusion script output omitted the QA result sentinel.")


def _decode_json_response(response: HttpResponse) -> dict[str, object]:
    """
    Decode one MCP JSON response and reject protocol errors.
    """
    payload = json.loads(response.body)
    if not isinstance(payload, dict):
        raise RuntimeError("Fusion MCP response was not an object.")
    if "error" in payload:
        raise RuntimeError(f"Fusion MCP protocol error: {payload['error']!r}")
    return payload


def _http_request(
    endpoint: str,
    method: str,
    headers: dict[str, str],
    body: Optional[bytes],
    timeout_seconds: float,
) -> HttpResponse:
    """
    Send one HTTP request using only the Python standard library.
    """
    parsed = urlparse(endpoint)
    host = parsed.hostname
    if parsed.scheme not in {"http", "https"} or host is None:
        raise ValueError(f"Invalid MCP endpoint: {endpoint!r}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    connection_type = (
        http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    )
    connection = connection_type(host, port, timeout=timeout_seconds)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        response_body = response.read().decode("utf-8", errors="replace")
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        result = HttpResponse(response.status, response_headers, response_body)
    finally:
        connection.close()
    return result
