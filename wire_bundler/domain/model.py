"""
Immutable domain objects for a versioned harness definition.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from uuid import UUID, uuid5

SCHEMA_VERSION = 5


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


class PathwayEnd(str, Enum):
    """
    Identify one stable endpoint of a pathway's traversal order.
    """

    A = "a"
    B = "b"


class TopologyNodeKind(str, Enum):
    """
    Identify the role of a node in the route graph.
    """

    EXTERNAL_END = "external_end"
    PATHWAY_END = "pathway_end"
    JUNCTION = "junction"


class RouteEdgeKind(str, Enum):
    """
    Identify the geometric or logical role of a route edge.
    """

    END_LINK = "end_link"
    PATHWAY = "pathway"
    EXTENSION = "extension"
    JUNCTION_TRANSITION = "junction_transition"


class PathwayExitState(str, Enum):
    """
    Describe graph-derived continuity at one occupied pathway endpoint.
    """

    OPEN = "open"
    TERMINATED = "terminated"
    EXTENDED = "extended"


class JunctionDisposition(str, Enum):
    """
    Describe one incoming member's behavior at a junction attachment.
    """

    EXCLUDE_BRANCH = "exclude_branch"
    BRANCH = "branch"
    REDIRECT_BRANCH = "redirect_branch"


class ElectricalRelationshipKind(str, Enum):
    """
    Identify an explicit electrical relationship between physical wires.
    """

    IDEAL_SPLICE = "ideal_splice"


class StripePattern(str, Enum):
    """
    Describe how an insulation-identification stripe repeats along a wire.
    """

    LONGITUDINAL = "longitudinal"
    DASHED = "dashed"
    HELICAL = "helical"


@dataclass(frozen=True)
class WireColor:
    """
    Store a portable named RGB color independently of Fusion appearances.
    """

    name: str
    red: int
    green: int
    blue: int

    def __post_init__(self) -> None:
        """
        Require a name and three byte-sized color channels.
        """
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Wire color name must not be empty.")
        for channel in (self.red, self.green, self.blue):
            if isinstance(channel, bool) or not isinstance(channel, int) or not 0 <= channel <= 255:
                raise ValueError("Wire color channels must be integers from 0 through 255.")

    @property
    def hex_rgb(self) -> str:
        """
        Return the color in HTML-compatible hexadecimal form.
        """
        return f"#{self.red:02X}{self.green:02X}{self.blue:02X}"


DEFAULT_WIRE_COLOR = WireColor("Black", 32, 32, 32)


@dataclass(frozen=True)
class WireAppearanceReference:
    """
    Identify an appearance in one of Fusion's installed material libraries.

    Names are retained for display and diagnostics while the stable library and
    appearance IDs drive host lookup.
    """

    library_id: str
    library_name: str
    appearance_id: str
    appearance_name: str

    def __post_init__(self) -> None:
        """
        Require complete lookup and display information.
        """
        for value in (
            self.library_id,
            self.library_name,
            self.appearance_id,
            self.appearance_name,
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Fusion appearance references require nonempty IDs and names.")


@dataclass(frozen=True)
class WireStripe:
    """
    Define one ordered procedural stripe on the insulation surface.

    ``repeat_mm`` is required for dashed and helical patterns and unused by a
    continuous longitudinal stripe. ``angle_deg`` locates the stripe around the
    wire circumference at its starting section.
    """

    color: WireColor
    width_mm: float
    pattern: StripePattern = StripePattern.LONGITUDINAL
    angle_deg: float = 0.0
    repeat_mm: Optional[float] = None

    def __post_init__(self) -> None:
        """
        Reject stripe dimensions that cannot drive procedural geometry.
        """
        if not isinstance(self.color, WireColor):
            raise ValueError("Stripe color must be a wire color.")
        if not isinstance(self.pattern, StripePattern):
            raise ValueError("Stripe pattern is not supported.")
        if (
            isinstance(self.width_mm, bool)
            or not isinstance(self.width_mm, (int, float))
            or not math.isfinite(self.width_mm)
            or self.width_mm <= 0
        ):
            raise ValueError("Stripe width must be a finite positive value in millimeters.")
        if (
            isinstance(self.angle_deg, bool)
            or not isinstance(self.angle_deg, (int, float))
            or not math.isfinite(self.angle_deg)
        ):
            raise ValueError("Stripe angle must be finite degrees.")
        if self.repeat_mm is not None and (
            isinstance(self.repeat_mm, bool)
            or not isinstance(self.repeat_mm, (int, float))
            or not math.isfinite(self.repeat_mm)
            or self.repeat_mm <= 0
        ):
            raise ValueError("Stripe repeat must be a finite positive value in millimeters.")
        if self.pattern is not StripePattern.LONGITUDINAL and self.repeat_mm is None:
            raise ValueError("Dashed and helical stripes require a positive repeat length.")


@dataclass(frozen=True)
class WireMaterialSettings:
    """
    Store resolved harness-level defaults for wire construction and identification.
    """

    insulation_material: str = "PVC"
    main_color: WireColor = DEFAULT_WIRE_COLOR
    appearance: Optional[WireAppearanceReference] = None
    stripes: tuple[WireStripe, ...] = ()
    conductor_material: str = "Copper"
    manufacturer: str = ""
    part_number: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        """
        Require usable material labels while permitting optional catalog metadata.
        """
        if not isinstance(self.insulation_material, str) or not self.insulation_material.strip():
            raise ValueError("Insulation material must not be empty.")
        if not isinstance(self.conductor_material, str) or not self.conductor_material.strip():
            raise ValueError("Conductor material must not be empty.")
        if not isinstance(self.main_color, WireColor):
            raise ValueError("Main insulation color must be a wire color.")
        if self.appearance is not None and not isinstance(self.appearance, WireAppearanceReference):
            raise ValueError("Main insulation appearance must reference a Fusion appearance.")
        if not isinstance(self.stripes, tuple) or not all(
            isinstance(stripe, WireStripe) for stripe in self.stripes
        ):
            raise ValueError("Wire stripes must be an ordered tuple of stripe definitions.")
        for value in (self.manufacturer, self.part_number, self.notes):
            if not isinstance(value, str):
                raise ValueError("Wire catalog metadata must be text.")


@dataclass(frozen=True)
class WireMaterialOverrides:
    """
    Override selected harness material defaults for one persistent wire.

    A null stripes value inherits the harness stripe collection. An explicit
    empty tuple suppresses every inherited stripe.
    """

    insulation_material: Optional[str] = None
    main_color: Optional[WireColor] = None
    appearance: Optional[WireAppearanceReference] = None
    stripes: Optional[tuple[WireStripe, ...]] = None
    conductor_material: Optional[str] = None
    manufacturer: Optional[str] = None
    part_number: Optional[str] = None
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        """
        Validate explicit overrides while preserving null inheritance markers.
        """
        for value, label in (
            (self.insulation_material, "Insulation material"),
            (self.conductor_material, "Conductor material"),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{label} override must not be empty.")
        if self.main_color is not None and not isinstance(self.main_color, WireColor):
            raise ValueError("Main color override must be a wire color.")
        if self.appearance is not None and not isinstance(self.appearance, WireAppearanceReference):
            raise ValueError("Main appearance override must reference a Fusion appearance.")
        if self.main_color is None and self.appearance is not None:
            raise ValueError("A main appearance override requires a main color override.")
        if self.stripes is not None and (
            not isinstance(self.stripes, tuple)
            or not all(isinstance(stripe, WireStripe) for stripe in self.stripes)
        ):
            raise ValueError("Stripe override must be an ordered tuple of stripe definitions.")
        for value in (self.manufacturer, self.part_number, self.notes):
            if value is not None and not isinstance(value, str):
                raise ValueError("Wire catalog metadata overrides must be text.")

    def resolve(self, parent: WireMaterialSettings) -> WireMaterialSettings:
        """
        Merge these field-level overrides over harness defaults.
        """
        return WireMaterialSettings(
            insulation_material=(
                parent.insulation_material
                if self.insulation_material is None
                else self.insulation_material
            ),
            main_color=parent.main_color if self.main_color is None else self.main_color,
            appearance=(parent.appearance if self.main_color is None else self.appearance),
            stripes=parent.stripes if self.stripes is None else self.stripes,
            conductor_material=(
                parent.conductor_material
                if self.conductor_material is None
                else self.conductor_material
            ),
            manufacturer=parent.manufacturer if self.manufacturer is None else self.manufacturer,
            part_number=parent.part_number if self.part_number is None else self.part_number,
            notes=parent.notes if self.notes is None else self.notes,
        )


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
    material_overrides: WireMaterialOverrides = WireMaterialOverrides()


@dataclass(frozen=True)
class TopologyNode:
    """
    Represent an external end, pathway endpoint, or movable junction.

    Optional fields are interpreted by ``kind`` and validated before generation.
    Junction distance and persisted diameter values use canonical millimeters.
    """

    node_id: UUID
    kind: TopologyNodeKind
    pathway_id: Optional[UUID] = None
    pathway_end: Optional[PathwayEnd] = None
    connection_id: Optional[UUID] = None
    physical_wire_id: Optional[UUID] = None
    distance_mm: Optional[float] = None
    slice_control_id: Optional[UUID] = None
    junction_diameter_factor_override: Optional[float] = None
    name: str = ""


@dataclass(frozen=True)
class PhysicalWire:
    """
    Preserve one generated body's identity within a logical wire network.
    """

    physical_wire_id: UUID
    network_id: UUID
    profile_id: UUID


@dataclass(frozen=True)
class RouteEdge:
    """
    Connect two topology nodes for one physical wire.

    ``pathway_id`` is present only for an edge occupying a pathway span.
    """

    edge_id: UUID
    kind: RouteEdgeKind
    physical_wire_id: UUID
    start_node_id: UUID
    end_node_id: UUID
    pathway_id: Optional[UUID] = None
    name: str = ""


@dataclass(frozen=True)
class JunctionMemberDisposition:
    """
    Persist one member's disposition toward one junction attachment.
    """

    junction_id: UUID
    attachment_pathway_id: UUID
    attachment_end: PathwayEnd
    incoming_wire_id: UUID
    disposition: JunctionDisposition
    branch_wire_id: Optional[UUID] = None


@dataclass(frozen=True)
class JunctionAttachment:
    """
    Attach one ordinary pathway endpoint to a persistent junction slice node.

    Attachments exist independently of member dispositions so an empty Y junction
    and multiple pathways sharing one cross-junction slice survive persistence.
    """

    junction_id: UUID
    pathway_id: UUID
    pathway_end: PathwayEnd


@dataclass(frozen=True)
class ElectricalRelationship:
    """
    Relate distinct physical wires without conflating their body identities.
    """

    relationship_id: UUID
    kind: ElectricalRelationshipKind
    junction_id: UUID
    physical_wire_ids: tuple[UUID, ...]
    notes: str = ""


@dataclass(frozen=True)
class RouteTopology:
    """
    Store the explicit directed route graph introduced by schema version five.
    """

    nodes: tuple[TopologyNode, ...] = ()
    physical_wires: tuple[PhysicalWire, ...] = ()
    edges: tuple[RouteEdge, ...] = ()
    junction_attachments: tuple[JunctionAttachment, ...] = ()
    junction_dispositions: tuple[JunctionMemberDisposition, ...] = ()
    electrical_relationships: tuple[ElectricalRelationship, ...] = ()


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
    material_defaults: WireMaterialSettings = WireMaterialSettings()
    topology: Optional[RouteTopology] = None

    def wire_materials(self, wire: WireDefinition) -> WireMaterialSettings:
        """
        Resolve one wire's effective material settings from parent defaults.
        """
        return wire.material_overrides.resolve(self.material_defaults)

    @property
    def resolved_topology(self) -> RouteTopology:
        """
        Return explicit topology or a deterministic projection of legacy linear routes.
        """
        if self.topology is not None:
            return self.topology

        from .topology import build_linear_topology

        topology = build_linear_topology(self.wires, self.pathways)
        return topology
