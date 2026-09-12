"""
Verify the host-independent master relationship projection and cross-check.
"""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from wire_bundler.application import audit_relationship_map, build_relationship_map
from wire_bundler.domain import (
    ControlKind,
    ControlStructure,
    HarnessDefinition,
    JunctionDefinition,
    PathwayDefinition,
    validate_harness,
)


def test_relationship_map_inserts_junction_between_segmented_pathways(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Project occupied and structural junction links in traversal order.
    """
    original = valid_harness.pathways[0]
    middle_id = UUID("30000000-0000-0000-0000-000000000002")
    final_id = UUID("30000000-0000-0000-0000-000000000003")
    following_id = UUID("35000000-0000-0000-0000-000000000002")
    junction_id = UUID("36000000-0000-0000-0000-000000000001")
    controls = (
        valid_harness.controls[0],
        ControlStructure(middle_id, "Routing Gate 02", ControlKind.ROUTING_GATE, "middle"),
        ControlStructure(final_id, "Routing Gate 03", ControlKind.ROUTING_GATE, "final"),
    )
    preceding = replace(original, ordered_control_ids=(controls[0].control_id,))
    following = PathwayDefinition(
        following_id, "Main Pathway ext 1", original.routing_mode, (final_id,)
    )
    junction = JunctionDefinition(
        junction_id, "Junction 01", middle_id, original.pathway_id, following_id
    )
    wire = replace(
        valid_harness.wires[0],
        ordered_pathway_ids=(original.pathway_id, following_id),
        ordered_control_ids=tuple(control.control_id for control in controls),
    )
    definition = replace(
        valid_harness,
        controls=controls,
        pathways=(preceding, following),
        junctions=(junction,),
        wires=(wire,),
    )

    relationship_map = build_relationship_map(definition)

    assert relationship_map.routes[0].node_ids[1:-1] == (
        f"pathway:{original.pathway_id}",
        f"junction:{junction_id}",
        f"pathway:{following_id}",
    )
    assert tuple(
        (edge.source_node_id, edge.target_node_id) for edge in relationship_map.structural_edges
    ) == (
        (f"pathway:{original.pathway_id}", f"junction:{junction_id}"),
        (f"junction:{junction_id}", f"pathway:{following_id}"),
    )
    assert relationship_map.audit_issues == ()
    assert validate_harness(definition) == ()


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
