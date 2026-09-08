"""
Tests for transactional ordered wire assignment.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional
from uuid import UUID

import pytest

from wire_bundler.application import WireBatchGateway, WireBatchUpdateError, add_wire_batch
from wire_bundler.domain import (
    HarnessDefinition,
    RouteEdgeKind,
    dumps,
    loads,
    validate_harness,
)

PROFILE_ID = UUID("81000000-0000-0000-0000-000000000001")
SOURCE_IDS = (
    UUID("82000000-0000-0000-0000-000000000001"),
    UUID("82000000-0000-0000-0000-000000000002"),
)
DESTINATION_IDS = (
    UUID("83000000-0000-0000-0000-000000000001"),
    UUID("83000000-0000-0000-0000-000000000002"),
)
WIRE_IDS = (
    UUID("84000000-0000-0000-0000-000000000001"),
    UUID("84000000-0000-0000-0000-000000000002"),
)


class _RecordingWireGateway(WireBatchGateway):
    """
    Record definition replacements and optionally fail writes.
    """

    def __init__(
        self,
        definition: HarnessDefinition,
        failures: tuple[Optional[Exception], ...] = (),
    ) -> None:
        """
        Store the initial definition and configured sequential failures.
        """
        self.serialized_definition = dumps(definition)
        self.failures = list(failures)
        self.writes: list[str] = []

    def read_harness_definition(self, harness_id: UUID) -> str:
        """
        Return the current serialized definition.
        """
        del harness_id
        return self.serialized_definition

    def replace_harness_definition(
        self,
        harness_id: UUID,
        serialized_definition: str,
    ) -> None:
        """
        Record or reject a replacement in configured call order.
        """
        del harness_id
        self.writes.append(serialized_definition)
        failure = self.failures.pop(0) if self.failures else None
        if failure is not None:
            raise failure
        self.serialized_definition = serialized_definition


def test_adds_ordered_wire_pairs_on_selected_pathway(valid_harness: HarnessDefinition) -> None:
    """
    Preserve End A/End B pairing and explicit pathway identity.
    """
    empty_harness = replace(valid_harness, profiles=(), connections=(), wires=())
    gateway = _RecordingWireGateway(empty_harness)
    identifiers = iter(
        (
            PROFILE_ID,
            SOURCE_IDS[0],
            DESTINATION_IDS[0],
            WIRE_IDS[0],
            SOURCE_IDS[1],
            DESTINATION_IDS[1],
            WIRE_IDS[1],
        )
    )

    result = add_wire_batch(
        empty_harness.harness_id,
        empty_harness.pathways[0].pathway_id,
        (" source-1 ", "source-2"),
        ("destination-1", " destination-2 "),
        1.5,
        gateway,
        id_factory=lambda: next(identifiers),
    )

    stored = loads(gateway.serialized_definition)
    assert [connection.entity_token for connection in result.connections] == [
        "source-1",
        "source-2",
        "destination-1",
        "destination-2",
    ]
    assert [connection.name for connection in result.connections] == [
        "End A 001",
        "End A 002",
        "End B 001",
        "End B 002",
    ]
    assert [wire.wire_number for wire in result.wires] == ["001", "002"]
    assert result.wires[0].start_connection_id == SOURCE_IDS[0]
    assert result.wires[0].end_connection_id == DESTINATION_IDS[0]
    assert result.wires[1].start_connection_id == SOURCE_IDS[1]
    assert result.wires[1].end_connection_id == DESTINATION_IDS[1]
    assert all(
        wire.ordered_pathway_ids == (empty_harness.pathways[0].pathway_id,)
        and wire.ordered_control_ids == empty_harness.pathways[0].ordered_control_ids
        for wire in result.wires
    )
    assert stored.profiles == (result.profile,)
    assert stored.connections == result.connections
    assert stored.wires == result.wires


def test_increments_after_existing_numeric_wire(valid_harness: HarnessDefinition) -> None:
    """
    Continue stable wire numbering after the greatest existing numeric value.
    """
    gateway = _RecordingWireGateway(valid_harness)

    result = add_wire_batch(
        valid_harness.harness_id,
        valid_harness.pathways[0].pathway_id,
        ("source",),
        ("destination",),
        2.0,
        gateway,
    )

    assert result.wires[0].wire_number == "002"


def test_new_wire_traverses_existing_junction_slices(
    branched_harness: HarnessDefinition,
) -> None:
    """
    Synchronize new primary wires with an already explicit parent topology.
    """
    gateway = _RecordingWireGateway(branched_harness)
    identifiers = iter((PROFILE_ID, SOURCE_IDS[0], DESTINATION_IDS[0], WIRE_IDS[0]))

    result = add_wire_batch(
        branched_harness.harness_id,
        branched_harness.pathways[0].pathway_id,
        ("new-source",),
        ("new-destination",),
        1.0,
        gateway,
        id_factory=lambda: next(identifiers),
    )

    stored = loads(gateway.serialized_definition)
    assert stored.topology is not None
    parent_spans = [
        edge
        for edge in stored.topology.edges
        if edge.kind is RouteEdgeKind.PATHWAY
        and edge.pathway_id == branched_harness.pathways[0].pathway_id
        and edge.physical_wire_id == result.wires[0].wire_id
    ]
    assert len(parent_spans) == 2
    assert validate_harness(stored) == ()


@pytest.mark.parametrize(
    ("sources", "destinations", "diameter", "message"),
    [
        ((), (), 1.0, "at least one"),
        (("source",), ("destination-1", "destination-2"), 1.0, "counts must match"),
        (("source",), ("destination",), 0.0, "finite positive"),
        (("source",), ("destination",), float("nan"), "finite positive"),
    ],
)
def test_rejects_invalid_wire_batch_without_writing(
    valid_harness: HarnessDefinition,
    sources: tuple[str, ...],
    destinations: tuple[str, ...],
    diameter: float,
    message: str,
) -> None:
    """
    Reject incomplete or physically invalid assignments before persistence.
    """
    gateway = _RecordingWireGateway(valid_harness)

    with pytest.raises(ValueError, match=message):
        add_wire_batch(
            valid_harness.harness_id,
            valid_harness.pathways[0].pathway_id,
            sources,
            destinations,
            diameter,
            gateway,
        )

    assert gateway.writes == []


def test_rejects_missing_pathway_without_writing(valid_harness: HarnessDefinition) -> None:
    """
    Require wire assignments to reference a pathway in the owning harness.
    """
    gateway = _RecordingWireGateway(valid_harness)

    with pytest.raises(ValueError, match="does not exist"):
        add_wire_batch(
            valid_harness.harness_id,
            UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
            ("source",),
            ("destination",),
            1.0,
            gateway,
        )

    assert gateway.writes == []


def test_restores_definition_when_wire_write_fails(valid_harness: HarnessDefinition) -> None:
    """
    Restore the exact original JSON after a rejected wire update.
    """
    failure = RuntimeError("write failed")
    gateway = _RecordingWireGateway(valid_harness, failures=(failure, None))

    with pytest.raises(RuntimeError, match="write failed"):
        add_wire_batch(
            valid_harness.harness_id,
            valid_harness.pathways[0].pathway_id,
            ("source",),
            ("destination",),
            1.0,
            gateway,
        )

    assert gateway.serialized_definition == dumps(valid_harness)


def test_reports_failed_wire_rollback(valid_harness: HarnessDefinition) -> None:
    """
    Preserve the persistence failure as cause when rollback also fails.
    """
    failure = RuntimeError("write failed")
    gateway = _RecordingWireGateway(
        valid_harness,
        failures=(failure, RuntimeError("rollback failed")),
    )

    with pytest.raises(WireBatchUpdateError, match="rollback failed") as error_info:
        add_wire_batch(
            valid_harness.harness_id,
            valid_harness.pathways[0].pathway_id,
            ("source",),
            ("destination",),
            1.0,
            gateway,
        )

    assert error_info.value.__cause__ is failure
