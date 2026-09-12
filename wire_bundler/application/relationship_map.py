"""
Build and independently audit a host-neutral harness relationship projection.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from enum import Enum
from uuid import UUID

from ..domain import HarnessDefinition, WireDefinition


class RelationshipNodeKind(str, Enum):
    """
    Classify nodes supported by the current master relationship graphic.
    """

    CONNECTION = "connection"
    PATHWAY = "pathway"
    JUNCTION = "junction"


@dataclass(frozen=True)
class RelationshipNode:
    """
    Describe one stable node in the display projection.
    """

    node_id: str
    kind: RelationshipNodeKind
    member_id: UUID
    label: str
    missing: bool = False


@dataclass(frozen=True)
class RelationshipEdge:
    """
    Describe one ordered wire segment between adjacent relationship nodes.
    """

    edge_id: str
    wire_id: UUID
    source_node_id: str
    target_node_id: str
    sequence: int


@dataclass(frozen=True)
class RelationshipStructuralEdge:
    """
    Describe one persistent pathway-to-junction relationship.
    """

    edge_id: str
    source_node_id: str
    target_node_id: str


@dataclass(frozen=True)
class RelationshipRoute:
    """
    Project one physical wire from its beginning through its pathways to its end.
    """

    route_id: str
    wire_id: UUID
    wire_number: str
    label: str
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]


@dataclass(frozen=True)
class RelationshipOccupancy:
    """
    Record the wire identities projected onto one pathway.
    """

    pathway_id: UUID
    wire_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class RelationshipConnectionUse:
    """
    Record every projected wire endpoint assigned to one connection.
    """

    connection_id: UUID
    endpoints: tuple[tuple[UUID, str], ...]


@dataclass(frozen=True)
class RelationshipAuditIssue:
    """
    Describe a deterministic mismatch between the definition and its projection.
    """

    code: str
    message: str
    member_type: str = ""
    member_id: str = ""


@dataclass(frozen=True)
class RelationshipMap:
    """
    Store the current master-graphic projection and its independent audit result.
    """

    nodes: tuple[RelationshipNode, ...]
    structural_edges: tuple[RelationshipStructuralEdge, ...]
    edges: tuple[RelationshipEdge, ...]
    routes: tuple[RelationshipRoute, ...]
    pathway_occupancy: tuple[RelationshipOccupancy, ...]
    connection_usage: tuple[RelationshipConnectionUse, ...]
    audit_issues: tuple[RelationshipAuditIssue, ...] = ()


def build_relationship_map(definition: HarnessDefinition) -> RelationshipMap:
    """
    Build the read-only connection, wire, and pathway projection for one harness.
    """
    nodes = _relationship_nodes(definition)
    routes: list[RelationshipRoute] = []
    edges: list[RelationshipEdge] = []
    for wire in definition.wires:
        node_ids = _wire_node_ids(definition, wire)
        wire_edges = tuple(
            RelationshipEdge(
                edge_id=f"wire:{wire.wire_id}:segment:{index}",
                wire_id=wire.wire_id,
                source_node_id=source,
                target_node_id=target,
                sequence=index,
            )
            for index, (source, target) in enumerate(zip(node_ids, node_ids[1:]))
        )
        edges.extend(wire_edges)
        routes.append(
            RelationshipRoute(
                route_id=f"wire:{wire.wire_id}",
                wire_id=wire.wire_id,
                wire_number=wire.wire_number,
                label=_wire_label(wire),
                node_ids=node_ids,
                edge_ids=tuple(edge.edge_id for edge in wire_edges),
            )
        )

    relationship_map = RelationshipMap(
        nodes=nodes,
        structural_edges=_structural_edges(definition),
        edges=tuple(edges),
        routes=tuple(routes),
        pathway_occupancy=tuple(
            RelationshipOccupancy(
                pathway_id=pathway.pathway_id,
                wire_ids=tuple(
                    wire.wire_id
                    for wire in definition.wires
                    if pathway.pathway_id in wire.ordered_pathway_ids
                ),
            )
            for pathway in definition.pathways
        ),
        connection_usage=tuple(
            RelationshipConnectionUse(
                connection_id=connection.connection_id,
                endpoints=_connection_endpoints(definition, connection.connection_id),
            )
            for connection in definition.connections
        ),
    )
    audit_issues = audit_relationship_map(definition, relationship_map)
    return replace(relationship_map, audit_issues=audit_issues)


def audit_relationship_map(
    definition: HarnessDefinition,
    relationship_map: RelationshipMap,
) -> tuple[RelationshipAuditIssue, ...]:
    """
    Independently compare every relationship projection with its source definition.
    """
    issues: list[RelationshipAuditIssue] = []
    _audit_unique_projection_ids(relationship_map, issues)
    expected_nodes = Counter(node.node_id for node in _relationship_nodes(definition))
    actual_nodes = Counter(node.node_id for node in relationship_map.nodes)
    if actual_nodes != expected_nodes:
        issues.append(
            RelationshipAuditIssue(
                "relationship_nodes_mismatch",
                "Master graphic nodes do not match the harness connections and pathways.",
            )
        )

    expected_structural_edges = _structural_edges(definition)
    if relationship_map.structural_edges != expected_structural_edges:
        issues.append(
            RelationshipAuditIssue(
                "relationship_structure_mismatch",
                "Master graphic junction structure does not match the harness definition.",
            )
        )

    if len(relationship_map.routes) != len(definition.wires):
        issues.append(
            RelationshipAuditIssue(
                "relationship_route_count_mismatch",
                "Master graphic wire count does not match the harness definition.",
            )
        )
    for index, wire in enumerate(definition.wires):
        if index >= len(relationship_map.routes):
            break
        route = relationship_map.routes[index]
        expected_node_ids = _wire_node_ids(definition, wire)
        expected_edge_ids = tuple(
            f"wire:{wire.wire_id}:segment:{sequence}"
            for sequence in range(len(expected_node_ids) - 1)
        )
        if (
            route.wire_id != wire.wire_id
            or route.node_ids != expected_node_ids
            or route.edge_ids != expected_edge_ids
        ):
            issues.append(
                RelationshipAuditIssue(
                    "wire_route_projection_mismatch",
                    f"{_wire_label(wire)} has an inconsistent master-graphic route.",
                    "wire",
                    str(wire.wire_id),
                )
            )

    expected_edges = tuple(
        (
            f"wire:{wire.wire_id}:segment:{sequence}",
            wire.wire_id,
            source,
            target,
            sequence,
        )
        for wire in definition.wires
        for sequence, (source, target) in enumerate(
            _adjacent_pairs(_wire_node_ids(definition, wire))
        )
    )
    actual_edges = tuple(
        (
            edge.edge_id,
            edge.wire_id,
            edge.source_node_id,
            edge.target_node_id,
            edge.sequence,
        )
        for edge in relationship_map.edges
    )
    if actual_edges != expected_edges:
        issues.append(
            RelationshipAuditIssue(
                "relationship_edges_mismatch",
                "Master graphic segments do not match the ordered wire routes.",
            )
        )

    expected_occupancy = tuple(
        (
            pathway.pathway_id,
            tuple(
                wire.wire_id
                for wire in definition.wires
                if pathway.pathway_id in wire.ordered_pathway_ids
            ),
        )
        for pathway in definition.pathways
    )
    actual_occupancy = tuple(
        (occupancy.pathway_id, occupancy.wire_ids)
        for occupancy in relationship_map.pathway_occupancy
    )
    if actual_occupancy != expected_occupancy:
        issues.append(
            RelationshipAuditIssue(
                "pathway_occupancy_projection_mismatch",
                "Master graphic pathway occupancy disagrees with Wire Routes.",
                "pathway",
            )
        )

    expected_usage = tuple(
        (
            connection.connection_id,
            _connection_endpoints(definition, connection.connection_id),
        )
        for connection in definition.connections
    )
    actual_usage = tuple(
        (usage.connection_id, usage.endpoints) for usage in relationship_map.connection_usage
    )
    if actual_usage != expected_usage:
        issues.append(
            RelationshipAuditIssue(
                "connection_usage_projection_mismatch",
                "Master graphic connection usage disagrees with Wire Routes.",
                "connection",
            )
        )
    return tuple(issues)


def _relationship_nodes(definition: HarnessDefinition) -> tuple[RelationshipNode, ...]:
    """
    Build existing and unresolved relationship nodes in deterministic order.
    """
    nodes = [
        *(
            RelationshipNode(
                _node_id(RelationshipNodeKind.CONNECTION, connection.connection_id),
                RelationshipNodeKind.CONNECTION,
                connection.connection_id,
                connection.name,
            )
            for connection in definition.connections
        ),
        *(
            RelationshipNode(
                _node_id(RelationshipNodeKind.PATHWAY, pathway.pathway_id),
                RelationshipNodeKind.PATHWAY,
                pathway.pathway_id,
                pathway.name,
            )
            for pathway in definition.pathways
        ),
        *(
            RelationshipNode(
                _node_id(RelationshipNodeKind.JUNCTION, junction.junction_id),
                RelationshipNodeKind.JUNCTION,
                junction.junction_id,
                junction.name,
            )
            for junction in definition.junctions
        ),
    ]
    existing = {node.node_id for node in nodes}
    missing = [
        *((RelationshipNodeKind.CONNECTION, wire.start_connection_id) for wire in definition.wires),
        *((RelationshipNodeKind.CONNECTION, wire.end_connection_id) for wire in definition.wires),
        *(
            (RelationshipNodeKind.PATHWAY, pathway_id)
            for wire in definition.wires
            for pathway_id in wire.ordered_pathway_ids
        ),
    ]
    for kind, member_id in missing:
        node_id = _node_id(kind, member_id)
        if node_id in existing:
            continue
        nodes.append(
            RelationshipNode(
                node_id=node_id,
                kind=kind,
                member_id=member_id,
                label=f"Missing {kind.value} #{str(member_id)[:8]}",
                missing=True,
            )
        )
        existing.add(node_id)
    return tuple(nodes)


def _audit_unique_projection_ids(
    relationship_map: RelationshipMap,
    issues: list[RelationshipAuditIssue],
) -> None:
    """
    Report duplicate presentation identities before comparing projection content.
    """
    for kind, identities in (
        ("node", (node.node_id for node in relationship_map.nodes)),
        ("edge", (edge.edge_id for edge in relationship_map.edges)),
        ("route", (route.route_id for route in relationship_map.routes)),
    ):
        duplicates = sorted(
            identity for identity, count in Counter(identities).items() if count > 1
        )
        for identity in duplicates:
            issues.append(
                RelationshipAuditIssue(
                    f"duplicate_relationship_{kind}_id",
                    f"Master graphic {kind} identity is duplicated: {identity}.",
                )
            )


def _node_id(kind: RelationshipNodeKind, member_id: UUID) -> str:
    """
    Create a stable typed presentation identity for one domain object.
    """
    return f"{kind.value}:{member_id}"


def _wire_node_ids(
    definition: HarnessDefinition,
    wire: WireDefinition,
) -> tuple[str, ...]:
    """
    Return the typed node sequence for a wire-like domain object.
    """
    junctions = {
        (junction.preceding_pathway_id, junction.following_pathway_id): junction
        for junction in definition.junctions
    }
    nodes = [_node_id(RelationshipNodeKind.CONNECTION, wire.start_connection_id)]
    for index, pathway_id in enumerate(wire.ordered_pathway_ids):
        nodes.append(_node_id(RelationshipNodeKind.PATHWAY, pathway_id))
        if index + 1 >= len(wire.ordered_pathway_ids):
            continue
        junction = junctions.get((pathway_id, wire.ordered_pathway_ids[index + 1]))
        if junction is not None:
            nodes.append(_node_id(RelationshipNodeKind.JUNCTION, junction.junction_id))
    nodes.append(_node_id(RelationshipNodeKind.CONNECTION, wire.end_connection_id))
    return tuple(nodes)


def _structural_edges(
    definition: HarnessDefinition,
) -> tuple[RelationshipStructuralEdge, ...]:
    """
    Project junction relationships even when no wire occupies the pathway chain.
    """
    return tuple(
        edge
        for junction in definition.junctions
        for edge in (
            RelationshipStructuralEdge(
                f"junction:{junction.junction_id}:preceding",
                _node_id(RelationshipNodeKind.PATHWAY, junction.preceding_pathway_id),
                _node_id(RelationshipNodeKind.JUNCTION, junction.junction_id),
            ),
            RelationshipStructuralEdge(
                f"junction:{junction.junction_id}:following",
                _node_id(RelationshipNodeKind.JUNCTION, junction.junction_id),
                _node_id(RelationshipNodeKind.PATHWAY, junction.following_pathway_id),
            ),
        )
    )


def _wire_label(wire: WireDefinition) -> str:
    """
    Return the display label used by a wire-like domain object.
    """
    return wire.display_name.strip() or f"Wire {wire.wire_number}"


def _adjacent_pairs(values: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """
    Return each ordered pair of neighboring node identities.
    """
    return tuple(zip(values, values[1:]))


def _connection_endpoints(
    definition: HarnessDefinition,
    connection_id: UUID,
) -> tuple[tuple[UUID, str], ...]:
    """
    Return wire endpoint assignments for one connection in definition order.
    """
    endpoints: list[tuple[UUID, str]] = []
    for wire in definition.wires:
        if wire.start_connection_id == connection_id:
            endpoints.append((wire.wire_id, "start"))
        if wire.end_connection_id == connection_id:
            endpoints.append((wire.wire_id, "end"))
    return tuple(endpoints)
