"""
Shared deterministic fixtures for domain tests.
"""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from wire_bundler.domain import (
    SCHEMA_VERSION,
    Connection,
    ControlKind,
    ControlStructure,
    ElectricalRelationship,
    ElectricalRelationshipKind,
    HarnessDefinition,
    JunctionAttachment,
    JunctionDisposition,
    JunctionMemberDisposition,
    PathwayDefinition,
    PathwayEnd,
    PhysicalWire,
    RouteEdge,
    RouteEdgeKind,
    RouteTopology,
    RoutingMode,
    TopologyNode,
    TopologyNodeKind,
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


@pytest.fixture
def branched_harness(valid_harness: HarnessDefinition) -> HarnessDefinition:
    """
    Create a deterministic valid Y-junction with one physical branch leg.

    Returns:
        Explicit schema-v5 topology covering a parent and branch pathway.
    """
    parent_pathway = valid_harness.pathways[0]
    primary_wire = valid_harness.wires[0]
    base = valid_harness.resolved_topology
    parent_start = next(
        node
        for node in base.nodes
        if node.pathway_id == parent_pathway.pathway_id and node.pathway_end is PathwayEnd.A
    )
    parent_end = next(
        node
        for node in base.nodes
        if node.pathway_id == parent_pathway.pathway_id and node.pathway_end is PathwayEnd.B
    )

    branch_connection = Connection(
        UUID("20000000-0000-0000-0000-000000000003"),
        "J3 / Pin 2",
        "fusion-branch-end-token",
    )
    branch_control = ControlStructure(
        UUID("30000000-0000-0000-0000-000000000002"),
        "Routing Gate 02",
        ControlKind.ROUTING_GATE,
        "fusion-branch-gate-token",
    )
    branch_pathway = PathwayDefinition(
        UUID("35000000-0000-0000-0000-000000000002"),
        "Branch Pathway",
        RoutingMode.ROUTING_GATES,
        (branch_control.control_id,),
    )
    branch_start = TopologyNode(
        UUID("60000000-0000-0000-0000-000000000001"),
        TopologyNodeKind.PATHWAY_END,
        pathway_id=branch_pathway.pathway_id,
        pathway_end=PathwayEnd.A,
    )
    branch_end = TopologyNode(
        UUID("60000000-0000-0000-0000-000000000002"),
        TopologyNodeKind.PATHWAY_END,
        pathway_id=branch_pathway.pathway_id,
        pathway_end=PathwayEnd.B,
    )
    junction = TopologyNode(
        UUID("60000000-0000-0000-0000-000000000003"),
        TopologyNodeKind.JUNCTION,
        pathway_id=parent_pathway.pathway_id,
        distance_mm=12.5,
        slice_control_id=parent_pathway.ordered_control_ids[0],
        junction_diameter_factor_override=2.25,
        name="Junction 1",
    )
    branch_wire_id = UUID("50000000-0000-0000-0000-000000000002")
    branch_external_end = TopologyNode(
        UUID("60000000-0000-0000-0000-000000000004"),
        TopologyNodeKind.EXTERNAL_END,
        connection_id=branch_connection.connection_id,
        physical_wire_id=branch_wire_id,
    )
    network_id = base.physical_wires[0].network_id
    branch_wire = PhysicalWire(branch_wire_id, network_id, primary_wire.profile_id)
    remaining_edges = tuple(edge for edge in base.edges if edge.kind is not RouteEdgeKind.PATHWAY)
    new_edges = (
        RouteEdge(
            UUID("70000000-0000-0000-0000-000000000001"),
            RouteEdgeKind.PATHWAY,
            primary_wire.wire_id,
            parent_start.node_id,
            junction.node_id,
            parent_pathway.pathway_id,
        ),
        RouteEdge(
            UUID("70000000-0000-0000-0000-000000000002"),
            RouteEdgeKind.PATHWAY,
            primary_wire.wire_id,
            junction.node_id,
            parent_end.node_id,
            parent_pathway.pathway_id,
        ),
        RouteEdge(
            UUID("70000000-0000-0000-0000-000000000003"),
            RouteEdgeKind.JUNCTION_TRANSITION,
            branch_wire_id,
            junction.node_id,
            branch_start.node_id,
        ),
        RouteEdge(
            UUID("70000000-0000-0000-0000-000000000004"),
            RouteEdgeKind.PATHWAY,
            branch_wire_id,
            branch_start.node_id,
            branch_end.node_id,
            branch_pathway.pathway_id,
        ),
        RouteEdge(
            UUID("70000000-0000-0000-0000-000000000005"),
            RouteEdgeKind.END_LINK,
            branch_wire_id,
            branch_end.node_id,
            branch_external_end.node_id,
        ),
    )
    disposition = JunctionMemberDisposition(
        junction.node_id,
        branch_pathway.pathway_id,
        PathwayEnd.A,
        primary_wire.wire_id,
        JunctionDisposition.BRANCH,
        branch_wire_id,
    )
    relationship = ElectricalRelationship(
        UUID("80000000-0000-0000-0000-000000000001"),
        ElectricalRelationshipKind.IDEAL_SPLICE,
        junction.node_id,
        (primary_wire.wire_id, branch_wire_id),
        "Fixture splice",
    )
    topology = RouteTopology(
        nodes=base.nodes + (branch_start, branch_end, junction, branch_external_end),
        physical_wires=base.physical_wires + (branch_wire,),
        edges=remaining_edges + new_edges,
        junction_attachments=(
            JunctionAttachment(
                junction.node_id,
                branch_pathway.pathway_id,
                PathwayEnd.A,
            ),
        ),
        junction_dispositions=(disposition,),
        electrical_relationships=(relationship,),
    )
    return replace(
        valid_harness,
        connections=valid_harness.connections + (branch_connection,),
        controls=valid_harness.controls + (branch_control,),
        pathways=valid_harness.pathways + (branch_pathway,),
        topology=topology,
    )
