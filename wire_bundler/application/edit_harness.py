"""
Edit ordered pathway gates and wire endpoint pairings transactionally.
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
    ControlStructure,
    HarnessDefinition,
    PathwayDefinition,
    RoutingMode,
    WireDefinition,
    dumps,
    loads,
    next_available_name,
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


def append_pathway_gates(
    harness_id: UUID,
    pathway_id: UUID,
    gate_entity_tokens: tuple[str, ...],
    gateway: HarnessEditGateway,
    id_factory: Callable[[], UUID] = uuid4,
) -> tuple[ControlStructure, ...]:
    """
    Append selected profiles to an existing pathway in selection order.

    Args:
        harness_id: Harness that owns the pathway.
        pathway_id: Pathway receiving the new gates.
        gate_entity_tokens: Fusion profile tokens in traversal order.
        gateway: Persistence boundary for the owning harness.
        id_factory: UUID factory, injectable for deterministic tests.

    Returns:
        Newly created routing controls.
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

    updated_pathway = replace(
        pathway,
        ordered_control_ids=(
            *pathway.ordered_control_ids,
            *(control.control_id for control in controls),
        ),
    )
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

    Args:
        harness_id: Harness that owns the pathway.
        pathway_id: Pathway containing the gate.
        control_id: Gate identity to move.
        offset: Nonzero relative movement to the drop position.
        gateway: Persistence boundary for the owning harness.

    Returns:
        Updated pathway definition.
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

    Args:
        harness_id: Harness that owns the pathway.
        pathway_id: Pathway containing the gate.
        control_id: Gate identity to remove.
        gateway: Persistence boundary for the owning harness.

    Returns:
        Updated pathway definition.
    """
    original, definition = _read_definition(harness_id, gateway)
    pathway = _require_pathway(definition, pathway_id)
    if control_id not in pathway.ordered_control_ids:
        raise ValueError("Selected gate does not belong to this pathway.")
    if len(pathway.ordered_control_ids) == 1:
        raise ValueError("A pathway must retain at least one gate.")
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

    Args:
        harness_id: Harness that owns the wires.
        wire_id: Stable wire row whose endpoint will move.
        endpoint: Endpoint sequence, ``start`` or ``end``.
        offset: Required movement, either ``-1`` or ``1``.
        gateway: Persistence boundary for the owning harness.

    Returns:
        Updated wires in their persisted display order.
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

    Args:
        harness_id: Harness that owns the wire.
        wire_id: Stable wire identity to remove.
        gateway: Persistence boundary for the owning harness.
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


def _synchronize_wire_controls(definition: HarnessDefinition) -> HarnessDefinition:
    """
    Rebuild every wire's flattened controls from its ordered pathways.
    """
    pathways = {pathway.pathway_id: pathway for pathway in definition.pathways}
    for wire in definition.wires:
        missing_pathway_ids = tuple(
            pathway_id for pathway_id in wire.ordered_pathway_ids if pathway_id not in pathways
        )
        if missing_pathway_ids:
            raise ValueError(
                f"Wire {wire.wire_number} references a missing pathway and cannot be updated."
            )
    wires = tuple(
        replace(
            wire,
            ordered_control_ids=tuple(
                control_id
                for pathway_id in wire.ordered_pathway_ids
                for control_id in pathways[pathway_id].ordered_control_ids
            ),
        )
        for wire in definition.wires
    )
    return replace(definition, wires=wires)


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
