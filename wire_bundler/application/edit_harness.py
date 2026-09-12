"""
Edit ordered pathway gates and wire endpoint pairings transactionally.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Optional, Protocol
from uuid import UUID, uuid4

from ..domain import (
    Connection,
    ControlKind,
    ControlStructure,
    HarnessDefinition,
    JunctionDefinition,
    JunctionPathwayRelationship,
    PathwayDefinition,
    PathwayEndpoint,
    RefineGeometry,
    RoutingMode,
    WireDefinition,
    WireMaterialOverrides,
    WireMaterialSettings,
    dumps,
    loads,
    next_available_name,
    route_control_ids,
    validate_harness,
)
from ..domain.model import InterpolationSettings


class HarnessEditGateway(Protocol):
    """
    Describe persisted harness operations required by ordered edits.
    """

    def read_harness_definition(self, harness_id: UUID) -> str:
        """
        Return the serialized definition owned by one harness.
        """

    def replace_harness_definition(self, harness_id: UUID, serialized_definition: str) -> None:
        """
        Replace the serialized definition owned by one harness.
        """


class HarnessEditError(RuntimeError):
    """
    Report an edit that failed and could not be rolled back cleanly.
    """


@dataclass(frozen=True)
class PathwaySegmentResult:
    """
    Return the two pathway halves and their intervening junction.
    """

    preceding_pathway: PathwayDefinition
    following_pathway: PathwayDefinition
    junction: JunctionDefinition


def add_junction(
    harness_id: UUID,
    entity_token: str,
    gateway: HarnessEditGateway,
    id_factory: Callable[[], UUID] = uuid4,
) -> JunctionDefinition:
    """
    Persist one unconnected routing-gate junction from unused Fusion geometry.
    """
    normalized_token = entity_token.strip()
    if not normalized_token:
        raise ValueError("A junction must reference Fusion geometry.")
    original, definition = _read_definition(harness_id, gateway)
    registered_tokens = {
        token.strip() for connection in definition.connections for token in connection.member_tokens
    } | {control.entity_token.strip() for control in definition.controls if control.entity_token}
    if normalized_token in registered_tokens:
        raise ValueError("Selected geometry is already registered in this harness.")

    control_id = id_factory()
    junction_id = id_factory()
    existing_ids = {
        definition.harness_id,
        *(profile.profile_id for profile in definition.profiles),
        *(connection.connection_id for connection in definition.connections),
        *(
            member_id
            for connection in definition.connections
            for member_id in connection.member_identities
        ),
        *(control.control_id for control in definition.controls),
        *(pathway.pathway_id for pathway in definition.pathways),
        *(junction.junction_id for junction in definition.junctions),
        *(wire.wire_id for wire in definition.wires),
    }
    if control_id in existing_ids or junction_id in existing_ids | {control_id}:
        raise ValueError("Generated control or junction identity is already in use.")
    control = ControlStructure(
        control_id=control_id,
        name=next_available_name(
            "Routing Gate 01", (candidate.name for candidate in definition.controls)
        ),
        kind=ControlKind.ROUTING_GATE,
        entity_token=normalized_token,
        interpolation=definition.gate_defaults,
    )
    junction = JunctionDefinition(
        junction_id=junction_id,
        name=next_available_name(
            "Junction 01", (candidate.name for candidate in definition.junctions)
        ),
        control_id=control.control_id,
    )
    updated = replace(
        definition,
        controls=(*definition.controls, control),
        junctions=(*definition.junctions, junction),
    )
    _persist(harness_id, original, updated, gateway)
    return junction


def update_junction_relationships(
    harness_id: UUID,
    junction_id: UUID,
    pathway_relationships: tuple[JunctionPathwayRelationship, ...],
    gateway: HarnessEditGateway,
) -> JunctionDefinition:
    """
    Replace one junction's endpoint relationships and preserve wire control order.
    """
    if any(
        not isinstance(relationship, JunctionPathwayRelationship)
        for relationship in pathway_relationships
    ):
        raise ValueError("Every junction relationship must identify a pathway endpoint.")
    original, definition = _read_definition(harness_id, gateway)
    updated_junction, updated = _replace_junction_relationships(
        definition,
        junction_id,
        pathway_relationships,
    )
    _persist(harness_id, original, updated, gateway)
    return updated_junction


def add_junction_relationship(
    harness_id: UUID,
    junction_id: UUID,
    pathway_relationship: JunctionPathwayRelationship,
    gateway: HarnessEditGateway,
) -> JunctionDefinition:
    """
    Attach one available pathway endpoint to a junction atomically.
    """
    if not isinstance(pathway_relationship, JunctionPathwayRelationship):
        raise ValueError("A junction relationship must identify a pathway endpoint.")
    original, definition = _read_definition(harness_id, gateway)
    junction = next(
        (candidate for candidate in definition.junctions if candidate.junction_id == junction_id),
        None,
    )
    if junction is None:
        raise ValueError("Selected junction does not exist in this harness.")
    if pathway_relationship in junction.pathway_relationships:
        raise ValueError("Selected pathway endpoint is already related to this junction.")
    updated_junction, updated = _replace_junction_relationships(
        definition,
        junction_id,
        (*junction.pathway_relationships, pathway_relationship),
    )
    _persist(harness_id, original, updated, gateway)
    return updated_junction


def remove_junction_relationship(
    harness_id: UUID,
    junction_id: UUID,
    pathway_relationship: JunctionPathwayRelationship,
    gateway: HarnessEditGateway,
) -> JunctionDefinition:
    """
    Detach one exact pathway endpoint from a junction atomically.
    """
    if not isinstance(pathway_relationship, JunctionPathwayRelationship):
        raise ValueError("A junction relationship must identify a pathway endpoint.")
    original, definition = _read_definition(harness_id, gateway)
    junction = next(
        (candidate for candidate in definition.junctions if candidate.junction_id == junction_id),
        None,
    )
    if junction is None:
        raise ValueError("Selected junction does not exist in this harness.")
    if pathway_relationship not in junction.pathway_relationships:
        raise ValueError("Selected junction relationship no longer exists.")
    updated_junction, updated = _replace_junction_relationships(
        definition,
        junction_id,
        tuple(
            relationship
            for relationship in junction.pathway_relationships
            if relationship != pathway_relationship
        ),
    )
    _persist(harness_id, original, updated, gateway)
    return updated_junction


def rename_junction(
    harness_id: UUID,
    junction_id: UUID,
    name: str,
    gateway: HarnessEditGateway,
) -> None:
    """
    Rename one junction without changing its control or pathway relationships.

    Clearing the name restores an available generated junction designation.
    """
    if not isinstance(name, str):
        raise ValueError("Junction name must be a string.")
    original, definition = _read_definition(harness_id, gateway)
    junction = next(
        (candidate for candidate in definition.junctions if candidate.junction_id == junction_id),
        None,
    )
    if junction is None:
        raise ValueError("Selected junction does not exist in this harness.")
    resolved_name = next_available_name(
        name.strip() or "Junction 01",
        (
            candidate.name
            for candidate in definition.junctions
            if candidate.junction_id != junction_id
        ),
    )
    updated = replace(junction, name=resolved_name)
    _persist(
        harness_id,
        original,
        replace(
            definition,
            junctions=tuple(
                updated if candidate.junction_id == junction_id else candidate
                for candidate in definition.junctions
            ),
        ),
        gateway,
    )


def _replace_junction_relationships(
    definition: HarnessDefinition,
    junction_id: UUID,
    pathway_relationships: tuple[JunctionPathwayRelationship, ...],
) -> tuple[JunctionDefinition, HarnessDefinition]:
    """
    Build and validate one deterministic junction-relationship replacement.

    This deliberately validates junction topology rather than whole-harness
    generation readiness, so a wire-free draft remains editable.
    """
    junction = next(
        (candidate for candidate in definition.junctions if candidate.junction_id == junction_id),
        None,
    )
    if junction is None:
        raise ValueError("Selected junction does not exist in this harness.")
    pathway_order = {pathway.pathway_id: index for index, pathway in enumerate(definition.pathways)}
    if any(relationship.pathway_id not in pathway_order for relationship in pathway_relationships):
        raise ValueError("A selected junction pathway no longer exists.")
    relationship_keys = {
        (relationship.pathway_id, relationship.endpoint) for relationship in pathway_relationships
    }
    if len(relationship_keys) != len(pathway_relationships):
        raise ValueError("A pathway endpoint may be selected only once per junction.")
    ordered_relationships = tuple(
        sorted(
            pathway_relationships,
            key=lambda relationship: (
                pathway_order[relationship.pathway_id],
                0 if relationship.endpoint is PathwayEndpoint.START else 1,
            ),
        )
    )
    updated_junction = replace(junction, pathway_relationships=ordered_relationships)
    updated = replace(
        definition,
        junctions=tuple(
            updated_junction if candidate.junction_id == junction_id else candidate
            for candidate in definition.junctions
        ),
    )
    updated = _synchronize_wire_controls(updated)
    issues = tuple(
        issue for issue in validate_harness(updated) if issue.path.startswith("junctions[")
    )
    if issues:
        raise ValueError(issues[0].message)
    return updated_junction, updated


def suggest_pathway_extension_name(
    harness_id: UUID,
    pathway_id: UUID,
    gateway: HarnessEditGateway,
) -> str:
    """
    Return the next root-sequenced extension name for a pathway chain.
    """
    _original, definition = _read_definition(harness_id, gateway)
    pathway = _require_pathway(definition, pathway_id)
    predecessors: dict[UUID, set[UUID]] = {}
    for junction in definition.junctions:
        preceding_ids = {
            relationship.pathway_id
            for relationship in junction.pathway_relationships
            if relationship.endpoint is PathwayEndpoint.END
        }
        for relationship in junction.pathway_relationships:
            if relationship.endpoint is PathwayEndpoint.START:
                predecessors.setdefault(relationship.pathway_id, set()).update(preceding_ids)
    root_id = pathway.pathway_id
    visited: set[UUID] = set()
    while len(predecessors.get(root_id, ())) == 1:
        if root_id in visited:
            raise ValueError("The pathway junction chain contains a cycle.")
        visited.add(root_id)
        root_id = next(iter(predecessors[root_id]))
    root = _require_pathway(definition, root_id)
    return next_available_name(
        f"{root.name} ext 1",
        (candidate.name for candidate in definition.pathways),
    )


def segment_pathway(
    harness_id: UUID,
    pathway_id: UUID,
    control_id: UUID,
    following_name: str,
    gateway: HarnessEditGateway,
    id_factory: Callable[[], UUID] = uuid4,
) -> PathwaySegmentResult:
    """
    Split a pathway around one interior control and persist its junction atomically.
    """
    normalized_name = following_name.strip()
    if not normalized_name:
        raise ValueError("New pathway name must not be empty.")
    original, definition = _read_definition(harness_id, gateway)
    pathway = _require_pathway(definition, pathway_id)
    try:
        control_index = pathway.ordered_control_ids.index(control_id)
    except ValueError as error:
        raise ValueError("Selected control does not belong to this pathway.") from error
    if control_index == 0 or control_index == len(pathway.ordered_control_ids) - 1:
        raise ValueError("Select a pathway control that is not an end.")
    control = next(
        (candidate for candidate in definition.controls if candidate.control_id == control_id),
        None,
    )
    if control is None:
        raise ValueError("Selected pathway control no longer exists.")
    if control.kind not in {ControlKind.ROUTING_GATE, ControlKind.REFINE}:
        raise ValueError("Only routing gates and refine points can currently segment a pathway.")

    following_pathway_id = id_factory()
    junction_id = id_factory()
    existing_ids = {
        definition.harness_id,
        *(profile.profile_id for profile in definition.profiles),
        *(connection.connection_id for connection in definition.connections),
        *(candidate.control_id for candidate in definition.controls),
        *(candidate.pathway_id for candidate in definition.pathways),
        *(candidate.junction_id for candidate in definition.junctions),
        *(wire.wire_id for wire in definition.wires),
    }
    if following_pathway_id in existing_ids or junction_id in existing_ids | {following_pathway_id}:
        raise ValueError("Generated pathway or junction identity is already in use.")
    resolved_name = next_available_name(
        normalized_name,
        (candidate.name for candidate in definition.pathways),
    )
    preceding_pathway = replace(
        pathway,
        ordered_control_ids=pathway.ordered_control_ids[:control_index],
        end_name="",
    )
    following_pathway = PathwayDefinition(
        pathway_id=following_pathway_id,
        name=resolved_name,
        routing_mode=pathway.routing_mode,
        ordered_control_ids=pathway.ordered_control_ids[control_index + 1 :],
        end_name=pathway.end_name,
    )
    junction = JunctionDefinition(
        junction_id=junction_id,
        name=next_available_name(
            "Junction 01", (candidate.name for candidate in definition.junctions)
        ),
        control_id=control_id,
        pathway_relationships=(
            JunctionPathwayRelationship(pathway.pathway_id, PathwayEndpoint.END),
            JunctionPathwayRelationship(following_pathway.pathway_id, PathwayEndpoint.START),
        ),
    )

    pathways: list[PathwayDefinition] = []
    for candidate in definition.pathways:
        pathways.append(preceding_pathway if candidate.pathway_id == pathway_id else candidate)
        if candidate.pathway_id == pathway_id:
            pathways.append(following_pathway)
    prior_junctions = tuple(
        replace(
            candidate,
            pathway_relationships=tuple(
                JunctionPathwayRelationship(following_pathway.pathway_id, relationship.endpoint)
                if relationship.pathway_id == pathway_id
                and relationship.endpoint is PathwayEndpoint.END
                else relationship
                for relationship in candidate.pathway_relationships
            ),
        )
        for candidate in definition.junctions
    )
    wires = tuple(
        replace(
            wire,
            ordered_pathway_ids=tuple(
                inserted_id
                for candidate_id in wire.ordered_pathway_ids
                for inserted_id in (
                    (candidate_id, following_pathway.pathway_id)
                    if candidate_id == pathway_id
                    else (candidate_id,)
                )
            ),
        )
        for wire in definition.wires
    )
    updated = replace(
        definition,
        pathways=tuple(pathways),
        junctions=(*prior_junctions, junction),
        wires=wires,
    )
    updated = _synchronize_wire_controls(updated)
    _persist(harness_id, original, updated, gateway)
    return PathwaySegmentResult(preceding_pathway, following_pathway, junction)


def add_pathway_refine(
    harness_id: UUID,
    pathway_id: UUID,
    insertion_index: int,
    geometry: RefineGeometry,
    gateway: HarnessEditGateway,
    id_factory: Callable[[], UUID] = uuid4,
) -> ControlStructure:
    """
    Insert one persistent unconstrained refine into a pathway traversal.
    """
    if isinstance(insertion_index, bool) or not isinstance(insertion_index, int):
        raise ValueError("Refine insertion position must be an integer.")
    if not isinstance(geometry, RefineGeometry):
        raise ValueError("Refine geometry is invalid.")
    original, definition = _read_definition(harness_id, gateway)
    pathway = _require_pathway(definition, pathway_id)
    if not 0 <= insertion_index <= len(pathway.ordered_control_ids):
        raise ValueError("Refine insertion position is outside the pathway.")
    insertion_index = _clamp_pathway_insertion_index(
        definition,
        pathway,
        insertion_index,
    )
    control = ControlStructure(
        control_id=id_factory(),
        name=next_available_name("Refine Point 01", (item.name for item in definition.controls)),
        kind=ControlKind.REFINE,
        entity_token="",
        interpolation=definition.gate_defaults,
        refine_geometry=geometry,
    )
    ordered_ids = list(pathway.ordered_control_ids)
    ordered_ids.insert(insertion_index, control.control_id)
    updated_pathway = replace(pathway, ordered_control_ids=tuple(ordered_ids))
    updated = replace(
        definition,
        controls=(*definition.controls, control),
        pathways=_replace_pathway(definition, updated_pathway),
    )
    updated = _synchronize_wire_controls(updated)
    _persist(harness_id, original, updated, gateway)
    return control


def update_pathway_refine(
    harness_id: UUID,
    control_id: UUID,
    geometry: RefineGeometry,
    gateway: HarnessEditGateway,
) -> ControlStructure:
    """
    Persist a new position, orientation, and display radius for one refine.
    """
    if not isinstance(geometry, RefineGeometry):
        raise ValueError("Refine geometry is invalid.")
    original, definition = _read_definition(harness_id, gateway)
    control = next(
        (item for item in definition.controls if item.control_id == control_id),
        None,
    )
    if control is None or control.kind is not ControlKind.REFINE:
        raise ValueError("Selected refine point no longer exists.")
    updated_control = replace(control, refine_geometry=geometry)
    updated = replace(
        definition,
        controls=tuple(
            updated_control if item.control_id == control_id else item
            for item in definition.controls
        ),
    )
    _persist(harness_id, original, updated, gateway)
    return updated_control


def append_pathway_gates(
    harness_id: UUID,
    pathway_id: UUID,
    gate_entity_tokens: tuple[str, ...],
    gateway: HarnessEditGateway,
    id_factory: Callable[[], UUID] = uuid4,
) -> tuple[ControlStructure, ...]:
    """
    Append selected profiles to an existing pathway in selection order.
    """
    normalized_tokens = tuple(token.strip() for token in gate_entity_tokens)
    if not normalized_tokens:
        raise ValueError("Select at least one gate profile to append.")
    if any(not token for token in normalized_tokens):
        raise ValueError("Every pathway gate must reference Fusion geometry.")

    original, definition = _read_definition(harness_id, gateway)
    pathway = _require_pathway(definition, pathway_id)
    kind = (
        ControlKind.ROUTING_GATE
        if pathway.routing_mode is RoutingMode.ROUTING_GATES
        else ControlKind.PROFILE_GATE
    )
    label = "Routing Gate" if kind is ControlKind.ROUTING_GATE else "Profile Gate"
    existing_names = [control.name for control in definition.controls]
    controls: list[ControlStructure] = []
    for token in normalized_tokens:
        name = next_available_name(f"{label} 01", (*existing_names, *(c.name for c in controls)))
        controls.append(ControlStructure(id_factory(), name, kind, token, definition.gate_defaults))

    insertion_index = _clamp_pathway_insertion_index(
        definition,
        pathway,
        len(pathway.ordered_control_ids),
    )
    ordered_control_ids = list(pathway.ordered_control_ids)
    ordered_control_ids[insertion_index:insertion_index] = [
        control.control_id for control in controls
    ]
    updated_pathway = replace(pathway, ordered_control_ids=tuple(ordered_control_ids))
    updated = replace(
        definition,
        controls=(*definition.controls, *controls),
        pathways=_replace_pathway(definition, updated_pathway),
    )
    updated = _synchronize_wire_controls(updated)
    _persist(harness_id, original, updated, gateway)
    return tuple(controls)


def move_pathway_gate(
    harness_id: UUID,
    pathway_id: UUID,
    control_id: UUID,
    offset: int,
    gateway: HarnessEditGateway,
) -> PathwayDefinition:
    """
    Insert one gate at a new position within its pathway.
    """
    if isinstance(offset, bool) or not isinstance(offset, int) or offset == 0:
        raise ValueError("Gate movement requires a nonzero integer offset.")
    original, definition = _read_definition(harness_id, gateway)
    pathway = _require_pathway(definition, pathway_id)
    ordered_ids = list(pathway.ordered_control_ids)
    try:
        current_index = ordered_ids.index(control_id)
    except ValueError as error:
        raise ValueError("Selected gate does not belong to this pathway.") from error
    target_index = current_index + offset
    if target_index < 0 or target_index >= len(ordered_ids):
        raise ValueError("Selected gate is already at that end of the pathway.")
    locked_indexes = _locked_pathway_control_indexes(definition, pathway)
    if current_index in locked_indexes or target_index in locked_indexes:
        raise ValueError("A junction-related pathway endpoint cannot be reordered.")
    ordered_ids.insert(target_index, ordered_ids.pop(current_index))
    updated_pathway = replace(pathway, ordered_control_ids=tuple(ordered_ids))
    updated = replace(definition, pathways=_replace_pathway(definition, updated_pathway))
    updated = _synchronize_wire_controls(updated)
    _persist(harness_id, original, updated, gateway)
    return updated_pathway


def remove_pathway_gate(
    harness_id: UUID,
    pathway_id: UUID,
    control_id: UUID,
    gateway: HarnessEditGateway,
) -> PathwayDefinition:
    """
    Remove one gate and prune its control when no pathway still uses it.
    """
    original, definition = _read_definition(harness_id, gateway)
    pathway = _require_pathway(definition, pathway_id)
    if control_id not in pathway.ordered_control_ids:
        raise ValueError("Selected gate does not belong to this pathway.")
    if len(pathway.ordered_control_ids) == 1:
        raise ValueError("A pathway must retain at least one gate.")
    control_index = pathway.ordered_control_ids.index(control_id)
    if control_index in _locked_pathway_control_indexes(definition, pathway):
        raise ValueError("A junction-related pathway endpoint cannot be removed.")
    updated_pathway = replace(
        pathway,
        ordered_control_ids=tuple(
            item for item in pathway.ordered_control_ids if item != control_id
        ),
    )
    pathways = _replace_pathway(definition, updated_pathway)
    referenced_control_ids = {
        item for candidate in pathways for item in candidate.ordered_control_ids
    }
    updated = replace(
        definition,
        controls=tuple(
            control
            for control in definition.controls
            if control.control_id != control_id or control.control_id in referenced_control_ids
        ),
        pathways=pathways,
    )
    updated = _synchronize_wire_controls(updated)
    _persist(harness_id, original, updated, gateway)
    return updated_pathway


def move_wire_endpoint(
    harness_id: UUID,
    wire_id: UUID,
    endpoint: str,
    offset: int,
    gateway: HarnessEditGateway,
) -> tuple[WireDefinition, ...]:
    """
    Reorder one endpoint within wires sharing the same pathway sequence.
    """
    if endpoint not in {"start", "end"}:
        raise ValueError("Endpoint must be 'start' or 'end'.")
    _validate_offset(offset)
    original, definition = _read_definition(harness_id, gateway)
    selected = next((wire for wire in definition.wires if wire.wire_id == wire_id), None)
    if selected is None:
        raise ValueError("Selected wire does not exist in this harness.")
    group = [
        wire
        for wire in definition.wires
        if wire.ordered_pathway_ids == selected.ordered_pathway_ids
    ]
    current_index = next(index for index, wire in enumerate(group) if wire.wire_id == wire_id)
    target_index = current_index + offset
    if target_index < 0 or target_index >= len(group):
        raise ValueError("Selected endpoint is already at that end of its sequence.")

    current_wire = group[current_index]
    target_wire = group[target_index]
    attribute = "start_connection_id" if endpoint == "start" else "end_connection_id"
    replacements = {
        current_wire.wire_id: replace(
            current_wire,
            **{attribute: getattr(target_wire, attribute)},
        ),
        target_wire.wire_id: replace(
            target_wire,
            **{attribute: getattr(current_wire, attribute)},
        ),
    }
    updated_wires = tuple(replacements.get(wire.wire_id, wire) for wire in definition.wires)
    updated = replace(definition, wires=updated_wires)
    _persist(harness_id, original, updated, gateway)
    return updated_wires


def edit_end_members(
    harness_id: UUID,
    wire_id: UUID,
    endpoint: str,
    action: str,
    gateway: HarnessEditGateway,
    tokens: tuple[str, ...] = (),
    member_index: int = 0,
    expected_members: int = 0,
    target_index: int = 0,
) -> None:
    """
    Insert, replace, reorder, or remove profiles without creating wires.

    Removing the final member deletes the connection and leaves a repairable
    missing end reference. The expected count rejects stale member edits.
    """
    if endpoint not in {"start", "end"} or action not in {
        "add",
        "replace",
        "remove",
        "reorder",
    }:
        raise ValueError("Unsupported end-member edit.")
    normalized = tuple(token.strip() for token in tokens)
    if action in {"add", "replace"} and (not normalized or any(not token for token in normalized)):
        raise ValueError("Select at least one connection profile.")
    if action == "replace" and len(normalized) != 1:
        raise ValueError("Select exactly one replacement profile.")
    original, definition = _read_definition(harness_id, gateway)
    wire = next((item for item in definition.wires if item.wire_id == wire_id), None)
    if wire is None:
        raise ValueError("Selected wire no longer exists.")
    connection_id = wire.start_connection_id if endpoint == "start" else wire.end_connection_id
    connection = next(
        (item for item in definition.connections if item.connection_id == connection_id), None
    )
    members = list(connection.member_tokens) if connection else []
    identities = list(connection.member_identities) if connection else []
    settings = (
        list(connection.member_interpolations or (None,) * len(members)) if connection else []
    )
    if len(members) != expected_members:
        raise ValueError("End members changed; refresh the palette and try again.")
    if action == "add":
        if members and not 0 <= member_index < len(members):
            raise ValueError("Selected end member no longer exists.")
        members[member_index + 1 : member_index + 1] = normalized
        identities[member_index + 1 : member_index + 1] = [uuid4() for _ in normalized]
        settings[member_index + 1 : member_index + 1] = [None for _ in normalized]
    else:
        if member_index < 0 or member_index >= len(members):
            raise ValueError("Selected end member no longer exists.")
        if action == "replace":
            members[member_index] = normalized[0]
        elif action == "reorder":
            if not 0 <= target_index < len(members):
                raise ValueError("Cannot move an end member beyond the sequence.")
            members.insert(target_index, members.pop(member_index))
            identities.insert(target_index, identities.pop(member_index))
            settings.insert(target_index, settings.pop(member_index))
        else:
            members.pop(member_index)
            identities.pop(member_index)
            settings.pop(member_index)
    remaining = tuple(
        item for item in definition.connections if item.connection_id != connection_id
    )
    if members:
        name = (
            connection.name
            if connection
            else next_available_name(
                "End A 001" if endpoint == "start" else "End B 001",
                (item.name for item in remaining),
            )
        )
        updated = Connection(
            connection_id,
            name,
            members[0],
            tuple(members[1:]),
            tuple(identities),
            connection.interpolation if connection else definition.end_defaults,
            tuple(settings),
        )
        connections = (
            tuple(
                updated if item.connection_id == connection_id else item
                for item in definition.connections
            )
            if connection
            else (*remaining, updated)
        )
    else:
        connections = remaining
    _persist(harness_id, original, replace(definition, connections=connections), gateway)


def rename_route_end(
    harness_id: UUID,
    wire_id: UUID,
    endpoint: str,
    name: str,
    gateway: HarnessEditGateway,
) -> None:
    """
    Save organizational end metadata for the selected wire only.

    Empty names clear the label; connection names and conductor identities remain intact.
    """
    if endpoint not in {"start", "end"}:
        raise ValueError("Endpoint must be 'start' or 'end'.")
    if not isinstance(name, str):
        raise ValueError("End name must be a string.")
    original, definition = _read_definition(harness_id, gateway)
    selected = next((wire for wire in definition.wires if wire.wire_id == wire_id), None)
    if selected is None:
        raise ValueError("Selected wire does not exist in this harness.")
    attribute = "start_end_name" if endpoint == "start" else "end_end_name"
    wires = tuple(
        replace(wire, **{attribute: name.strip()}) if wire.wire_id == selected.wire_id else wire
        for wire in definition.wires
    )
    _persist(harness_id, original, replace(definition, wires=wires), gateway)


def rename_wire(
    harness_id: UUID,
    wire_id: UUID,
    name: str,
    gateway: HarnessEditGateway,
) -> None:
    """
    Set an optional display name while retaining the wire's number and UUID.
    """
    if not isinstance(name, str):
        raise ValueError("Wire name must be a string.")
    original, definition = _read_definition(harness_id, gateway)
    if all(wire.wire_id != wire_id for wire in definition.wires):
        raise ValueError("Selected wire does not exist in this harness.")
    normalized = name.strip()
    if normalized:
        normalized = next_available_name(
            normalized,
            (wire.display_name for wire in definition.wires if wire.wire_id != wire_id),
        )
    wires = tuple(
        replace(wire, display_name=normalized) if wire.wire_id == wire_id else wire
        for wire in definition.wires
    )
    _persist(harness_id, original, replace(definition, wires=wires), gateway)


def set_wire_diameter(
    harness_id: UUID,
    wire_id: UUID,
    diameter_mm: float,
    gateway: HarnessEditGateway,
    id_factory: Callable[[], UUID] = uuid4,
) -> None:
    """
    Update one wire's diameter, copying a shared profile before changing it.
    """
    if not math.isfinite(diameter_mm) or diameter_mm <= 0:
        raise ValueError("Wire diameter must be a finite positive value.")
    original, definition = _read_definition(harness_id, gateway)
    wire = next((item for item in definition.wires if item.wire_id == wire_id), None)
    if wire is None:
        raise ValueError("Selected wire does not exist in this harness.")
    profile = next(
        (item for item in definition.profiles if item.profile_id == wire.profile_id), None
    )
    if profile is None:
        raise ValueError("Selected wire has a missing profile.")
    shared = any(
        item.wire_id != wire_id and item.profile_id == profile.profile_id
        for item in definition.wires
    )
    if shared:
        updated_profile = replace(
            profile,
            profile_id=id_factory(),
            diameter_mm=diameter_mm,
            name=next_available_name(profile.name, (item.name for item in definition.profiles)),
        )
        profiles = (*definition.profiles, updated_profile)
    else:
        updated_profile = replace(profile, diameter_mm=diameter_mm)
        profiles = tuple(
            updated_profile if item.profile_id == profile.profile_id else item
            for item in definition.profiles
        )
    wires = tuple(
        replace(item, profile_id=updated_profile.profile_id) if item.wire_id == wire_id else item
        for item in definition.wires
    )
    _persist(harness_id, original, replace(definition, profiles=profiles, wires=wires), gateway)


def set_harness_material_defaults(
    harness_id: UUID,
    settings: WireMaterialSettings,
    gateway: HarnessEditGateway,
) -> None:
    """
    Replace the parent material settings inherited by wires without overrides.
    """
    if not isinstance(settings, WireMaterialSettings):
        raise ValueError("Harness material defaults are invalid.")
    original, definition = _read_definition(harness_id, gateway)
    _persist(
        harness_id,
        original,
        replace(definition, material_defaults=settings),
        gateway,
    )


def set_wire_material_overrides(
    harness_id: UUID,
    wire_id: UUID,
    overrides: WireMaterialOverrides,
    gateway: HarnessEditGateway,
) -> None:
    """
    Replace one wire's field-level overrides while retaining parent inheritance.
    """
    if not isinstance(overrides, WireMaterialOverrides):
        raise ValueError("Wire material overrides are invalid.")
    original, definition = _read_definition(harness_id, gateway)
    if not any(wire.wire_id == wire_id for wire in definition.wires):
        raise ValueError("Selected wire does not exist in this harness.")
    wires = tuple(
        replace(wire, material_overrides=overrides) if wire.wire_id == wire_id else wire
        for wire in definition.wires
    )
    _persist(harness_id, original, replace(definition, wires=wires), gateway)


def rename_pathway(
    harness_id: UUID,
    pathway_id: UUID,
    field: str,
    name: str,
    gateway: HarnessEditGateway,
) -> None:
    """
    Rename a pathway or either traversal end without changing route identity.

    Clearing the pathway name restores an available generated designation.
    """
    if field not in {"name", "start_name", "end_name"}:
        raise ValueError("Unsupported pathway name field.")
    if not isinstance(name, str):
        raise ValueError("Pathway name must be a string.")
    original, definition = _read_definition(harness_id, gateway)
    pathway = _require_pathway(definition, pathway_id)
    normalized = name.strip()
    if field == "name":
        normalized = next_available_name(
            normalized or "Pathway 01",
            (item.name for item in definition.pathways if item.pathway_id != pathway_id),
        )
    updated = replace(pathway, **{field: normalized})
    _persist(
        harness_id,
        original,
        replace(definition, pathways=_replace_pathway(definition, updated)),
        gateway,
    )


def remove_wire(
    harness_id: UUID,
    wire_id: UUID,
    gateway: HarnessEditGateway,
) -> None:
    """
    Remove one complete wire pair and prune its unused connections and profile.
    """
    original, definition = _read_definition(harness_id, gateway)
    removed = next((wire for wire in definition.wires if wire.wire_id == wire_id), None)
    if removed is None:
        raise ValueError("Selected wire does not exist in this harness.")
    wires = tuple(wire for wire in definition.wires if wire.wire_id != wire_id)
    referenced_connection_ids = {
        connection_id
        for wire in wires
        for connection_id in (wire.start_connection_id, wire.end_connection_id)
    }
    referenced_profile_ids = {wire.profile_id for wire in wires}
    removed_connection_ids = {removed.start_connection_id, removed.end_connection_id}
    updated = replace(
        definition,
        connections=tuple(
            connection
            for connection in definition.connections
            if connection.connection_id not in removed_connection_ids
            or connection.connection_id in referenced_connection_ids
        ),
        profiles=tuple(
            profile
            for profile in definition.profiles
            if profile.profile_id != removed.profile_id
            or profile.profile_id in referenced_profile_ids
        ),
        wires=wires,
    )
    _persist(harness_id, original, updated, gateway)


def _validate_offset(offset: int) -> None:
    """
    Require a single-position ordered move.
    """
    if offset not in {-1, 1}:
        raise ValueError("Ordered moves must use an offset of -1 or 1.")


def _read_definition(
    harness_id: UUID,
    gateway: HarnessEditGateway,
) -> tuple[str, HarnessDefinition]:
    """
    Read both the exact serialized value and its parsed definition.
    """
    original = gateway.read_harness_definition(harness_id)
    return original, loads(original)


def _require_pathway(
    definition: HarnessDefinition,
    pathway_id: UUID,
) -> PathwayDefinition:
    """
    Return an existing pathway or reject a stale palette identity.
    """
    pathway = next(
        (item for item in definition.pathways if item.pathway_id == pathway_id),
        None,
    )
    if pathway is None:
        raise ValueError("Selected pathway does not exist in this harness.")
    return pathway


def _replace_pathway(
    definition: HarnessDefinition,
    updated_pathway: PathwayDefinition,
) -> tuple[PathwayDefinition, ...]:
    """
    Replace one pathway without changing collection order.
    """
    return tuple(
        updated_pathway if item.pathway_id == updated_pathway.pathway_id else item
        for item in definition.pathways
    )


def _related_pathway_endpoints(
    definition: HarnessDefinition,
    pathway_id: UUID,
) -> set[PathwayEndpoint]:
    """
    Return endpoint boundaries claimed by any junction for one pathway.
    """
    return {
        relationship.endpoint
        for junction in definition.junctions
        for relationship in junction.pathway_relationships
        if relationship.pathway_id == pathway_id
    }


def _locked_pathway_control_indexes(
    definition: HarnessDefinition,
    pathway: PathwayDefinition,
) -> set[int]:
    """
    Return control positions that define junction-related pathway boundaries.
    """
    if not pathway.ordered_control_ids:
        return set()
    endpoints = _related_pathway_endpoints(definition, pathway.pathway_id)
    locked: set[int] = set()
    if PathwayEndpoint.START in endpoints:
        locked.add(0)
    if PathwayEndpoint.END in endpoints:
        locked.add(len(pathway.ordered_control_ids) - 1)
    return locked


def _clamp_pathway_insertion_index(
    definition: HarnessDefinition,
    pathway: PathwayDefinition,
    requested_index: int,
) -> int:
    """
    Clamp new controls inside endpoint boundaries reserved by junctions.
    """
    endpoints = _related_pathway_endpoints(definition, pathway.pathway_id)
    minimum = 1 if PathwayEndpoint.START in endpoints else 0
    maximum = (
        len(pathway.ordered_control_ids) - 1
        if PathwayEndpoint.END in endpoints
        else len(pathway.ordered_control_ids)
    )
    if maximum < minimum:
        raise ValueError(
            "A one-control pathway related at both ends has no interior insertion position."
        )
    return min(max(requested_index, minimum), maximum)


def _synchronize_wire_controls(definition: HarnessDefinition) -> HarnessDefinition:
    """
    Rebuild every wire's flattened controls from its ordered pathways.
    """
    wires: list[WireDefinition] = []
    for wire in definition.wires:
        try:
            control_ids = route_control_ids(definition, wire.ordered_pathway_ids)
        except ValueError as error:
            if "missing pathway" in str(error):
                raise ValueError(
                    f"Wire {wire.wire_number} references a missing pathway and cannot be updated."
                ) from error
            raise ValueError(
                f"Wire {wire.wire_number} references an invalid pathway route and cannot be updated."
            ) from error
        wires.append(replace(wire, ordered_control_ids=control_ids))
    return replace(definition, wires=tuple(wires))


def _persist(
    harness_id: UUID,
    original_serialized: str,
    definition: HarnessDefinition,
    gateway: HarnessEditGateway,
) -> None:
    """
    Persist one edit and restore the exact prior value after failure.
    """
    try:
        gateway.replace_harness_definition(harness_id, dumps(definition))
    except Exception as persistence_error:
        try:
            gateway.replace_harness_definition(harness_id, original_serialized)
        except Exception as rollback_error:
            message = (
                f"Failed to persist the harness edit and restore its definition: {rollback_error}"
            )
            raise HarnessEditError(message) from persistence_error
        raise


def set_interpolation(
    harness_id: UUID,
    target: str,
    settings: InterpolationSettings,
    gateway: HarnessEditGateway,
    target_id: Optional[UUID] = None,
    end_defaults: Optional[InterpolationSettings] = None,
    apply_existing: bool = False,
    member_id: Optional[UUID] = None,
    use_defaults: bool = False,
) -> None:
    """
    Save section controls or creation defaults in one reversible metadata edit.

    Optionally apply both presets to existing sections in the same transaction.
    """
    original, definition = _read_definition(harness_id, gateway)
    if target == "defaults":
        if end_defaults is None:
            raise ValueError("Both gate and end defaults are required.")
        updated = replace(definition, gate_defaults=settings, end_defaults=end_defaults)
        if apply_existing:
            updated = replace(
                updated,
                controls=tuple(
                    replace(item, interpolation=settings)
                    if not item.interpolation_is_override
                    else item
                    for item in definition.controls
                ),
                connections=tuple(
                    replace(item, interpolation=end_defaults) for item in definition.connections
                ),
            )
    elif target == "gate":
        if not any(item.control_id == target_id for item in definition.controls):
            raise ValueError("Selected gate no longer exists.")
        updated = replace(
            definition,
            controls=tuple(
                replace(
                    item,
                    interpolation=definition.gate_defaults if use_defaults else settings,
                    interpolation_is_override=not use_defaults,
                )
                if item.control_id == target_id
                else item
                for item in definition.controls
            ),
        )
    elif target == "end":
        connection = next(
            (item for item in definition.connections if item.connection_id == target_id), None
        )
        if connection is None:
            raise ValueError("Selected end section no longer exists.")
        if member_id is None:
            edited = replace(connection, interpolation=settings, member_interpolations=())
        else:
            if member_id not in connection.member_identities:
                raise ValueError("Selected end member no longer exists.")
            edited = replace(
                connection,
                interpolation=definition.end_defaults if use_defaults else connection.interpolation,
                member_interpolations=tuple(
                    (None if use_defaults else settings) if identity == member_id else previous
                    for identity, previous in zip(
                        connection.member_identities,
                        connection.member_interpolations or (None,) * len(connection.member_tokens),
                    )
                ),
            )
        updated = replace(
            definition,
            connections=tuple(
                edited if item.connection_id == target_id else item
                for item in definition.connections
            ),
        )
    else:
        raise ValueError("Unsupported interpolation target.")
    _persist(harness_id, original, updated, gateway)
