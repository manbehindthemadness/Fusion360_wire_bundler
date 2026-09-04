"""
Deterministic validation for harness definitions before generation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID

from .model import (
    SCHEMA_VERSION,
    ControlKind,
    HarnessDefinition,
    RoutingMode,
)


@dataclass(frozen=True)
class ValidationIssue:
    """
    Describe one actionable harness validation failure.

    Args:
        code: Stable machine-readable issue code.
        path: Dot-and-index path to the invalid value.
        message: Human-readable explanation.
    """

    code: str
    path: str
    message: str


def validate_harness(definition: HarnessDefinition) -> tuple[ValidationIssue, ...]:
    """
    Validate logical readiness without accessing Fusion geometry.

    Args:
        definition: Harness definition to validate.

    Returns:
        Validation issues in deterministic discovery order.
    """
    issues: list[ValidationIssue] = []
    if definition.schema_version != SCHEMA_VERSION:
        issues.append(
            ValidationIssue(
                "unsupported_schema_version",
                "schema_version",
                f"Expected schema version {SCHEMA_VERSION}.",
            )
        )
    if not definition.name.strip():
        issues.append(ValidationIssue("missing_name", "name", "Harness name is required."))
    if not definition.wires:
        issues.append(ValidationIssue("missing_wires", "wires", "At least one wire is required."))

    _validate_unique_ids(definition, issues)
    _validate_profiles(definition, issues)
    _validate_connections(definition, issues)
    _validate_controls(definition, issues)
    _validate_wires(definition, issues)
    return tuple(issues)


def _validate_unique_ids(
    definition: HarnessDefinition,
    issues: list[ValidationIssue],
) -> None:
    """
    Require identities to be unique across the complete harness definition.

    Args:
        definition: Harness definition to validate.
        issues: Mutable issue accumulator.
    """
    seen: dict[UUID, str] = {definition.harness_id: "harness_id"}
    identities = [
        *(
            (profile.profile_id, f"profiles[{index}].profile_id")
            for index, profile in enumerate(definition.profiles)
        ),
        *(
            (connection.connection_id, f"connections[{index}].connection_id")
            for index, connection in enumerate(definition.connections)
        ),
        *(
            (control.control_id, f"controls[{index}].control_id")
            for index, control in enumerate(definition.controls)
        ),
        *((wire.wire_id, f"wires[{index}].wire_id") for index, wire in enumerate(definition.wires)),
    ]
    for identity, path in identities:
        previous_path = seen.get(identity)
        if previous_path is not None:
            issues.append(
                ValidationIssue(
                    "duplicate_id",
                    path,
                    f"Identity duplicates {previous_path}.",
                )
            )
        else:
            seen[identity] = path


def _validate_profiles(
    definition: HarnessDefinition,
    issues: list[ValidationIssue],
) -> None:
    """
    Validate conductor profile fields.

    Args:
        definition: Harness definition to validate.
        issues: Mutable issue accumulator.
    """
    for index, profile in enumerate(definition.profiles):
        path = f"profiles[{index}]"
        if not profile.name.strip():
            issues.append(
                ValidationIssue("missing_profile_name", f"{path}.name", "Profile name is required.")
            )
        if not math.isfinite(profile.diameter_mm) or profile.diameter_mm <= 0:
            issues.append(
                ValidationIssue(
                    "invalid_profile_diameter",
                    f"{path}.diameter_mm",
                    "Diameter must be a finite positive value.",
                )
            )


def _validate_connections(
    definition: HarnessDefinition,
    issues: list[ValidationIssue],
) -> None:
    """
    Validate physical connection references.

    Args:
        definition: Harness definition to validate.
        issues: Mutable issue accumulator.
    """
    for index, connection in enumerate(definition.connections):
        path = f"connections[{index}]"
        if not connection.name.strip():
            issues.append(
                ValidationIssue(
                    "missing_connection_name",
                    f"{path}.name",
                    "Connection name is required.",
                )
            )
        if not connection.entity_token.strip():
            issues.append(
                ValidationIssue(
                    "missing_connection_geometry",
                    f"{path}.entity_token",
                    "Connection must reference Fusion geometry.",
                )
            )


def _validate_controls(
    definition: HarnessDefinition,
    issues: list[ValidationIssue],
) -> None:
    """
    Validate routing-control references and mode compatibility.

    Args:
        definition: Harness definition to validate.
        issues: Mutable issue accumulator.
    """
    expected_kind: ControlKind = (
        ControlKind.ROUTING_GATE
        if definition.routing_mode is RoutingMode.ROUTING_GATES
        else ControlKind.PROFILE_GATE
    )
    for index, control in enumerate(definition.controls):
        path = f"controls[{index}]"
        if not control.name.strip():
            issues.append(
                ValidationIssue("missing_control_name", f"{path}.name", "Control name is required.")
            )
        if not control.entity_token.strip():
            issues.append(
                ValidationIssue(
                    "missing_control_geometry",
                    f"{path}.entity_token",
                    "Control must reference Fusion geometry.",
                )
            )
        if control.kind is not expected_kind:
            issues.append(
                ValidationIssue(
                    "control_mode_mismatch",
                    f"{path}.kind",
                    f"Control kind must be {expected_kind.value} for this routing mode.",
                )
            )


def _validate_wires(
    definition: HarnessDefinition,
    issues: list[ValidationIssue],
) -> None:
    """
    Validate conductor mappings and ordered references.

    Args:
        definition: Harness definition to validate.
        issues: Mutable issue accumulator.
    """
    profile_ids = {profile.profile_id for profile in definition.profiles}
    connection_ids = {connection.connection_id for connection in definition.connections}
    control_ids = {control.control_id for control in definition.controls}
    seen_numbers: dict[str, str] = {}
    seen_endpoints: dict[UUID, str] = {}

    for index, wire in enumerate(definition.wires):
        path = f"wires[{index}]"
        _validate_wire_number(wire.wire_number, path, seen_numbers, issues)
        _validate_reference(
            wire.profile_id,
            profile_ids,
            "missing_profile_reference",
            f"{path}.profile_id",
            issues,
        )
        _validate_endpoint(
            wire.start_connection_id,
            connection_ids,
            f"{path}.start_connection_id",
            seen_endpoints,
            issues,
        )
        _validate_endpoint(
            wire.end_connection_id,
            connection_ids,
            f"{path}.end_connection_id",
            seen_endpoints,
            issues,
        )
        if wire.start_connection_id == wire.end_connection_id:
            issues.append(
                ValidationIssue(
                    "identical_wire_endpoints",
                    f"{path}.end_connection_id",
                    "Start and destination connections must differ.",
                )
            )
        if not wire.ordered_control_ids:
            issues.append(
                ValidationIssue(
                    "missing_wire_controls",
                    f"{path}.ordered_control_ids",
                    "At least one ordered control is required.",
                )
            )

        seen_wire_controls: set[UUID] = set()
        for control_index, control_id in enumerate(wire.ordered_control_ids):
            control_path = f"{path}.ordered_control_ids[{control_index}]"
            _validate_reference(
                control_id,
                control_ids,
                "missing_control_reference",
                control_path,
                issues,
            )
            if control_id in seen_wire_controls:
                issues.append(
                    ValidationIssue(
                        "duplicate_wire_control",
                        control_path,
                        "A control may appear only once in a wire route.",
                    )
                )
            else:
                seen_wire_controls.add(control_id)


def _validate_wire_number(
    wire_number: str,
    path: str,
    seen_numbers: dict[str, str],
    issues: list[ValidationIssue],
) -> None:
    """
    Validate one stable user-facing wire number.

    Args:
        wire_number: Wire number to validate.
        path: Parent wire path.
        seen_numbers: Previously encountered wire numbers.
        issues: Mutable issue accumulator.
    """
    number_path = f"{path}.wire_number"
    if not wire_number.isdecimal() or int(wire_number) <= 0:
        issues.append(
            ValidationIssue(
                "invalid_wire_number",
                number_path,
                "Wire number must be a positive decimal string.",
            )
        )
    previous_path = seen_numbers.get(wire_number)
    if previous_path is not None:
        issues.append(
            ValidationIssue(
                "duplicate_wire_number",
                number_path,
                f"Wire number duplicates {previous_path}.",
            )
        )
    else:
        seen_numbers[wire_number] = number_path


def _validate_endpoint(
    endpoint_id: UUID,
    connection_ids: set[UUID],
    path: str,
    seen_endpoints: dict[UUID, str],
    issues: list[ValidationIssue],
) -> None:
    """
    Validate one endpoint reference and require unique physical use.

    Args:
        endpoint_id: Referenced connection identity.
        connection_ids: Available connection identities.
        path: Endpoint field path.
        seen_endpoints: Previously assigned physical endpoints.
        issues: Mutable issue accumulator.
    """
    _validate_reference(
        endpoint_id,
        connection_ids,
        "missing_connection_reference",
        path,
        issues,
    )
    previous_path = seen_endpoints.get(endpoint_id)
    if previous_path is not None:
        issues.append(
            ValidationIssue(
                "duplicate_endpoint",
                path,
                f"Connection is already assigned at {previous_path}.",
            )
        )
    else:
        seen_endpoints[endpoint_id] = path


def _validate_reference(
    reference_id: UUID,
    available_ids: set[UUID],
    code: str,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    """
    Validate that an identity references an available domain object.

    Args:
        reference_id: Referenced identity.
        available_ids: Valid identities for the reference type.
        code: Stable issue code for a missing reference.
        path: Reference field path.
        issues: Mutable issue accumulator.
    """
    if reference_id not in available_ids:
        issues.append(ValidationIssue(code, path, "Referenced identity does not exist."))
