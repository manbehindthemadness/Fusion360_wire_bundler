"""
Structured, durable reporting for live Fusion verification scenarios.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Optional


@dataclass(frozen=True)
class ScenarioStep:
    """
    Record the outcome and duration of one verification operation.

    Args:
        name: Human-readable operation name.
        status: Stable ``passed`` or ``failed`` state.
        elapsed_ms: Operation duration in milliseconds.
        detail: Optional result or failure detail.
    """

    name: str
    status: str
    elapsed_ms: float
    detail: str = ""


@dataclass
class ScenarioReport:
    """
    Write incremental text logs and a machine-readable scenario report.

    Args:
        scenario_name: Stable scenario identifier.
        artifact_root: Directory that will receive generated reports.
        sink: Optional secondary logging destination, such as Fusion's log.
    """

    scenario_name: str
    artifact_root: Path
    sink: Optional[Callable[[str], None]] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    steps: list[ScenarioStep] = field(default_factory=list)
    observations: dict[str, object] = field(default_factory=dict)
    status: str = "running"
    error: str = ""
    log_path: Path = field(init=False)
    json_path: Path = field(init=False)

    def __post_init__(self) -> None:
        """
        Create the artifact directory and initialize the report files.
        """
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        timestamp = self.started_at.strftime("%Y%m%dT%H%M%S.%fZ")
        stem = f"{self.scenario_name}_{timestamp}"
        self.log_path = self.artifact_root / f"{stem}.log"
        self.json_path = self.artifact_root / f"{stem}.json"
        self.log(f"Scenario started: {self.scenario_name}")
        self.write_json()

    def log(self, message: str) -> None:
        """
        Append one timestamped line and forward it to the optional host sink.

        Args:
            message: Diagnostic message to record.
        """
        timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        line = f"{timestamp} {message}"
        with self.log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"{line}\n")
        if self.sink is not None:
            self.sink(line)

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        """
        Measure and persist one scenario operation.

        Args:
            name: Human-readable operation name.

        Yields:
            Control to the verification operation.
        """
        self.log(f"START {name}")
        started = perf_counter()
        try:
            yield
        except Exception as error:
            elapsed_ms = (perf_counter() - started) * 1000
            self.steps.append(ScenarioStep(name, "failed", elapsed_ms, str(error)))
            self.log(f"FAIL {name}: {error}")
            self.write_json()
            raise
        elapsed_ms = (perf_counter() - started) * 1000
        self.steps.append(ScenarioStep(name, "passed", elapsed_ms))
        self.log(f"PASS {name} ({elapsed_ms:.1f} ms)")
        self.write_json()

    def finish(self, success: bool, error: str = "") -> None:
        """
        Finalize and persist the overall scenario result.

        Args:
            success: Whether every required verification passed.
            error: Optional traceback or terminal failure detail.
        """
        self.status = "passed" if success else "failed"
        self.error = error
        self.log(f"Scenario {self.status}: {self.scenario_name}")
        self.write_json()

    def record_observation(self, name: str, value: object) -> None:
        """
        Persist one structured capability or diagnostic observation.

        Args:
            name: Stable observation identifier.
            value: JSON-serializable observation value.

        Raises:
            ValueError: If the observation name is empty or already present.
            TypeError: If the value cannot be serialized as JSON.
        """
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Observation name must not be empty.")
        if normalized_name in self.observations:
            raise ValueError(f"Observation already recorded: {normalized_name}")
        try:
            serialized_value = json.dumps(value, sort_keys=True)
        except (TypeError, ValueError) as error:
            raise TypeError(
                f"Observation {normalized_name!r} must be JSON serializable."
            ) from error
        self.observations[normalized_name] = value
        self.log(f"OBSERVE {normalized_name}: {serialized_value}")
        self.write_json()

    def write_json(self) -> None:
        """
        Replace the structured report with the latest complete state.
        """
        payload = {
            "scenario": self.scenario_name,
            "startedAt": self.started_at.isoformat(),
            "status": self.status,
            "error": self.error,
            "observations": self.observations,
            "steps": [asdict(step) for step in self.steps],
            "logPath": str(self.log_path),
        }
        serialized = json.dumps(payload, indent=2, sort_keys=True)
        self.json_path.write_text(f"{serialized}\n", encoding="utf-8")
