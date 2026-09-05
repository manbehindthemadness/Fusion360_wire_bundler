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
