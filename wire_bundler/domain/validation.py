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
    PathwayDefinition,
    RoutingMode,
)


@dataclass(frozen=True)
class ValidationIssue:
    """
    Describe one actionable harness validation failure.
    """

    code: str
    path: str
    message: str


def validate_harness(definition: HarnessDefinition) -> tuple[ValidationIssue, ...]:
    """
    Return logical-readiness issues in deterministic order without accessing Fusion.
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
    _validate_pathways(definition, issues)
    _validate_wires(definition, issues)
    return tuple(issues)


def _validate_unique_ids(
    definition: HarnessDefinition,
    issues: list[ValidationIssue],
) -> None:
    """
    Require identities to be unique across the complete harness definition.
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
        *(
            (pathway.pathway_id, f"pathways[{index}].pathway_id")
            for index, pathway in enumerate(definition.pathways)
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
    Validate routing-control references.
    """
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


def _validate_pathways(
    definition: HarnessDefinition,
    issues: list[ValidationIssue],
) -> None:
    """
    Validate pathway names, ordered gates, and routing-mode compatibility.
    """
    controls_by_id = {control.control_id: control for control in definition.controls}
    seen_names: dict[str, str] = {}
    for index, pathway in enumerate(definition.pathways):
        path = f"pathways[{index}]"
        normalized_name = pathway.name.strip()
        if not normalized_name:
            issues.append(
                ValidationIssue(
                    "missing_pathway_name",
                    f"{path}.name",
                    "Pathway name is required.",
                )
            )
        else:
            name_key = normalized_name.casefold()
            previous_path = seen_names.get(name_key)
            if previous_path is not None:
                issues.append(
                    ValidationIssue(
                        "duplicate_pathway_name",
                        f"{path}.name",
                        f"Pathway name duplicates {previous_path}.",
                    )
                )
            else:
                seen_names[name_key] = f"{path}.name"

        if not pathway.ordered_control_ids:
            issues.append(
                ValidationIssue(
                    "missing_pathway_controls",
                    f"{path}.ordered_control_ids",
                    "At least one ordered gate is required.",
                )
            )

        expected_kind: ControlKind = (
            ControlKind.ROUTING_GATE
            if pathway.routing_mode is RoutingMode.ROUTING_GATES
            else ControlKind.PROFILE_GATE
        )
        seen_control_ids: set[UUID] = set()
        for control_index, control_id in enumerate(pathway.ordered_control_ids):
            control_path = f"{path}.ordered_control_ids[{control_index}]"
            control = controls_by_id.get(control_id)
            if control is None:
                issues.append(
                    ValidationIssue(
                        "missing_pathway_control_reference",
                        control_path,
                        "Referenced routing control does not exist.",
                    )
                )
            elif control.kind is not expected_kind:
                issues.append(
                    ValidationIssue(
                        "pathway_control_mode_mismatch",
                        control_path,
                        f"Control kind must be {expected_kind.value} for this pathway.",
                    )
                )
            if control_id in seen_control_ids:
                issues.append(
                    ValidationIssue(
                        "duplicate_pathway_control",
                        control_path,
                        "A gate may appear only once in a pathway.",
                    )
                )
            else:
                seen_control_ids.add(control_id)


def _validate_wires(
    definition: HarnessDefinition,
    issues: list[ValidationIssue],
) -> None:
    """
    Validate conductor mappings and ordered references.
    """
    profile_ids = {profile.profile_id for profile in definition.profiles}
    connection_ids = {connection.connection_id for connection in definition.connections}
    control_ids = {control.control_id for control in definition.controls}
    pathways_by_id = {pathway.pathway_id: pathway for pathway in definition.pathways}
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
                    "End A and End B connections must differ.",
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

        if not wire.ordered_pathway_ids:
            issues.append(
                ValidationIssue(
                    "missing_wire_pathways",
                    f"{path}.ordered_pathway_ids",
                    "At least one ordered pathway is required.",
                )
            )

        resolved_pathways: list[PathwayDefinition] = []
        seen_wire_pathways: set[UUID] = set()
        for pathway_index, pathway_id in enumerate(wire.ordered_pathway_ids):
            pathway_path = f"{path}.ordered_pathway_ids[{pathway_index}]"
            pathway = pathways_by_id.get(pathway_id)
            if pathway is None:
                issues.append(
                    ValidationIssue(
                        "missing_pathway_reference",
                        pathway_path,
                        "Referenced pathway does not exist.",
                    )
                )
            else:
                resolved_pathways.append(pathway)
            if pathway_id in seen_wire_pathways:
                issues.append(
                    ValidationIssue(
                        "duplicate_wire_pathway",
                        pathway_path,
                        "A pathway may appear only once in a wire route.",
                    )
                )
            else:
                seen_wire_pathways.add(pathway_id)

        controls_are_resolvable = all(
            control_id in control_ids for control_id in wire.ordered_control_ids
        )
        if (
            wire.ordered_control_ids
            and controls_are_resolvable
            and len(resolved_pathways) == len(wire.ordered_pathway_ids)
        ):
            expected_control_ids = tuple(
                control_id
                for pathway in resolved_pathways
                for control_id in pathway.ordered_control_ids
            )
            if expected_control_ids != wire.ordered_control_ids:
                issues.append(
                    ValidationIssue(
                        "wire_pathway_controls_mismatch",
                        f"{path}.ordered_control_ids",
                        "Wire control order must match its ordered pathways.",
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
    """
    if reference_id not in available_ids:
        issues.append(ValidationIssue(code, path, "Referenced identity does not exist."))
