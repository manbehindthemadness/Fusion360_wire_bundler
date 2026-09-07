"""
Orchestrate local checks and cleanup-safe Fusion scenarios into one QA report.
"""

from __future__ import annotations

import argparse
import http.client
import json
import platform
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Optional
from urllib.parse import urlparse

from experiments.qa_coverage import load_coverage_ledger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "verification"
DEFAULT_MCP_URL = "http://127.0.0.1:27182/mcp"
MCP_PROTOCOL_VERSION = "2025-03-26"
FUSION_RESULT_PREFIX = "WIRE_BUNDLER_QA_RESULT="


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
) -> tuple[int, Path]:
    """
    Run the selected QA layers and write one aggregate report.

    Args:
        run_local: Execute pytest, palette, Ruff, formatting, and diff checks.
        run_fusion: Execute the cleanup-safe in-host Fusion suite through MCP.
        mcp_url: Local Fusion MCP endpoint.
        command_timeout_seconds: Timeout for each local subprocess.
        fusion_timeout_seconds: Timeout for each MCP request.

    Returns:
        Process exit code and aggregate JSON report path.
    """
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc)
    local_results = (
        _run_local_checks(command_timeout_seconds)
        if run_local
        else [CheckResult("local", "skipped", 0.0, "Disabled by command option.")]
    )
    fusion_result: dict[str, object]
    if run_fusion:
        fusion_result = _run_fusion_suite(mcp_url, fusion_timeout_seconds)
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
        "selection": {"local": run_local, "fusion": run_fusion},
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
    options = parser.parse_args(arguments)
    exit_code, report_path = run_qa(
        run_local=not options.fusion_only,
        run_fusion=not options.local_only,
        mcp_url=options.mcp_url,
        command_timeout_seconds=options.command_timeout,
        fusion_timeout_seconds=options.fusion_timeout,
    )
    print(f"Wire Bundler QA: {'PASS' if exit_code == 0 else 'FAIL'}")
    print(f"Report: {report_path}")
    return exit_code


def _run_local_checks(timeout_seconds: float) -> list[CheckResult]:
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
    return [_run_command(name, command, timeout_seconds) for name, command in commands]


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


def _run_fusion_suite(endpoint: str, timeout_seconds: float) -> dict[str, object]:
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
            {"featureType": "script", "object": {"script": _fusion_suite_script()}},
        )
        suite_result = _parse_fusion_tool_result(tool_result)
        suite_result["server"] = server
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


def _fusion_suite_script() -> str:
    """
    Build the small in-host bootstrap submitted to ``fusion_mcp_execute``.
    """
    root = json.dumps(str(PROJECT_ROOT))
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
    import experiments.fusion_qa_suite as suite_module

    suite_module = importlib.reload(suite_module)
    result = suite_module.run_automated_fusion_suite(adsk.core.Application.get())
    print("{FUSION_RESULT_PREFIX}" + json.dumps(result, sort_keys=True))
'''


def _parse_fusion_tool_result(tool_result: dict[str, object]) -> dict[str, object]:
    """
    Extract the suite sentinel from Fusion MCP's nested execute result.
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
        if line.startswith(FUSION_RESULT_PREFIX):
            result = json.loads(line[len(FUSION_RESULT_PREFIX) :])
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
