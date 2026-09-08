"""
Apply persistent schema-v5 topology edits as atomic harness-definition replacements.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace
from typing import Optional, Protocol
from uuid import UUID, uuid4

from ..domain import (
    Connection,
    ControlKind,
    ElectricalRelationship,
    ElectricalRelationshipKind,
    HarnessDefinition,
    JunctionAttachment,
    JunctionDisposition,
    JunctionMemberDisposition,
    PathwayDefinition,
    PathwayEnd,
    PathwayExitState,
    PhysicalWire,
    RouteEdge,
    RouteEdgeKind,
    RouteTopology,
    TopologyNode,
    TopologyNodeKind,
    dumps,
    loads,
    next_available_name,
    pathway_end_node_id,
    pathway_exit_states,
)


class TopologyEditGateway(Protocol):
    """
    Describe persisted harness operations required by topology editing.
    """

    def read_harness_definition(self, harness_id: UUID) -> str:
        """
        Return the serialized definition owned by one harness.
        """

    def replace_harness_definition(
        self,
        harness_id: UUID,
        serialized_definition: str,
    ) -> None:
        """
        Replace the serialized definition owned by one harness.
        """


class TopologyUpdateError(RuntimeError):
    """
    Report a topology edit that failed and could not be rolled back cleanly.
    """


def extend_pathway_member(
    harness_id: UUID,
    physical_wire_id: UUID,
    source_pathway_id: UUID,
    source_end: PathwayEnd,
    target_pathway_id: UUID,
    target_end: PathwayEnd,
    gateway: TopologyEditGateway,
    id_factory: Callable[[], UUID] = uuid4,
) -> tuple[RouteEdge, RouteEdge]:
    """
    Continue one open physical member through an ordinary target pathway.

    The source and target are explicit A/B routing gates. The operation adds one
    logical extension followed by the target pathway span, leaving the far target
    gate open until it is extended again or terminated with an external end.
    """
    if source_pathway_id == target_pathway_id:
        raise ValueError("An extension must connect two different pathways.")
    original, definition = _read_definition(harness_id, gateway)
    topology = _require_explicit_topology(definition)
    _require_pathway(definition, source_pathway_id)
    _require_pathway(definition, target_pathway_id)
    _require_physical_wire(topology, physical_wire_id)
    topology = _ensure_pathway_end_nodes(topology, source_pathway_id)
    topology = _ensure_pathway_end_nodes(topology, target_pathway_id)
    source_node_id = pathway_end_node_id(source_pathway_id, source_end)
    target_node_id = pathway_end_node_id(target_pathway_id, target_end)

    source_edges = _incident_wire_edges(topology, physical_wire_id, source_node_id)
    if not any(
        edge.kind is RouteEdgeKind.PATHWAY
        and edge.pathway_id == source_pathway_id
        and edge.end_node_id == source_node_id
        for edge in source_edges
    ):
        raise ValueError("Extension source must be the downstream open gate of this member.")
    source_status = next(
        (
            status
            for status in pathway_exit_states(topology)
            if status.pathway_id == source_pathway_id
            and status.pathway_end is source_end
            and status.physical_wire_id == physical_wire_id
        ),
        None,
    )
    if source_status is None or source_status.state is not PathwayExitState.OPEN:
        raise ValueError("Extension source gate is already connected or terminated.")
    if _incident_wire_edges(topology, physical_wire_id, target_node_id):
        raise ValueError("Target gate is already occupied by this physical member.")
    if any(
        attachment.pathway_id == target_pathway_id and attachment.pathway_end is target_end
        for attachment in topology.junction_attachments
    ):
        raise ValueError("Target gate is reserved by a junction attachment.")
    if any(
        edge.kind is RouteEdgeKind.PATHWAY
        and edge.pathway_id == target_pathway_id
        and edge.physical_wire_id == physical_wire_id
        for edge in topology.edges
    ):
        raise ValueError("This physical member already occupies the target pathway.")

    used_ids = _definition_ids(definition, topology)
    opposite_target_end = PathwayEnd.B if target_end is PathwayEnd.A else PathwayEnd.A
    extension = RouteEdge(
        _allocate_id(id_factory, used_ids, "extension"),
        RouteEdgeKind.EXTENSION,
        physical_wire_id,
        source_node_id,
        target_node_id,
        name=next_available_name(
            "Extension 1",
            (
                edge.name
                for edge in topology.edges
                if edge.kind is RouteEdgeKind.EXTENSION and edge.name
            ),
        ),
    )
    pathway_edge = RouteEdge(
        _allocate_id(id_factory, used_ids, "extended pathway span"),
        RouteEdgeKind.PATHWAY,
        physical_wire_id,
        target_node_id,
        pathway_end_node_id(target_pathway_id, opposite_target_end),
        target_pathway_id,
    )
    updated_topology = replace(topology, edges=topology.edges + (extension, pathway_edge))
    _persist(
        harness_id,
        original,
        replace(definition, topology=updated_topology),
        gateway,
    )
    return extension, pathway_edge


def rename_pathway_extension(
    harness_id: UUID,
    extension_edge_id: UUID,
    name: str,
    gateway: TopologyEditGateway,
) -> RouteEdge:
    """
    Rename one extension with a non-empty conflict-free display name.
    """
    original, definition = _read_definition(harness_id, gateway)
    topology = _require_explicit_topology(definition)
    extension = _require_extension(topology, extension_edge_id)
    normalized = name.strip()
    if not normalized:
        raise ValueError("Extension name must not be empty.")
    resolved = next_available_name(
        normalized,
        (
            edge.name
            for edge in topology.edges
            if edge.kind is RouteEdgeKind.EXTENSION
            and edge.edge_id != extension_edge_id
            and edge.name
        ),
    )
    updated = replace(extension, name=resolved)
    updated_topology = replace(
        topology,
        edges=tuple(
            updated if edge.edge_id == extension_edge_id else edge for edge in topology.edges
        ),
    )
    _persist(
        harness_id,
        original,
        replace(definition, topology=updated_topology),
        gateway,
    )
    return updated


def disconnect_pathway_extension(
    harness_id: UUID,
    extension_edge_id: UUID,
    gateway: TopologyEditGateway,
) -> None:
    """
    Remove one selected extension while retaining both editable route fragments.
    """
    original, definition = _read_definition(harness_id, gateway)
    topology = _require_explicit_topology(definition)
    _require_extension(topology, extension_edge_id)
    updated_topology = replace(
        topology,
        edges=tuple(edge for edge in topology.edges if edge.edge_id != extension_edge_id),
    )
    _persist(
        harness_id,
        original,
        replace(definition, topology=updated_topology),
        gateway,
    )


def add_external_end(
    harness_id: UUID,
    physical_wire_id: UUID,
    pathway_id: UUID,
    pathway_end: PathwayEnd,
    connection: Connection,
    gateway: TopologyEditGateway,
    id_factory: Callable[[], UUID] = uuid4,
) -> TopologyNode:
    """
    Terminate one open downstream pathway gate at a new physical connection.
    """
    original, definition = _read_definition(harness_id, gateway)
    topology = _require_explicit_topology(definition)
    _require_pathway(definition, pathway_id)
    _require_physical_wire(topology, physical_wire_id)
    if any(item.connection_id == connection.connection_id for item in definition.connections):
        raise ValueError("External-end connection identity already exists.")
    if not connection.name.strip() or not connection.entity_token.strip():
        raise ValueError("External-end connection requires a name and linked geometry token.")
    endpoint_id = pathway_end_node_id(pathway_id, pathway_end)
    incident = _incident_wire_edges(topology, physical_wire_id, endpoint_id)
    if not any(
        edge.kind is RouteEdgeKind.PATHWAY
        and edge.pathway_id == pathway_id
        and edge.end_node_id == endpoint_id
        for edge in incident
    ):
        raise ValueError("External end must terminate the downstream open gate of this member.")
    if any(edge.kind is not RouteEdgeKind.PATHWAY for edge in incident):
        raise ValueError("Selected pathway gate is already connected or terminated.")

    used_ids = _definition_ids(definition, topology)
    if connection.connection_id in used_ids:
        raise ValueError("External-end connection identity collides with existing harness data.")
    used_ids.add(connection.connection_id)
    external_end = TopologyNode(
        node_id=_allocate_id(id_factory, used_ids, "external end"),
        kind=TopologyNodeKind.EXTERNAL_END,
        connection_id=connection.connection_id,
        physical_wire_id=physical_wire_id,
    )
    end_link = RouteEdge(
        edge_id=_allocate_id(id_factory, used_ids, "external end link"),
        kind=RouteEdgeKind.END_LINK,
        physical_wire_id=physical_wire_id,
        start_node_id=endpoint_id,
        end_node_id=external_end.node_id,
    )
    updated_topology = replace(
        topology,
        nodes=topology.nodes + (external_end,),
        edges=topology.edges + (end_link,),
    )
    _persist(
        harness_id,
        original,
        replace(
            definition,
            connections=definition.connections + (connection,),
            topology=updated_topology,
        ),
        gateway,
    )
    return external_end


def add_junction_pigtail_end(
    harness_id: UUID,
    junction_id: UUID,
    incoming_wire_id: UUID,
    connection: Connection,
    gateway: TopologyEditGateway,
    id_factory: Callable[[], UUID] = uuid4,
) -> TopologyNode:
    """
    Add a distinct terminated pigtail leg while the incoming trace continues.
    """
    original, definition = _read_definition(harness_id, gateway)
    topology = _require_explicit_topology(definition)
    junction = _require_junction(topology, junction_id)
    incoming_wire = _require_physical_wire(topology, incoming_wire_id)
    _require_wire_at_junction(topology, junction, incoming_wire_id)
    if any(item.connection_id == connection.connection_id for item in definition.connections):
        raise ValueError("Pigtail connection identity already exists.")
    if not connection.name.strip() or not connection.entity_token.strip():
        raise ValueError("Pigtail connection requires a name and linked geometry token.")

    used_ids = _definition_ids(definition, topology)
    if connection.connection_id in used_ids:
        raise ValueError("Pigtail connection identity collides with existing harness data.")
    used_ids.add(connection.connection_id)
    pigtail_wire_id = _allocate_id(id_factory, used_ids, "pigtail physical wire")
    external_end = TopologyNode(
        node_id=_allocate_id(id_factory, used_ids, "pigtail external end"),
        kind=TopologyNodeKind.EXTERNAL_END,
        connection_id=connection.connection_id,
        physical_wire_id=pigtail_wire_id,
    )
    end_link = RouteEdge(
        edge_id=_allocate_id(id_factory, used_ids, "pigtail end link"),
        kind=RouteEdgeKind.END_LINK,
        physical_wire_id=pigtail_wire_id,
        start_node_id=junction_id,
        end_node_id=external_end.node_id,
    )
    pigtail_wire = PhysicalWire(
        pigtail_wire_id,
        incoming_wire.network_id,
        incoming_wire.profile_id,
    )
    relationship = ElectricalRelationship(
        relationship_id=_allocate_id(id_factory, used_ids, "pigtail electrical relationship"),
        kind=ElectricalRelationshipKind.IDEAL_SPLICE,
        junction_id=junction_id,
        physical_wire_ids=(incoming_wire_id, pigtail_wire_id),
    )
    updated_topology = replace(
        topology,
        nodes=topology.nodes + (external_end,),
        physical_wires=topology.physical_wires + (pigtail_wire,),
        edges=topology.edges + (end_link,),
        electrical_relationships=topology.electrical_relationships + (relationship,),
    )
    _persist(
        harness_id,
        original,
        replace(
            definition,
            connections=definition.connections + (connection,),
            topology=updated_topology,
        ),
        gateway,
    )
    return external_end


def remove_external_end(
    harness_id: UUID,
    external_end_node_id: UUID,
    gateway: TopologyEditGateway,
) -> None:
    """
    Remove one added end and its link, preserving the now-open route for editing.
    """
    original, definition = _read_definition(harness_id, gateway)
    topology = _require_explicit_topology(definition)
    external_end = next(
        (
            node
            for node in topology.nodes
            if node.node_id == external_end_node_id and node.kind is TopologyNodeKind.EXTERNAL_END
        ),
        None,
    )
    if external_end is None:
        raise ValueError("Selected external end does not exist.")
    links = [
        edge
        for edge in topology.edges
        if edge.kind is RouteEdgeKind.END_LINK
        and external_end_node_id in {edge.start_node_id, edge.end_node_id}
    ]
    if len(links) != 1:
        raise ValueError("External end must have exactly one link before removal.")
    legacy_connection_ids = {
        connection_id
        for wire in definition.wires
        for connection_id in (wire.start_connection_id, wire.end_connection_id)
    }
    remaining_nodes = tuple(node for node in topology.nodes if node.node_id != external_end_node_id)
    remaining_connection_ids = {
        node.connection_id
        for node in remaining_nodes
        if node.kind is TopologyNodeKind.EXTERNAL_END and node.connection_id is not None
    }
    removable_connection_id = external_end.connection_id
    connections = definition.connections
    if (
        removable_connection_id is not None
        and removable_connection_id not in legacy_connection_ids
        and removable_connection_id not in remaining_connection_ids
    ):
        connections = tuple(
            connection
            for connection in definition.connections
            if connection.connection_id != removable_connection_id
        )
    updated_topology = replace(
        topology,
        nodes=remaining_nodes,
        edges=tuple(edge for edge in topology.edges if edge not in links),
    )
    _persist(
        harness_id,
        original,
        replace(definition, connections=connections, topology=updated_topology),
        gateway,
    )


def add_junction(
    harness_id: UUID,
    parent_pathway_id: UUID,
    distance_mm: float,
    gateway: TopologyEditGateway,
    slice_control_id: Optional[UUID] = None,
    junction_diameter_factor_override: Optional[float] = None,
    id_factory: Callable[[], UUID] = uuid4,
    name: str = "Junction 1",
) -> TopologyNode:
    """
    Insert a movable junction node and bisect every occupied parent-pathway span.
    """
    _require_nonnegative_finite(distance_mm, "Junction distance")
    if junction_diameter_factor_override is not None:
        _require_positive_finite(
            junction_diameter_factor_override,
            "Junction diameter factor",
        )
        if slice_control_id is None:
            raise ValueError("A junction diameter factor requires a routing-gate slice.")

    original, definition = _read_definition(harness_id, gateway)
    pathway = _require_pathway(definition, parent_pathway_id)
    if slice_control_id is not None:
        control = next(
            (item for item in definition.controls if item.control_id == slice_control_id),
            None,
        )
        if (
            control is None
            or control.kind is not ControlKind.ROUTING_GATE
            or slice_control_id not in pathway.ordered_control_ids
        ):
            raise ValueError("Junction slice control must be a routing gate on the parent pathway.")

    topology = definition.resolved_topology
    normalized_name = next_available_name(
        name.strip() or "Junction 1",
        (
            node.name
            for node in topology.nodes
            if node.kind is TopologyNodeKind.JUNCTION and node.name
        ),
    )
    if any(
        node.kind is TopologyNodeKind.JUNCTION
        and node.pathway_id == parent_pathway_id
        and node.distance_mm == distance_mm
        for node in topology.nodes
    ):
        raise ValueError("A junction already exists at this pathway distance.")

    used_ids = _definition_ids(definition, topology)
    junction_id = _allocate_id(id_factory, used_ids, "junction")
    junction = TopologyNode(
        node_id=junction_id,
        kind=TopologyNodeKind.JUNCTION,
        pathway_id=parent_pathway_id,
        distance_mm=distance_mm,
        slice_control_id=slice_control_id,
        junction_diameter_factor_override=junction_diameter_factor_override,
        name=normalized_name,
    )
    edges: list[RouteEdge] = []
    for edge in topology.edges:
        if (
            edge.kind is RouteEdgeKind.PATHWAY
            and edge.pathway_id == parent_pathway_id
            and _span_contains_distance(topology, edge, distance_mm)
        ):
            first_edge_id = _allocate_id(id_factory, used_ids, "pathway span")
            second_edge_id = _allocate_id(id_factory, used_ids, "pathway span")
            edges.extend(
                (
                    replace(
                        edge,
                        edge_id=first_edge_id,
                        end_node_id=junction_id,
                    ),
                    replace(
                        edge,
                        edge_id=second_edge_id,
                        start_node_id=junction_id,
                    ),
                )
            )
        else:
            edges.append(edge)

    updated_topology = replace(
        topology,
        nodes=topology.nodes + (junction,),
        edges=tuple(edges),
    )
    _persist(
        harness_id,
        original,
        replace(definition, topology=updated_topology),
        gateway,
    )
    return junction


def rename_junction(
    harness_id: UUID,
    junction_id: UUID,
    name: str,
    gateway: TopologyEditGateway,
) -> TopologyNode:
    """
    Rename one junction with a non-empty conflict-free display name.
    """
    original, definition = _read_definition(harness_id, gateway)
    topology = _require_explicit_topology(definition)
    junction = _require_junction(topology, junction_id)
    normalized = name.strip()
    if not normalized:
        raise ValueError("Junction name must not be empty.")
    unavailable = (
        node.name
        for node in topology.nodes
        if node.kind is TopologyNodeKind.JUNCTION and node.node_id != junction_id and node.name
    )
    resolved = next_available_name(normalized, unavailable)
    updated = replace(junction, name=resolved)
    updated_topology = replace(
        topology,
        nodes=tuple(updated if node.node_id == junction_id else node for node in topology.nodes),
    )
    _persist(
        harness_id,
        original,
        replace(definition, topology=updated_topology),
        gateway,
    )
    return updated


def move_junction(
    harness_id: UUID,
    junction_id: UUID,
    distance_mm: float,
    gateway: TopologyEditGateway,
) -> TopologyNode:
    """
    Move a junction within its current adjacent pathway span.
    """
    _require_nonnegative_finite(distance_mm, "Junction distance")
    original, definition = _read_definition(harness_id, gateway)
    topology = _require_explicit_topology(definition)
    junction = _require_junction(topology, junction_id)
    if junction.distance_mm == distance_mm:
        return junction
    if any(
        node.kind is TopologyNodeKind.JUNCTION
        and node.node_id != junction_id
        and node.pathway_id == junction.pathway_id
        and node.distance_mm == distance_mm
        for node in topology.nodes
    ):
        raise ValueError("A junction already exists at this pathway distance.")

    for edge in topology.edges:
        if (
            edge.kind is not RouteEdgeKind.PATHWAY
            or edge.pathway_id != junction.pathway_id
            or junction_id not in {edge.start_node_id, edge.end_node_id}
        ):
            continue
        other_node_id = (
            edge.end_node_id if edge.start_node_id == junction_id else edge.start_node_id
        )
        other_position = _node_position(topology, other_node_id)
        old_position = _node_position(topology, junction_id)
        if distance_mm <= other_position < old_position:
            raise ValueError("Junction movement cannot cross an adjacent slice.")
        if distance_mm >= other_position > old_position:
            raise ValueError("Junction movement cannot cross an adjacent slice.")

    moved = replace(junction, distance_mm=distance_mm)
    updated_topology = replace(
        topology,
        nodes=tuple(moved if node.node_id == junction_id else node for node in topology.nodes),
    )
    _persist(
        harness_id,
        original,
        replace(definition, topology=updated_topology),
        gateway,
    )
    return moved


def set_junction_diameter_factor(
    harness_id: UUID,
    junction_id: UUID,
    factor: Optional[float],
    gateway: TopologyEditGateway,
) -> TopologyNode:
    """
    Set or clear a routing-gate junction's positive unitless diameter factor.
    """
    if factor is not None:
        _require_positive_finite(factor, "Junction diameter factor")
    original, definition = _read_definition(harness_id, gateway)
    topology = _require_explicit_topology(definition)
    junction = _require_junction(topology, junction_id)
    if junction.slice_control_id is None and factor is not None:
        raise ValueError("A junction diameter factor requires a routing-gate slice.")
    updated = replace(junction, junction_diameter_factor_override=factor)
    updated_topology = replace(
        topology,
        nodes=tuple(updated if node.node_id == junction_id else node for node in topology.nodes),
    )
    _persist(
        harness_id,
        original,
        replace(definition, topology=updated_topology),
        gateway,
    )
    return updated


def attach_pathway_to_junction(
    harness_id: UUID,
    junction_id: UUID,
    pathway_id: UUID,
    pathway_end: PathwayEnd,
    gateway: TopologyEditGateway,
) -> JunctionAttachment:
    """
    Attach an empty ordinary pathway endpoint to a junction slice.
    """
    original, definition = _read_definition(harness_id, gateway)
    topology = _require_explicit_topology(definition)
    junction = _require_junction(topology, junction_id)
    _require_pathway(definition, pathway_id)
    if pathway_id == junction.pathway_id:
        raise ValueError("A junction cannot attach its own parent pathway.")
    if any(
        edge.kind is RouteEdgeKind.PATHWAY and edge.pathway_id == pathway_id
        for edge in topology.edges
    ):
        raise ValueError("Only a pathway with no member wires may be attached.")
    if any(
        item.pathway_id == pathway_id and item.pathway_end is pathway_end
        for item in topology.junction_attachments
    ):
        raise ValueError("This pathway endpoint is already attached to a junction.")

    attachment = JunctionAttachment(junction_id, pathway_id, pathway_end)
    topology = _ensure_pathway_end_nodes(topology, pathway_id)
    updated_topology = replace(
        topology,
        junction_attachments=topology.junction_attachments + (attachment,),
    )
    _persist(
        harness_id,
        original,
        replace(definition, topology=updated_topology),
        gateway,
    )
    return attachment


def detach_pathway_from_junction(
    harness_id: UUID,
    junction_id: UUID,
    pathway_id: UUID,
    pathway_end: PathwayEnd,
    gateway: TopologyEditGateway,
) -> None:
    """
    Remove an empty junction attachment without deleting its ordinary pathway.
    """
    original, definition = _read_definition(harness_id, gateway)
    topology = _require_explicit_topology(definition)
    attachment = _require_attachment(topology, junction_id, pathway_id, pathway_end)
    if any(
        item.junction_id == junction_id
        and item.attachment_pathway_id == pathway_id
        and item.attachment_end is pathway_end
        for item in topology.junction_dispositions
    ):
        raise ValueError("Disconnect all junction members before detaching this pathway.")
    attachment_node_id = pathway_end_node_id(pathway_id, pathway_end)
    if any(
        edge.kind is RouteEdgeKind.JUNCTION_TRANSITION
        and edge.start_node_id == junction_id
        and edge.end_node_id == attachment_node_id
        for edge in topology.edges
    ):
        raise ValueError("Disconnect all junction transitions before detaching this pathway.")
    updated_topology = replace(
        topology,
        junction_attachments=tuple(
            item for item in topology.junction_attachments if item != attachment
        ),
    )
    _persist(
        harness_id,
        original,
        replace(definition, topology=updated_topology),
        gateway,
    )


def set_junction_member_disposition(
    harness_id: UUID,
    junction_id: UUID,
    pathway_id: UUID,
    pathway_end: PathwayEnd,
    incoming_wire_id: UUID,
    disposition: JunctionDisposition,
    gateway: TopologyEditGateway,
    id_factory: Callable[[], UUID] = uuid4,
) -> JunctionMemberDisposition:
    """
    Apply one member's exclusion, branch, or first-time redirect atomically.
    """
    original, definition = _read_definition(harness_id, gateway)
    topology = _require_explicit_topology(definition)
    _require_attachment(topology, junction_id, pathway_id, pathway_end)
    junction = _require_junction(topology, junction_id)
    incoming_wire = _require_physical_wire(topology, incoming_wire_id)
    _require_wire_at_junction(topology, junction, incoming_wire_id)

    existing = _find_disposition(
        topology,
        junction_id,
        pathway_id,
        pathway_end,
        incoming_wire_id,
    )
    if existing is not None and existing.disposition is disposition:
        return existing
    if existing is not None and existing.disposition is JunctionDisposition.REDIRECT_BRANCH:
        raise ValueError("A redirect must be changed with Undo or by repairing its detached route.")
    if existing is not None:
        topology = _remove_configurable_disposition(topology, existing)

    used_ids = _definition_ids(definition, topology)
    branch_wire_id: Optional[UUID] = None
    if disposition is JunctionDisposition.BRANCH:
        new_branch_wire_id = _allocate_id(
            id_factory,
            used_ids,
            "branch physical wire",
        )
        branch_wire_id = new_branch_wire_id
        branch_wire = PhysicalWire(
            new_branch_wire_id,
            incoming_wire.network_id,
            incoming_wire.profile_id,
        )
        topology = replace(
            topology,
            physical_wires=topology.physical_wires + (branch_wire,),
        )
        topology = _add_attached_path_edges(
            topology,
            junction_id,
            pathway_id,
            pathway_end,
            new_branch_wire_id,
            used_ids,
            id_factory,
        )
        relationship = ElectricalRelationship(
            relationship_id=_allocate_id(
                id_factory,
                used_ids,
                "electrical relationship",
            ),
            kind=ElectricalRelationshipKind.IDEAL_SPLICE,
            junction_id=junction_id,
            physical_wire_ids=(incoming_wire_id, new_branch_wire_id),
        )
        topology = replace(
            topology,
            electrical_relationships=topology.electrical_relationships + (relationship,),
        )
    elif disposition is JunctionDisposition.REDIRECT_BRANCH:
        topology = _redirect_member(
            topology,
            junction,
            pathway_id,
            pathway_end,
            incoming_wire_id,
            used_ids,
            id_factory,
        )

    member_disposition = JunctionMemberDisposition(
        junction_id=junction_id,
        attachment_pathway_id=pathway_id,
        attachment_end=pathway_end,
        incoming_wire_id=incoming_wire_id,
        disposition=disposition,
        branch_wire_id=branch_wire_id,
    )
    topology = replace(
        topology,
        junction_dispositions=topology.junction_dispositions + (member_disposition,),
    )
    _persist(
        harness_id,
        original,
        replace(definition, topology=topology),
        gateway,
    )
    return member_disposition


def branch_all_junction_members(
    harness_id: UUID,
    junction_id: UUID,
    pathway_id: UUID,
    pathway_end: PathwayEnd,
    gateway: TopologyEditGateway,
    id_factory: Callable[[], UUID] = uuid4,
) -> tuple[JunctionMemberDisposition, ...]:
    """
    Branch every eligible parent-pathway member into one attached empty pathway.
    """
    original, definition = _read_definition(harness_id, gateway)
    topology = _require_explicit_topology(definition)
    _require_attachment(topology, junction_id, pathway_id, pathway_end)
    junction = _require_junction(topology, junction_id)
    incoming_ids = _physical_wires_at_junction(topology, junction)
    if not incoming_ids:
        return ()

    updated = topology
    created: list[JunctionMemberDisposition] = []
    used_ids = _definition_ids(definition, topology)
    for incoming_wire_id in incoming_ids:
        if (
            _find_disposition(
                updated,
                junction_id,
                pathway_id,
                pathway_end,
                incoming_wire_id,
            )
            is not None
        ):
            continue
        incoming_wire = _require_physical_wire(updated, incoming_wire_id)
        branch_wire_id = _allocate_id(id_factory, used_ids, "branch physical wire")
        updated = replace(
            updated,
            physical_wires=updated.physical_wires
            + (
                PhysicalWire(
                    branch_wire_id,
                    incoming_wire.network_id,
                    incoming_wire.profile_id,
                ),
            ),
        )
        updated = _add_attached_path_edges(
            updated,
            junction_id,
            pathway_id,
            pathway_end,
            branch_wire_id,
            used_ids,
            id_factory,
        )
        relationship = ElectricalRelationship(
            _allocate_id(id_factory, used_ids, "electrical relationship"),
            ElectricalRelationshipKind.IDEAL_SPLICE,
            junction_id,
            (incoming_wire_id, branch_wire_id),
        )
        disposition = JunctionMemberDisposition(
            junction_id,
            pathway_id,
            pathway_end,
            incoming_wire_id,
            JunctionDisposition.BRANCH,
            branch_wire_id,
        )
        updated = replace(
            updated,
            junction_dispositions=updated.junction_dispositions + (disposition,),
            electrical_relationships=updated.electrical_relationships + (relationship,),
        )
        created.append(disposition)

    if not created:
        return ()
    _persist(
        harness_id,
        original,
        replace(definition, topology=updated),
        gateway,
    )
    return tuple(created)


def disconnect_junction_member(
    harness_id: UUID,
    junction_id: UUID,
    pathway_id: UUID,
    pathway_end: PathwayEnd,
    incoming_wire_id: UUID,
    gateway: TopologyEditGateway,
) -> None:
    """
    Remove only a selected attachment transition and retain repairable partial topology.
    """
    original, definition = _read_definition(harness_id, gateway)
    topology = _require_explicit_topology(definition)
    disposition = _find_disposition(
        topology,
        junction_id,
        pathway_id,
        pathway_end,
        incoming_wire_id,
    )
    if disposition is None:
        raise ValueError("Selected junction member does not exist.")
    transition_wire_id = disposition.branch_wire_id or disposition.incoming_wire_id
    attachment_node_id = pathway_end_node_id(pathway_id, pathway_end)
    updated_topology = replace(
        topology,
        edges=tuple(
            edge
            for edge in topology.edges
            if not (
                edge.kind is RouteEdgeKind.JUNCTION_TRANSITION
                and edge.physical_wire_id == transition_wire_id
                and edge.start_node_id == junction_id
                and edge.end_node_id == attachment_node_id
            )
        ),
        junction_dispositions=tuple(
            item for item in topology.junction_dispositions if item != disposition
        ),
    )
    _persist(
        harness_id,
        original,
        replace(definition, topology=updated_topology),
        gateway,
    )


def cleanup_orphaned_topology(
    harness_id: UUID,
    gateway: TopologyEditGateway,
) -> tuple[UUID, ...]:
    """
    Remove unused nonprimary physical legs left by explicit edge deletion.
    """
    original, definition = _read_definition(harness_id, gateway)
    topology = _require_explicit_topology(definition)
    primary_ids = {wire.wire_id for wire in definition.wires}
    referenced_by_disposition = {
        wire_id
        for item in topology.junction_dispositions
        for wire_id in (item.incoming_wire_id, item.branch_wire_id)
        if wire_id is not None
    }
    external_wire_ids = {
        node.physical_wire_id
        for node in topology.nodes
        if node.kind is TopologyNodeKind.EXTERNAL_END and node.physical_wire_id is not None
    }
    removed_ids = tuple(
        sorted(
            (
                wire.physical_wire_id
                for wire in topology.physical_wires
                if wire.physical_wire_id not in primary_ids
                and wire.physical_wire_id not in referenced_by_disposition
                and wire.physical_wire_id not in external_wire_ids
            ),
            key=lambda identity: identity.hex,
        )
    )
    if not removed_ids:
        return ()
    removed = set(removed_ids)
    updated_topology = replace(
        topology,
        physical_wires=tuple(
            wire for wire in topology.physical_wires if wire.physical_wire_id not in removed
        ),
        edges=tuple(edge for edge in topology.edges if edge.physical_wire_id not in removed),
        electrical_relationships=tuple(
            relationship
            for relationship in topology.electrical_relationships
            if not (set(relationship.physical_wire_ids) & removed)
        ),
    )
    _persist(
        harness_id,
        original,
        replace(definition, topology=updated_topology),
        gateway,
    )
    return removed_ids


def remove_junction(
    harness_id: UUID,
    junction_id: UUID,
    gateway: TopologyEditGateway,
    id_factory: Callable[[], UUID] = uuid4,
) -> None:
    """
    Remove an unattached junction and merge each bisected parent-pathway span.
    """
    original, definition = _read_definition(harness_id, gateway)
    topology = _require_explicit_topology(definition)
    junction = _require_junction(topology, junction_id)
    if any(item.junction_id == junction_id for item in topology.junction_attachments):
        raise ValueError("Detach every pathway before deleting this junction.")
    if any(item.junction_id == junction_id for item in topology.junction_dispositions):
        raise ValueError("Disconnect every member before deleting this junction.")

    incident = [
        edge
        for edge in topology.edges
        if edge.kind is RouteEdgeKind.PATHWAY
        and edge.pathway_id == junction.pathway_id
        and junction_id in {edge.start_node_id, edge.end_node_id}
    ]
    by_wire: dict[UUID, list[RouteEdge]] = {}
    for edge in incident:
        by_wire.setdefault(edge.physical_wire_id, []).append(edge)
    if any(len(edges) != 2 for edges in by_wire.values()):
        raise ValueError("Junction spans are incomplete and must be repaired before deletion.")

    used_ids = _definition_ids(definition, topology)
    removed_edge_ids = {edge.edge_id for edge in incident}
    merged_edges: list[RouteEdge] = []
    for physical_wire_id in sorted(by_wire, key=lambda identity: identity.hex):
        edges = by_wire[physical_wire_id]
        incoming = next(
            (edge for edge in edges if edge.end_node_id == junction_id),
            None,
        )
        outgoing = next(
            (edge for edge in edges if edge.start_node_id == junction_id),
            None,
        )
        if incoming is None or outgoing is None:
            raise ValueError("Junction span directions are inconsistent.")
        merged_edges.append(
            RouteEdge(
                edge_id=_allocate_id(id_factory, used_ids, "merged pathway span"),
                kind=RouteEdgeKind.PATHWAY,
                physical_wire_id=physical_wire_id,
                start_node_id=incoming.start_node_id,
                end_node_id=outgoing.end_node_id,
                pathway_id=junction.pathway_id,
            )
        )
    updated_topology = replace(
        topology,
        nodes=tuple(node for node in topology.nodes if node.node_id != junction_id),
        edges=tuple(edge for edge in topology.edges if edge.edge_id not in removed_edge_ids)
        + tuple(merged_edges),
    )
    _persist(
        harness_id,
        original,
        replace(definition, topology=updated_topology),
        gateway,
    )


def _redirect_member(
    topology: RouteTopology,
    junction: TopologyNode,
    pathway_id: UUID,
    pathway_end: PathwayEnd,
    physical_wire_id: UUID,
    used_ids: set[UUID],
    id_factory: Callable[[], UUID],
) -> RouteTopology:
    """
    Redirect one simple downstream trace to the attached pathway's opposite gate.
    """
    outgoing = [
        edge
        for edge in topology.edges
        if edge.physical_wire_id == physical_wire_id and edge.start_node_id == junction.node_id
    ]
    if len(outgoing) != 1 or outgoing[0].kind is not RouteEdgeKind.PATHWAY:
        raise ValueError("Redirect requires one simple downstream parent-pathway trace.")

    downstream: list[RouteEdge] = []
    current = outgoing[0]
    external_node: TopologyNode
    while True:
        downstream.append(current)
        node = next(
            (item for item in topology.nodes if item.node_id == current.end_node_id),
            None,
        )
        if node is None:
            raise ValueError("Redirect downstream route contains a dangling node.")
        if node.kind is TopologyNodeKind.EXTERNAL_END:
            external_node = node
            break
        if node.kind is TopologyNodeKind.JUNCTION:
            raise ValueError("Redirect through a downstream junction is not yet supported.")
        successors = [
            edge
            for edge in topology.edges
            if edge.physical_wire_id == physical_wire_id and edge.start_node_id == node.node_id
        ]
        if len(successors) != 1:
            raise ValueError("Redirect requires one terminated downstream trace.")
        current = successors[0]

    remaining_edges = tuple(edge for edge in topology.edges if edge not in downstream)
    topology = replace(topology, edges=remaining_edges)
    topology = _add_attached_path_edges(
        topology,
        junction.node_id,
        pathway_id,
        pathway_end,
        physical_wire_id,
        used_ids,
        id_factory,
    )
    opposite_end = PathwayEnd.B if pathway_end is PathwayEnd.A else PathwayEnd.A
    end_link = RouteEdge(
        edge_id=_allocate_id(id_factory, used_ids, "redirect end link"),
        kind=RouteEdgeKind.END_LINK,
        physical_wire_id=physical_wire_id,
        start_node_id=pathway_end_node_id(pathway_id, opposite_end),
        end_node_id=external_node.node_id,
    )
    return replace(topology, edges=topology.edges + (end_link,))


def _add_attached_path_edges(
    topology: RouteTopology,
    junction_id: UUID,
    pathway_id: UUID,
    pathway_end: PathwayEnd,
    physical_wire_id: UUID,
    used_ids: set[UUID],
    id_factory: Callable[[], UUID],
) -> RouteTopology:
    """
    Add a transition and complete attached-pathway span for one physical leg.
    """
    topology = _ensure_pathway_end_nodes(topology, pathway_id)
    entry_id = pathway_end_node_id(pathway_id, pathway_end)
    opposite_end = PathwayEnd.B if pathway_end is PathwayEnd.A else PathwayEnd.A
    exit_id = pathway_end_node_id(pathway_id, opposite_end)
    transition = RouteEdge(
        _allocate_id(id_factory, used_ids, "junction transition"),
        RouteEdgeKind.JUNCTION_TRANSITION,
        physical_wire_id,
        junction_id,
        entry_id,
    )
    pathway_edge = RouteEdge(
        _allocate_id(id_factory, used_ids, "attached pathway span"),
        RouteEdgeKind.PATHWAY,
        physical_wire_id,
        entry_id,
        exit_id,
        pathway_id,
    )
    return replace(topology, edges=topology.edges + (transition, pathway_edge))


def _remove_configurable_disposition(
    topology: RouteTopology,
    disposition: JunctionMemberDisposition,
) -> RouteTopology:
    """
    Remove a branch/exclusion that has not acquired a real external end.
    """
    branch_wire_id = disposition.branch_wire_id
    if branch_wire_id is None:
        return replace(
            topology,
            junction_dispositions=tuple(
                item for item in topology.junction_dispositions if item != disposition
            ),
        )
    if any(
        node.kind is TopologyNodeKind.EXTERNAL_END and node.physical_wire_id == branch_wire_id
        for node in topology.nodes
    ):
        raise ValueError(
            "A branch with an external end must be disconnected and repaired explicitly."
        )
    return replace(
        topology,
        physical_wires=tuple(
            wire for wire in topology.physical_wires if wire.physical_wire_id != branch_wire_id
        ),
        edges=tuple(edge for edge in topology.edges if edge.physical_wire_id != branch_wire_id),
        junction_dispositions=tuple(
            item for item in topology.junction_dispositions if item != disposition
        ),
        electrical_relationships=tuple(
            relationship
            for relationship in topology.electrical_relationships
            if branch_wire_id not in relationship.physical_wire_ids
        ),
    )


def _physical_wires_at_junction(
    topology: RouteTopology,
    junction: TopologyNode,
) -> tuple[UUID, ...]:
    """
    Return stable physical members occupying the junction's parent pathway.
    """
    wire_ids = {
        edge.physical_wire_id
        for edge in topology.edges
        if edge.kind is RouteEdgeKind.PATHWAY
        and edge.pathway_id == junction.pathway_id
        and junction.node_id in {edge.start_node_id, edge.end_node_id}
    }
    return tuple(sorted(wire_ids, key=lambda identity: identity.hex))


def _incident_wire_edges(
    topology: RouteTopology,
    physical_wire_id: UUID,
    node_id: UUID,
) -> tuple[RouteEdge, ...]:
    """
    Return one physical member's edges incident to a selected topology node.
    """
    return tuple(
        edge
        for edge in topology.edges
        if edge.physical_wire_id == physical_wire_id
        and node_id in {edge.start_node_id, edge.end_node_id}
    )


def _require_wire_at_junction(
    topology: RouteTopology,
    junction: TopologyNode,
    physical_wire_id: UUID,
) -> None:
    """
    Reject a member that does not occupy the parent slice.
    """
    if physical_wire_id not in _physical_wires_at_junction(topology, junction):
        raise ValueError("Selected physical wire does not occupy this junction slice.")


def _find_disposition(
    topology: RouteTopology,
    junction_id: UUID,
    pathway_id: UUID,
    pathway_end: PathwayEnd,
    incoming_wire_id: UUID,
) -> Optional[JunctionMemberDisposition]:
    """
    Find one member disposition at an exact junction attachment.
    """
    return next(
        (
            item
            for item in topology.junction_dispositions
            if item.junction_id == junction_id
            and item.attachment_pathway_id == pathway_id
            and item.attachment_end is pathway_end
            and item.incoming_wire_id == incoming_wire_id
        ),
        None,
    )


def _ensure_pathway_end_nodes(
    topology: RouteTopology,
    pathway_id: UUID,
) -> RouteTopology:
    """
    Add stable A/B endpoint nodes for a pathway missing from explicit topology.
    """
    existing_ids = {node.node_id for node in topology.nodes}
    nodes = list(topology.nodes)
    for pathway_end in PathwayEnd:
        node_id = pathway_end_node_id(pathway_id, pathway_end)
        if node_id not in existing_ids:
            nodes.append(
                TopologyNode(
                    node_id=node_id,
                    kind=TopologyNodeKind.PATHWAY_END,
                    pathway_id=pathway_id,
                    pathway_end=pathway_end,
                )
            )
    return replace(topology, nodes=tuple(nodes))


def _span_contains_distance(
    topology: RouteTopology,
    edge: RouteEdge,
    distance_mm: float,
) -> bool:
    """
    Return whether a parent-pathway edge contains an interior slice distance.
    """
    first = _node_position(topology, edge.start_node_id)
    second = _node_position(topology, edge.end_node_id)
    lower, upper = sorted((first, second))
    return lower < distance_mm < upper


def _node_position(topology: RouteTopology, node_id: UUID) -> float:
    """
    Resolve pathway-order position for an endpoint or junction node.
    """
    node = next((item for item in topology.nodes if item.node_id == node_id), None)
    if node is None:
        raise ValueError("Topology edge references a missing node.")
    if node.kind is TopologyNodeKind.JUNCTION and node.distance_mm is not None:
        return node.distance_mm
    if node.kind is TopologyNodeKind.PATHWAY_END:
        return -math.inf if node.pathway_end is PathwayEnd.A else math.inf
    raise ValueError("Pathway span contains a node without a pathway position.")


def _require_attachment(
    topology: RouteTopology,
    junction_id: UUID,
    pathway_id: UUID,
    pathway_end: PathwayEnd,
) -> JunctionAttachment:
    """
    Return an existing exact junction attachment.
    """
    attachment = next(
        (
            item
            for item in topology.junction_attachments
            if item.junction_id == junction_id
            and item.pathway_id == pathway_id
            and item.pathway_end is pathway_end
        ),
        None,
    )
    if attachment is None:
        raise ValueError("Selected pathway endpoint is not attached to this junction.")
    return attachment


def _require_junction(topology: RouteTopology, junction_id: UUID) -> TopologyNode:
    """
    Return an existing junction node.
    """
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
    return junction


def _require_extension(topology: RouteTopology, edge_id: UUID) -> RouteEdge:
    """
    Return one existing extension edge or reject a stale selection.
    """
    extension = next(
        (
            edge
            for edge in topology.edges
            if edge.edge_id == edge_id and edge.kind is RouteEdgeKind.EXTENSION
        ),
        None,
    )
    if extension is None:
        raise ValueError("Selected pathway extension does not exist.")
    return extension


def _require_physical_wire(
    topology: RouteTopology,
    physical_wire_id: UUID,
) -> PhysicalWire:
    """
    Return an existing physical-wire identity.
    """
    wire = next(
        (item for item in topology.physical_wires if item.physical_wire_id == physical_wire_id),
        None,
    )
    if wire is None:
        raise ValueError("Selected physical wire does not exist.")
    return wire


def _require_pathway(
    definition: HarnessDefinition,
    pathway_id: UUID,
) -> PathwayDefinition:
    """
    Return an existing pathway or reject a stale identity.
    """
    pathway = next(
        (item for item in definition.pathways if item.pathway_id == pathway_id),
        None,
    )
    if pathway is None:
        raise ValueError("Selected pathway does not exist in this harness.")
    return pathway


def _require_explicit_topology(definition: HarnessDefinition) -> RouteTopology:
    """
    Return explicit topology required by edits after junction creation.
    """
    if definition.topology is None:
        raise ValueError("Create a junction before editing topology.")
    return definition.topology


def _definition_ids(
    definition: HarnessDefinition,
    topology: RouteTopology,
) -> set[UUID]:
    """
    Collect every persisted identity before allocating mutation records.
    """
    return {
        definition.harness_id,
        *(profile.profile_id for profile in definition.profiles),
        *(connection.connection_id for connection in definition.connections),
        *(control.control_id for control in definition.controls),
        *(pathway.pathway_id for pathway in definition.pathways),
        *(wire.wire_id for wire in definition.wires),
        *(node.node_id for node in topology.nodes),
        *(wire.physical_wire_id for wire in topology.physical_wires),
        *(edge.edge_id for edge in topology.edges),
        *(relationship.relationship_id for relationship in topology.electrical_relationships),
    }


def _allocate_id(
    id_factory: Callable[[], UUID],
    used_ids: set[UUID],
    label: str,
) -> UUID:
    """
    Allocate one new identity and reject collisions explicitly.
    """
    identity = id_factory()
    if identity in used_ids:
        raise ValueError(f"Allocated {label} identity already exists.")
    used_ids.add(identity)
    return identity


def _read_definition(
    harness_id: UUID,
    gateway: TopologyEditGateway,
) -> tuple[str, HarnessDefinition]:
    """
    Read both the exact serialized value and its parsed definition.
    """
    original = gateway.read_harness_definition(harness_id)
    return original, loads(original)


def _persist(
    harness_id: UUID,
    original_serialized: str,
    definition: HarnessDefinition,
    gateway: TopologyEditGateway,
) -> None:
    """
    Persist one edit and restore the exact prior definition after failure.
    """
    try:
        gateway.replace_harness_definition(harness_id, dumps(definition))
    except Exception as persistence_error:
        try:
            gateway.replace_harness_definition(harness_id, original_serialized)
        except Exception as rollback_error:
            message = (
                "Failed to persist the topology edit and restore the harness "
                f"definition: {rollback_error}"
            )
            raise TopologyUpdateError(message) from persistence_error
        raise


def _require_nonnegative_finite(value: float, label: str) -> None:
    """
    Require a finite canonical-millimeter distance.
    """
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{label} must be finite and nonnegative.")


def _require_positive_finite(value: float, label: str) -> None:
    """
    Require a finite positive unitless value.
    """
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be finite and positive.")
