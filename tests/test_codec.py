"""
Tests for harness definition JSON serialization.
"""

import json
from dataclasses import replace
from uuid import UUID

import pytest

from wire_bundler.domain import (
    ControlKind,
    ControlStructure,
    DefinitionParseError,
    HarnessDefinition,
    JunctionDefinition,
    JunctionPathwayRelationship,
    PathwayEndpoint,
    RefineGeometry,
    StripePattern,
    WireAppearanceReference,
    WireColor,
    WireMaterialOverrides,
    WireMaterialSettings,
    WireStripe,
    dumps,
    loads,
)


def test_round_trip_preserves_definition(valid_harness: HarnessDefinition) -> None:
    """
    Preserve immutable identities and explicit control ordering through JSON.
    """
    serialized = dumps(valid_harness)

    parsed = loads(serialized)

    assert parsed == valid_harness
    assert parsed.wires[0].ordered_pathway_ids == valid_harness.wires[0].ordered_pathway_ids
    assert parsed.wires[0].ordered_control_ids == valid_harness.wires[0].ordered_control_ids


def test_round_trip_preserves_refine_geometry(valid_harness: HarnessDefinition) -> None:
    """
    Persist an unconstrained control frame without a Fusion entity token.
    """
    geometry = RefineGeometry(
        (1.0, 2.0, 3.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        8.0,
    )
    refine = replace(
        valid_harness.controls[0],
        kind=ControlKind.REFINE,
        entity_token="",
        refine_geometry=geometry,
    )
    definition = replace(valid_harness, controls=(refine,))

    parsed = loads(dumps(definition))

    assert parsed == definition


def test_round_trip_preserves_isolated_junction_relationships(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Encode an unconnected schema-v8 junction with an empty relationship list.
    """
    control = ControlStructure(
        UUID("37000000-0000-0000-0000-000000000001"),
        "Routing Gate 02",
        ControlKind.ROUTING_GATE,
        "isolated-profile-token",
    )
    junction = JunctionDefinition(
        UUID("37000000-0000-0000-0000-000000000002"),
        "Junction 01",
        control.control_id,
    )
    definition = replace(
        valid_harness,
        controls=(*valid_harness.controls, control),
        junctions=(junction,),
    )

    serialized = dumps(definition)
    parsed = loads(serialized)

    assert parsed == definition
    assert json.loads(serialized)["junctions"][0]["pathway_relationships"] == []


def test_serialization_is_deterministic(valid_harness: HarnessDefinition) -> None:
    """
    Produce stable metadata text for identical definitions.
    """
    first = dumps(valid_harness)
    second = dumps(valid_harness)

    assert first == second


def test_round_trip_preserves_parent_materials_and_wire_overrides(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Preserve ordered stripes and nullable field-level inheritance through JSON.
    """
    defaults = WireMaterialSettings(
        insulation_material="ETFE",
        main_color=WireColor("Blue", 35, 94, 190),
        appearance=WireAppearanceReference(
            "library-id", "My Appearances", "appearance-id", "Blue Rubber"
        ),
        stripes=(
            WireStripe(WireColor("White", 245, 245, 245), 0.25),
            WireStripe(
                WireColor("Red", 200, 38, 38),
                0.15,
                StripePattern.HELICAL,
                90.0,
                12.0,
            ),
        ),
        conductor_material="Tinned Copper",
        manufacturer="Acme",
        part_number="WB-18",
        notes="Engine bay",
    )
    orange = WireColor("Orange", 232, 117, 17)
    overrides = WireMaterialOverrides(
        main_color=orange,
        appearance=WireAppearanceReference(
            "library-id", "My Appearances", "orange-id", "Orange Rubber"
        ),
        stripes=(),
        part_number="WB-18-OR",
    )
    definition = replace(
        valid_harness,
        material_defaults=defaults,
        wires=(replace(valid_harness.wires[0], material_overrides=overrides),),
    )

    parsed = loads(dumps(definition))

    assert parsed == definition
    assert parsed.wire_materials(parsed.wires[0]) == replace(
        defaults,
        main_color=orange,
        appearance=overrides.appearance,
        stripes=(),
        part_number="WB-18-OR",
    )


def test_reads_version_three_with_default_materials(valid_harness: HarnessDefinition) -> None:
    """
    Migrate saved harnesses from before wire materials without guessing values.
    """
    payload = json.loads(dumps(valid_harness))
    payload["schema_version"] = 3
    payload.pop("material_defaults")
    for wire in payload["wires"]:
        wire.pop("material_overrides")

    migrated = loads(json.dumps(payload))

    assert migrated.material_defaults == WireMaterialSettings()
    assert migrated.wires[0].material_overrides == WireMaterialOverrides()


def test_reads_version_five_without_junctions(valid_harness: HarnessDefinition) -> None:
    """
    Migrate saved linear routes to schema six without inventing junctions.
    """
    payload = json.loads(dumps(valid_harness))
    payload["schema_version"] = 5
    payload.pop("junctions")

    migrated = loads(json.dumps(payload))

    assert migrated.junctions == ()


def test_reads_version_six_with_required_junction_relationships(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Migrate connected schema-v6 junction fields without changing their identities.
    """
    payload = json.loads(dumps(valid_harness))
    pathway_id = str(valid_harness.pathways[0].pathway_id)
    payload["schema_version"] = 6
    payload["junctions"] = [
        {
            "junction_id": "37000000-0000-0000-0000-000000000002",
            "name": "Junction 01",
            "control_id": str(valid_harness.controls[0].control_id),
            "preceding_pathway_id": pathway_id,
            "following_pathway_id": pathway_id,
        }
    ]

    migrated = loads(json.dumps(payload))

    assert migrated.junctions[0].pathway_relationships == (
        JunctionPathwayRelationship(valid_harness.pathways[0].pathway_id, PathwayEndpoint.END),
        JunctionPathwayRelationship(valid_harness.pathways[0].pathway_id, PathwayEndpoint.START),
    )


def test_reads_version_seven_with_optional_pair_relationships(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Migrate both connected and isolated draft schema-v7 junctions.
    """
    payload = json.loads(dumps(valid_harness))
    pathway_id = str(valid_harness.pathways[0].pathway_id)
    payload["schema_version"] = 7
    payload["junctions"] = [
        {
            "junction_id": "37000000-0000-0000-0000-000000000002",
            "name": "Junction 01",
            "control_id": str(valid_harness.controls[0].control_id),
            "preceding_pathway_id": pathway_id,
            "following_pathway_id": None,
        }
    ]

    migrated = loads(json.dumps(payload))

    assert migrated.junctions[0].pathway_relationships == (
        JunctionPathwayRelationship(valid_harness.pathways[0].pathway_id, PathwayEndpoint.END),
    )


def test_rejects_stripe_without_required_repeat(valid_harness: HarnessDefinition) -> None:
    """
    Reject a dashed stripe that cannot define a procedural repetition.
    """
    payload = json.loads(dumps(valid_harness))
    payload["material_defaults"]["stripes"] = [
        {
            "color": {"name": "White", "red": 255, "green": 255, "blue": 255},
            "width_mm": 0.2,
            "pattern": "dashed",
            "angle_deg": 0,
            "repeat_mm": None,
        }
    ]

    with pytest.raises(DefinitionParseError, match="require a positive repeat"):
        loads(json.dumps(payload))


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
