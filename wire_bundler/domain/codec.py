"""
JSON serialization for versioned harness definitions.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any, Optional, Type, TypeVar
from uuid import UUID

from .model import (
    SCHEMA_VERSION,
    Connection,
    ControlKind,
    ControlStructure,
    HarnessDefinition,
    InterpolationSettings,
    PathwayDefinition,
    RoutingMode,
    StripePattern,
    WireAppearanceReference,
    WireColor,
    WireDefinition,
    WireMaterialOverrides,
    WireMaterialSettings,
    WireProfile,
    WireStripe,
)

EnumType = TypeVar("EnumType", RoutingMode, ControlKind, StripePattern)


class DefinitionParseError(ValueError):
    """
    Report invalid serialized harness data at a precise field path.
    """

    def __init__(self, path: str, message: str) -> None:
        """
        Initialize a structured parse error.
        """
        self.path = path
        self.reason = message
        super().__init__(f"{path}: {message}")


def dumps(definition: HarnessDefinition) -> str:
    """
    Serialize a harness definition to deterministic JSON.
    """
    payload = _definition_to_dict(definition)
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    return serialized


def loads(serialized: str) -> HarnessDefinition:
    """
    Parse and shape-check a serialized harness definition.

    Raises:
        DefinitionParseError: If JSON or a required data shape is invalid.
    """
    try:
        raw_payload = json.loads(serialized)
    except json.JSONDecodeError as error:
        raise DefinitionParseError("$", f"invalid JSON: {error.msg}") from error

    payload = _require_mapping(raw_payload, "$")
    schema_version = _require_int(payload, "schema_version", "$.schema_version")
    if schema_version not in (1, 2, 3, SCHEMA_VERSION):
        raise DefinitionParseError(
            "$.schema_version",
            f"unsupported version {schema_version}; expected 1, 2, 3, or {SCHEMA_VERSION}",
        )

    harness_id = _require_uuid(payload, "harness_id", "$.harness_id")
    name = _require_str(payload, "name", "$.name")
    routing_mode = _require_enum(RoutingMode, payload, "routing_mode", "$.routing_mode")
    profiles = tuple(
        _parse_profile(item, f"$.profiles[{index}]")
        for index, item in enumerate(_require_list(payload, "profiles", "$.profiles"))
    )
    connections = tuple(
        _parse_connection(item, f"$.connections[{index}]")
        for index, item in enumerate(_require_list(payload, "connections", "$.connections"))
    )
    controls = tuple(
        _parse_control(item, f"$.controls[{index}]")
        for index, item in enumerate(_require_list(payload, "controls", "$.controls"))
    )
    pathways = (
        tuple(
            _parse_pathway(item, f"$.pathways[{index}]")
            for index, item in enumerate(_require_list(payload, "pathways", "$.pathways"))
        )
        if schema_version >= 2
        else ()
    )
    wires = tuple(
        _parse_wire(item, f"$.wires[{index}]", schema_version, pathways)
        for index, item in enumerate(_require_list(payload, "wires", "$.wires"))
    )
    definition = HarnessDefinition(
        schema_version=SCHEMA_VERSION,
        harness_id=harness_id,
        name=name,
        routing_mode=routing_mode,
        profiles=profiles,
        connections=connections,
        controls=controls,
        pathways=pathways,
        wires=wires,
        gate_defaults=parse_interpolation(payload.get("gate_defaults", {}), "$.gate_defaults"),
        end_defaults=parse_interpolation(payload.get("end_defaults", {}), "$.end_defaults"),
        material_defaults=(
            parse_material_settings(payload.get("material_defaults"), "$.material_defaults")
            if schema_version >= 4
            else WireMaterialSettings()
        ),
    )
    return definition


def _definition_to_dict(definition: HarnessDefinition) -> dict[str, Any]:
    """
    Convert a definition to JSON-compatible primitives.
    """
    payload = {
        "schema_version": definition.schema_version,
        "harness_id": str(definition.harness_id),
        "name": definition.name,
        "routing_mode": definition.routing_mode.value,
        "gate_defaults": asdict(definition.gate_defaults),
        "end_defaults": asdict(definition.end_defaults),
        "material_defaults": _materials_to_dict(definition.material_defaults),
        "profiles": [
            {
                "profile_id": str(profile.profile_id),
                "name": profile.name,
                "diameter_mm": profile.diameter_mm,
            }
            for profile in definition.profiles
        ],
        "connections": [
            {
                "interpolation": asdict(connection.interpolation),
                "connection_id": str(connection.connection_id),
                "name": connection.name,
                "entity_token": connection.entity_token,
                "additional_entity_tokens": list(connection.additional_entity_tokens),
                **(
                    {
                        "member_interpolations": [
                            asdict(item) if item is not None else None
                            for item in connection.member_interpolations
                        ]
                    }
                    if connection.member_interpolations
                    else {}
                ),
                **(
                    {"member_ids": [str(identity) for identity in connection.member_ids]}
                    if connection.member_ids
                    else {}
                ),
            }
            for connection in definition.connections
        ],
        "controls": [
            {
                "interpolation": asdict(control.interpolation),
                "interpolation_is_override": control.interpolation_is_override,
                "control_id": str(control.control_id),
                "name": control.name,
                "kind": control.kind.value,
                "entity_token": control.entity_token,
            }
            for control in definition.controls
        ],
        "pathways": [
            {
                "pathway_id": str(pathway.pathway_id),
                "name": pathway.name,
                "start_name": pathway.start_name,
                "end_name": pathway.end_name,
                "routing_mode": pathway.routing_mode.value,
                "ordered_control_ids": [
                    str(control_id) for control_id in pathway.ordered_control_ids
                ],
            }
            for pathway in definition.pathways
        ],
        "wires": [
            {
                "wire_id": str(wire.wire_id),
                "wire_number": wire.wire_number,
                "display_name": wire.display_name,
                "start_end_name": wire.start_end_name,
                "end_end_name": wire.end_end_name,
                "start_connection_id": str(wire.start_connection_id),
                "end_connection_id": str(wire.end_connection_id),
                "profile_id": str(wire.profile_id),
                "ordered_pathway_ids": [str(pathway_id) for pathway_id in wire.ordered_pathway_ids],
                "ordered_control_ids": [str(control_id) for control_id in wire.ordered_control_ids],
                "material_overrides": _material_overrides_to_dict(wire.material_overrides),
            }
            for wire in definition.wires
        ],
    }
    return payload


def _parse_profile(raw_value: object, path: str) -> WireProfile:
    """
    Parse one conductor profile.
    """
    value = _require_mapping(raw_value, path)
    profile = WireProfile(
        profile_id=_require_uuid(value, "profile_id", f"{path}.profile_id"),
        name=_require_str(value, "name", f"{path}.name"),
        diameter_mm=_require_float(value, "diameter_mm", f"{path}.diameter_mm"),
    )
    return profile


def _color_to_dict(color: WireColor) -> dict[str, object]:
    """
    Convert one portable wire color to JSON-compatible values.
    """
    return {
        "name": color.name,
        "red": color.red,
        "green": color.green,
        "blue": color.blue,
    }


def _stripe_to_dict(stripe: WireStripe) -> dict[str, object]:
    """
    Convert one procedural stripe to JSON-compatible values.
    """
    return {
        "color": _color_to_dict(stripe.color),
        "width_mm": stripe.width_mm,
        "pattern": stripe.pattern.value,
        "angle_deg": stripe.angle_deg,
        "repeat_mm": stripe.repeat_mm,
    }


def _materials_to_dict(settings: WireMaterialSettings) -> dict[str, object]:
    """
    Convert resolved wire material settings to JSON-compatible values.
    """
    return {
        "insulation_material": settings.insulation_material,
        "main_color": _color_to_dict(settings.main_color),
        "appearance": _appearance_to_dict(settings.appearance),
        "stripes": [_stripe_to_dict(stripe) for stripe in settings.stripes],
        "conductor_material": settings.conductor_material,
        "manufacturer": settings.manufacturer,
        "part_number": settings.part_number,
        "notes": settings.notes,
    }


def _material_overrides_to_dict(overrides: WireMaterialOverrides) -> dict[str, object]:
    """
    Preserve null inheritance markers while serializing per-wire overrides.
    """
    return {
        "insulation_material": overrides.insulation_material,
        "main_color": (
            None if overrides.main_color is None else _color_to_dict(overrides.main_color)
        ),
        "appearance": _appearance_to_dict(overrides.appearance),
        "stripes": (
            None
            if overrides.stripes is None
            else [_stripe_to_dict(stripe) for stripe in overrides.stripes]
        ),
        "conductor_material": overrides.conductor_material,
        "manufacturer": overrides.manufacturer,
        "part_number": overrides.part_number,
        "notes": overrides.notes,
    }


def _parse_color(raw_value: object, path: str) -> WireColor:
    """
    Parse one named RGB color at an external-data boundary.
    """
    value = _require_mapping(raw_value, path)
    try:
        return WireColor(
            name=_require_str(value, "name", f"{path}.name"),
            red=_require_int(value, "red", f"{path}.red"),
            green=_require_int(value, "green", f"{path}.green"),
            blue=_require_int(value, "blue", f"{path}.blue"),
        )
    except ValueError as error:
        raise DefinitionParseError(path, str(error)) from error


def _appearance_to_dict(
    appearance: Optional[WireAppearanceReference],
) -> Optional[dict[str, str]]:
    """
    Convert an optional Fusion library appearance reference to portable values.
    """
    if appearance is None:
        return None
    return {
        "library_id": appearance.library_id,
        "library_name": appearance.library_name,
        "appearance_id": appearance.appearance_id,
        "appearance_name": appearance.appearance_name,
    }


def _parse_appearance(raw_value: object, path: str) -> Optional[WireAppearanceReference]:
    """
    Parse an optional Fusion library appearance reference.
    """
    if raw_value is None:
        return None
    value = _require_mapping(raw_value, path)
    try:
        return WireAppearanceReference(
            library_id=_require_str(value, "library_id", f"{path}.library_id"),
            library_name=_require_str(value, "library_name", f"{path}.library_name"),
            appearance_id=_require_str(value, "appearance_id", f"{path}.appearance_id"),
            appearance_name=_require_str(value, "appearance_name", f"{path}.appearance_name"),
        )
    except ValueError as error:
        raise DefinitionParseError(path, str(error)) from error


def _parse_stripes(raw_value: object, path: str) -> tuple[WireStripe, ...]:
    """
    Parse an ordered procedural stripe collection.
    """
    if not isinstance(raw_value, list):
        raise DefinitionParseError(path, "expected a list")
    stripes: list[WireStripe] = []
    for index, raw_stripe in enumerate(raw_value):
        stripe_path = f"{path}[{index}]"
        value = _require_mapping(raw_stripe, stripe_path)
        try:
            stripes.append(
                WireStripe(
                    color=_parse_color(value.get("color"), f"{stripe_path}.color"),
                    width_mm=_require_float(value, "width_mm", f"{stripe_path}.width_mm"),
                    pattern=_require_enum(
                        StripePattern, value, "pattern", f"{stripe_path}.pattern"
                    ),
                    angle_deg=_require_float(
                        {"angle_deg": 0.0, **value}, "angle_deg", f"{stripe_path}.angle_deg"
                    ),
                    repeat_mm=_optional_float(value.get("repeat_mm"), f"{stripe_path}.repeat_mm"),
                )
            )
        except ValueError as error:
            raise DefinitionParseError(stripe_path, str(error)) from error
    return tuple(stripes)


def parse_material_settings(raw_value: object, path: str) -> WireMaterialSettings:
    """
    Parse complete harness-level wire material defaults.
    """
    value = _require_mapping(raw_value, path)
    try:
        return WireMaterialSettings(
            insulation_material=_require_str(
                value, "insulation_material", f"{path}.insulation_material"
            ),
            main_color=_parse_color(value.get("main_color"), f"{path}.main_color"),
            appearance=_parse_appearance(value.get("appearance"), f"{path}.appearance"),
            stripes=_parse_stripes(value.get("stripes"), f"{path}.stripes"),
            conductor_material=_require_str(
                value, "conductor_material", f"{path}.conductor_material"
            ),
            manufacturer=_require_str(value, "manufacturer", f"{path}.manufacturer"),
            part_number=_require_str(value, "part_number", f"{path}.part_number"),
            notes=_require_str(value, "notes", f"{path}.notes"),
        )
    except ValueError as error:
        raise DefinitionParseError(path, str(error)) from error


def parse_material_overrides(raw_value: object, path: str) -> WireMaterialOverrides:
    """
    Parse nullable field-level material overrides for one wire.
    """
    value = _require_mapping(raw_value, path)
    try:
        return WireMaterialOverrides(
            insulation_material=_optional_str(
                value.get("insulation_material"), f"{path}.insulation_material"
            ),
            main_color=(
                None
                if value.get("main_color") is None
                else _parse_color(value.get("main_color"), f"{path}.main_color")
            ),
            appearance=_parse_appearance(value.get("appearance"), f"{path}.appearance"),
            stripes=(
                None
                if value.get("stripes") is None
                else _parse_stripes(value.get("stripes"), f"{path}.stripes")
            ),
            conductor_material=_optional_str(
                value.get("conductor_material"), f"{path}.conductor_material"
            ),
            manufacturer=_optional_str(value.get("manufacturer"), f"{path}.manufacturer"),
            part_number=_optional_str(value.get("part_number"), f"{path}.part_number"),
            notes=_optional_str(value.get("notes"), f"{path}.notes"),
        )
    except ValueError as error:
        raise DefinitionParseError(path, str(error)) from error


def _parse_connection(raw_value: object, path: str) -> Connection:
    """
    Parse one physical connection reference.
    """
    value = _require_mapping(raw_value, path)
    raw_members = _require_list(
        {"additional_entity_tokens": [], **value},
        "additional_entity_tokens",
        f"{path}.additional_entity_tokens",
    )
    members: list[str] = []
    for token in raw_members:
        if not isinstance(token, str) or not token.strip():
            raise DefinitionParseError(
                f"{path}.additional_entity_tokens", "expected non-empty strings"
            )
        members.append(token)
    identities = tuple(
        _parse_uuid(identity, f"{path}.member_ids[{index}]")
        for index, identity in enumerate(
            _require_list({"member_ids": [], **value}, "member_ids", f"{path}.member_ids")
        )
    )
    if "member_ids" in value and (
        len(identities) != len(members) + 1 or len(set(identities)) != len(identities)
    ):
        raise DefinitionParseError(f"{path}.member_ids", "expected one unique ID per member")
    settings = tuple(
        parse_interpolation(item, f"{path}.member_interpolations[{index}]")
        if item is not None
        else None
        for index, item in enumerate(
            _require_list(
                {"member_interpolations": [], **value},
                "member_interpolations",
                f"{path}.member_interpolations",
            )
        )
    )
    if "member_interpolations" in value and len(settings) != len(members) + 1:
        raise DefinitionParseError(
            f"{path}.member_interpolations", "expected one setting per member"
        )
    connection = Connection(
        connection_id=_require_uuid(value, "connection_id", f"{path}.connection_id"),
        name=_require_str(value, "name", f"{path}.name"),
        entity_token=_require_str(value, "entity_token", f"{path}.entity_token"),
        additional_entity_tokens=tuple(members),
        member_ids=identities,
        member_interpolations=settings,
        interpolation=parse_interpolation(value.get("interpolation", {}), f"{path}.interpolation"),
    )
    return connection


def _parse_control(raw_value: object, path: str) -> ControlStructure:
    """
    Parse one routing control reference.
    """
    value = _require_mapping(raw_value, path)
    override = value.get("interpolation_is_override", False)
    if not isinstance(override, bool):
        raise DefinitionParseError(f"{path}.interpolation_is_override", "expected a boolean")
    control = ControlStructure(
        control_id=_require_uuid(value, "control_id", f"{path}.control_id"),
        name=_require_str(value, "name", f"{path}.name"),
        kind=_require_enum(ControlKind, value, "kind", f"{path}.kind"),
        interpolation_is_override=override,
        interpolation=parse_interpolation(value.get("interpolation", {}), f"{path}.interpolation"),
        entity_token=_require_str(value, "entity_token", f"{path}.entity_token"),
    )
    return control


def _parse_pathway(raw_value: object, path: str) -> PathwayDefinition:
    """
    Parse one reusable ordered pathway.
    """
    value = _require_mapping(raw_value, path)
    raw_control_ids = _require_list(
        value,
        "ordered_control_ids",
        f"{path}.ordered_control_ids",
    )
    control_ids = tuple(
        _parse_uuid(raw_id, f"{path}.ordered_control_ids[{index}]")
        for index, raw_id in enumerate(raw_control_ids)
    )
    pathway = PathwayDefinition(
        pathway_id=_require_uuid(value, "pathway_id", f"{path}.pathway_id"),
        name=_require_str(value, "name", f"{path}.name"),
        start_name=_require_str({"start_name": "", **value}, "start_name", f"{path}.start_name"),
        end_name=_require_str({"end_name": "", **value}, "end_name", f"{path}.end_name"),
        routing_mode=_require_enum(
            RoutingMode,
            value,
            "routing_mode",
            f"{path}.routing_mode",
        ),
        ordered_control_ids=control_ids,
    )
    return pathway


def _parse_wire(
    raw_value: object,
    path: str,
    schema_version: int,
    pathways: tuple[PathwayDefinition, ...],
) -> WireDefinition:
    """
    Parse one authoritative conductor mapping.
    """
    value = _require_mapping(raw_value, path)
    raw_control_ids = _require_list(
        value,
        "ordered_control_ids",
        f"{path}.ordered_control_ids",
    )
    control_ids = tuple(
        _parse_uuid(raw_id, f"{path}.ordered_control_ids[{index}]")
        for index, raw_id in enumerate(raw_control_ids)
    )
    if schema_version >= 3:
        raw_pathway_ids = _require_list(
            value,
            "ordered_pathway_ids",
            f"{path}.ordered_pathway_ids",
        )
        pathway_ids = tuple(
            _parse_uuid(raw_id, f"{path}.ordered_pathway_ids[{index}]")
            for index, raw_id in enumerate(raw_pathway_ids)
        )
    else:
        matching_pathways = tuple(
            pathway.pathway_id for pathway in pathways if pathway.ordered_control_ids == control_ids
        )
        pathway_ids = matching_pathways if len(matching_pathways) == 1 else ()
    wire = WireDefinition(
        wire_id=_require_uuid(value, "wire_id", f"{path}.wire_id"),
        wire_number=_require_str(value, "wire_number", f"{path}.wire_number"),
        display_name=_require_str(
            {"display_name": "", **value}, "display_name", f"{path}.display_name"
        ),
        start_connection_id=_require_uuid(
            value,
            "start_connection_id",
            f"{path}.start_connection_id",
        ),
        end_connection_id=_require_uuid(
            value,
            "end_connection_id",
            f"{path}.end_connection_id",
        ),
        profile_id=_require_uuid(value, "profile_id", f"{path}.profile_id"),
        ordered_pathway_ids=pathway_ids,
        ordered_control_ids=control_ids,
        start_end_name=_require_str(
            {"start_end_name": "", **value}, "start_end_name", f"{path}.start_end_name"
        ),
        end_end_name=_require_str(
            {"end_end_name": "", **value}, "end_end_name", f"{path}.end_end_name"
        ),
        material_overrides=(
            parse_material_overrides(value.get("material_overrides"), f"{path}.material_overrides")
            if schema_version >= 4
            else WireMaterialOverrides()
        ),
    )
    return wire


def _require_mapping(raw_value: object, path: str) -> Mapping[str, Any]:
    """
    Require a mapping with string keys.
    """
    if not isinstance(raw_value, Mapping):
        raise DefinitionParseError(path, "expected an object")
    if not all(isinstance(key, str) for key in raw_value):
        raise DefinitionParseError(path, "expected string object keys")
    return raw_value


def _require_value(value: Mapping[str, Any], key: str, path: str) -> object:
    """
    Require a named mapping value.
    """
    if key not in value:
        raise DefinitionParseError(path, "missing required field")
    return value[key]


def _require_str(value: Mapping[str, Any], key: str, path: str) -> str:
    """
    Require a string field.
    """
    raw_value = _require_value(value, key, path)
    if not isinstance(raw_value, str):
        raise DefinitionParseError(path, "expected a string")
    return raw_value


def _require_int(value: Mapping[str, Any], key: str, path: str) -> int:
    """
    Require an integer field without accepting booleans.
    """
    raw_value = _require_value(value, key, path)
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise DefinitionParseError(path, "expected an integer")
    return raw_value


def _require_float(value: Mapping[str, Any], key: str, path: str) -> float:
    """
    Require a numeric field without accepting booleans.
    """
    raw_value = _require_value(value, key, path)
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise DefinitionParseError(path, "expected a number")
    return float(raw_value)


def _optional_float(raw_value: object, path: str) -> Optional[float]:
    """
    Parse a nullable finite number.
    """
    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise DefinitionParseError(path, "expected a number or null")
    parsed = float(raw_value)
    if not math.isfinite(parsed):
        raise DefinitionParseError(path, "expected a finite number or null")
    return parsed


def _optional_str(raw_value: object, path: str) -> Optional[str]:
    """
    Parse nullable override text without treating an empty string as inheritance.
    """
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise DefinitionParseError(path, "expected a string or null")
    return raw_value


def _require_list(value: Mapping[str, Any], key: str, path: str) -> Sequence[object]:
    """
    Require an array field.
    """
    raw_value = _require_value(value, key, path)
    if not isinstance(raw_value, list):
        raise DefinitionParseError(path, "expected an array")
    return raw_value


def _require_uuid(value: Mapping[str, Any], key: str, path: str) -> UUID:
    """
    Require and parse a UUID string field.
    """
    raw_value = _require_value(value, key, path)
    parsed_uuid = _parse_uuid(raw_value, path)
    return parsed_uuid


def _parse_uuid(raw_value: object, path: str) -> UUID:
    """
    Parse a UUID string.
    """
    if not isinstance(raw_value, str):
        raise DefinitionParseError(path, "expected a UUID string")
    try:
        parsed_uuid = UUID(raw_value)
    except ValueError as error:
        raise DefinitionParseError(path, "invalid UUID") from error
    return parsed_uuid


def _require_enum(
    enum_type: Type[EnumType],
    value: Mapping[str, Any],
    key: str,
    path: str,
) -> EnumType:
    """
    Require a string matching a supported enum value.
    """
    raw_value = _require_str(value, key, path)
    try:
        parsed_value = enum_type(raw_value)
    except ValueError as error:
        allowed_values = ", ".join(member.value for member in enum_type)
        raise DefinitionParseError(path, f"expected one of: {allowed_values}") from error
    return parsed_value


def parse_interpolation(raw_value: object, path: str) -> InterpolationSettings:
    """
    Parse optional automatic or explicit distances for persistence and UI requests.
    """
    value = _require_mapping(raw_value, path)
    distances = []
    for field in ("approach_mm", "departure_mm"):
        raw = value.get(field)
        if raw is None:
            distances.append(None)
            continue
        number = _require_float(value, field, f"{path}.{field}")
        try:
            InterpolationSettings(number)
        except ValueError as error:
            raise DefinitionParseError(f"{path}.{field}", str(error)) from error
        distances.append(number)
    return InterpolationSettings(*distances)
