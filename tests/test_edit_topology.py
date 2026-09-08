"""
Tests for atomic schema-v5 topology mutation workflows.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable, Optional
from uuid import UUID

import pytest

from wire_bundler.application import (
    TopologyEditGateway,
    TopologyUpdateError,
    add_external_end,
    add_junction,
    add_junction_pigtail_end,
    attach_pathway_to_junction,
    branch_all_junction_members,
    cleanup_orphaned_topology,
    detach_pathway_from_junction,
    disconnect_junction_member,
    disconnect_pathway_extension,
    extend_pathway_member,
    move_junction,
    remove_external_end,
    remove_junction,
    rename_junction,
    rename_pathway_extension,
    set_junction_diameter_factor,
    set_junction_member_disposition,
)
from wire_bundler.domain import (
    Connection,
    ControlKind,
    ControlStructure,
    HarnessDefinition,
    JunctionDisposition,
    PathwayDefinition,
    PathwayEnd,
    RouteEdgeKind,
    RoutingMode,
    TopologyNodeKind,
    dumps,
    loads,
    validate_harness,
)


class _RecordingTopologyGateway(TopologyEditGateway):
    """
    Store harness definitions and configurable persistence failures.
    """

    def __init__(
        self,
        definition: HarnessDefinition,
        failures: tuple[Optional[Exception], ...] = (),
    ) -> None:
        """
        Initialize serialized state and sequential failures.
        """
        self.serialized_definition = dumps(definition)
        self.failures = list(failures)
        self.writes: list[str] = []

    def read_harness_definition(self, harness_id: UUID) -> str:
        """
        Return the current serialized harness definition.
        """
        return self.serialized_definition

    def replace_harness_definition(
        self,
        harness_id: UUID,
        serialized_definition: str,
    ) -> None:
        """
        Store or reject one atomic replacement.
        """
        self.writes.append(serialized_definition)
        failure = self.failures.pop(0) if self.failures else None
        if failure is not None:
            raise failure
        self.serialized_definition = serialized_definition


def _id_factory(first: int) -> Callable[[], UUID]:
    """
    Return a deterministic sequence of collision-free UUIDs.
    """
    next_value = first

    def create() -> UUID:
        """
        Allocate the next UUID in the test sequence.
        """
        nonlocal next_value
        identity = UUID(int=next_value)
        next_value += 1
        return identity

    return create


def _with_empty_pathways(
    definition: HarnessDefinition,
    count: int = 1,
) -> HarnessDefinition:
    """
    Add ordinary unoccupied pathways used as junction attachments.
    """
    controls = list(definition.controls)
    pathways = list(definition.pathways)
    for index in range(count):
        control = ControlStructure(
            UUID(int=1000 + index),
            f"Branch Gate {index + 1}",
            ControlKind.ROUTING_GATE,
            f"branch-gate-{index + 1}",
        )
        pathway = PathwayDefinition(
            UUID(int=1100 + index),
            f"Branch Pathway {index + 1}",
            RoutingMode.ROUTING_GATES,
            (control.control_id,),
        )
        controls.append(control)
        pathways.append(pathway)
    return replace(
        definition,
        controls=tuple(controls),
        pathways=tuple(pathways),
    )


def _prepare_junction(
    definition: HarnessDefinition,
    *,
    id_start: int = 1,
) -> tuple[_RecordingTopologyGateway, UUID, UUID]:
    """
    Materialize one junction and attach the first empty branch pathway.
    """
    prepared = _with_empty_pathways(definition)
    gateway = _RecordingTopologyGateway(prepared)
    junction = add_junction(
        prepared.harness_id,
        prepared.pathways[0].pathway_id,
        10.0,
        gateway,
        slice_control_id=prepared.pathways[0].ordered_control_ids[0],
        id_factory=_id_factory(id_start),
    )
    branch_pathway_id = prepared.pathways[1].pathway_id
    attach_pathway_to_junction(
        prepared.harness_id,
        junction.node_id,
        branch_pathway_id,
        PathwayEnd.A,
        gateway,
    )
    return gateway, junction.node_id, branch_pathway_id


def _prepare_open_route(
    definition: HarnessDefinition,
) -> tuple[_RecordingTopologyGateway, UUID]:
    """
    Materialize a route with its downstream legacy end detached for editing.
    """
    prepared = _with_empty_pathways(definition)
    topology = prepared.resolved_topology
    downstream_end = next(
        node
        for node in topology.nodes
        if node.kind is TopologyNodeKind.EXTERNAL_END
        and node.connection_id == definition.wires[0].end_connection_id
    )
    topology = replace(
        topology,
        nodes=tuple(node for node in topology.nodes if node != downstream_end),
        edges=tuple(
            edge
            for edge in topology.edges
            if downstream_end.node_id not in {edge.start_node_id, edge.end_node_id}
        ),
    )
    return _RecordingTopologyGateway(replace(prepared, topology=topology)), downstream_end.node_id


def test_extension_and_added_end_complete_an_open_route(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Continue through an empty pathway and terminate at a newly selected face.
    """
    gateway, _ = _prepare_open_route(valid_harness)
    target_pathway = _with_empty_pathways(valid_harness).pathways[1]
    wire_id = valid_harness.wires[0].wire_id

    extension, target_span = extend_pathway_member(
        valid_harness.harness_id,
        wire_id,
        valid_harness.pathways[0].pathway_id,
        PathwayEnd.B,
        target_pathway.pathway_id,
        PathwayEnd.A,
        gateway,
        id_factory=_id_factory(200),
    )
    partial = loads(gateway.serialized_definition)
    assert extension.kind is RouteEdgeKind.EXTENSION
    assert extension.name == "Extension 1"
    assert target_span.pathway_id == target_pathway.pathway_id
    assert "partial_topology" in {issue.code for issue in validate_harness(partial)}

    connection = Connection(UUID(int=300), "J3 / Pin 1", "fusion-new-end-token")
    external_end = add_external_end(
        valid_harness.harness_id,
        wire_id,
        target_pathway.pathway_id,
        PathwayEnd.B,
        connection,
        gateway,
        id_factory=_id_factory(301),
    )
    completed = loads(gateway.serialized_definition)
    assert external_end.connection_id == connection.connection_id
    assert connection in completed.connections
    assert validate_harness(completed) == ()

    renamed = rename_pathway_extension(
        valid_harness.harness_id,
        extension.edge_id,
        "Cabin branch",
        gateway,
    )
    assert renamed.name == "Cabin branch"


