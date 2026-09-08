"""
Tests for transactional pathway creation.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional
from uuid import UUID

import pytest

from wire_bundler.application import (
    PathwayGateway,
    PathwayUpdateError,
    add_pathway,
    suggest_pathway_name,
)
from wire_bundler.domain import (
    HarnessDefinition,
    PathwayEnd,
    RoutingMode,
    TopologyNodeKind,
    dumps,
    loads,
)

PATHWAY_ID = UUID("60000000-0000-0000-0000-000000000001")
GATE_1_ID = UUID("61000000-0000-0000-0000-000000000001")
GATE_2_ID = UUID("61000000-0000-0000-0000-000000000002")


class _RecordingPathwayGateway(PathwayGateway):
    """
    Record definition replacements and optionally fail writes.
    """

    def __init__(
        self,
        definition: HarnessDefinition,
        failures: tuple[Optional[Exception], ...] = (),
    ) -> None:
        """
        Store the initial definition and configured sequential write failures.
        """
        self.serialized_definition = dumps(definition)
        self.failures = list(failures)
        self.writes: list[str] = []
        self.requested_harness_ids: list[UUID] = []

    def read_harness_definition(self, harness_id: UUID) -> str:
        """
        Return the current serialized definition.
        """
        self.requested_harness_ids.append(harness_id)
        return self.serialized_definition

    def replace_harness_definition(
        self,
        harness_id: UUID,
        serialized_definition: str,
    ) -> None:
        """
        Record or reject a replacement in configured call order.
        """
        self.requested_harness_ids.append(harness_id)
        self.writes.append(serialized_definition)
        failure = self.failures.pop(0) if self.failures else None
        if failure is not None:
            raise failure
        self.serialized_definition = serialized_definition


def test_adds_ordered_pathway_to_existing_harness(valid_harness: HarnessDefinition) -> None:
    """
    Persist selected profile tokens in traversal order with stable identities.
    """
    empty_harness = replace(valid_harness, controls=(), pathways=(), wires=())
    gateway = _RecordingPathwayGateway(empty_harness)
    identifiers = iter((GATE_1_ID, GATE_2_ID, PATHWAY_ID))

    pathway = add_pathway(
        empty_harness.harness_id,
        " Main Pathway ",
        RoutingMode.ROUTING_GATES,
        ("gate-token-1", "gate-token-2"),
        gateway,
        id_factory=lambda: next(identifiers),
    )

    stored = loads(gateway.serialized_definition)
    assert pathway.pathway_id == PATHWAY_ID
    assert pathway.name == "Main Pathway"
    assert pathway.ordered_control_ids == (GATE_1_ID, GATE_2_ID)
    assert [control.entity_token for control in stored.controls] == [
        "gate-token-1",
        "gate-token-2",
    ]
    assert stored.pathways == (pathway,)


def test_suggests_next_pathway_name(valid_harness: HarnessDefinition) -> None:
    """
    Increment pathway names case-insensitively within the owning harness.
    """
    gateway = _RecordingPathwayGateway(valid_harness)

    suggested = suggest_pathway_name(valid_harness.harness_id, "Main Pathway", gateway)

    assert suggested == "Main Pathway_2"


def test_adds_endpoint_nodes_when_explicit_topology_exists(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Keep a newly created empty pathway available for junction attachment.
    """
    explicit = replace(valid_harness, topology=valid_harness.resolved_topology)
    gateway = _RecordingPathwayGateway(explicit)
    identifiers = iter((GATE_1_ID, PATHWAY_ID))

    pathway = add_pathway(
        explicit.harness_id,
        "Branch Pathway",
        RoutingMode.ROUTING_GATES,
        ("branch-gate",),
        gateway,
        id_factory=lambda: next(identifiers),
    )

    stored = loads(gateway.serialized_definition)
    assert stored.topology is not None
    endpoints = {
        node.pathway_end
        for node in stored.topology.nodes
        if node.kind is TopologyNodeKind.PATHWAY_END and node.pathway_id == pathway.pathway_id
    }
    assert endpoints == set(PathwayEnd)


def test_rejects_pathway_without_gate_profiles(valid_harness: HarnessDefinition) -> None:
    """
    Avoid metadata writes when no traversal gates were selected.
    """
    gateway = _RecordingPathwayGateway(valid_harness)

    with pytest.raises(ValueError, match="at least one gate"):
        add_pathway(
            valid_harness.harness_id,
            "Pathway_001",
            RoutingMode.ROUTING_GATES,
            (),
            gateway,
        )

    assert gateway.writes == []


def test_restores_definition_when_pathway_write_fails(valid_harness: HarnessDefinition) -> None:
    """
    Restore the exact original JSON after a rejected pathway update.
    """
    failure = RuntimeError("write failed")
    gateway = _RecordingPathwayGateway(valid_harness, failures=(failure, None))

    with pytest.raises(RuntimeError, match="write failed"):
        add_pathway(
            valid_harness.harness_id,
            "Pathway_002",
            RoutingMode.PROFILE_GATES,
            ("gate-token",),
            gateway,
        )

    assert gateway.serialized_definition == dumps(valid_harness)


def test_reports_failed_pathway_rollback(valid_harness: HarnessDefinition) -> None:
    """
    Preserve the persistence failure as cause when rollback also fails.
    """
    failure = RuntimeError("write failed")
    gateway = _RecordingPathwayGateway(
        valid_harness,
        failures=(failure, RuntimeError("rollback failed")),
    )

    with pytest.raises(PathwayUpdateError, match="rollback failed") as error_info:
        add_pathway(
            valid_harness.harness_id,
            "Pathway_002",
            RoutingMode.PROFILE_GATES,
            ("gate-token",),
            gateway,
        )

    assert error_info.value.__cause__ is failure
