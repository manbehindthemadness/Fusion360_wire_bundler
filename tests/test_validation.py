"""
Tests for pure harness definition validation.
"""

from dataclasses import replace
from uuid import UUID

from wire_bundler.domain import (
    ControlKind,
    HarnessDefinition,
    RoutingMode,
    WireDefinition,
    validate_harness,
)


def test_accepts_complete_harness(valid_harness: HarnessDefinition) -> None:
    """
    Accept a complete logical route without consulting Fusion geometry.
    """
    issues = validate_harness(valid_harness)

    assert issues == ()


def test_reports_missing_references(valid_harness: HarnessDefinition) -> None:
    """
    Report missing profile, connection, and control identities.
    """
    missing_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    invalid_wire = replace(
        valid_harness.wires[0],
        start_connection_id=missing_id,
        profile_id=missing_id,
        ordered_control_ids=(missing_id,),
    )
    definition = replace(valid_harness, wires=(invalid_wire,))

    issue_codes = {issue.code for issue in validate_harness(definition)}

    assert issue_codes == {
        "missing_connection_reference",
        "missing_control_reference",
        "missing_profile_reference",
    }


def test_reports_duplicate_wire_identity_number_and_endpoints(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Reject duplicate identities, visible numbers, and physical endpoint use.
    """
    first_wire = valid_harness.wires[0]
    duplicate_wire = WireDefinition(
        wire_id=first_wire.wire_id,
        wire_number=first_wire.wire_number,
        start_connection_id=first_wire.start_connection_id,
        end_connection_id=first_wire.end_connection_id,
        profile_id=first_wire.profile_id,
        ordered_control_ids=first_wire.ordered_control_ids,
    )
    definition = replace(valid_harness, wires=(first_wire, duplicate_wire))

    issue_codes = [issue.code for issue in validate_harness(definition)]

    assert "duplicate_id" in issue_codes
    assert "duplicate_wire_number" in issue_codes
    assert issue_codes.count("duplicate_endpoint") == 2


def test_reports_profile_and_route_failures(valid_harness: HarnessDefinition) -> None:
    """
    Reject invalid dimensions, incompatible controls, and incomplete routes.
    """
    profile = replace(valid_harness.profiles[0], diameter_mm=float("nan"))
    control = replace(valid_harness.controls[0], kind=ControlKind.PROFILE_GATE)
    wire = replace(valid_harness.wires[0], wire_number="wire-one", ordered_control_ids=())
    definition = replace(
        valid_harness,
        routing_mode=RoutingMode.ROUTING_GATES,
        profiles=(profile,),
        controls=(control,),
        wires=(wire,),
    )

    issue_codes = {issue.code for issue in validate_harness(definition)}

    assert issue_codes == {
        "control_mode_mismatch",
        "invalid_profile_diameter",
        "invalid_wire_number",
        "missing_wire_controls",
    }
