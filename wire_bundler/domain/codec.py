"""
JSON serialization for versioned harness definitions.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Type, TypeVar
from uuid import UUID

from .model import (
    SCHEMA_VERSION,
    Connection,
    ControlKind,
    ControlStructure,
    HarnessDefinition,
    PathwayDefinition,
    RoutingMode,
    WireDefinition,
    WireProfile,
)

EnumType = TypeVar("EnumType", RoutingMode, ControlKind)


class DefinitionParseError(ValueError):
    """
    Report invalid serialized harness data at a precise field path.
    """

    def __init__(self, path: str, message: str) -> None:
        """
        Initialize a structured parse error.

        Args:
            path: Dot-and-index path to the invalid field.
            message: Human-readable explanation.
        """
        self.path = path
        self.reason = message
        super().__init__(f"{path}: {message}")


def dumps(definition: HarnessDefinition) -> str:
    """
    Serialize a harness definition to deterministic JSON.

    Args:
        definition: Harness definition to serialize.

    Returns:
        Indented JSON with stable key ordering.
    """
    payload = _definition_to_dict(definition)
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    return serialized


def loads(serialized: str) -> HarnessDefinition:
    """
    Parse and shape-check a serialized harness definition.

    Args:
        serialized: JSON representation of a harness definition.

    Returns:
        Parsed immutable harness definition.

    Raises:
        DefinitionParseError: If JSON or a required data shape is invalid.
    """
    try:
        raw_payload = json.loads(serialized)
    except json.JSONDecodeError as error:
        raise DefinitionParseError("$", f"invalid JSON: {error.msg}") from error

    payload = _require_mapping(raw_payload, "$")
    schema_version = _require_int(payload, "schema_version", "$.schema_version")
    if schema_version not in (1, 2, SCHEMA_VERSION):
        raise DefinitionParseError(
            "$.schema_version",
            f"unsupported version {schema_version}; expected 1, 2, or {SCHEMA_VERSION}",
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
    )
    return definition


def _definition_to_dict(definition: HarnessDefinition) -> dict[str, Any]:
    """
    Convert a definition to JSON-compatible primitives.

    Args:
        definition: Harness definition to convert.

    Returns:
        JSON-compatible dictionary.
    """
    payload = {
        "schema_version": definition.schema_version,
        "harness_id": str(definition.harness_id),
        "name": definition.name,
        "routing_mode": definition.routing_mode.value,
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
                "connection_id": str(connection.connection_id),
                "name": connection.name,
                "entity_token": connection.entity_token,
            }
            for connection in definition.connections
        ],
        "controls": [
            {
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
                "start_connection_id": str(wire.start_connection_id),
                "end_connection_id": str(wire.end_connection_id),
                "profile_id": str(wire.profile_id),
                "ordered_pathway_ids": [str(pathway_id) for pathway_id in wire.ordered_pathway_ids],
                "ordered_control_ids": [str(control_id) for control_id in wire.ordered_control_ids],
            }
            for wire in definition.wires
        ],
    }
    return payload


def _parse_profile(raw_value: object, path: str) -> WireProfile:
    """
    Parse one conductor profile.

    Args:
        raw_value: Untrusted profile value.
        path: Profile path for error reporting.

    Returns:
        Parsed conductor profile.
    """
    value = _require_mapping(raw_value, path)
    profile = WireProfile(
        profile_id=_require_uuid(value, "profile_id", f"{path}.profile_id"),
        name=_require_str(value, "name", f"{path}.name"),
        diameter_mm=_require_float(value, "diameter_mm", f"{path}.diameter_mm"),
    )
    return profile


def _parse_connection(raw_value: object, path: str) -> Connection:
    """
    Parse one physical connection reference.

    Args:
        raw_value: Untrusted connection value.
        path: Connection path for error reporting.

    Returns:
        Parsed physical connection.
    """
    value = _require_mapping(raw_value, path)
    connection = Connection(
        connection_id=_require_uuid(value, "connection_id", f"{path}.connection_id"),
        name=_require_str(value, "name", f"{path}.name"),
        entity_token=_require_str(value, "entity_token", f"{path}.entity_token"),
    )
    return connection


def _parse_control(raw_value: object, path: str) -> ControlStructure:
    """
    Parse one routing control reference.

    Args:
        raw_value: Untrusted control value.
        path: Control path for error reporting.

    Returns:
        Parsed routing control.
    """
    value = _require_mapping(raw_value, path)
    control = ControlStructure(
        control_id=_require_uuid(value, "control_id", f"{path}.control_id"),
        name=_require_str(value, "name", f"{path}.name"),
        kind=_require_enum(ControlKind, value, "kind", f"{path}.kind"),
        entity_token=_require_str(value, "entity_token", f"{path}.entity_token"),
    )
    return control


def _parse_pathway(raw_value: object, path: str) -> PathwayDefinition:
    """
    Parse one reusable ordered pathway.

    Args:
        raw_value: Untrusted pathway value.
        path: Pathway path for error reporting.

    Returns:
        Parsed pathway definition.
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

    Args:
        raw_value: Untrusted wire value.
        path: Wire path for error reporting.
        schema_version: Source definition schema version.
        pathways: Parsed pathways available for legacy inference.

    Returns:
        Parsed conductor mapping.
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
    )
    return wire


