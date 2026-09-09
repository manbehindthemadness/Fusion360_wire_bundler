"""
Shared deterministic fixtures for domain tests.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from wire_bundler.domain import (
    SCHEMA_VERSION,
    Connection,
    ControlKind,
    ControlStructure,
    HarnessDefinition,
    PathwayDefinition,
    RoutingMode,
    WireDefinition,
    WireProfile,
)


@pytest.fixture
def valid_harness() -> HarnessDefinition:
    """
    Create a deterministic, logically valid one-wire harness.

    Returns:
        Complete harness definition for tests.
    """
    profile_id = UUID("10000000-0000-0000-0000-000000000001")
    start_id = UUID("20000000-0000-0000-0000-000000000001")
    end_id = UUID("20000000-0000-0000-0000-000000000002")
    control_id = UUID("30000000-0000-0000-0000-000000000001")
    pathway_id = UUID("35000000-0000-0000-0000-000000000001")
    definition = HarnessDefinition(
        schema_version=SCHEMA_VERSION,
        harness_id=UUID("40000000-0000-0000-0000-000000000001"),
        name="Harness_001",
        routing_mode=RoutingMode.ROUTING_GATES,
        profiles=(WireProfile(profile_id, "Primary wire", 1.2),),
        connections=(
            Connection(start_id, "J1 / Pin 1", "fusion-start-token"),
            Connection(end_id, "J2 / Pin 4", "fusion-end-token"),
        ),
        controls=(
            ControlStructure(
                control_id,
                "Routing Gate 01",
                ControlKind.ROUTING_GATE,
                "fusion-gate-token",
            ),
        ),
        pathways=(
            PathwayDefinition(
                pathway_id,
                "Main Pathway",
                RoutingMode.ROUTING_GATES,
                (control_id,),
            ),
        ),
        wires=(
            WireDefinition(
                wire_id=UUID("50000000-0000-0000-0000-000000000001"),
                wire_number="001",
                start_connection_id=start_id,
                end_connection_id=end_id,
                profile_id=profile_id,
                ordered_pathway_ids=(pathway_id,),
                ordered_control_ids=(control_id,),
            ),
        ),
    )
    return definition
