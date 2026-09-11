"""
Add ordered End A-to-End B wire assignments to an existing pathway.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID, uuid4

from ..domain import (
    Connection,
    HarnessDefinition,
    WireDefinition,
    WireProfile,
    dumps,
    loads,
    next_available_name,
)


class WireBatchGateway(Protocol):
    """
    Describe persisted harness operations required by wire assignment.
    """

    def read_harness_definition(self, harness_id: UUID) -> str:
        """
        Return the serialized definition owned by one harness.
        """

    def replace_harness_definition(self, harness_id: UUID, serialized_definition: str) -> None:
        """
        Replace the serialized definition owned by one harness.
        """


class WireBatchUpdateError(RuntimeError):
    """
    Report a wire update that failed and could not be rolled back cleanly.
    """


@dataclass(frozen=True)
class WireBatchResult:
    """
    Return the profile, connections, and wires added by one operation.

    Connections retain End A then End B order; wires retain user selection order.
    """

    profile: WireProfile
    connections: tuple[Connection, ...]
    wires: tuple[WireDefinition, ...]


def add_wire_batch(
    harness_id: UUID,
    pathway_id: UUID,
    source_entity_tokens: tuple[str, ...],
    destination_entity_tokens: tuple[str, ...],
    diameter_mm: float,
    gateway: WireBatchGateway,
    id_factory: Callable[[], UUID] = uuid4,
) -> WireBatchResult:
    """
    Pair ordered endpoint selections and atomically persist their wire mappings.

    Raises:
        ValueError: If selections, diameter, or pathway identity are invalid.
        WireBatchUpdateError: If persistence fails and rollback also fails.
    """
    normalized_sources = _normalize_tokens(source_entity_tokens, "End A")
    normalized_destinations = _normalize_tokens(destination_entity_tokens, "End B")
    if len(normalized_sources) != len(normalized_destinations):
        raise ValueError("End A and End B profile counts must match.")
    if not math.isfinite(diameter_mm) or diameter_mm <= 0.0:
        raise ValueError("Wire diameter must be a finite positive value.")

    original_serialized = gateway.read_harness_definition(harness_id)
    definition = loads(original_serialized)
    pathway = next(
        (item for item in definition.pathways if item.pathway_id == pathway_id),
        None,
    )
    if pathway is None:
        raise ValueError("Selected pathway does not exist in this harness.")

    profile_name = next_available_name(
        "Wire Profile 01",
        [profile.name for profile in definition.profiles],
    )
    profile = WireProfile(id_factory(), profile_name, diameter_mm)
    existing_connection_names = [connection.name for connection in definition.connections]
    next_wire_number = _next_wire_number(definition)
    sources: list[Connection] = []
    destinations: list[Connection] = []
    wires: list[WireDefinition] = []
    for index, (source_token, destination_token) in enumerate(
        zip(normalized_sources, normalized_destinations)
    ):
        source_name = next_available_name(
            f"End A {index + 1:03d}",
            (*existing_connection_names, *(item.name for item in sources)),
        )
        source = Connection(
            id_factory(), source_name, source_token, interpolation=definition.end_defaults
        )
        destination_name = next_available_name(
            f"End B {index + 1:03d}",
            (
                *existing_connection_names,
                *(item.name for item in sources),
                *(item.name for item in destinations),
            ),
        )
        destination = Connection(
            id_factory(), destination_name, destination_token, interpolation=definition.end_defaults
        )
        wire = WireDefinition(
            wire_id=id_factory(),
            wire_number=f"{next_wire_number + index:03d}",
            start_connection_id=source.connection_id,
            end_connection_id=destination.connection_id,
            profile_id=profile.profile_id,
            ordered_pathway_ids=(pathway.pathway_id,),
            ordered_control_ids=pathway.ordered_control_ids,
        )
        sources.append(source)
        destinations.append(destination)
        wires.append(wire)

    result = WireBatchResult(
        profile=profile,
        connections=(*sources, *destinations),
        wires=tuple(wires),
    )
    updated_definition: HarnessDefinition = replace(
        definition,
        profiles=(*definition.profiles, profile),
        connections=(*definition.connections, *result.connections),
        wires=(*definition.wires, *result.wires),
    )
    try:
        gateway.replace_harness_definition(harness_id, dumps(updated_definition))
    except Exception as persistence_error:
        try:
            gateway.replace_harness_definition(harness_id, original_serialized)
        except Exception as rollback_error:
            message = (
                "Failed to persist the wire batch and restore the harness definition: "
                f"{rollback_error}"
            )
            raise WireBatchUpdateError(message) from persistence_error
        raise
    return result


def _normalize_tokens(tokens: tuple[str, ...], role: str) -> tuple[str, ...]:
    """
    Normalize and validate one ordered endpoint-token collection.
    """
    if not tokens:
        raise ValueError("Select at least one End A and End B profile.")
    normalized = tuple(token.strip() for token in tokens)
    if any(not token for token in normalized):
        raise ValueError(f"Every {role} profile must reference Fusion geometry.")
    return normalized


def _next_wire_number(definition: HarnessDefinition) -> int:
    """
    Return the next positive number after existing numeric wire identifiers.
    """
    numeric_values = tuple(
        int(wire.wire_number) for wire in definition.wires if wire.wire_number.isdecimal()
    )
    return max(numeric_values, default=0) + 1