def test_removing_added_end_and_extension_preserves_repairable_fragments(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Delete selected links independently and leave partial topology for repair.
    """
    gateway, _ = _prepare_open_route(valid_harness)
    target_pathway = _with_empty_pathways(valid_harness).pathways[1]
    wire_id = valid_harness.wires[0].wire_id
    extension, _ = extend_pathway_member(
        valid_harness.harness_id,
        wire_id,
        valid_harness.pathways[0].pathway_id,
        PathwayEnd.B,
        target_pathway.pathway_id,
        PathwayEnd.A,
        gateway,
        id_factory=_id_factory(400),
    )
    connection = Connection(UUID(int=500), "J3 / Pin 1", "fusion-new-end-token")
    external_end = add_external_end(
        valid_harness.harness_id,
        wire_id,
        target_pathway.pathway_id,
        PathwayEnd.B,
        connection,
        gateway,
        id_factory=_id_factory(501),
    )

    remove_external_end(valid_harness.harness_id, external_end.node_id, gateway)
    without_end = loads(gateway.serialized_definition)
    assert connection not in without_end.connections
    disconnect_pathway_extension(valid_harness.harness_id, extension.edge_id, gateway)
    disconnected = loads(gateway.serialized_definition)
    assert disconnected.topology is not None
    assert extension.edge_id not in {edge.edge_id for edge in disconnected.topology.edges}
    assert "partial_topology" in {issue.code for issue in validate_harness(disconnected)}


def test_junction_pigtail_adds_a_distinct_terminated_physical_leg(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Keep the main trace continuous while a local end branches at its junction.
    """
    gateway, junction_id, _ = _prepare_junction(valid_harness)
    connection = Connection(UUID(int=600), "Shield drain", "fusion-pigtail-token")

    external_end = add_junction_pigtail_end(
        valid_harness.harness_id,
        junction_id,
        valid_harness.wires[0].wire_id,
        connection,
        gateway,
        id_factory=_id_factory(601),
    )

    stored = loads(gateway.serialized_definition)
    assert stored.topology is not None
    assert external_end.physical_wire_id != valid_harness.wires[0].wire_id
    assert any(
        edge.kind is RouteEdgeKind.END_LINK
        and edge.start_node_id == junction_id
        and edge.end_node_id == external_end.node_id
        for edge in stored.topology.edges
    )
    assert validate_harness(stored) == ()


def test_extension_rejects_a_source_that_is_already_terminated(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Require the selected source routing gate to be open.
    """
    prepared = _with_empty_pathways(valid_harness)
    gateway = _RecordingTopologyGateway(replace(prepared, topology=prepared.resolved_topology))

    with pytest.raises(ValueError, match="already connected or terminated"):
        extend_pathway_member(
            valid_harness.harness_id,
            valid_harness.wires[0].wire_id,
            valid_harness.pathways[0].pathway_id,
            PathwayEnd.B,
            prepared.pathways[1].pathway_id,
            PathwayEnd.A,
            gateway,
        )


def test_add_junction_materializes_and_bisects_legacy_route(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Convert a linear route once and split its occupied pathway span atomically.
    """
    gateway = _RecordingTopologyGateway(valid_harness)

    junction = add_junction(
        valid_harness.harness_id,
        valid_harness.pathways[0].pathway_id,
        12.0,
        gateway,
        slice_control_id=valid_harness.controls[0].control_id,
        id_factory=_id_factory(1),
    )

    stored = loads(gateway.serialized_definition)
    assert stored.topology is not None
    assert junction in stored.topology.nodes
    parent_edges = [
        edge
        for edge in stored.topology.edges
        if edge.kind is RouteEdgeKind.PATHWAY
        and edge.pathway_id == valid_harness.pathways[0].pathway_id
    ]
    assert len(parent_edges) == 2
    assert all(junction.node_id in {edge.start_node_id, edge.end_node_id} for edge in parent_edges)
    assert validate_harness(stored) == ()


def test_empty_attachment_and_shared_slice_survive_round_trip(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Persist empty Y and cross attachments independently of member dispositions.
    """
    prepared = _with_empty_pathways(valid_harness, count=2)
    gateway = _RecordingTopologyGateway(prepared)
    junction = add_junction(
        prepared.harness_id,
        prepared.pathways[0].pathway_id,
        10.0,
        gateway,
        id_factory=_id_factory(1),
    )
    for pathway in prepared.pathways[1:]:
        attach_pathway_to_junction(
            prepared.harness_id,
            junction.node_id,
            pathway.pathway_id,
            PathwayEnd.A,
            gateway,
        )

    stored = loads(gateway.serialized_definition)

    assert stored.topology is not None
    assert len(stored.topology.junction_attachments) == 2
    assert stored.topology.junction_dispositions == ()
    assert validate_harness(stored) == ()


def test_batch_branch_matches_individual_member_operation(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Produce identical topology for one-member batch and individual branch actions.
    """
    batch_gateway, batch_junction_id, batch_pathway_id = _prepare_junction(valid_harness)
    individual_gateway, individual_junction_id, individual_pathway_id = _prepare_junction(
        valid_harness
    )
    incoming_wire_id = valid_harness.wires[0].wire_id

    batch = branch_all_junction_members(
        valid_harness.harness_id,
        batch_junction_id,
        batch_pathway_id,
        PathwayEnd.A,
        batch_gateway,
        id_factory=_id_factory(100),
    )
    individual = set_junction_member_disposition(
        valid_harness.harness_id,
        individual_junction_id,
        individual_pathway_id,
        PathwayEnd.A,
        incoming_wire_id,
        JunctionDisposition.BRANCH,
        individual_gateway,
        id_factory=_id_factory(100),
    )

    assert batch == (individual,)
    assert loads(batch_gateway.serialized_definition) == loads(
        individual_gateway.serialized_definition
    )


def test_branch_disconnect_preserves_partial_until_explicit_cleanup(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Delete only the selected transition, then remove its orphan in a second action.
    """
    gateway, junction_id, pathway_id = _prepare_junction(valid_harness)
    disposition = set_junction_member_disposition(
        valid_harness.harness_id,
        junction_id,
        pathway_id,
        PathwayEnd.A,
        valid_harness.wires[0].wire_id,
        JunctionDisposition.BRANCH,
        gateway,
        id_factory=_id_factory(100),
    )
    assert disposition.branch_wire_id is not None

    disconnect_junction_member(
        valid_harness.harness_id,
        junction_id,
        pathway_id,
        PathwayEnd.A,
        valid_harness.wires[0].wire_id,
        gateway,
    )

    disconnected = loads(gateway.serialized_definition)
    assert disconnected.topology is not None
    assert disposition.branch_wire_id in {
        wire.physical_wire_id for wire in disconnected.topology.physical_wires
    }
    assert "partial_topology" in {issue.code for issue in validate_harness(disconnected)}

    removed = cleanup_orphaned_topology(valid_harness.harness_id, gateway)
    cleaned = loads(gateway.serialized_definition)
    assert removed == (disposition.branch_wire_id,)
    assert validate_harness(cleaned) == ()


def test_exclusion_records_no_branch_geometry(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Persist EXCLUDE_BRANCH without allocating a physical leg or transition.
    """
    gateway, junction_id, pathway_id = _prepare_junction(valid_harness)
    before = loads(gateway.serialized_definition)
    assert before.topology is not None

    disposition = set_junction_member_disposition(
        valid_harness.harness_id,
        junction_id,
        pathway_id,
        PathwayEnd.A,
        valid_harness.wires[0].wire_id,
        JunctionDisposition.EXCLUDE_BRANCH,
        gateway,
    )

    stored = loads(gateway.serialized_definition)
    assert stored.topology is not None
    assert disposition.branch_wire_id is None
    assert len(stored.topology.physical_wires) == len(before.topology.physical_wires)
    assert len(stored.topology.edges) == len(before.topology.edges)
    assert validate_harness(stored) == ()


def test_redirect_moves_simple_downstream_trace_and_preserves_identity(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Route the existing physical leg through the branch pathway to its original end.
    """
    gateway, junction_id, pathway_id = _prepare_junction(valid_harness)

    disposition = set_junction_member_disposition(
        valid_harness.harness_id,
        junction_id,
        pathway_id,
        PathwayEnd.A,
        valid_harness.wires[0].wire_id,
        JunctionDisposition.REDIRECT_BRANCH,
        gateway,
        id_factory=_id_factory(100),
    )

    stored = loads(gateway.serialized_definition)
    assert stored.topology is not None
    assert disposition.branch_wire_id is None
    assert len(stored.topology.physical_wires) == 1
    assert not any(
        edge.kind is RouteEdgeKind.PATHWAY
        and edge.pathway_id == valid_harness.pathways[0].pathway_id
        and edge.start_node_id == junction_id
        for edge in stored.topology.edges
    )
    assert validate_harness(stored) == ()


def test_move_rejects_crossing_an_adjacent_junction(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Preserve pathway slice order when moving a junction.
    """
    gateway = _RecordingTopologyGateway(valid_harness)
    first = add_junction(
        valid_harness.harness_id,
        valid_harness.pathways[0].pathway_id,
        10.0,
        gateway,
        id_factory=_id_factory(1),
    )
    second = add_junction(
        valid_harness.harness_id,
        valid_harness.pathways[0].pathway_id,
        20.0,
        gateway,
        id_factory=_id_factory(10),
    )

    moved = move_junction(
        valid_harness.harness_id,
        first.node_id,
        15.0,
        gateway,
    )
    assert moved.distance_mm == 15.0
    with pytest.raises(ValueError, match="cannot cross"):
        move_junction(
            valid_harness.harness_id,
            first.node_id,
            25.0,
            gateway,
        )
    stored = loads(gateway.serialized_definition)
    assert stored.topology is not None
    assert (
        next(node for node in stored.topology.nodes if node.node_id == second.node_id).distance_mm
        == 20.0
    )


def test_junction_names_are_numbered_unique_and_renamable(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Keep junction cards distinct even when callers reuse the default name.
    """
    gateway = _RecordingTopologyGateway(valid_harness)
    first = add_junction(
        valid_harness.harness_id,
        valid_harness.pathways[0].pathway_id,
        10.0,
        gateway,
        id_factory=_id_factory(1),
    )
    second = add_junction(
        valid_harness.harness_id,
        valid_harness.pathways[0].pathway_id,
        20.0,
        gateway,
        id_factory=_id_factory(10),
    )
    assert (first.name, second.name) == ("Junction 1", "Junction 2")

    renamed = rename_junction(
        valid_harness.harness_id,
        second.node_id,
        "Junction 1",
        gateway,
    )
    assert renamed.name == "Junction 2"


def test_second_junction_preserves_first_junction_members(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Keep an existing Y branch intact when another slice bisects the parent path.
    """
    gateway, first_junction_id, branch_pathway_id = _prepare_junction(valid_harness)
    stored = loads(gateway.serialized_definition)
    assert stored.topology is not None
    incoming_wire_id = stored.topology.physical_wires[0].physical_wire_id
    set_junction_member_disposition(
        valid_harness.harness_id,
        first_junction_id,
        branch_pathway_id,
        PathwayEnd.A,
        incoming_wire_id,
        JunctionDisposition.BRANCH,
        gateway,
        id_factory=_id_factory(100),
    )

    add_junction(
        valid_harness.harness_id,
        valid_harness.pathways[0].pathway_id,
        20.0,
        gateway,
        id_factory=_id_factory(200),
    )

    updated = loads(gateway.serialized_definition)
    assert updated.topology is not None
    assert any(
        item.junction_id == first_junction_id
        and item.incoming_wire_id == incoming_wire_id
        and item.disposition is JunctionDisposition.BRANCH
        for item in updated.topology.junction_dispositions
    )
    assert any(
        attachment.junction_id == first_junction_id and attachment.pathway_id == branch_pathway_id
        for attachment in updated.topology.junction_attachments
    )


def test_junction_diameter_factor_can_be_overridden_and_reset(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Persist a positive routing-gate factor while keeping the default nullable.
    """
    gateway, junction_id, _ = _prepare_junction(valid_harness)

    updated = set_junction_diameter_factor(valid_harness.harness_id, junction_id, 2.4, gateway)
    assert updated.junction_diameter_factor_override == 2.4
    reset = set_junction_diameter_factor(valid_harness.harness_id, junction_id, None, gateway)
    assert reset.junction_diameter_factor_override is None


def test_detach_and_remove_empty_junction_restore_parent_span(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Remove an empty attachment and merge the parent route around its junction.
    """
    gateway, junction_id, pathway_id = _prepare_junction(valid_harness)

    detach_pathway_from_junction(
        valid_harness.harness_id,
        junction_id,
        pathway_id,
        PathwayEnd.A,
        gateway,
    )
    remove_junction(
        valid_harness.harness_id,
        junction_id,
        gateway,
        id_factory=_id_factory(100),
    )

    stored = loads(gateway.serialized_definition)
    assert stored.topology is not None
    assert not any(node.kind is TopologyNodeKind.JUNCTION for node in stored.topology.nodes)
    assert (
        len(
            [
                edge
                for edge in stored.topology.edges
                if edge.kind is RouteEdgeKind.PATHWAY
                and edge.pathway_id == valid_harness.pathways[0].pathway_id
            ]
        )
        == 1
    )
    assert validate_harness(stored) == ()


def test_attachment_cannot_detach_while_members_remain(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Prevent an attachment record from disappearing beneath member topology.
    """
    gateway, junction_id, pathway_id = _prepare_junction(valid_harness)
    set_junction_member_disposition(
        valid_harness.harness_id,
        junction_id,
        pathway_id,
        PathwayEnd.A,
        valid_harness.wires[0].wire_id,
        JunctionDisposition.EXCLUDE_BRANCH,
        gateway,
    )

    with pytest.raises(ValueError, match="Disconnect all junction members"):
        detach_pathway_from_junction(
            valid_harness.harness_id,
            junction_id,
            pathway_id,
            PathwayEnd.A,
            gateway,
        )


def test_persistence_failure_restores_exact_definition(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Restore the exact source JSON if an atomic topology write is rejected.
    """
    write_error = RuntimeError("write failed")
    gateway = _RecordingTopologyGateway(
        valid_harness,
        failures=(write_error, None),
    )

    with pytest.raises(RuntimeError, match="write failed"):
        add_junction(
            valid_harness.harness_id,
            valid_harness.pathways[0].pathway_id,
            10.0,
            gateway,
            id_factory=_id_factory(1),
        )

    assert gateway.serialized_definition == dumps(valid_harness)


def test_failed_rollback_reports_topology_update_error(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Retain the original write failure as cause when rollback also fails.
    """
    write_error = RuntimeError("write failed")
    gateway = _RecordingTopologyGateway(
        valid_harness,
        failures=(write_error, RuntimeError("rollback failed")),
    )

    with pytest.raises(TopologyUpdateError, match="rollback failed") as error_info:
        add_junction(
            valid_harness.harness_id,
            valid_harness.pathways[0].pathway_id,
            10.0,
            gateway,
            id_factory=_id_factory(1),
        )

    assert error_info.value.__cause__ is write_error
