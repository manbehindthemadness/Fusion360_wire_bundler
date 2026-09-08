"""
Verify the host-independent master relationship projection and cross-check.
"""

from __future__ import annotations

from dataclasses import replace

from wire_bundler.application import audit_relationship_map, build_relationship_map
from wire_bundler.domain import HarnessDefinition


def test_relationship_map_projects_current_wire_route(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Project connections, ordered pathways, segments, and independent indexes.
    """
    relationship_map = build_relationship_map(valid_harness)
    wire = valid_harness.wires[0]
    pathway = valid_harness.pathways[0]
    start, end = valid_harness.connections

    assert tuple(node.node_id for node in relationship_map.nodes) == (
        f"connection:{start.connection_id}",
        f"connection:{end.connection_id}",
        f"pathway:{pathway.pathway_id}",
    )
    assert relationship_map.routes[0].node_ids == (
        f"connection:{start.connection_id}",
        f"pathway:{pathway.pathway_id}",
        f"connection:{end.connection_id}",
    )
    assert tuple((edge.source_node_id, edge.target_node_id) for edge in relationship_map.edges) == (
        (f"connection:{start.connection_id}", f"pathway:{pathway.pathway_id}"),
        (f"pathway:{pathway.pathway_id}", f"connection:{end.connection_id}"),
    )
    assert relationship_map.pathway_occupancy[0].wire_ids == (wire.wire_id,)
    assert relationship_map.connection_usage[0].endpoints == ((wire.wire_id, "start"),)
    assert relationship_map.connection_usage[1].endpoints == ((wire.wire_id, "end"),)
    assert relationship_map.audit_issues == ()


def test_relationship_map_marks_unresolved_references(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Retain missing route members as visible typed placeholders for debugging.
    """
    definition = replace(valid_harness, connections=valid_harness.connections[1:])

    relationship_map = build_relationship_map(definition)

    missing = tuple(node for node in relationship_map.nodes if node.missing)
    assert len(missing) == 1
    assert missing[0].node_id == f"connection:{valid_harness.connections[0].connection_id}"
    assert relationship_map.audit_issues == ()


def test_relationship_map_projects_explicit_branches_and_exact_spans(
    branched_harness: HarnessDefinition,
) -> None:
    """
    Expose stable graph nodes, physical legs, and per-span membership additively.
    """
    relationship_map = build_relationship_map(branched_harness)
    topology = branched_harness.resolved_topology

    assert len(relationship_map.topology_nodes) == len(topology.nodes)
    assert len(relationship_map.topology_edges) == len(topology.edges)
    assert len(relationship_map.topology_routes) == 2
    assert len(relationship_map.span_occupancy) == 3
    assert {route.wire_id for route in relationship_map.topology_routes} == {
        wire.physical_wire_id for wire in topology.physical_wires
    }
    assert all(
        route.primary_wire_id == branched_harness.wires[0].wire_id
        for route in relationship_map.topology_routes
    )
    assert relationship_map.audit_issues == ()


def test_relationship_audit_detects_tampered_topology_span(
    branched_harness: HarnessDefinition,
) -> None:
    """
    Cross-check graph occupancy independently of the palette projection.
    """
    relationship_map = build_relationship_map(branched_harness)
    tampered = replace(
        relationship_map,
        span_occupancy=relationship_map.span_occupancy[1:],
    )

    codes = {issue.code for issue in audit_relationship_map(branched_harness, tampered)}

    assert "topology_span_occupancy_mismatch" in codes


def test_relationship_audit_detects_tampered_route_and_occupancy(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Report projection drift independently of the normal harness validation pass.
    """
    relationship_map = build_relationship_map(valid_harness)
    route = relationship_map.routes[0]
    occupancy = relationship_map.pathway_occupancy[0]
    tampered = replace(
        relationship_map,
        routes=(replace(route, node_ids=tuple(reversed(route.node_ids))),),
        pathway_occupancy=(replace(occupancy, wire_ids=()),),
    )

    issues = audit_relationship_map(valid_harness, tampered)
    codes = {issue.code for issue in issues}

    assert "wire_route_projection_mismatch" in codes
    assert "pathway_occupancy_projection_mismatch" in codes


def test_relationship_map_scales_by_wire_rows(valid_harness: HarnessDefinition) -> None:
    """
    Keep large harness projections deterministic without merging conductor identity.
    """
    template = valid_harness.wires[0]
    wires = tuple(
        replace(
            template,
            wire_id=template.wire_id.__class__(int=index + 1),
            wire_number=f"{index + 1:03d}",
        )
        for index in range(120)
    )
    definition = replace(valid_harness, wires=wires)

    relationship_map = build_relationship_map(definition)

    assert len(relationship_map.routes) == 120
    assert len(relationship_map.edges) == 240
    assert relationship_map.pathway_occupancy[0].wire_ids == tuple(wire.wire_id for wire in wires)
    assert relationship_map.audit_issues == ()
