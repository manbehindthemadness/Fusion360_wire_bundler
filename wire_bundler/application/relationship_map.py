"""
Build and independently audit a host-neutral harness relationship projection.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional
from uuid import UUID

from ..domain import (
    Connection,
    HarnessDefinition,
    PathwayDefinition,
    RouteEdge,
    TopologyNode,
    TopologyNodeKind,
    WireDefinition,
    ordered_physical_wire_edges,
    pathway_span_membership,
)


class RelationshipNodeKind(str, Enum):
    """
    Classify nodes supported by the current master relationship graphic.
    """

    CONNECTION = "connection"
    PATHWAY = "pathway"
    EXTERNAL_END = "external_end"
    PATHWAY_END = "pathway_end"
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
    network_id: Optional[UUID] = None
    primary_wire_id: Optional[UUID] = None


@dataclass(frozen=True)
class RelationshipOccupancy:
    """
    Record the wire identities projected onto one pathway.
    """

    pathway_id: UUID
    wire_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class RelationshipSpanOccupancy:
    """
    Record physical-wire membership on one exact pathway span.
    """

    pathway_id: UUID
    first_node_id: UUID
    second_node_id: UUID
    physical_wire_ids: tuple[UUID, ...]


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
    edges: tuple[RelationshipEdge, ...]
    routes: tuple[RelationshipRoute, ...]
    pathway_occupancy: tuple[RelationshipOccupancy, ...]
    connection_usage: tuple[RelationshipConnectionUse, ...]
    audit_issues: tuple[RelationshipAuditIssue, ...] = ()
    topology_nodes: tuple[RelationshipNode, ...] = ()
    topology_edges: tuple[RelationshipEdge, ...] = ()
    topology_routes: tuple[RelationshipRoute, ...] = ()
    span_occupancy: tuple[RelationshipSpanOccupancy, ...] = ()


def build_relationship_map(definition: HarnessDefinition) -> RelationshipMap:
    """
    Build the read-only connection, wire, and pathway projection for one harness.
    """
    nodes = _relationship_nodes(definition)
    routes: list[RelationshipRoute] = []
    edges: list[RelationshipEdge] = []
    for wire in definition.wires:
        node_ids = _wire_node_ids(wire)
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
        topology_nodes=_topology_relationship_nodes(definition),
        topology_edges=_topology_relationship_edges(definition),
        topology_routes=_topology_relationship_routes(definition),
        span_occupancy=_topology_span_occupancy(definition),
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
        expected_node_ids = _wire_node_ids(wire)
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
        for sequence, (source, target) in enumerate(_adjacent_pairs(_wire_node_ids(wire)))
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
    _audit_topology_projection(definition, relationship_map, issues)
    return tuple(issues)


def _audit_topology_projection(
    definition: HarnessDefinition,
    relationship_map: RelationshipMap,
    issues: list[RelationshipAuditIssue],
) -> None:
    """
    Compare additive graph projection fields directly with explicit topology.
    """
    topology = definition.topology
    if topology is None:
        if any(
            (
                relationship_map.topology_nodes,
                relationship_map.topology_edges,
                relationship_map.topology_routes,
                relationship_map.span_occupancy,
            )
        ):
            issues.append(
                RelationshipAuditIssue(
                    "unexpected_topology_projection",
                    "Linear definition unexpectedly contains topology projection data.",
                )
            )
        return

    expected_node_ids = tuple(_topology_node_id(node.node_id) for node in topology.nodes)
    if tuple(node.node_id for node in relationship_map.topology_nodes) != expected_node_ids:
        issues.append(
            RelationshipAuditIssue(
                "topology_nodes_mismatch",
                "Topology diagram nodes do not match the explicit route graph.",
            )
        )
    expected_edges = tuple(
        (
            f"topology-edge:{edge.edge_id}",
            edge.physical_wire_id,
            _topology_node_id(edge.start_node_id),
            _topology_node_id(edge.end_node_id),
        )
        for edge in topology.edges
    )
    actual_edges = tuple(
        (
            edge.edge_id,
            edge.wire_id,
            edge.source_node_id,
            edge.target_node_id,
        )
        for edge in relationship_map.topology_edges
    )
    if actual_edges != expected_edges:
        issues.append(
            RelationshipAuditIssue(
                "topology_edges_mismatch",
                "Topology diagram edges do not match the explicit route graph.",
            )
        )
    expected_spans = tuple(
        (
            item.pathway_id,
            item.first_node_id,
            item.second_node_id,
            item.physical_wire_ids,
        )
        for item in pathway_span_membership(topology)
    )
    actual_spans = tuple(
        (
            item.pathway_id,
            item.first_node_id,
            item.second_node_id,
            item.physical_wire_ids,
        )
        for item in relationship_map.span_occupancy
    )
    if actual_spans != expected_spans:
        issues.append(
            RelationshipAuditIssue(
                "topology_span_occupancy_mismatch",
                "Topology span occupancy does not match the explicit route graph.",
            )
        )
    routes_by_wire = {route.wire_id: route for route in relationship_map.topology_routes}
    for physical_wire in topology.physical_wires:
        route = routes_by_wire.get(physical_wire.physical_wire_id)
        expected_route_edges = ordered_physical_wire_edges(
            topology,
            physical_wire.physical_wire_id,
        )
        if route is None or route.edge_ids != tuple(
            f"topology-edge:{edge.edge_id}" for edge in expected_route_edges
        ):
            issues.append(
                RelationshipAuditIssue(
                    "topology_route_mismatch",
                    "Physical-wire traversal does not match the explicit route graph.",
                    "physical_wire",
                    str(physical_wire.physical_wire_id),
                )
            )


def _topology_relationship_nodes(
    definition: HarnessDefinition,
) -> tuple[RelationshipNode, ...]:
    """
    Project every explicit graph node without collapsing pathway spans.
    """
    if definition.topology is None:
        return ()
    pathways = {item.pathway_id: item for item in definition.pathways}
    connections = {item.connection_id: item for item in definition.connections}
    kind_map = {
        TopologyNodeKind.EXTERNAL_END: RelationshipNodeKind.EXTERNAL_END,
        TopologyNodeKind.PATHWAY_END: RelationshipNodeKind.PATHWAY_END,
        TopologyNodeKind.JUNCTION: RelationshipNodeKind.JUNCTION,
    }
    return tuple(
        RelationshipNode(
            node_id=_topology_node_id(node.node_id),
            kind=kind_map[node.kind],
            member_id=node.node_id,
            label=_topology_node_label(node, pathways, connections),
        )
        for node in definition.topology.nodes
    )


def _topology_relationship_edges(
    definition: HarnessDefinition,
) -> tuple[RelationshipEdge, ...]:
    """
    Project every explicit directed route edge with its stable identity.
    """
    if definition.topology is None:
        return ()
    return tuple(
        RelationshipEdge(
            edge_id=f"topology-edge:{edge.edge_id}",
            wire_id=edge.physical_wire_id,
            source_node_id=_topology_node_id(edge.start_node_id),
            target_node_id=_topology_node_id(edge.end_node_id),
            sequence=index,
        )
        for index, edge in enumerate(definition.topology.edges)
    )


def _topology_relationship_routes(
    definition: HarnessDefinition,
) -> tuple[RelationshipRoute, ...]:
    """
    Project one deterministic route for each distinct physical wire leg.
    """
    topology = definition.topology
    if topology is None:
        return ()
    logical_wires = {wire.wire_id: wire for wire in definition.wires}
    primary_by_network = {
        physical.network_id: logical_wires[physical.physical_wire_id]
        for physical in topology.physical_wires
        if physical.physical_wire_id in logical_wires
    }
    routes: list[RelationshipRoute] = []
    for physical in topology.physical_wires:
        edges = ordered_physical_wire_edges(topology, physical.physical_wire_id)
        primary = primary_by_network.get(physical.network_id)
        if primary is None:
            wire_number = ""
            label = f"Physical wire {str(physical.physical_wire_id)[:8]}"
            primary_wire_id = None
        else:
            wire_number = primary.wire_number
            label = _wire_label(primary)
            primary_wire_id = primary.wire_id
            if physical.physical_wire_id != primary.wire_id:
                label = f"{label} branch {str(physical.physical_wire_id)[:8]}"
        node_ids = _edge_route_node_ids(edges)
        routes.append(
            RelationshipRoute(
                route_id=f"physical-wire:{physical.physical_wire_id}",
                wire_id=physical.physical_wire_id,
                wire_number=wire_number,
                label=label,
                node_ids=node_ids,
                edge_ids=tuple(f"topology-edge:{edge.edge_id}" for edge in edges),
                network_id=physical.network_id,
                primary_wire_id=primary_wire_id,
            )
        )
    return tuple(routes)


def _topology_span_occupancy(
    definition: HarnessDefinition,
) -> tuple[RelationshipSpanOccupancy, ...]:
    """
    Project exact per-span membership for capacity and diagram consumers.
    """
    if definition.topology is None:
        return ()
    return tuple(
        RelationshipSpanOccupancy(
            item.pathway_id,
            item.first_node_id,
            item.second_node_id,
            item.physical_wire_ids,
        )
        for item in pathway_span_membership(definition.topology)
    )


def _edge_route_node_ids(edges: tuple[RouteEdge, ...]) -> tuple[str, ...]:
    """
    Convert an ordered edge collection into its ordered topology-node sequence.
    """
    if not edges:
        return ()
    return (
        _topology_node_id(edges[0].start_node_id),
        *(_topology_node_id(edge.end_node_id) for edge in edges),
    )


def _topology_node_label(
    node: TopologyNode,
    pathways: dict[UUID, PathwayDefinition],
    connections: dict[UUID, Connection],
) -> str:
    """
    Resolve a compact graph-node label from current domain names.
    """
    if node.kind is TopologyNodeKind.EXTERNAL_END:
        connection_id = node.connection_id
        connection = None if connection_id is None else connections.get(connection_id)
        return connection.name if connection is not None else "Missing external end"
    pathway_id = node.pathway_id
    pathway = None if pathway_id is None else pathways.get(pathway_id)
    pathway_name = pathway.name if pathway is not None else "Missing pathway"
    if node.kind is TopologyNodeKind.PATHWAY_END:
        suffix = node.pathway_end.value.upper() if node.pathway_end is not None else "?"
        return f"{pathway_name} / {suffix}"
    if node.name:
        return node.name
    distance = node.distance_mm if node.distance_mm is not None else 0.0
    return f"{pathway_name} junction at {distance:g} mm"


def _topology_node_id(node_id: UUID) -> str:
    """
    Create a stable presentation identity for one topology node.
    """
    return f"topology:{node_id}"


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


def _wire_node_ids(wire: WireDefinition) -> tuple[str, ...]:
    """
    Return the typed node sequence for a wire-like domain object.
    """
    return (
        _node_id(RelationshipNodeKind.CONNECTION, wire.start_connection_id),
        *(
            _node_id(RelationshipNodeKind.PATHWAY, pathway_id)
            for pathway_id in wire.ordered_pathway_ids
        ),
        _node_id(RelationshipNodeKind.CONNECTION, wire.end_connection_id),
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
