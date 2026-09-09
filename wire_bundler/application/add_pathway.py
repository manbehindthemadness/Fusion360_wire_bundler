"""
Add an ordered reusable pathway to an existing harness definition.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Protocol
from uuid import UUID, uuid4

from ..domain import (
    ControlKind,
    ControlStructure,
    HarnessDefinition,
    PathwayDefinition,
    RoutingMode,
    dumps,
    loads,
    next_available_name,
)


class PathwayGateway(Protocol):
    """
    Describe persisted harness operations required by pathway creation.
    """

    def read_harness_definition(self, harness_id: UUID) -> str:
        """
        Return the serialized definition owned by one harness.
        """

    def replace_harness_definition(self, harness_id: UUID, serialized_definition: str) -> None:
        """
        Replace the serialized definition owned by one harness.
        """


class PathwayUpdateError(RuntimeError):
    """
    Report a pathway update that failed and could not be rolled back cleanly.
    """


def suggest_pathway_name(
    harness_id: UUID,
    requested_name: str,
    gateway: PathwayGateway,
) -> str:
    """
    Return a normalized conflict-free pathway name for one harness.

    Args:
        harness_id: Harness that will own the pathway.
        requested_name: Preferred user-facing pathway name.
        gateway: Persistence boundary for the owning harness.

    Returns:
        First available pathway name.
    """
    normalized_name = requested_name.strip()
    if not normalized_name:
        raise ValueError("Pathway name must not be empty.")
    definition = loads(gateway.read_harness_definition(harness_id))
    existing_names = [pathway.name for pathway in definition.pathways]
    resolved_name = next_available_name(normalized_name, existing_names)
    return resolved_name


def add_pathway(
    harness_id: UUID,
    name: str,
    routing_mode: RoutingMode,
    gate_entity_tokens: tuple[str, ...],
    gateway: PathwayGateway,
    id_factory: Callable[[], UUID] = uuid4,
) -> PathwayDefinition:
    """
    Append an ordered pathway and atomically persist the updated definition.

    Args:
        harness_id: Harness that will own the new pathway.
        name: Preferred user-facing pathway name.
        routing_mode: Routing strategy for the selected gates.
        gate_entity_tokens: Pathway-control profile tokens in traversal order.
            Connection-owned end profiles are not pathway gates; they still
            participate in downstream centerline fairing and solid sweeps.
        gateway: Persistence boundary for the owning harness.
        id_factory: UUID factory, injectable for deterministic tests.

    Returns:
        The newly persisted pathway.

    Raises:
        ValueError: If the pathway name or gate selections are invalid.
        PathwayUpdateError: If persistence fails and rollback also fails.
    """
    if not gate_entity_tokens:
        raise ValueError("A pathway requires at least one gate profile.")
    normalized_tokens = tuple(token.strip() for token in gate_entity_tokens)
    if any(not token for token in normalized_tokens):
        raise ValueError("Every pathway gate must reference Fusion geometry.")
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Pathway name must not be empty.")

    original_serialized = gateway.read_harness_definition(harness_id)
    definition = loads(original_serialized)
    resolved_name = next_available_name(
        normalized_name, [item.name for item in definition.pathways]
    )

    control_kind = (
        ControlKind.ROUTING_GATE
        if routing_mode is RoutingMode.ROUTING_GATES
        else ControlKind.PROFILE_GATE
    )
    control_label = "Routing Gate" if control_kind is ControlKind.ROUTING_GATE else "Profile Gate"
    controls = tuple(
        ControlStructure(
            control_id=id_factory(),
            name=f"{control_label} {index:02d}",
            kind=control_kind,
            entity_token=entity_token,
            interpolation=definition.gate_defaults,
        )
        for index, entity_token in enumerate(normalized_tokens, start=1)
    )
    pathway = PathwayDefinition(
        pathway_id=id_factory(),
        name=resolved_name,
        routing_mode=routing_mode,
        ordered_control_ids=tuple(control.control_id for control in controls),
    )
    updated_definition: HarnessDefinition = replace(
        definition,
        controls=(*definition.controls, *controls),
        pathways=(*definition.pathways, pathway),
    )

    try:
        gateway.replace_harness_definition(harness_id, dumps(updated_definition))
    except Exception as persistence_error:
        try:
            gateway.replace_harness_definition(harness_id, original_serialized)
        except Exception as rollback_error:
            message = f"Failed to persist the pathway and restore the harness definition: {rollback_error}"
            raise PathwayUpdateError(message) from persistence_error
        raise
    return pathway
