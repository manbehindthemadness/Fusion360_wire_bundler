"""
Tests for schema-v5 route topology, migration projections, and validation.
"""

from dataclasses import replace
from uuid import UUID

from wire_bundler.domain import (
    DEFAULT_JUNCTION_DIAMETER_FACTOR,
    ElectricalRelationship,
    HarnessDefinition,
    JunctionDisposition,
    PathwayEnd,
    PathwayExitState,
    RouteEdge,
    RouteEdgeKind,
    TopologyNodeKind,
    build_linear_topology,
    dumps,
    junction_required_diameter,
    loads,
    ordered_physical_wire_edges,
    pathway_exit_states,
    pathway_span_membership,
    validate_harness,
)


def test_true_routing_gate_branch_applies_default_or_override_envelope(
    branched_harness: HarnessDefinition,
) -> None:
    """
    Expand only a true constrained branch by its persistent unitless factor.
    """
    assert branched_harness.topology is not None
    junction = next(
        node for node in branched_harness.topology.nodes if node.kind is TopologyNodeKind.JUNCTION
    )
    assert DEFAULT_JUNCTION_DIAMETER_FACTOR == 2.0
    assert junction_required_diameter(branched_harness.topology, junction.node_id, 4.0) == 9.0
    default_topology = replace(
        branched_harness.topology,
        nodes=tuple(
            replace(node, junction_diameter_factor_override=None)
            if node.node_id == junction.node_id
            else node
            for node in branched_harness.topology.nodes
        ),
    )
    assert junction_required_diameter(default_topology, junction.node_id, 4.0) == 8.0


def test_virtual_or_empty_junction_does_not_expand_envelope(
    branched_harness: HarnessDefinition,
) -> None:
    """
    Ignore the approximation without a routing gate or true branch disposition.
    """
    assert branched_harness.topology is not None
    junction = next(
        node for node in branched_harness.topology.nodes if node.kind is TopologyNodeKind.JUNCTION
    )
    virtual = replace(
        branched_harness.topology,
        nodes=tuple(
            replace(node, slice_control_id=None, junction_diameter_factor_override=None)
            if node.node_id == junction.node_id
            else node
            for node in branched_harness.topology.nodes
        ),
    )
    empty = replace(branched_harness.topology, junction_dispositions=())
    assert junction_required_diameter(virtual, junction.node_id, 4.0) is None
    assert junction_required_diameter(empty, junction.node_id, 4.0) is None


def _issue_codes(definition: HarnessDefinition) -> set[str]:
    """
    Return stable validation codes for one definition.
    """
    return {issue.code for issue in validate_harness(definition)}


