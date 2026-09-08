"""
Deterministic validation for harness definitions before generation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID

from .model import (
    SCHEMA_VERSION,
    ControlKind,
    ElectricalRelationshipKind,
    HarnessDefinition,
    JunctionDisposition,
    PathwayDefinition,
    PathwayEnd,
    PhysicalWire,
    RouteEdge,
    RouteEdgeKind,
    RouteTopology,
    RoutingMode,
    TopologyNode,
    TopologyNodeKind,
)


@dataclass(frozen=True)
class ValidationIssue:
    """
    Describe one actionable harness validation failure.

    Args:
        code: Stable machine-readable issue code.
        path: Dot-and-index path to the invalid value.
        message: Human-readable explanation.
    """

    code: str
    path: str
    message: str


def validate_harness(definition: HarnessDefinition) -> tuple[ValidationIssue, ...]:
    """
    Validate logical readiness without accessing Fusion geometry.

    Args:
        definition: Harness definition to validate.

    Returns:
        Validation issues in deterministic discovery order.
    """
    issues: list[ValidationIssue] = []
    if definition.schema_version != SCHEMA_VERSION:
        issues.append(
            ValidationIssue(
                "unsupported_schema_version",
                "schema_version",
                f"Expected schema version {SCHEMA_VERSION}.",
            )
        )
    if not definition.name.strip():
        issues.append(ValidationIssue("missing_name", "name", "Harness name is required."))
    if not definition.wires:
        issues.append(ValidationIssue("missing_wires", "wires", "At least one wire is required."))

    _validate_unique_ids(definition, issues)
    _validate_profiles(definition, issues)
    _validate_connections(definition, issues)
    _validate_controls(definition, issues)
    _validate_pathways(definition, issues)
    _validate_wires(definition, issues)
    if definition.topology is not None:
        _validate_topology(definition, issues)
    return tuple(issues)


def _validate_unique_ids(
    definition: HarnessDefinition,
    issues: list[ValidationIssue],
) -> None:
    """
    Require identities to be unique across the complete harness definition.

    Args:
        definition: Harness definition to validate.
        issues: Mutable issue accumulator.
    """
    seen: dict[UUID, str] = {definition.harness_id: "harness_id"}
    identities = [
        *(
            (profile.profile_id, f"profiles[{index}].profile_id")
            for index, profile in enumerate(definition.profiles)
        ),
        *(
            (connection.connection_id, f"connections[{index}].connection_id")
            for index, connection in enumerate(definition.connections)
        ),
        *(
            (control.control_id, f"controls[{index}].control_id")
            for index, control in enumerate(definition.controls)
        ),
        *(
            (pathway.pathway_id, f"pathways[{index}].pathway_id")
            for index, pathway in enumerate(definition.pathways)
        ),
        *((wire.wire_id, f"wires[{index}].wire_id") for index, wire in enumerate(definition.wires)),
    ]
    for identity, path in identities:
        previous_path = seen.get(identity)
        if previous_path is not None:
            issues.append(
                ValidationIssue(
                    "duplicate_id",
                    path,
                    f"Identity duplicates {previous_path}.",
                )
            )
        else:
            seen[identity] = path


def _validate_profiles(
    definition: HarnessDefinition,
    issues: list[ValidationIssue],
) -> None:
    """
    Validate conductor profile fields.

    Args:
        definition: Harness definition to validate.
        issues: Mutable issue accumulator.
    """
    for index, profile in enumerate(definition.profiles):
        path = f"profiles[{index}]"
        if not profile.name.strip():
            issues.append(
                ValidationIssue("missing_profile_name", f"{path}.name", "Profile name is required.")
            )
        if not math.isfinite(profile.diameter_mm) or profile.diameter_mm <= 0:
            issues.append(
                ValidationIssue(
                    "invalid_profile_diameter",
                    f"{path}.diameter_mm",
                    "Diameter must be a finite positive value.",
                )
            )


def _validate_connections(
    definition: HarnessDefinition,
    issues: list[ValidationIssue],
) -> None:
    """
    Validate physical connection references.

    Args:
        definition: Harness definition to validate.
        issues: Mutable issue accumulator.
    """
    for index, connection in enumerate(definition.connections):
        path = f"connections[{index}]"
        if not connection.name.strip():
            issues.append(
                ValidationIssue(
                    "missing_connection_name",
                    f"{path}.name",
                    "Connection name is required.",
                )
            )
        if not connection.entity_token.strip():
            issues.append(
                ValidationIssue(
                    "missing_connection_geometry",
                    f"{path}.entity_token",
                    "Connection must reference Fusion geometry.",
                )
            )


def _validate_controls(
    definition: HarnessDefinition,
    issues: list[ValidationIssue],
) -> None:
    """
    Validate routing-control references.

    Args:
        definition: Harness definition to validate.
        issues: Mutable issue accumulator.
    """
    for index, control in enumerate(definition.controls):
        path = f"controls[{index}]"
        if not control.name.strip():
            issues.append(
                ValidationIssue("missing_control_name", f"{path}.name", "Control name is required.")
            )
        if not control.entity_token.strip():
            issues.append(
                ValidationIssue(
                    "missing_control_geometry",
                    f"{path}.entity_token",
                    "Control must reference Fusion geometry.",
                )
            )


def _validate_pathways(
    definition: HarnessDefinition,
    issues: list[ValidationIssue],
) -> None:
    """
    Validate pathway names, ordered gates, and routing-mode compatibility.

    Args:
        definition: Harness definition to validate.
        issues: Mutable issue accumulator.
    """
    controls_by_id = {control.control_id: control for control in definition.controls}
    seen_names: dict[str, str] = {}
    for index, pathway in enumerate(definition.pathways):
        path = f"pathways[{index}]"
        normalized_name = pathway.name.strip()
        if not normalized_name:
            issues.append(
                ValidationIssue(
                    "missing_pathway_name",
                    f"{path}.name",
                    "Pathway name is required.",
                )
            )
        else:
            name_key = normalized_name.casefold()
            previous_path = seen_names.get(name_key)
            if previous_path is not None:
                issues.append(
                    ValidationIssue(
                        "duplicate_pathway_name",
                        f"{path}.name",
                        f"Pathway name duplicates {previous_path}.",
                    )
                )
            else:
                seen_names[name_key] = f"{path}.name"

        if not pathway.ordered_control_ids:
            issues.append(
                ValidationIssue(
                    "missing_pathway_controls",
                    f"{path}.ordered_control_ids",
                    "At least one ordered gate is required.",
                )
            )

        expected_kind: ControlKind = (
            ControlKind.ROUTING_GATE
            if pathway.routing_mode is RoutingMode.ROUTING_GATES
            else ControlKind.PROFILE_GATE
        )
        seen_control_ids: set[UUID] = set()
        for control_index, control_id in enumerate(pathway.ordered_control_ids):
            control_path = f"{path}.ordered_control_ids[{control_index}]"
            control = controls_by_id.get(control_id)
            if control is None:
                issues.append(
                    ValidationIssue(
                        "missing_pathway_control_reference",
                        control_path,
                        "Referenced routing control does not exist.",
                    )
                )
            elif control.kind is not expected_kind:
                issues.append(
                    ValidationIssue(
                        "pathway_control_mode_mismatch",
                        control_path,
                        f"Control kind must be {expected_kind.value} for this pathway.",
                    )
                )
            if control_id in seen_control_ids:
                issues.append(
                    ValidationIssue(
                        "duplicate_pathway_control",
                        control_path,
                        "A gate may appear only once in a pathway.",
                    )
                )
            else:
                seen_control_ids.add(control_id)


def _validate_wires(
    definition: HarnessDefinition,
    issues: list[ValidationIssue],
) -> None:
    """
    Validate conductor mappings and ordered references.

    Args:
        definition: Harness definition to validate.
        issues: Mutable issue accumulator.
    """
    profile_ids = {profile.profile_id for profile in definition.profiles}
    connection_ids = {connection.connection_id for connection in definition.connections}
    control_ids = {control.control_id for control in definition.controls}
    pathways_by_id = {pathway.pathway_id: pathway for pathway in definition.pathways}
    seen_numbers: dict[str, str] = {}
    seen_endpoints: dict[UUID, str] = {}

    for index, wire in enumerate(definition.wires):
        path = f"wires[{index}]"
        _validate_wire_number(wire.wire_number, path, seen_numbers, issues)
        _validate_reference(
            wire.profile_id,
            profile_ids,
            "missing_profile_reference",
            f"{path}.profile_id",
            issues,
        )
        _validate_endpoint(
            wire.start_connection_id,
            connection_ids,
            f"{path}.start_connection_id",
            seen_endpoints,
            issues,
        )
        _validate_endpoint(
            wire.end_connection_id,
            connection_ids,
            f"{path}.end_connection_id",
            seen_endpoints,
            issues,
        )
        if wire.start_connection_id == wire.end_connection_id:
            issues.append(
                ValidationIssue(
                    "identical_wire_endpoints",
                    f"{path}.end_connection_id",
                    "End A and End B connections must differ.",
                )
            )
        if not wire.ordered_control_ids:
            issues.append(
                ValidationIssue(
                    "missing_wire_controls",
                    f"{path}.ordered_control_ids",
                    "At least one ordered control is required.",
                )
            )

        if not wire.ordered_pathway_ids:
            issues.append(
                ValidationIssue(
                    "missing_wire_pathways",
                    f"{path}.ordered_pathway_ids",
                    "At least one ordered pathway is required.",
                )
            )

        resolved_pathways: list[PathwayDefinition] = []
        seen_wire_pathways: set[UUID] = set()
        for pathway_index, pathway_id in enumerate(wire.ordered_pathway_ids):
            pathway_path = f"{path}.ordered_pathway_ids[{pathway_index}]"
            pathway = pathways_by_id.get(pathway_id)
            if pathway is None:
                issues.append(
                    ValidationIssue(
                        "missing_pathway_reference",
                        pathway_path,
                        "Referenced pathway does not exist.",
                    )
                )
            else:
                resolved_pathways.append(pathway)
            if pathway_id in seen_wire_pathways:
                issues.append(
                    ValidationIssue(
                        "duplicate_wire_pathway",
                        pathway_path,
                        "A pathway may appear only once in a wire route.",
                    )
                )
            else:
                seen_wire_pathways.add(pathway_id)

        controls_are_resolvable = all(
            control_id in control_ids for control_id in wire.ordered_control_ids
        )
        if (
            wire.ordered_control_ids
            and controls_are_resolvable
            and len(resolved_pathways) == len(wire.ordered_pathway_ids)
        ):
            expected_control_ids = tuple(
                control_id
                for pathway in resolved_pathways
                for control_id in pathway.ordered_control_ids
            )
            if expected_control_ids != wire.ordered_control_ids:
                issues.append(
                    ValidationIssue(
                        "wire_pathway_controls_mismatch",
                        f"{path}.ordered_control_ids",
                        "Wire control order must match its ordered pathways.",
                    )
                )

        seen_wire_controls: set[UUID] = set()
        for control_index, control_id in enumerate(wire.ordered_control_ids):
            control_path = f"{path}.ordered_control_ids[{control_index}]"
            _validate_reference(
                control_id,
                control_ids,
                "missing_control_reference",
                control_path,
                issues,
            )
            if control_id in seen_wire_controls:
                issues.append(
                    ValidationIssue(
                        "duplicate_wire_control",
                        control_path,
                        "A control may appear only once in a wire route.",
                    )
                )
            else:
                seen_wire_controls.add(control_id)


def _validate_wire_number(
    wire_number: str,
    path: str,
    seen_numbers: dict[str, str],
    issues: list[ValidationIssue],
) -> None:
    """
    Validate one stable user-facing wire number.

    Args:
        wire_number: Wire number to validate.
        path: Parent wire path.
        seen_numbers: Previously encountered wire numbers.
        issues: Mutable issue accumulator.
    """
    number_path = f"{path}.wire_number"
    if not wire_number.isdecimal() or int(wire_number) <= 0:
        issues.append(
            ValidationIssue(
                "invalid_wire_number",
                number_path,
                "Wire number must be a positive decimal string.",
            )
        )
    previous_path = seen_numbers.get(wire_number)
    if previous_path is not None:
        issues.append(
            ValidationIssue(
                "duplicate_wire_number",
                number_path,
                f"Wire number duplicates {previous_path}.",
            )
        )
    else:
        seen_numbers[wire_number] = number_path


def _validate_endpoint(
    endpoint_id: UUID,
    connection_ids: set[UUID],
    path: str,
    seen_endpoints: dict[UUID, str],
    issues: list[ValidationIssue],
) -> None:
    """
    Validate one endpoint reference and require unique physical use.

    Args:
        endpoint_id: Referenced connection identity.
        connection_ids: Available connection identities.
        path: Endpoint field path.
        seen_endpoints: Previously assigned physical endpoints.
        issues: Mutable issue accumulator.
    """
    _validate_reference(
        endpoint_id,
        connection_ids,
        "missing_connection_reference",
        path,
        issues,
    )
    previous_path = seen_endpoints.get(endpoint_id)
    if previous_path is not None:
        issues.append(
            ValidationIssue(
                "duplicate_endpoint",
                path,
                f"Connection is already assigned at {previous_path}.",
            )
        )
    else:
        seen_endpoints[endpoint_id] = path


def _validate_reference(
    reference_id: UUID,
    available_ids: set[UUID],
    code: str,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    """
    Validate that an identity references an available domain object.

    Args:
        reference_id: Referenced identity.
        available_ids: Valid identities for the reference type.
        code: Stable issue code for a missing reference.
        path: Reference field path.
        issues: Mutable issue accumulator.
    """
    if reference_id not in available_ids:
        issues.append(ValidationIssue(code, path, "Referenced identity does not exist."))


def _validate_topology(
    definition: HarnessDefinition,
    issues: list[ValidationIssue],
) -> None:
    """
    Validate schema-v5 graph shape, references, and generation readiness.
    """
    topology = definition.resolved_topology
    _validate_topology_identities(definition, topology, issues)
    profiles = {profile.profile_id for profile in definition.profiles}
    pathways = {pathway.pathway_id: pathway for pathway in definition.pathways}
    connections = {connection.connection_id for connection in definition.connections}
    controls = {control.control_id: control for control in definition.controls}
    nodes = {node.node_id: node for node in topology.nodes}
    physical_wires = {wire.physical_wire_id: wire for wire in topology.physical_wires}
    network_by_wire = {wire.physical_wire_id: wire.network_id for wire in topology.physical_wires}

    _validate_physical_wires(definition, topology, profiles, issues)
    _validate_topology_nodes(topology, pathways, connections, controls, physical_wires, issues)
    _validate_route_edges(topology, pathways, nodes, physical_wires, issues)
    _validate_junction_attachments(topology, nodes, pathways, issues)
    _validate_junction_dispositions(topology, nodes, pathways, physical_wires, issues)
    _validate_electrical_relationships(topology, nodes, physical_wires, issues)
    _validate_network_graph(topology, network_by_wire, issues)


def _validate_topology_identities(
    definition: HarnessDefinition,
    topology: RouteTopology,
    issues: list[ValidationIssue],
) -> None:
    """
    Require unique graph identities while preserving migrated primary wire IDs.
    """
    wire_ids = {wire.wire_id for wire in definition.wires}
    reserved: dict[UUID, str] = {definition.harness_id: "harness_id"}
    for collection_name, id_name, collection in (
        ("profiles", "profile_id", definition.profiles),
        ("connections", "connection_id", definition.connections),
        ("controls", "control_id", definition.controls),
        ("pathways", "pathway_id", definition.pathways),
        ("wires", "wire_id", definition.wires),
    ):
        for index, item in enumerate(collection):
            reserved[getattr(item, id_name)] = f"{collection_name}[{index}].{id_name}"
    seen: dict[UUID, str] = {}
    identities = [
        *(
            (item.node_id, f"topology.nodes[{index}].node_id")
            for index, item in enumerate(topology.nodes)
        ),
        *(
            (item.edge_id, f"topology.edges[{index}].edge_id")
            for index, item in enumerate(topology.edges)
        ),
        *(
            (item.relationship_id, f"topology.electrical_relationships[{index}].relationship_id")
            for index, item in enumerate(topology.electrical_relationships)
        ),
    ]
    for identity, path in identities:
        previous = seen.get(identity)
        reserved_path = reserved.get(identity)
        if previous is not None or reserved_path is not None:
            duplicate_path = previous or reserved_path or "an existing identity"
            issues.append(
                ValidationIssue(
                    "duplicate_topology_id",
                    path,
                    f"Topology identity duplicates {duplicate_path}.",
                )
            )
        else:
            seen[identity] = path

    for index, wire in enumerate(topology.physical_wires):
        path = f"topology.physical_wires[{index}].physical_wire_id"
        previous = seen.get(wire.physical_wire_id)
        duplicate_primary = sum(
            item.physical_wire_id == wire.physical_wire_id
            for item in topology.physical_wires[:index]
        )
        reserved_path = reserved.get(wire.physical_wire_id)
        reserved_collision = reserved_path is not None and wire.physical_wire_id not in wire_ids
        if previous is not None or duplicate_primary or reserved_collision:
            issues.append(
                ValidationIssue(
                    "duplicate_topology_id",
                    path,
                    "Physical-wire identity duplicates "
                    f"{previous or reserved_path or 'an earlier physical wire'}.",
                )
            )
        elif wire.physical_wire_id not in wire_ids:
            seen[wire.physical_wire_id] = path


def _validate_physical_wires(
    definition: HarnessDefinition,
    topology: RouteTopology,
    profile_ids: set[UUID],
    issues: list[ValidationIssue],
) -> None:
    """
    Validate physical-wire profiles and logical-network roots.
    """
    primary_ids = {wire.wire_id for wire in definition.wires}
    networks: dict[UUID, list[UUID]] = {}
    for index, wire in enumerate(topology.physical_wires):
        path = f"topology.physical_wires[{index}]"
        _validate_reference(
            wire.profile_id,
            profile_ids,
            "missing_topology_profile_reference",
            f"{path}.profile_id",
            issues,
        )
        networks.setdefault(wire.network_id, []).append(wire.physical_wire_id)

    for network_id, members in networks.items():
        primary_count = sum(member in primary_ids for member in members)
        if primary_count != 1:
            issues.append(
                ValidationIssue(
                    "invalid_network_primary",
                    "topology.physical_wires",
                    f"Network {network_id} must contain exactly one primary wire identity.",
                )
            )
    available_physical_ids = {wire.physical_wire_id for wire in topology.physical_wires}
    for wire_index, wire in enumerate(definition.wires):
        if wire.wire_id not in available_physical_ids:
            issues.append(
                ValidationIssue(
                    "missing_primary_physical_wire",
                    f"wires[{wire_index}].wire_id",
                    "The topology must retain this primary physical-wire identity.",
                )
            )


def _validate_topology_nodes(
    topology: RouteTopology,
    pathways: dict[UUID, PathwayDefinition],
    connection_ids: set[UUID],
    controls: dict[UUID, object],
    physical_wires: dict[UUID, PhysicalWire],
    issues: list[ValidationIssue],
) -> None:
    """
    Validate kind-specific node fields and linked identities.
    """
    junction_names: set[str] = set()
    for index, node in enumerate(topology.nodes):
        path = f"topology.nodes[{index}]"
        if node.kind is TopologyNodeKind.EXTERNAL_END:
            if node.connection_id not in connection_ids:
                issues.append(
                    ValidationIssue(
                        "missing_topology_connection_reference",
                        f"{path}.connection_id",
                        "External end must reference an existing connection.",
                    )
                )
            if node.physical_wire_id not in physical_wires:
                issues.append(
                    ValidationIssue(
                        "missing_topology_wire_reference",
                        f"{path}.physical_wire_id",
                        "External end must reference an existing physical wire.",
                    )
                )
            if any(
                value is not None
                for value in (
                    node.pathway_id,
                    node.pathway_end,
                    node.distance_mm,
                    node.slice_control_id,
                    node.junction_diameter_factor_override,
                )
            ):
                issues.append(
                    ValidationIssue(
                        "unexpected_external_end_fields",
                        path,
                        "External-end nodes may contain only connection and physical-wire references.",
                    )
                )
        elif node.kind is TopologyNodeKind.PATHWAY_END:
            if node.pathway_id not in pathways or node.pathway_end is None:
                issues.append(
                    ValidationIssue(
                        "invalid_pathway_end_node",
                        path,
                        "Pathway-end node requires an existing pathway and A/B end.",
                    )
                )
            if any(
                value is not None
                for value in (
                    node.connection_id,
                    node.physical_wire_id,
                    node.distance_mm,
                    node.slice_control_id,
                    node.junction_diameter_factor_override,
                )
            ):
                issues.append(
                    ValidationIssue(
                        "unexpected_pathway_end_fields",
                        path,
                        "Pathway-end nodes may contain only pathway and endpoint references.",
                    )
                )
        elif node.kind is TopologyNodeKind.JUNCTION:
            normalized_name = node.name.strip()
            if not normalized_name:
                issues.append(
                    ValidationIssue(
                        "missing_junction_name",
                        f"{path}.name",
                        "Junction must have a visible name.",
                    )
                )
            elif normalized_name.casefold() in junction_names:
                issues.append(
                    ValidationIssue(
                        "duplicate_junction_name",
                        f"{path}.name",
                        "Junction names must be unique.",
                    )
                )
            else:
                junction_names.add(normalized_name.casefold())
            if node.pathway_id not in pathways:
                issues.append(
                    ValidationIssue(
                        "missing_junction_pathway_reference",
                        f"{path}.pathway_id",
                        "Junction must reference its parent pathway.",
                    )
                )
            if any(
                value is not None
                for value in (
                    node.pathway_end,
                    node.connection_id,
                    node.physical_wire_id,
                )
            ):
                issues.append(
                    ValidationIssue(
                        "unexpected_junction_fields",
                        path,
                        "Junction nodes may not carry endpoint or physical-wire fields.",
                    )
                )
            if (
                node.distance_mm is None
                or not math.isfinite(node.distance_mm)
                or node.distance_mm < 0
            ):
                issues.append(
                    ValidationIssue(
                        "invalid_junction_distance",
                        f"{path}.distance_mm",
                        "Junction distance must be finite nonnegative millimeters.",
                    )
                )
            if node.slice_control_id is not None:
                control = controls.get(node.slice_control_id)
                if (
                    control is None
                    or getattr(control, "kind", None) is not ControlKind.ROUTING_GATE
                ):
                    issues.append(
                        ValidationIssue(
                            "invalid_junction_slice_control",
                            f"{path}.slice_control_id",
                            "Junction slice control must be an existing routing gate.",
                        )
                    )
            factor = node.junction_diameter_factor_override
            if factor is not None and (
                node.slice_control_id is None or not math.isfinite(factor) or factor <= 0
            ):
                issues.append(
                    ValidationIssue(
                        "invalid_junction_diameter_factor",
                        f"{path}.junction_diameter_factor_override",
                        "Diameter factor requires a routing-gate slice and a finite positive value.",
                    )
                )


def _validate_route_edges(
    topology: RouteTopology,
    pathways: dict[UUID, PathwayDefinition],
    nodes: dict[UUID, TopologyNode],
    physical_wires: dict[UUID, PhysicalWire],
    issues: list[ValidationIssue],
) -> None:
    """
    Validate edge references and pathway occupancy shape.
    """
    seen_memberships: set[tuple[UUID, UUID, UUID, UUID]] = set()
    for index, edge in enumerate(topology.edges):
        path = f"topology.edges[{index}]"
        _validate_reference(
            edge.physical_wire_id,
            set(physical_wires),
            "missing_topology_wire_reference",
            f"{path}.physical_wire_id",
            issues,
        )
        _validate_reference(
            edge.start_node_id,
            set(nodes),
            "missing_topology_node_reference",
            f"{path}.start_node_id",
            issues,
        )
        _validate_reference(
            edge.end_node_id,
            set(nodes),
            "missing_topology_node_reference",
            f"{path}.end_node_id",
            issues,
        )
        if edge.start_node_id == edge.end_node_id:
            issues.append(
                ValidationIssue(
                    "topology_self_edge",
                    f"{path}.end_node_id",
                    "Route edge must connect distinct nodes.",
                )
            )
        if edge.kind is RouteEdgeKind.PATHWAY:
            pathway_id = edge.pathway_id
            if pathway_id not in pathways:
                issues.append(
                    ValidationIssue(
                        "missing_topology_pathway_reference",
                        f"{path}.pathway_id",
                        "Pathway edge must reference an existing pathway.",
                    )
                )
            if pathway_id is not None and pathway_id in pathways:
                for node_field, node_id in (
                    ("start_node_id", edge.start_node_id),
                    ("end_node_id", edge.end_node_id),
                ):
                    node = nodes.get(node_id)
                    if node is not None and not _node_lies_on_pathway(node, pathway_id):
                        issues.append(
                            ValidationIssue(
                                "pathway_edge_node_mismatch",
                                f"{path}.{node_field}",
                                "Pathway edge node must lie on its referenced pathway.",
                            )
                        )
            if pathway_id is not None:
                first, second = sorted(
                    (edge.start_node_id, edge.end_node_id),
                    key=lambda identity: identity.hex,
                )
                membership = (edge.physical_wire_id, pathway_id, first, second)
                if membership in seen_memberships:
                    issues.append(
                        ValidationIssue(
                            "duplicate_span_membership",
                            path,
                            "Physical wire may occupy a pathway span only once.",
                        )
                    )
                seen_memberships.add(membership)
        elif edge.pathway_id is not None:
            issues.append(
                ValidationIssue(
                    "unexpected_edge_pathway",
                    f"{path}.pathway_id",
                    "Only pathway edges may carry a pathway identity.",
                )
            )
        _validate_edge_node_kinds(edge, nodes, path, issues)


def _validate_junction_attachments(
    topology: RouteTopology,
    nodes: dict[UUID, TopologyNode],
    pathways: dict[UUID, PathwayDefinition],
    issues: list[ValidationIssue],
) -> None:
    """
    Validate persistent empty or populated pathway attachments.
    """
    seen: set[tuple[UUID, UUID, PathwayEnd]] = set()
    attached_pathway_ends: set[tuple[UUID, PathwayEnd]] = set()
    for index, item in enumerate(topology.junction_attachments):
        path = f"topology.junction_attachments[{index}]"
        junction = nodes.get(item.junction_id)
        if junction is None or junction.kind is not TopologyNodeKind.JUNCTION:
            issues.append(
                ValidationIssue(
                    "missing_junction_reference",
                    f"{path}.junction_id",
                    "Attachment must reference a junction node.",
                )
            )
        _validate_reference(
            item.pathway_id,
            set(pathways),
            "missing_attachment_pathway_reference",
            f"{path}.pathway_id",
            issues,
        )
        if junction is not None and junction.pathway_id == item.pathway_id:
            issues.append(
                ValidationIssue(
                    "junction_self_attachment",
                    f"{path}.pathway_id",
                    "A junction cannot attach its own parent pathway as a branch.",
                )
            )
        key = (item.junction_id, item.pathway_id, item.pathway_end)
        if key in seen:
            issues.append(
                ValidationIssue(
                    "duplicate_junction_attachment",
                    path,
                    "Junction attachment already exists.",
                )
            )
        seen.add(key)
        pathway_end = (item.pathway_id, item.pathway_end)
        if pathway_end in attached_pathway_ends:
            issues.append(
                ValidationIssue(
                    "reused_attachment_pathway_end",
                    path,
                    "A pathway endpoint may attach to only one junction.",
                )
            )
        attached_pathway_ends.add(pathway_end)


def _validate_junction_dispositions(
    topology: RouteTopology,
    nodes: dict[UUID, TopologyNode],
    pathways: dict[UUID, PathwayDefinition],
    physical_wires: dict[UUID, PhysicalWire],
    issues: list[ValidationIssue],
) -> None:
    """
    Validate branch identities and redirect exclusivity.
    """
    redirects: set[tuple[UUID, UUID]] = set()
    splice_members: dict[UUID, set[UUID]] = {}
    for relationship in topology.electrical_relationships:
        if relationship.kind is ElectricalRelationshipKind.IDEAL_SPLICE:
            splice_members.setdefault(relationship.junction_id, set()).update(
                relationship.physical_wire_ids
            )
    seen_dispositions: set[tuple[UUID, UUID, PathwayEnd, UUID]] = set()
    attachment_keys = {
        (item.junction_id, item.pathway_id, item.pathway_end)
        for item in topology.junction_attachments
    }
    for index, item in enumerate(topology.junction_dispositions):
        path = f"topology.junction_dispositions[{index}]"
        junction = nodes.get(item.junction_id)
        if junction is None or getattr(junction, "kind", None) is not TopologyNodeKind.JUNCTION:
            issues.append(
                ValidationIssue(
                    "missing_junction_reference",
                    f"{path}.junction_id",
                    "Disposition must reference a junction node.",
                )
            )
        _validate_reference(
            item.attachment_pathway_id,
            set(pathways),
            "missing_attachment_pathway_reference",
            f"{path}.attachment_pathway_id",
            issues,
        )
        if (
            item.junction_id,
            item.attachment_pathway_id,
            item.attachment_end,
        ) not in attachment_keys:
            issues.append(
                ValidationIssue(
                    "missing_junction_attachment",
                    path,
                    "Disposition must reference a persisted junction attachment.",
                )
            )
        _validate_reference(
            item.incoming_wire_id,
            set(physical_wires),
            "missing_topology_wire_reference",
            f"{path}.incoming_wire_id",
            issues,
        )
        disposition_key = (
            item.junction_id,
            item.attachment_pathway_id,
            item.attachment_end,
            item.incoming_wire_id,
        )
        if disposition_key in seen_dispositions:
            issues.append(
                ValidationIssue(
                    "duplicate_junction_disposition",
                    path,
                    "A member may have only one disposition per junction attachment.",
                )
            )
        seen_dispositions.add(disposition_key)

        attachment_node_ids = {
            node.node_id
            for node in topology.nodes
            if node.kind is TopologyNodeKind.PATHWAY_END
            and node.pathway_id == item.attachment_pathway_id
            and node.pathway_end is item.attachment_end
        }
        expected_wire_id = (
            item.branch_wire_id
            if item.disposition is JunctionDisposition.BRANCH
            else item.incoming_wire_id
        )
        matching_transition = any(
            edge.kind is RouteEdgeKind.JUNCTION_TRANSITION
            and edge.physical_wire_id == expected_wire_id
            and edge.start_node_id == item.junction_id
            and edge.end_node_id in attachment_node_ids
            for edge in topology.edges
        )
        if item.disposition is JunctionDisposition.BRANCH:
            incoming_wire_id = item.incoming_wire_id
            branch_wire_id = item.branch_wire_id
            if (
                incoming_wire_id not in physical_wires
                or branch_wire_id not in physical_wires
                or branch_wire_id == incoming_wire_id
            ):
                issues.append(
                    ValidationIssue(
                        "invalid_branch_wire",
                        f"{path}.branch_wire_id",
                        "Branch requires a distinct existing physical-wire identity.",
                    )
                )
            elif (
                branch_wire_id is not None
                and physical_wires[branch_wire_id].network_id
                != physical_wires[incoming_wire_id].network_id
            ):
                issues.append(
                    ValidationIssue(
                        "branch_network_mismatch",
                        f"{path}.branch_wire_id",
                        "Branch and incoming physical wires must share one logical network.",
                    )
                )
            elif not {
                incoming_wire_id,
                branch_wire_id,
            }.issubset(splice_members.get(item.junction_id, set())):
                issues.append(
                    ValidationIssue(
                        "missing_branch_electrical_relationship",
                        path,
                        "Branch requires an ideal-splice relationship for both physical wires.",
                    )
                )
            if not matching_transition:
                issues.append(
                    ValidationIssue(
                        "missing_junction_transition",
                        path,
                        "Branch disposition requires a matching transition to the attachment gate.",
                    )
                )
        elif item.branch_wire_id is not None:
            issues.append(
                ValidationIssue(
                    "unexpected_branch_wire",
                    f"{path}.branch_wire_id",
                    "Only BRANCH dispositions may reference a branch wire.",
                )
            )
        if item.disposition is JunctionDisposition.REDIRECT_BRANCH:
            key = (item.junction_id, item.incoming_wire_id)
            if key in redirects:
                issues.append(
                    ValidationIssue(
                        "multiple_junction_redirects",
                        path,
                        "A member may redirect into only one attachment at a junction.",
                    )
                )
            redirects.add(key)
            if not matching_transition:
                issues.append(
                    ValidationIssue(
                        "missing_junction_transition",
                        path,
                        "Redirect disposition requires a matching transition to the attachment gate.",
                    )
                )
        elif item.disposition is JunctionDisposition.EXCLUDE_BRANCH and matching_transition:
            issues.append(
                ValidationIssue(
                    "excluded_junction_transition",
                    path,
                    "Excluded attachment must not contain a transition for this member.",
                )
            )


def _validate_electrical_relationships(
    topology: RouteTopology,
    nodes: dict[UUID, TopologyNode],
    physical_wires: dict[UUID, PhysicalWire],
    issues: list[ValidationIssue],
) -> None:
    """
    Validate ideal-splice membership and network consistency.
    """
    for index, relationship in enumerate(topology.electrical_relationships):
        path = f"topology.electrical_relationships[{index}]"
        junction = nodes.get(relationship.junction_id)
        if junction is None or getattr(junction, "kind", None) is not TopologyNodeKind.JUNCTION:
            issues.append(
                ValidationIssue(
                    "missing_relationship_junction",
                    f"{path}.junction_id",
                    "Electrical relationship must reference a junction node.",
                )
            )
        if len(set(relationship.physical_wire_ids)) < 2:
            issues.append(
                ValidationIssue(
                    "invalid_electrical_relationship_members",
                    f"{path}.physical_wire_ids",
                    "Ideal splice requires at least two distinct physical wires.",
                )
            )
        networks: set[UUID] = set()
        for wire_index, wire_id in enumerate(relationship.physical_wire_ids):
            wire = physical_wires.get(wire_id)
            if wire is None:
                issues.append(
                    ValidationIssue(
                        "missing_topology_wire_reference",
                        f"{path}.physical_wire_ids[{wire_index}]",
                        "Referenced physical wire does not exist.",
                    )
                )
            else:
                networks.add(wire.network_id)
        if len(networks) > 1:
            issues.append(
                ValidationIssue(
                    "electrical_network_mismatch",
                    f"{path}.physical_wire_ids",
                    "Spliced physical wires must belong to one logical network.",
                )
            )


def _node_lies_on_pathway(node: TopologyNode, pathway_id: UUID) -> bool:
    """
    Return whether a node is a valid endpoint for a span on one pathway.
    """
    return node.pathway_id == pathway_id and node.kind in {
        TopologyNodeKind.PATHWAY_END,
        TopologyNodeKind.JUNCTION,
    }


def _validate_edge_node_kinds(
    edge: RouteEdge,
    nodes: dict[UUID, TopologyNode],
    path: str,
    issues: list[ValidationIssue],
) -> None:
    """
    Require each edge kind to connect the node roles it represents.
    """
    start = nodes.get(edge.start_node_id)
    end = nodes.get(edge.end_node_id)
    if start is None or end is None:
        return
    node_kinds = {start.kind, end.kind}
    valid = True
    if edge.kind is RouteEdgeKind.END_LINK:
        valid = TopologyNodeKind.EXTERNAL_END in node_kinds and bool(
            node_kinds & {TopologyNodeKind.PATHWAY_END, TopologyNodeKind.JUNCTION}
        )
    elif edge.kind is RouteEdgeKind.EXTENSION:
        valid = (
            start.kind is TopologyNodeKind.PATHWAY_END and end.kind is TopologyNodeKind.PATHWAY_END
        )
    elif edge.kind is RouteEdgeKind.JUNCTION_TRANSITION:
        valid = start.kind is TopologyNodeKind.JUNCTION and end.kind is TopologyNodeKind.PATHWAY_END
    if not valid:
        issues.append(
            ValidationIssue(
                "invalid_edge_node_kinds",
                path,
                "Route edge endpoints do not match the edge kind.",
            )
        )


def _validate_network_graph(
    topology: RouteTopology,
    network_by_wire: dict[UUID, UUID],
    issues: list[ValidationIssue],
) -> None:
    """
    Reject cycles, recombination, and components without two real ends.
    """
    edges_by_network: dict[UUID, list[RouteEdge]] = {}
    external_by_network: dict[UUID, set[UUID]] = {}
    for node in topology.nodes:
        if getattr(node, "kind", None) is TopologyNodeKind.EXTERNAL_END:
            wire_id = node.physical_wire_id
            network_id = None if wire_id is None else network_by_wire.get(wire_id)
            if network_id is not None:
                external_by_network.setdefault(network_id, set()).add(node.node_id)
    for edge in topology.edges:
        network_id = network_by_wire.get(edge.physical_wire_id)
        if network_id is not None:
            edges_by_network.setdefault(network_id, []).append(edge)

    for network_id in set(network_by_wire.values()):
        network_edges = edges_by_network.get(network_id, [])
        adjacency: dict[UUID, set[UUID]] = {}
        incoming_wires: dict[UUID, set[UUID]] = {}
        outgoing_nodes: set[UUID] = set()
        undirected: dict[UUID, set[UUID]] = {}
        physical_incidence: dict[tuple[UUID, UUID], int] = {}
        for edge in network_edges:
            adjacency.setdefault(edge.start_node_id, set()).add(edge.end_node_id)
            incoming_wires.setdefault(edge.end_node_id, set()).add(edge.physical_wire_id)
            outgoing_nodes.add(edge.start_node_id)
            undirected.setdefault(edge.start_node_id, set()).add(edge.end_node_id)
            undirected.setdefault(edge.end_node_id, set()).add(edge.start_node_id)
            for node_id in (edge.start_node_id, edge.end_node_id):
                key = (edge.physical_wire_id, node_id)
                physical_incidence[key] = physical_incidence.get(key, 0) + 1

        if _contains_cycle(adjacency):
            issues.append(
                ValidationIssue(
                    "topology_cycle",
                    "topology.edges",
                    f"Logical network {network_id} contains a directed cycle.",
                )
            )
        for node_id, incoming in incoming_wires.items():
            if len(incoming) > 1 and node_id in outgoing_nodes:
                issues.append(
                    ValidationIssue(
                        "physical_leg_recombination",
                        "topology.edges",
                        "Separate physical legs may not recombine during M2.",
                    )
                )
        if any(count > 2 for count in physical_incidence.values()):
            issues.append(
                ValidationIssue(
                    "physical_wire_branching",
                    "topology.edges",
                    "A physical-wire identity must remain a single unbranched leg.",
                )
            )

        candidate_nodes = set(undirected) | external_by_network.get(network_id, set())
        remaining = set(candidate_nodes)
        while remaining:
            start = min(remaining, key=lambda identity: identity.hex)
            component = _connected_component(start, undirected)
            remaining.difference_update(component)
            real_ends = component & external_by_network.get(network_id, set())
            if len(real_ends) < 2:
                issues.append(
                    ValidationIssue(
                        "partial_topology",
                        "topology.edges",
                        "Every active route component must connect at least two external ends.",
                    )
                )


def _contains_cycle(adjacency: dict[UUID, set[UUID]]) -> bool:
    """
    Return whether a directed adjacency map contains a cycle.
    """
    visiting: set[UUID] = set()
    visited: set[UUID] = set()

    def visit(node_id: UUID) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        if any(visit(next_id) for next_id in adjacency.get(node_id, set())):
            return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    return any(visit(node_id) for node_id in adjacency)


def _connected_component(start: UUID, adjacency: dict[UUID, set[UUID]]) -> set[UUID]:
    """
    Return the undirected component containing one node.
    """
    found: set[UUID] = set()
    pending = [start]
    while pending:
        node_id = pending.pop()
        if node_id in found:
            continue
        found.add(node_id)
        pending.extend(adjacency.get(node_id, ()))
    return found
