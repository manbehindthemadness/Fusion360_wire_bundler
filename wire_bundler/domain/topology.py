"""
Host-independent route-graph construction and deterministic membership queries.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional
from uuid import UUID, uuid5

from .model import (
    JunctionDisposition,
    PathwayDefinition,
    PathwayEnd,
    PathwayExitState,
    PhysicalWire,
    RouteEdge,
    RouteEdgeKind,
    RouteTopology,
    TopologyNode,
    TopologyNodeKind,
    WireDefinition,
)

DEFAULT_JUNCTION_DIAMETER_FACTOR = 2.0


@dataclass(frozen=True)
class PathwaySpanMembership:
    """
    Describe the physical wires occupying one undirected pathway span.
    """

    pathway_id: UUID
    first_node_id: UUID
    second_node_id: UUID
    physical_wire_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class PathwayExitStatus:
    """
    Report derived continuity for one wire at one pathway endpoint.
    """

    pathway_id: UUID
    pathway_end: PathwayEnd
    physical_wire_id: UUID
    state: PathwayExitState


def junction_required_diameter(
    topology: RouteTopology,
    junction_id: UUID,
    ordinary_bundle_diameter_mm: float,
) -> Optional[float]:
    """
    Return the routing-gate junction envelope required by true branch members.

    Empty, virtual, redirect-only, and exclusion-only junctions do not expand the
    ordinary bundle envelope. A nullable override follows the default factor 2.0.
    """
    if not math.isfinite(ordinary_bundle_diameter_mm) or ordinary_bundle_diameter_mm <= 0:
        raise ValueError("Ordinary bundle diameter must be finite and positive.")
    junction = next(
        (
            node
            for node in topology.nodes
            if node.node_id == junction_id and node.kind is TopologyNodeKind.JUNCTION
        ),
        None,
    )
    if junction is None:
        raise ValueError("Selected junction does not exist.")
    if junction.slice_control_id is None or not any(
        item.junction_id == junction_id and item.disposition is JunctionDisposition.BRANCH
        for item in topology.junction_dispositions
    ):
        return None
    factor = junction.junction_diameter_factor_override or DEFAULT_JUNCTION_DIAMETER_FACTOR
    return ordinary_bundle_diameter_mm * factor


def build_linear_topology(
    wires: tuple[WireDefinition, ...],
    pathways: tuple[PathwayDefinition, ...],
) -> RouteTopology:
    """
    Project legacy ordered routes into a deterministic schema-v5 graph.

    Empty pathways receive stable endpoint nodes but no route edges. A legacy wire
    keeps its existing UUID as its primary physical-wire identity.
    """
    pathways_by_id = {pathway.pathway_id: pathway for pathway in pathways}
    nodes_by_id: dict[UUID, TopologyNode] = {}
    physical_wires: list[PhysicalWire] = []
    edges: list[RouteEdge] = []

    for pathway in pathways:
        for pathway_end in PathwayEnd:
            node = _pathway_end_node(pathway.pathway_id, pathway_end)
            nodes_by_id[node.node_id] = node

    for wire in wires:
        network_id = uuid5(wire.wire_id, "topology:network")
        physical_wires.append(PhysicalWire(wire.wire_id, network_id, wire.profile_id))
        end_a = TopologyNode(
            node_id=uuid5(wire.wire_id, "topology:external-end:a"),
            kind=TopologyNodeKind.EXTERNAL_END,
            connection_id=wire.start_connection_id,
            physical_wire_id=wire.wire_id,
        )
        end_b = TopologyNode(
            node_id=uuid5(wire.wire_id, "topology:external-end:b"),
            kind=TopologyNodeKind.EXTERNAL_END,
            connection_id=wire.end_connection_id,
            physical_wire_id=wire.wire_id,
        )
        nodes_by_id[end_a.node_id] = end_a
        nodes_by_id[end_b.node_id] = end_b

        route_pathways = tuple(
            pathways_by_id[pathway_id]
            for pathway_id in wire.ordered_pathway_ids
            if pathway_id in pathways_by_id
        )
        if not route_pathways:
            continue

        first_node = _pathway_end_node(route_pathways[0].pathway_id, PathwayEnd.A)
        edges.append(
            _edge(wire.wire_id, 0, RouteEdgeKind.END_LINK, end_a.node_id, first_node.node_id)
        )
        edge_index = 1
        previous_end_id: Optional[UUID] = None
        for pathway in route_pathways:
            pathway_start = _pathway_end_node(pathway.pathway_id, PathwayEnd.A)
            pathway_end = _pathway_end_node(pathway.pathway_id, PathwayEnd.B)
            if previous_end_id is not None:
                edges.append(
                    _edge(
                        wire.wire_id,
                        edge_index,
                        RouteEdgeKind.EXTENSION,
                        previous_end_id,
                        pathway_start.node_id,
                    )
                )
                edge_index += 1
            edges.append(
                _edge(
                    wire.wire_id,
                    edge_index,
                    RouteEdgeKind.PATHWAY,
                    pathway_start.node_id,
                    pathway_end.node_id,
                    pathway.pathway_id,
                )
            )
            edge_index += 1
            previous_end_id = pathway_end.node_id

        assert previous_end_id is not None
        edges.append(
            _edge(
                wire.wire_id,
                edge_index,
                RouteEdgeKind.END_LINK,
                previous_end_id,
                end_b.node_id,
            )
        )

    return RouteTopology(
        nodes=tuple(nodes_by_id.values()),
        physical_wires=tuple(physical_wires),
        edges=tuple(edges),
    )


def pathway_span_membership(topology: RouteTopology) -> tuple[PathwaySpanMembership, ...]:
    """
    Compute deterministic physical-wire membership for every occupied pathway span.
    """
    members: dict[tuple[UUID, UUID, UUID], set[UUID]] = defaultdict(set)
    for edge in topology.edges:
        if edge.kind is not RouteEdgeKind.PATHWAY or edge.pathway_id is None:
            continue
        first_node_id, second_node_id = sorted(
            (edge.start_node_id, edge.end_node_id), key=lambda identity: identity.hex
        )
        members[(edge.pathway_id, first_node_id, second_node_id)].add(edge.physical_wire_id)

    return tuple(
        PathwaySpanMembership(
            pathway_id=pathway_id,
            first_node_id=first_node_id,
            second_node_id=second_node_id,
            physical_wire_ids=tuple(sorted(wire_ids, key=lambda identity: identity.hex)),
        )
        for (pathway_id, first_node_id, second_node_id), wire_ids in sorted(
            members.items(),
            key=lambda item: tuple(identity.hex for identity in item[0]),
        )
    )


def pathway_exit_states(topology: RouteTopology) -> tuple[PathwayExitStatus, ...]:
    """
    Derive OPEN, TERMINATED, or EXTENDED for every occupied pathway endpoint.

    An end link terminates a trace and an extension or junction transition continues
    it. A pathway endpoint with no adjacent continuation remains open for editing.
    """
    nodes = {node.node_id: node for node in topology.nodes}
    incident_edges: dict[tuple[UUID, UUID], list[RouteEdge]] = defaultdict(list)
    occupied: set[tuple[UUID, UUID]] = set()
    for edge in topology.edges:
        incident_edges[(edge.start_node_id, edge.physical_wire_id)].append(edge)
        incident_edges[(edge.end_node_id, edge.physical_wire_id)].append(edge)
        if edge.kind is RouteEdgeKind.PATHWAY:
            occupied.add((edge.start_node_id, edge.physical_wire_id))
            occupied.add((edge.end_node_id, edge.physical_wire_id))

    statuses: list[PathwayExitStatus] = []
    for node_id, physical_wire_id in occupied:
        node = nodes.get(node_id)
        if (
            node is None
            or node.kind is not TopologyNodeKind.PATHWAY_END
            or node.pathway_id is None
            or node.pathway_end is None
        ):
            continue
        adjacent_kinds = {
            edge.kind
            for edge in incident_edges[(node_id, physical_wire_id)]
            if edge.kind is not RouteEdgeKind.PATHWAY
        }
        if RouteEdgeKind.END_LINK in adjacent_kinds:
            state = PathwayExitState.TERMINATED
        elif adjacent_kinds & {
            RouteEdgeKind.EXTENSION,
            RouteEdgeKind.JUNCTION_TRANSITION,
        }:
            state = PathwayExitState.EXTENDED
        else:
            state = PathwayExitState.OPEN
        statuses.append(
            PathwayExitStatus(
                pathway_id=node.pathway_id,
                pathway_end=node.pathway_end,
                physical_wire_id=physical_wire_id,
                state=state,
            )
        )

    return tuple(
        sorted(
            statuses,
            key=lambda item: (
                item.pathway_id.hex,
                item.pathway_end.value,
                item.physical_wire_id.hex,
            ),
        )
    )


def ordered_physical_wire_edges(
    topology: RouteTopology,
    physical_wire_id: UUID,
) -> tuple[RouteEdge, ...]:
    """
    Return a physical leg's directed edges in deterministic traversal order.

    Valid M2 legs are unbranched and acyclic. For an invalid partial graph, separate
    components and ambiguous successors still receive stable UUID ordering so callers
    can display the repairable state before validation succeeds.
    """
    remaining = {
        edge.edge_id: edge for edge in topology.edges if edge.physical_wire_id == physical_wire_id
    }
    ordered: list[RouteEdge] = []
    while remaining:
        remaining_edges = tuple(remaining.values())
        end_node_ids = {edge.end_node_id for edge in remaining_edges}
        candidates = [edge for edge in remaining_edges if edge.start_node_id not in end_node_ids]
        current = min(
            candidates or list(remaining_edges),
            key=lambda edge: (edge.start_node_id.hex, edge.edge_id.hex),
        )
        while current.edge_id in remaining:
            ordered.append(current)
            del remaining[current.edge_id]
            successors = [
                edge for edge in remaining.values() if edge.start_node_id == current.end_node_id
            ]
            if not successors:
                break
            current = min(successors, key=lambda edge: edge.edge_id.hex)
    return tuple(ordered)


def _pathway_end_node(pathway_id: UUID, pathway_end: PathwayEnd) -> TopologyNode:
    """
    Create one deterministic pathway endpoint node.
    """
    return TopologyNode(
        node_id=pathway_end_node_id(pathway_id, pathway_end),
        kind=TopologyNodeKind.PATHWAY_END,
        pathway_id=pathway_id,
        pathway_end=pathway_end,
    )


def pathway_end_node_id(pathway_id: UUID, pathway_end: PathwayEnd) -> UUID:
    """
    Return the deterministic topology-node identity for one pathway endpoint.
    """
    return uuid5(pathway_id, f"topology:pathway-end:{pathway_end.value}")


def _edge(
    wire_id: UUID,
    index: int,
    kind: RouteEdgeKind,
    start_node_id: UUID,
    end_node_id: UUID,
    pathway_id: Optional[UUID] = None,
) -> RouteEdge:
    """
    Create one deterministic edge in a migrated linear route.
    """
    edge_id = uuid5(
        wire_id,
        f"topology:edge:{index}:{kind.value}:{start_node_id}:{end_node_id}",
    )
    return RouteEdge(
        edge_id=edge_id,
        kind=kind,
        physical_wire_id=wire_id,
        start_node_id=start_node_id,
        end_node_id=end_node_id,
        pathway_id=pathway_id,
    )