def test_linear_projection_is_deterministic_and_preserves_primary_identity(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Project legacy routes repeatedly without changing the primary physical-wire UUID.
    """
    first = build_linear_topology(valid_harness.wires, valid_harness.pathways)
    second = build_linear_topology(valid_harness.wires, valid_harness.pathways)

    assert first == second
    assert first == valid_harness.resolved_topology
    assert first.physical_wires[0].physical_wire_id == valid_harness.wires[0].wire_id
    assert pathway_span_membership(first)[0].physical_wire_ids == (valid_harness.wires[0].wire_id,)


def test_linear_projection_derives_terminated_pathway_ends(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Derive both ends of a single completed legacy pathway as terminated.
    """
    states = pathway_exit_states(valid_harness.resolved_topology)

    assert {(item.pathway_end, item.state) for item in states} == {
        (PathwayEnd.A, PathwayExitState.TERMINATED),
        (PathwayEnd.B, PathwayExitState.TERMINATED),
    }


def test_branched_topology_round_trips_with_stable_membership(
    branched_harness: HarnessDefinition,
) -> None:
    """
    Preserve junction entities, physical legs, relationships, and pathway spans.
    """
    parsed = loads(dumps(branched_harness))

    assert parsed == branched_harness
    assert validate_harness(parsed) == ()
    memberships = pathway_span_membership(parsed.resolved_topology)
    assert len(memberships) == 3
    assert sum(len(item.physical_wire_ids) for item in memberships) == 3
    assert len(parsed.resolved_topology.physical_wires) == 2
    assert len(parsed.resolved_topology.electrical_relationships) == 1


def test_branched_topology_derives_extension_and_termination_states(
    branched_harness: HarnessDefinition,
) -> None:
    """
    Classify the branch attachment as extended and every real ending as terminated.
    """
    states = pathway_exit_states(branched_harness.resolved_topology)

    assert len(states) == 4
    branch_pathway_id = branched_harness.pathways[1].pathway_id
    by_end = {(item.pathway_id, item.pathway_end): item.state for item in states}
    assert by_end[(branch_pathway_id, PathwayEnd.A)] is PathwayExitState.EXTENDED
    assert by_end[(branch_pathway_id, PathwayEnd.B)] is PathwayExitState.TERMINATED


def test_branched_physical_legs_have_deterministic_traversal_order(
    branched_harness: HarnessDefinition,
) -> None:
    """
    Order each distinct generated leg without relying on serialized edge position.
    """
    topology = branched_harness.resolved_topology
    primary = ordered_physical_wire_edges(
        replace(topology, edges=tuple(reversed(topology.edges))),
        topology.physical_wires[0].physical_wire_id,
    )
    branch = ordered_physical_wire_edges(
        topology,
        topology.physical_wires[1].physical_wire_id,
    )

    assert [edge.kind for edge in primary] == [
        RouteEdgeKind.END_LINK,
        RouteEdgeKind.PATHWAY,
        RouteEdgeKind.PATHWAY,
        RouteEdgeKind.END_LINK,
    ]
    assert [edge.kind for edge in branch] == [
        RouteEdgeKind.JUNCTION_TRANSITION,
        RouteEdgeKind.PATHWAY,
        RouteEdgeKind.END_LINK,
    ]


def test_open_exit_is_editable_but_blocks_generation(
    branched_harness: HarnessDefinition,
) -> None:
    """
    Keep a detached endpoint in the model while diagnosing the incomplete component.
    """
    topology = branched_harness.resolved_topology
    branch_end_id = next(
        node.node_id
        for node in topology.nodes
        if node.kind is TopologyNodeKind.PATHWAY_END
        and node.pathway_id == branched_harness.pathways[1].pathway_id
        and node.pathway_end is PathwayEnd.B
    )
    topology = replace(
        topology,
        edges=tuple(
            edge
            for edge in topology.edges
            if not (edge.kind is RouteEdgeKind.END_LINK and edge.start_node_id == branch_end_id)
        ),
    )
    definition = replace(branched_harness, topology=topology)

    states = pathway_exit_states(topology)
    branch_end_state = next(
        item.state
        for item in states
        if item.pathway_id == branched_harness.pathways[1].pathway_id
        and item.pathway_end is PathwayEnd.B
    )
    assert branch_end_state is PathwayExitState.OPEN
    assert "partial_topology" in _issue_codes(definition)


def test_empty_pathway_has_no_membership_and_remains_valid(
    branched_harness: HarnessDefinition,
) -> None:
    """
    Exclude an ordinary pathway with no member edges from processing.
    """
    empty_pathway = branched_harness.pathways[1]
    topology = branched_harness.resolved_topology
    branch_wire_id = topology.physical_wires[1].physical_wire_id
    topology = replace(
        topology,
        nodes=tuple(
            node
            for node in topology.nodes
            if node.pathway_id != empty_pathway.pathway_id
            and node.physical_wire_id != branch_wire_id
        ),
        physical_wires=(topology.physical_wires[0],),
        edges=tuple(
            edge
            for edge in topology.edges
            if edge.physical_wire_id != branch_wire_id
            and edge.start_node_id != UUID("60000000-0000-0000-0000-000000000003")
            and edge.end_node_id != UUID("60000000-0000-0000-0000-000000000003")
        ),
        junction_attachments=(),
        junction_dispositions=(),
        electrical_relationships=(),
    )
    # Restore the unsplit parent span after removing the junction.
    parent_pathway = branched_harness.pathways[0]
    parent_nodes = [
        node
        for node in topology.nodes
        if node.pathway_id == parent_pathway.pathway_id
        and node.kind is TopologyNodeKind.PATHWAY_END
    ]
    parent_nodes.sort(key=lambda node: node.pathway_end.value)
    topology = replace(
        topology,
        edges=topology.edges
        + (
            RouteEdge(
                UUID("70000000-0000-0000-0000-000000000099"),
                RouteEdgeKind.PATHWAY,
                topology.physical_wires[0].physical_wire_id,
                parent_nodes[0].node_id,
                parent_nodes[1].node_id,
                parent_pathway.pathway_id,
            ),
        ),
    )
    definition = replace(branched_harness, topology=topology)

    assert validate_harness(definition) == ()
    assert all(
        item.pathway_id != empty_pathway.pathway_id for item in pathway_span_membership(topology)
    )


def test_cycle_and_physical_leg_recombination_are_rejected(
    branched_harness: HarnessDefinition,
) -> None:
    """
    Reject cyclic graphs and downstream joins between separate physical legs.
    """
    topology = branched_harness.resolved_topology
    branch_end = next(
        node
        for node in topology.nodes
        if node.pathway_id == branched_harness.pathways[1].pathway_id
        and node.pathway_end is PathwayEnd.B
    )
    junction = next(node for node in topology.nodes if node.kind is TopologyNodeKind.JUNCTION)
    cycle_edge = RouteEdge(
        UUID("70000000-0000-0000-0000-000000000090"),
        RouteEdgeKind.JUNCTION_TRANSITION,
        topology.physical_wires[1].physical_wire_id,
        branch_end.node_id,
        junction.node_id,
    )
    recombination_edge = RouteEdge(
        UUID("70000000-0000-0000-0000-000000000091"),
        RouteEdgeKind.JUNCTION_TRANSITION,
        topology.physical_wires[0].physical_wire_id,
        junction.node_id,
        branch_end.node_id,
    )
    definition = replace(
        branched_harness,
        topology=replace(
            topology,
            edges=topology.edges + (cycle_edge, recombination_edge),
        ),
    )

    codes = _issue_codes(definition)

    assert "topology_cycle" in codes
    assert "physical_leg_recombination" in codes


def test_dangling_reference_and_reused_identity_are_rejected(
    branched_harness: HarnessDefinition,
) -> None:
    """
    Diagnose missing graph nodes and duplicate physical-wire UUIDs deterministically.
    """
    topology = branched_harness.resolved_topology
    dangling_edge = replace(
        topology.edges[0],
        edge_id=UUID("70000000-0000-0000-0000-000000000092"),
        end_node_id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
    )
    topology = replace(
        topology,
        physical_wires=topology.physical_wires + (topology.physical_wires[0],),
        edges=topology.edges + (dangling_edge,),
    )

    codes = _issue_codes(replace(branched_harness, topology=topology))

    assert "duplicate_topology_id" in codes
    assert "missing_topology_node_reference" in codes


def test_branch_requires_matching_transition_and_ideal_splice(
    branched_harness: HarnessDefinition,
) -> None:
    """
    Require both geometric attachment and explicit electrical continuity.
    """
    topology = branched_harness.resolved_topology
    topology = replace(
        topology,
        edges=tuple(
            edge for edge in topology.edges if edge.kind is not RouteEdgeKind.JUNCTION_TRANSITION
        ),
        electrical_relationships=(),
    )

    codes = _issue_codes(replace(branched_harness, topology=topology))

    assert "missing_junction_transition" in codes
    assert "missing_branch_electrical_relationship" in codes


def test_multiple_redirects_for_one_member_are_rejected(
    branched_harness: HarnessDefinition,
) -> None:
    """
    Permit one redirect destination per incoming member and junction.
    """
    topology = branched_harness.resolved_topology
    original = topology.junction_dispositions[0]
    first = replace(
        original,
        disposition=JunctionDisposition.REDIRECT_BRANCH,
        branch_wire_id=None,
    )
    second = replace(first, attachment_end=PathwayEnd.B)
    topology = replace(
        topology,
        junction_dispositions=(first, second),
        electrical_relationships=(),
    )

    assert "multiple_junction_redirects" in _issue_codes(
        replace(branched_harness, topology=topology)
    )


def test_invalid_junction_factor_and_pathway_span_are_rejected(
    branched_harness: HarnessDefinition,
) -> None:
    """
    Reject nonpositive gate factors and span endpoints on another pathway.
    """
    topology = branched_harness.resolved_topology
    junction = next(node for node in topology.nodes if node.kind is TopologyNodeKind.JUNCTION)
    nodes = tuple(
        replace(node, junction_diameter_factor_override=0.0)
        if node.node_id == junction.node_id
        else node
        for node in topology.nodes
    )
    branch_edge = next(
        edge
        for edge in topology.edges
        if edge.kind is RouteEdgeKind.PATHWAY
        and edge.physical_wire_id == topology.physical_wires[1].physical_wire_id
    )
    edges = tuple(
        replace(edge, pathway_id=branched_harness.pathways[0].pathway_id)
        if edge.edge_id == branch_edge.edge_id
        else edge
        for edge in topology.edges
    )

    codes = _issue_codes(
        replace(branched_harness, topology=replace(topology, nodes=nodes, edges=edges))
    )

    assert "invalid_junction_diameter_factor" in codes
    assert "pathway_edge_node_mismatch" in codes


def test_electrical_relationship_can_group_multiple_colocated_branches(
    branched_harness: HarnessDefinition,
) -> None:
    """
    Let one ideal-splice record cover more than one branch at a junction.
    """
    topology = branched_harness.resolved_topology
    relationship = topology.electrical_relationships[0]
    topology = replace(
        topology,
        electrical_relationships=(
            ElectricalRelationship(
                relationship.relationship_id,
                relationship.kind,
                relationship.junction_id,
                relationship.physical_wire_ids + (relationship.physical_wire_ids[1],),
                relationship.notes,
            ),
        ),
    )

    codes = _issue_codes(replace(branched_harness, topology=topology))

    assert "missing_branch_electrical_relationship" not in codes
