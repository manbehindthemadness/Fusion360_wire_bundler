"""
Immutable domain objects for a versioned harness definition.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

SCHEMA_VERSION = 1


class RoutingMode(str, Enum):
    """
    Identify the primary routing-control strategy for a harness.
    """

    ROUTING_GATES = "routing_gates"
    PROFILE_GATES = "profile_gates"


class ControlKind(str, Enum):
    """
    Identify a routing control's geometric role.
    """

    ROUTING_GATE = "routing_gate"
    PROFILE_GATE = "profile_gate"


@dataclass(frozen=True)
class WireProfile:
    """
    Describe the initial circular profile assigned to a conductor.

    Args:
        profile_id: Persistent profile identity.
        name: User-facing profile name.
        diameter_mm: Finished conductor diameter in millimeters.
    """

    profile_id: UUID
    name: str
    diameter_mm: float


@dataclass(frozen=True)
class Connection:
    """
    Reference a physical connection profile in a Fusion design.

    Args:
        connection_id: Persistent connection identity.
        name: User-facing connection name.
        entity_token: Opaque Fusion entity token resolved by the host adapter.
    """

    connection_id: UUID
    name: str
    entity_token: str


@dataclass(frozen=True)
class ControlStructure:
    """
    Reference a routing or profile gate in a Fusion design.

    Args:
        control_id: Persistent control identity.
        name: User-facing control name.
        kind: Routing or profile gate classification.
        entity_token: Opaque Fusion entity token resolved by the host adapter.
    """

    control_id: UUID
    name: str
    kind: ControlKind
    entity_token: str


@dataclass(frozen=True)
class WireDefinition:
    """
    Map one persistent conductor from a start to a destination.

    Args:
        wire_id: Immutable conductor identity.
        wire_number: Stable user-facing numerical identifier.
        start_connection_id: Referenced physical starting connection.
        end_connection_id: Referenced physical destination connection.
        profile_id: Referenced conductor profile.
        ordered_control_ids: Control identities in traversal order.
    """

    wire_id: UUID
    wire_number: str
    start_connection_id: UUID
    end_connection_id: UUID
    profile_id: UUID
    ordered_control_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class HarnessDefinition:
    """
    Store the complete logical definition independently of Fusion geometry.

    Args:
        schema_version: Serialized definition schema version.
        harness_id: Persistent harness identity.
        name: User-facing harness assembly name.
        routing_mode: Primary routing-control strategy.
        profiles: Available conductor profiles.
        connections: Available physical connections.
        controls: Available routing controls.
        wires: Authoritative conductor mappings.
    """

    schema_version: int
    harness_id: UUID
    name: str
    routing_mode: RoutingMode
    profiles: tuple[WireProfile, ...]
    connections: tuple[Connection, ...]
    controls: tuple[ControlStructure, ...]
    wires: tuple[WireDefinition, ...]
