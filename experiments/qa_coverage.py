"""
Load and validate the machine-readable QA coverage ledger.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

LEDGER_PATH = Path(__file__).with_name("qa_coverage.json")
VALID_STATUSES = frozenset(("automated", "partial", "candidate", "manual"))
VALID_PLATFORMS = frozenset(("macos", "windows"))
VALID_LAYERS = frozenset(
    (
        "pytest",
        "palette",
        "fusion-script",
        "fusion-command",
        "fusion-api",
        "mcp",
        "os-window",
        "manual",
    )
)


@dataclass(frozen=True)
class CoverageTarget:
    """
    Describe the automation state of one stable acceptance target.

    Args:
        target_id: Stable milestone-scoped target identifier.
        area: Product or infrastructure area covered by the target.
        behavior: Observable behavior that must be verified.
        status: Current automation status.
        layers: Test or experiment layers used or proposed.
        evidence: Repository files that currently exercise the target.
        capabilities: Host controls or observations still required.
        manual_reason: Why the target cannot currently be fully automated.
        review_trigger: Event that should cause a new automation attempt.
    """

    target_id: str
    area: str
    behavior: str
    status: str
    layers: tuple[str, ...]
    evidence: tuple[str, ...]
    capabilities: tuple[str, ...]
    manual_reason: str = ""
    review_trigger: str = ""


@dataclass(frozen=True)
class CoverageLedger:
    """
    Hold one validated milestone coverage inventory.

    Args:
        schema_version: Ledger format version.
        milestone: Milestone whose acceptance targets are inventoried.
        required_platforms: Operating systems required for milestone completion.
        targets: Ordered coverage targets.
    """

    schema_version: int
    milestone: str
    required_platforms: tuple[str, ...]
    targets: tuple[CoverageTarget, ...]

    def counts_by_status(self) -> dict[str, int]:
        """
        Count targets in each automation state.

        Returns:
            Mapping from status to target count.
        """
        counts = Counter(target.status for target in self.targets)
        return {status: counts.get(status, 0) for status in sorted(VALID_STATUSES)}


def load_coverage_ledger(path: Optional[Path] = None) -> CoverageLedger:
    """
    Load and validate a QA coverage ledger.

    Args:
        path: Optional ledger path. The repository M0 ledger is used by default.

    Returns:
        Validated immutable coverage ledger.

    Raises:
        ValueError: If JSON content or any ledger field is malformed.
    """
    ledger_path = LEDGER_PATH if path is None else path
    try:
        raw_payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError(f"Cannot load QA coverage ledger {ledger_path}: {error}") from error
    if not isinstance(raw_payload, dict):
        raise ValueError("QA coverage ledger root must be an object.")
    schema_version = raw_payload.get("schemaVersion")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ValueError("QA coverage schemaVersion must be integer 1.")
    if schema_version != 1:
        raise ValueError(f"Unsupported QA coverage schema version: {schema_version}")
    milestone = _required_string(raw_payload, "milestone")
    required_platforms = _string_tuple(raw_payload, "requiredPlatforms")
    if (
        len(required_platforms) != len(VALID_PLATFORMS)
        or set(required_platforms) != VALID_PLATFORMS
    ):
        raise ValueError("QA coverage requiredPlatforms must contain macos and windows.")
    raw_targets = raw_payload.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise ValueError("QA coverage ledger targets must be a non-empty array.")

    targets = tuple(
        _parse_target(raw_target, index) for index, raw_target in enumerate(raw_targets)
    )
    target_ids = tuple(target.target_id for target in targets)
    if len(set(target_ids)) != len(target_ids):
        raise ValueError("QA coverage target IDs must be unique.")
    return CoverageLedger(schema_version, milestone, required_platforms, targets)


def _parse_target(raw_target: object, index: int) -> CoverageTarget:
    """
    Validate and convert one target payload.

    Args:
        raw_target: Untrusted decoded target value.
        index: Target position used in validation errors.

    Returns:
        Validated immutable coverage target.
    """
    if not isinstance(raw_target, dict):
        raise ValueError(f"QA coverage target {index} must be an object.")
    target_id = _required_string(raw_target, "id")
    area = _required_string(raw_target, "area")
    behavior = _required_string(raw_target, "behavior")
    status = _required_string(raw_target, "status")
    if status not in VALID_STATUSES:
        raise ValueError(f"QA coverage target {target_id} has invalid status {status!r}.")
    layers = _string_tuple(raw_target, "layers")
    invalid_layers = set(layers) - VALID_LAYERS
    if invalid_layers:
        raise ValueError(
            f"QA coverage target {target_id} has invalid layers: {sorted(invalid_layers)!r}."
        )
    evidence = _string_tuple(raw_target, "evidence")
    capabilities = _string_tuple(raw_target, "capabilities")
    manual_reason = _optional_string(raw_target, "manualReason")
    review_trigger = _optional_string(raw_target, "reviewTrigger")
    if status == "automated" and not evidence:
        raise ValueError(f"Automated QA coverage target {target_id} requires evidence.")
    if status == "manual" and (not manual_reason or not review_trigger):
        raise ValueError(
            f"Manual QA coverage target {target_id} requires a reason and review trigger."
        )
    return CoverageTarget(
        target_id,
        area,
        behavior,
        status,
        layers,
        evidence,
        capabilities,
        manual_reason,
        review_trigger,
    )


def _required_string(payload: Mapping[str, object], key: str) -> str:
    """
    Read a required non-empty string.
    """
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"QA coverage field {key!r} must be a non-empty string.")
    return value.strip()


def _optional_string(payload: Mapping[str, object], key: str) -> str:
    """
    Read an optional string while rejecting other JSON types.
    """
    value = payload.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"QA coverage field {key!r} must be a string.")
    return value.strip()


def _string_tuple(payload: Mapping[str, object], key: str) -> tuple[str, ...]:
    """
    Read an array containing only non-empty strings.
    """
    value = payload.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"QA coverage field {key!r} must be an array.")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"QA coverage field {key!r} must contain non-empty strings.")
    return tuple(item.strip() for item in value)