def _require_mapping(raw_value: object, path: str) -> Mapping[str, Any]:
    """
    Require a mapping with string keys.

    Args:
        raw_value: Untrusted value.
        path: Value path for error reporting.

    Returns:
        Validated mapping.
    """
    if not isinstance(raw_value, Mapping):
        raise DefinitionParseError(path, "expected an object")
    if not all(isinstance(key, str) for key in raw_value):
        raise DefinitionParseError(path, "expected string object keys")
    return raw_value


def _require_value(value: Mapping[str, Any], key: str, path: str) -> object:
    """
    Require a named mapping value.

    Args:
        value: Mapping to inspect.
        key: Required key.
        path: Field path for error reporting.

    Returns:
        Present field value.
    """
    if key not in value:
        raise DefinitionParseError(path, "missing required field")
    return value[key]


def _require_str(value: Mapping[str, Any], key: str, path: str) -> str:
    """
    Require a string field.

    Args:
        value: Mapping to inspect.
        key: Required key.
        path: Field path for error reporting.

    Returns:
        String field value.
    """
    raw_value = _require_value(value, key, path)
    if not isinstance(raw_value, str):
        raise DefinitionParseError(path, "expected a string")
    return raw_value


def _require_int(value: Mapping[str, Any], key: str, path: str) -> int:
    """
    Require an integer field without accepting booleans.

    Args:
        value: Mapping to inspect.
        key: Required key.
        path: Field path for error reporting.

    Returns:
        Integer field value.
    """
    raw_value = _require_value(value, key, path)
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise DefinitionParseError(path, "expected an integer")
    return raw_value


def _require_float(value: Mapping[str, Any], key: str, path: str) -> float:
    """
    Require a numeric field without accepting booleans.

    Args:
        value: Mapping to inspect.
        key: Required key.
        path: Field path for error reporting.

    Returns:
        Floating-point field value.
    """
    raw_value = _require_value(value, key, path)
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise DefinitionParseError(path, "expected a number")
    return float(raw_value)


def _require_list(value: Mapping[str, Any], key: str, path: str) -> Sequence[object]:
    """
    Require an array field.

    Args:
        value: Mapping to inspect.
        key: Required key.
        path: Field path for error reporting.

    Returns:
        Sequence field value.
    """
    raw_value = _require_value(value, key, path)
    if not isinstance(raw_value, list):
        raise DefinitionParseError(path, "expected an array")
    return raw_value


def _require_uuid(value: Mapping[str, Any], key: str, path: str) -> UUID:
    """
    Require and parse a UUID string field.

    Args:
        value: Mapping to inspect.
        key: Required key.
        path: Field path for error reporting.

    Returns:
        Parsed UUID.
    """
    raw_value = _require_value(value, key, path)
    parsed_uuid = _parse_uuid(raw_value, path)
    return parsed_uuid


def _parse_uuid(raw_value: object, path: str) -> UUID:
    """
    Parse a UUID string.

    Args:
        raw_value: Untrusted UUID value.
        path: Value path for error reporting.

    Returns:
        Parsed UUID.
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

    Args:
        enum_type: Enum class to parse.
        value: Mapping to inspect.
        key: Required key.
        path: Field path for error reporting.

    Returns:
        Parsed enum member.
    """
    raw_value = _require_str(value, key, path)
    try:
        parsed_value = enum_type(raw_value)
    except ValueError as error:
        allowed_values = ", ".join(member.value for member in enum_type)
        raise DefinitionParseError(path, f"expected one of: {allowed_values}") from error
    return parsed_value
