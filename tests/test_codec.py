"""
Tests for harness definition JSON serialization.
"""

import json

import pytest

from wire_bundler.domain import DefinitionParseError, HarnessDefinition, dumps, loads


def test_round_trip_preserves_definition(valid_harness: HarnessDefinition) -> None:
    """
    Preserve immutable identities and explicit control ordering through JSON.
    """
    serialized = dumps(valid_harness)

    parsed = loads(serialized)

    assert parsed == valid_harness
    assert parsed.wires[0].ordered_pathway_ids == valid_harness.wires[0].ordered_pathway_ids
    assert parsed.wires[0].ordered_control_ids == valid_harness.wires[0].ordered_control_ids


def test_serialization_is_deterministic(valid_harness: HarnessDefinition) -> None:
    """
    Produce stable metadata text for identical definitions.
    """
    first = dumps(valid_harness)
    second = dumps(valid_harness)

    assert first == second


def test_missing_end_names_default_to_blank(valid_harness: HarnessDefinition) -> None:
    """
    Read stored definitions created before organizational end names were added.
    """
    payload = json.loads(dumps(valid_harness))
    for wire in payload["wires"]:
        del wire["start_end_name"]
        del wire["end_end_name"]
        del wire["display_name"]
    for pathway in payload["pathways"]:
        del pathway["start_name"]
        del pathway["end_name"]
    for connection in payload["connections"]:
        del connection["additional_entity_tokens"]
    assert loads(json.dumps(payload)) == valid_harness


@pytest.mark.parametrize("value", [None, 42, [], {}])
def test_malformed_end_name_is_rejected(valid_harness: HarnessDefinition, value: object) -> None:
    """
    Reject malformed optional metadata instead of silently dropping it.
    """
    payload = json.loads(dumps(valid_harness))
    payload["wires"][0]["start_end_name"] = value
    with pytest.raises(DefinitionParseError):
        loads(json.dumps(payload))


@pytest.mark.parametrize("members", [None, "token", [None], [""]])
def test_malformed_connection_members_rejected(
    valid_harness: HarnessDefinition,
    members: object,
) -> None:
    """
    Reject malformed connection collections before exposing member controls.
    """
    payload = json.loads(dumps(valid_harness))
    payload["connections"][0]["additional_entity_tokens"] = members
    with pytest.raises(DefinitionParseError):
        loads(json.dumps(payload))


def test_rejects_unknown_schema_version(valid_harness: HarnessDefinition) -> None:
    """
    Refuse definitions that require an unsupported schema migration.
    """
    payload = json.loads(dumps(valid_harness))
    payload["schema_version"] = 99

    with pytest.raises(DefinitionParseError) as error_info:
        loads(json.dumps(payload))

    assert error_info.value.path == "$.schema_version"
    assert "unsupported version" in error_info.value.reason


def test_reads_version_one_definition_as_current_schema(valid_harness: HarnessDefinition) -> None:
    """
    Preserve existing harnesses while introducing reusable pathways in version two.
    """
    payload = json.loads(dumps(valid_harness))
    payload["schema_version"] = 1
    payload.pop("pathways")

    migrated = loads(json.dumps(payload))

    assert migrated.schema_version == valid_harness.schema_version
    assert migrated.pathways == ()
    assert migrated.wires[0].ordered_pathway_ids == ()
    assert migrated.wires[0].ordered_control_ids == valid_harness.wires[0].ordered_control_ids


def test_reads_version_two_wire_pathway_from_matching_controls(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Infer the initial pathway identity for definitions written before schema three.
    """
    payload = json.loads(dumps(valid_harness))
    payload["schema_version"] = 2
    payload["wires"][0].pop("ordered_pathway_ids")

    migrated = loads(json.dumps(payload))

    assert migrated.wires[0].ordered_pathway_ids == (valid_harness.pathways[0].pathway_id,)


@pytest.mark.parametrize(
    ("serialized", "expected_path"),
    [
        ("not-json", "$"),
        ("[]", "$"),
        ('{"schema_version": true}', "$.schema_version"),
        ('{"schema_version": 1}', "$.harness_id"),
    ],
)
def test_rejects_malformed_external_data(serialized: str, expected_path: str) -> None:
    """
    Report malformed external data at the exact failing path.
    """
    with pytest.raises(DefinitionParseError) as error_info:
        loads(serialized)

    assert error_info.value.path == expected_path


@pytest.mark.parametrize(
    "identities", [[], ["bad-id"], ["00000000-0000-0000-0000-000000000001"] * 2]
)
def test_rejects_malformed_member_identities(
    valid_harness: HarnessDefinition, identities: list[str]
) -> None:
    """
    Require valid, unique member identifiers matching the profile count.
    """
    payload = json.loads(dumps(valid_harness))
    payload["connections"][0]["member_ids"] = identities
    with pytest.raises(DefinitionParseError):
        loads(json.dumps(payload))


def test_legacy_interpolation_is_automatic(valid_harness: HarnessDefinition) -> None:
    """
    Keep older definitions visually unchanged when optional settings are absent.
    """
    payload = json.loads(dumps(valid_harness))
    del payload["gate_defaults"]
    del payload["end_defaults"]
    for member in (*payload["controls"], *payload["connections"]):
        del member["interpolation"]
    assert loads(json.dumps(payload)) == valid_harness


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {"approach_mm": -1},
        {"departure_mm": True},
        {"approach_mm": "4"},
        {"departure_mm": float("inf")},
    ],
)
def test_rejects_malformed_interpolation(valid_harness: HarnessDefinition, raw: object) -> None:
    """
    Report the precise section path instead of allowing invalid geometry settings through.
    """
    payload = json.loads(dumps(valid_harness))
    payload["connections"][0]["interpolation"] = raw
    with pytest.raises(DefinitionParseError, match=r"connections\[0\].interpolation"):
        loads(json.dumps(payload))
