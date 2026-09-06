"""
Immutable domain objects for a versioned harness definition.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from uuid import UUID, uuid5

SCHEMA_VERSION = 3


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
class InterpolationSettings:
    """
    Bound each profile's orientation influence; None selects a quarter-span length.

    End sections interpret approach/departure in terminal-to-pathway stack order.
    """

    approach_mm: Optional[float] = None
    departure_mm: Optional[float] = None

    def __post_init__(self) -> None:
        """
        Reject malformed or non-finite distances at the domain boundary.
        """
        for value in (self.approach_mm, self.departure_mm):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(
                    "Transition distances must be finite nonnegative millimeters or Auto."
                )


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
        additional_entity_tokens: Remaining connection members in explicit order.
        member_ids: Persistent per-member identities aligned with the token order.
        interpolation: Transition distances applied to every member in local stack order.
    """

    connection_id: UUID
    name: str
    entity_token: str
    additional_entity_tokens: tuple[str, ...] = ()
    member_ids: tuple[UUID, ...] = ()
    interpolation: InterpolationSettings = InterpolationSettings()
    member_interpolations: tuple[Optional[InterpolationSettings], ...] = ()

    @property
    def member_settings(self) -> tuple[InterpolationSettings, ...]:
        """
        Resolve per-member settings, retaining legacy section-wide values as fallback.
        """
        return tuple(
            item if item is not None else self.interpolation for item in self.member_interpolations
        ) or (self.interpolation,) * len(self.member_tokens)

    @property
    def member_identities(self) -> tuple[UUID, ...]:
        """
        Return saved member identities or deterministic identities for legacy data.
        """
        return self.member_ids or tuple(
            uuid5(self.connection_id, f"member:{index}") for index in range(len(self.member_tokens))
        )

    @property
    def member_tokens(self) -> tuple[str, ...]:
        """
        Return the primary profile followed by the remaining connection members.
        """
        tokens = (self.entity_token, *self.additional_entity_tokens)
        return tokens


@dataclass(frozen=True)
class ControlStructure:
    """
    Reference a routing or profile gate in a Fusion design.

    Args:
        interpolation: Approach/departure distances in gate traversal order.
        control_id: Persistent control identity.
        name: User-facing control name.
        kind: Routing or profile gate classification.
        entity_token: Opaque Fusion entity token resolved by the host adapter.
    """

    control_id: UUID
    name: str
    kind: ControlKind
    entity_token: str
    interpolation: InterpolationSettings = InterpolationSettings()
    interpolation_is_override: bool = False


@dataclass(frozen=True)
class PathwayDefinition:
    """
    Group an ordered sequence of routing controls into a reusable pathway.

    Args:
        pathway_id: Persistent pathway identity.
        name: User-facing pathway name.
        routing_mode: Routing strategy used by every gate in the pathway.
        ordered_control_ids: Gate identities in traversal order.
        start_name: Optional label at the start of gate traversal.
        end_name: Optional label at the end of gate traversal.
    """

    pathway_id: UUID
    name: str
    routing_mode: RoutingMode
    ordered_control_ids: tuple[UUID, ...]
    start_name: str = ""
    end_name: str = ""


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
        ordered_pathway_ids: Pathway identities in traversal order.
        ordered_control_ids: Control identities in traversal order.
        start_end_name: Organizational name for this wire's End A.
        end_end_name: Organizational name for this wire's End B.
        display_name: Optional user-facing label replacing the numbered designation.
    """

    wire_id: UUID
    wire_number: str
    start_connection_id: UUID
    end_connection_id: UUID
    profile_id: UUID
    ordered_pathway_ids: tuple[UUID, ...]
    ordered_control_ids: tuple[UUID, ...]
    start_end_name: str = ""
    end_end_name: str = ""
    display_name: str = ""


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
        pathways: Reusable ordered routing pathways.
        wires: Authoritative conductor mappings.
        gate_defaults: Interpolation preset copied to newly created controls.
        end_defaults: Interpolation preset copied to newly created connections.
    """

    schema_version: int
    harness_id: UUID
    name: str
    routing_mode: RoutingMode
    profiles: tuple[WireProfile, ...]
    connections: tuple[Connection, ...]
    controls: tuple[ControlStructure, ...]
    pathways: tuple[PathwayDefinition, ...]
    wires: tuple[WireDefinition, ...]
    gate_defaults: InterpolationSettings = InterpolationSettings()
    end_defaults: InterpolationSettings = InterpolationSettings()
