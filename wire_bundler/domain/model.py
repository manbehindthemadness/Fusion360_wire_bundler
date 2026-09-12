"""
Immutable domain objects for a versioned harness definition.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from uuid import UUID, uuid5

SCHEMA_VERSION = 6


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
    REFINE = "refine"


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
class RefineGeometry:
    """
    Store an unconstrained oriented pathway point independently of Fusion.

    The two unit directions span the marker plane. Their cross product is the
    route tangent; the display radius affects only the persistent marker.
    """

    origin_mm: tuple[float, float, float]
    u_direction: tuple[float, float, float]
    v_direction: tuple[float, float, float]
    display_radius_mm: float

    def __post_init__(self) -> None:
        """
        Require a finite origin, orthonormal frame, and positive marker radius.
        """
        vectors = (self.origin_mm, self.u_direction, self.v_direction)
        if any(not isinstance(vector, tuple) or len(vector) != 3 for vector in vectors):
            raise ValueError("Refine geometry requires three-dimensional vectors.")
        values = (*self.origin_mm, *self.u_direction, *self.v_direction)
        if not all(
            not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
            for value in values
        ):
            raise ValueError("Refine geometry requires finite vectors.")
        u_length = math.sqrt(sum(value * value for value in self.u_direction))
        v_length = math.sqrt(sum(value * value for value in self.v_direction))
        frame_dot = sum(left * right for left, right in zip(self.u_direction, self.v_direction))
        if not math.isclose(u_length, 1.0, abs_tol=1e-6):
            raise ValueError("Refine U direction must be a unit vector.")
        if not math.isclose(v_length, 1.0, abs_tol=1e-6):
            raise ValueError("Refine V direction must be a unit vector.")
        if not math.isclose(frame_dot, 0.0, abs_tol=1e-6):
            raise ValueError("Refine directions must be orthogonal.")
        if (
            isinstance(self.display_radius_mm, bool)
            or not isinstance(self.display_radius_mm, (int, float))
            or not math.isfinite(self.display_radius_mm)
            or self.display_radius_mm <= 0.0
        ):
            raise ValueError("Refine display radius must be finite and positive.")


@dataclass(frozen=True)
class WireProfile:
    """
    Describe the initial circular profile assigned to a conductor.
    """

    profile_id: UUID
    name: str
    diameter_mm: float


@dataclass(frozen=True)
class Connection:
    """
    Reference a physical connection profile in a Fusion design.

    Member identities and interpolation settings align with the full token sequence.
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
    """

    control_id: UUID
    name: str
    kind: ControlKind
    entity_token: str
    interpolation: InterpolationSettings = InterpolationSettings()
    interpolation_is_override: bool = False
    refine_geometry: Optional[RefineGeometry] = None


@dataclass(frozen=True)
class PathwayDefinition:
    """
    Group an ordered sequence of routing controls into a reusable pathway.
    """

    pathway_id: UUID
    name: str
    routing_mode: RoutingMode
    ordered_control_ids: tuple[UUID, ...]
    start_name: str = ""
    end_name: str = ""


@dataclass(frozen=True)
class JunctionDefinition:
    """
    Join two ordered pathway spans at one standalone routing control.
    """

    junction_id: UUID
    name: str
    control_id: UUID
    preceding_pathway_id: UUID
    following_pathway_id: UUID


@dataclass(frozen=True)
class WireDefinition:
    """
    Map one persistent conductor from a start to a destination.
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
class HarnessDefinition:
    """
    Store the complete logical definition independently of Fusion geometry.

    Gate and end defaults are presets copied into newly created members.
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
    junctions: tuple[JunctionDefinition, ...] = ()
    gate_defaults: InterpolationSettings = InterpolationSettings()
    end_defaults: InterpolationSettings = InterpolationSettings()
    material_defaults: WireMaterialSettings = WireMaterialSettings()

    def wire_materials(self, wire: WireDefinition) -> WireMaterialSettings:
        """
        Resolve one wire's effective material settings from parent defaults.
        """
        return wire.material_overrides.resolve(self.material_defaults)


def route_control_ids(
    definition: HarnessDefinition,
    pathway_ids: tuple[UUID, ...],
) -> tuple[UUID, ...]:
    """
    Expand ordered pathways and their intervening junctions into routing controls.

    Raises:
        ValueError: If a pathway is missing or an adjacency has multiple junctions.
    """
    pathways = {pathway.pathway_id: pathway for pathway in definition.pathways}
    junctions: dict[tuple[UUID, UUID], UUID] = {}
    for junction in definition.junctions:
        key = (junction.preceding_pathway_id, junction.following_pathway_id)
        if key in junctions:
            raise ValueError("A pathway adjacency has more than one junction.")
        junctions[key] = junction.control_id

    controls: list[UUID] = []
    for index, pathway_id in enumerate(pathway_ids):
        pathway = pathways.get(pathway_id)
        if pathway is None:
            raise ValueError("A wire references a missing pathway.")
        controls.extend(pathway.ordered_control_ids)
        if index + 1 < len(pathway_ids):
            junction_control_id = junctions.get((pathway_id, pathway_ids[index + 1]))
            if junction_control_id is not None:
                controls.append(junction_control_id)
    return tuple(controls)
