"""
Tests for transactional pathway and wire-sequence editing.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Optional, Protocol, cast
from uuid import UUID

import pytest

from wire_bundler.application import (
    HarnessEditError,
    HarnessEditGateway,
    add_pathway,
    add_wire_batch,
    append_pathway_gates,
    move_pathway_gate,
    move_wire_endpoint,
    remove_pathway_gate,
    remove_wire,
    rename_pathway,
    rename_route_end,
    rename_wire,
    set_harness_material_defaults,
    set_wire_diameter,
    set_wire_material_overrides,
)
from wire_bundler.application.edit_harness import edit_end_members, set_interpolation
from wire_bundler.domain import (
    Connection,
    ControlKind,
    ControlStructure,
    HarnessDefinition,
    WireColor,
    WireDefinition,
    WireMaterialOverrides,
    WireMaterialSettings,
    dumps,
    loads,
)
from wire_bundler.domain.model import InterpolationSettings

GATE_2_ID = UUID("30000000-0000-0000-0000-000000000002")
GATE_3_ID = UUID("30000000-0000-0000-0000-000000000003")
WIRE_2_ID = UUID("50000000-0000-0000-0000-000000000002")
SOURCE_2_ID = UUID("20000000-0000-0000-0000-000000000003")
END_2_ID = UUID("20000000-0000-0000-0000-000000000004")


def test_end_names_persist_independently_and_survive_edits(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Retain organizational names across reordering, additions, and clearing one end.
    """
    definition = _expanded_harness(valid_harness)
    gateway = _recording_gateway(definition)
    wire_id = definition.wires[0].wire_id
    rename_route_end(definition.harness_id, wire_id, "start", "  Controller  ", gateway)
    rename_route_end(definition.harness_id, wire_id, "end", "Motor", gateway)
    named = loads(gateway.serialized_definition)
    assert named.connections == definition.connections
    assert named.wires[0].start_end_name == "Controller"
    assert named.wires[0].end_end_name == "Motor"
    assert named.wires[1] == definition.wires[1]
    assert tuple(replace(wire, start_end_name="", end_end_name="") for wire in named.wires) == (
        definition.wires
    )
    move_wire_endpoint(definition.harness_id, wire_id, "start", 1, gateway)
    result = add_wire_batch(
        definition.harness_id,
        definition.pathways[0].pathway_id,
        ("new-a",),
        ("new-b",),
        1.5,
        gateway,
    )
    assert result.wires[0].start_end_name == ""
    assert result.wires[0].end_end_name == ""
    rename_route_end(definition.harness_id, wire_id, "start", "", gateway)
    cleared = loads(gateway.serialized_definition)
    assert all(wire.start_end_name == "" for wire in cleared.wires)
    assert cleared.wires[0].end_end_name == "Motor"
    assert cleared.wires[1].end_end_name == ""


def test_renaming_preserves_routes_and_wire_identity(valid_harness: HarnessDefinition) -> None:
    """
    Persist optional labels independently without changing identity or gate order.
    """
    gateway = _recording_gateway(valid_harness)
    pathway = valid_harness.pathways[0]
    wire = valid_harness.wires[0]
    for field, name in (
        ("name", "Lower fuse box"),
        ("start_name", "o2-sensor"),
        ("end_name", "can_bus-ctrl"),
    ):
        rename_pathway(valid_harness.harness_id, pathway.pathway_id, field, name, gateway)
    rename_wire(valid_harness.harness_id, wire.wire_id, "Sensor signal", gateway)
    stored = loads(gateway.serialized_definition)
    assert stored.pathways[0] == replace(
        pathway, name="Lower fuse box", start_name="o2-sensor", end_name="can_bus-ctrl"
    )
    assert stored.wires[0] == replace(wire, display_name="Sensor signal")
    rename_wire(valid_harness.harness_id, wire.wire_id, " ", gateway)
    rename_pathway(valid_harness.harness_id, pathway.pathway_id, "start_name", "", gateway)
    cleared = loads(gateway.serialized_definition)
    assert cleared.wires[0] == wire
    assert cleared.pathways[0].start_name == ""
    assert cleared.pathways[0].end_name == "can_bus-ctrl"


def test_wire_rename_resolves_collisions(valid_harness: HarnessDefinition) -> None:
    """
    Keep editable wire labels distinct without renumbering conductors.
    """
    definition = _expanded_harness(valid_harness)
    gateway = _recording_gateway(definition)
    for wire in definition.wires:
        rename_wire(definition.harness_id, wire.wire_id, "Signal", gateway)
    stored = loads(gateway.serialized_definition)
    assert [wire.display_name for wire in stored.wires] == ["Signal", "Signal_2"]
    assert [wire.wire_number for wire in stored.wires] == ["001", "002"]


def test_rejects_invalid_pathway_rename(valid_harness: HarnessDefinition) -> None:
    """
    Reject unsupported field updates before writing metadata.
    """
    gateway = _recording_gateway(valid_harness)
    with pytest.raises(ValueError, match="Unsupported"):
        rename_pathway(
            valid_harness.harness_id,
            valid_harness.pathways[0].pathway_id,
            "ordered_control_ids",
            "bad",
            gateway,
        )
    assert gateway.writes == []


def test_diameter_edit_isolates_shared_profile(valid_harness: HarnessDefinition) -> None:
    """
    Change only the selected wire, then reuse its private profile on subsequent edits.
    """
    definition = _expanded_harness(valid_harness)
    gateway = _recording_gateway(definition)
    profile_id = UUID("60000000-0000-0000-0000-000000000001")
    set_wire_diameter(
        definition.harness_id,
        definition.wires[0].wire_id,
        2.5,
        gateway,
        id_factory=lambda: profile_id,
    )
    stored = loads(gateway.serialized_definition)
    assert stored.wires[1] == definition.wires[1]
    assert stored.profiles[0] == definition.profiles[0]
    assert stored.profiles[-1].diameter_mm == 2.5
    assert stored.wires[0] == replace(definition.wires[0], profile_id=profile_id)
    set_wire_diameter(definition.harness_id, definition.wires[0].wire_id, 3.0, gateway)
    updated = loads(gateway.serialized_definition)
    assert len(updated.profiles) == len(stored.profiles)
    assert updated.profiles[-1].diameter_mm == 3.0


def test_wire_material_overrides_take_precedence_over_parent(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Update inherited fields while preserving each explicit per-wire override.
    """
    definition = _expanded_harness(valid_harness)
    gateway = _recording_gateway(definition)
    first, second = definition.wires
    red = WireColor("Red", 200, 38, 38)
    blue = WireColor("Blue", 35, 94, 190)

    set_wire_material_overrides(
        definition.harness_id,
        first.wire_id,
        WireMaterialOverrides(main_color=red, stripes=()),
        gateway,
    )
    set_harness_material_defaults(
        definition.harness_id,
        WireMaterialSettings(insulation_material="ETFE", main_color=blue),
        gateway,
    )

    stored = loads(gateway.serialized_definition)
    assert stored.wire_materials(stored.wires[0]).main_color == red
    assert stored.wire_materials(stored.wires[0]).stripes == ()
    assert stored.wire_materials(stored.wires[1]).main_color == blue
    assert stored.wire_materials(stored.wires[1]).insulation_material == "ETFE"
    assert stored.wires[1] == second


@pytest.mark.parametrize("diameter", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_diameter_does_not_write(
    valid_harness: HarnessDefinition,
    diameter: float,
) -> None:
    """
    Reject sizes that cannot define a circular wire before touching persistence.
    """
    gateway = _recording_gateway(valid_harness)
    with pytest.raises(ValueError, match="positive"):
        set_wire_diameter(
            valid_harness.harness_id, valid_harness.wires[0].wire_id, diameter, gateway
        )
    assert gateway.writes == []


def test_end_name_failure_restores_definition(valid_harness: HarnessDefinition) -> None:
    """
    Roll back a rejected metadata write without losing the prior definition.
    """
    gateway = _recording_gateway(valid_harness, (RuntimeError("write failed"),))
    original = gateway.serialized_definition
    with pytest.raises(RuntimeError, match="write failed"):
        rename_route_end(
            valid_harness.harness_id, valid_harness.wires[0].wire_id, "end", "Motor", gateway
        )
    assert gateway.serialized_definition == original


class _RecordingGateway(HarnessEditGateway, Protocol):
    """
    Expose recorded test state in addition to the application gateway contract.
    """

    serialized_definition: str
    writes: list[str]


def _recording_gateway(
    definition: HarnessDefinition,
    failures: tuple[Optional[Exception], ...] = (),
) -> _RecordingGateway:
    """
    Return an in-memory gateway that can reject sequential writes.
    """
    state = SimpleNamespace(
        serialized_definition=dumps(definition),
        failures=list(failures),
        writes=[],
    )

    def read_harness_definition(harness_id: UUID) -> str:
        """
        Return the current serialized definition.
        """
        del harness_id
        return state.serialized_definition

    def replace_harness_definition(harness_id: UUID, serialized_definition: str) -> None:
        """
        Record or reject a replacement in configured call order.
        """
        del harness_id
        state.writes.append(serialized_definition)
        failure = state.failures.pop(0) if state.failures else None
        if failure is not None:
            raise failure
        state.serialized_definition = serialized_definition

    state.read_harness_definition = read_harness_definition
    state.replace_harness_definition = replace_harness_definition
    return cast(_RecordingGateway, cast(object, state))


def _expanded_harness(valid_harness: HarnessDefinition) -> HarnessDefinition:
    """
    Return a deterministic two-wire, three-gate harness.
    """
    first_pathway = valid_harness.pathways[0]
    first_wire = valid_harness.wires[0]
    controls = (
        *valid_harness.controls,
        ControlStructure(GATE_2_ID, "Routing Gate 02", ControlKind.ROUTING_GATE, "gate-2"),
        ControlStructure(GATE_3_ID, "Routing Gate 03", ControlKind.ROUTING_GATE, "gate-3"),
    )
    pathway = replace(
        first_pathway,
        ordered_control_ids=(first_pathway.ordered_control_ids[0], GATE_2_ID, GATE_3_ID),
    )
    connections = (
        *valid_harness.connections,
        Connection(SOURCE_2_ID, "J1 / Pin 2", "source-2"),
        Connection(END_2_ID, "J2 / Pin 5", "end-2"),
    )
    second_wire = WireDefinition(
        WIRE_2_ID,
        "002",
        SOURCE_2_ID,
        END_2_ID,
        first_wire.profile_id,
        first_wire.ordered_pathway_ids,
        pathway.ordered_control_ids,
    )
    return replace(
        valid_harness,
        controls=controls,
        connections=connections,
        pathways=(pathway,),
        wires=(replace(first_wire, ordered_control_ids=pathway.ordered_control_ids), second_wire),
    )


def test_moves_gate_and_resynchronizes_wire_routes(valid_harness: HarnessDefinition) -> None:
    """
    Keep pathway and every dependent wire in the same explicit gate order.
    """
    definition = _expanded_harness(valid_harness)
    gateway = _recording_gateway(definition)
    pathway = definition.pathways[0]

    updated_pathway = move_pathway_gate(
        definition.harness_id,
        pathway.pathway_id,
        GATE_2_ID,
        -1,
        gateway,
    )

    stored = loads(gateway.serialized_definition)
    expected = (GATE_2_ID, definition.controls[0].control_id, GATE_3_ID)
    assert updated_pathway.ordered_control_ids == expected
    assert all(wire.ordered_control_ids == expected for wire in stored.wires)


def test_removes_gate_and_retains_at_least_one(valid_harness: HarnessDefinition) -> None:
    """
    Prune removed gate metadata while rejecting an empty pathway.
    """
    definition = _expanded_harness(valid_harness)
    gateway = _recording_gateway(definition)
    pathway = definition.pathways[0]

    remove_pathway_gate(
        definition.harness_id,
        pathway.pathway_id,
        GATE_2_ID,
        gateway,
    )

    stored = loads(gateway.serialized_definition)
    assert GATE_2_ID not in {control.control_id for control in stored.controls}
    assert all(GATE_2_ID not in wire.ordered_control_ids for wire in stored.wires)

    single_gate = replace(
        stored,
        pathways=(replace(stored.pathways[0], ordered_control_ids=(GATE_3_ID,)),),
    )
    single_gateway = _recording_gateway(single_gate)
    with pytest.raises(ValueError, match="retain at least one"):
        remove_pathway_gate(
            single_gate.harness_id,
            single_gate.pathways[0].pathway_id,
            GATE_3_ID,
            single_gateway,
        )
    assert single_gateway.writes == []


def test_appends_named_gates_and_resynchronizes_wires(valid_harness: HarnessDefinition) -> None:
    """
    Append controls in selection order with conflict-free user-facing names.
    """
    gateway = _recording_gateway(valid_harness)

    controls = append_pathway_gates(
        valid_harness.harness_id,
        valid_harness.pathways[0].pathway_id,
        ("new-gate-1", "new-gate-2"),
        gateway,
        id_factory=iter((GATE_2_ID, GATE_3_ID)).__next__,
    )

    stored = loads(gateway.serialized_definition)
    assert [control.name for control in controls] == ["Routing Gate 02", "Routing Gate 03"]
    assert stored.pathways[0].ordered_control_ids[-2:] == (GATE_2_ID, GATE_3_ID)
    assert stored.wires[0].ordered_control_ids == stored.pathways[0].ordered_control_ids


def test_rejects_gate_edit_when_wire_references_missing_pathway(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Avoid persisting a partial route update through already-invalid wire metadata.
    """
    definition = _expanded_harness(valid_harness)
    missing_pathway_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    damaged = replace(
        definition,
        wires=(
            replace(definition.wires[0], ordered_pathway_ids=(missing_pathway_id,)),
            definition.wires[1],
        ),
    )
    gateway = _recording_gateway(damaged)

    with pytest.raises(ValueError, match="references a missing pathway"):
        move_pathway_gate(
            damaged.harness_id,
            damaged.pathways[0].pathway_id,
            GATE_2_ID,
            -1,
            gateway,
        )

    assert gateway.writes == []


@pytest.mark.parametrize("endpoint", ["start", "end"])
def test_reorders_endpoint_sequence_without_replacing_wire_identity(
    valid_harness: HarnessDefinition,
    endpoint: str,
) -> None:
    """
    Swap one endpoint pairing while preserving stable wire rows and numbers.
    """
    definition = _expanded_harness(valid_harness)
    gateway = _recording_gateway(definition)
    original_first = definition.wires[0]
    original_second = definition.wires[1]

    move_wire_endpoint(
        definition.harness_id,
        original_second.wire_id,
        endpoint,
        -1,
        gateway,
    )

    stored = loads(gateway.serialized_definition)
    assert [wire.wire_id for wire in stored.wires] == [
        original_first.wire_id,
        original_second.wire_id,
    ]
    attribute = "start_connection_id" if endpoint == "start" else "end_connection_id"
    assert getattr(stored.wires[0], attribute) == getattr(original_second, attribute)
    assert getattr(stored.wires[1], attribute) == getattr(original_first, attribute)


def test_removes_complete_wire_pair_and_only_its_unused_members(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Delete both endpoints but preserve a profile shared by another wire.
    """
    definition = _expanded_harness(valid_harness)
    gateway = _recording_gateway(definition)

    remove_wire(definition.harness_id, definition.wires[1].wire_id, gateway)

    stored = loads(gateway.serialized_definition)
    assert stored.wires == (definition.wires[0],)
    assert SOURCE_2_ID not in {item.connection_id for item in stored.connections}
    assert END_2_ID not in {item.connection_id for item in stored.connections}
    assert stored.profiles == definition.profiles


def test_restores_exact_definition_after_edit_failure(valid_harness: HarnessDefinition) -> None:
    """
    Roll back atomically and report a failed rollback distinctly.
    """
    definition = _expanded_harness(valid_harness)
    write_error = RuntimeError("write failed")
    gateway = _recording_gateway(definition, (write_error, None))

    with pytest.raises(RuntimeError, match="write failed"):
        move_pathway_gate(
            definition.harness_id,
            definition.pathways[0].pathway_id,
            GATE_2_ID,
            -1,
            gateway,
        )
    assert gateway.serialized_definition == dumps(definition)

    failed_rollback = _recording_gateway(
        definition,
        (write_error, RuntimeError("rollback failed")),
    )
    with pytest.raises(HarnessEditError, match="rollback failed") as error_info:
        remove_wire(definition.harness_id, definition.wires[1].wire_id, failed_rollback)
    assert error_info.value.__cause__ is write_error


def test_end_members_add_replace_remove_and_restore(valid_harness: HarnessDefinition) -> None:
    """
    Edit one connection without replacing the wire or its other end.
    """
    gateway = _recording_gateway(valid_harness)
    wire = valid_harness.wires[0]
    edit_end_members(
        valid_harness.harness_id,
        wire.wire_id,
        "start",
        "add",
        gateway,
        ("second", "third"),
        expected_members=1,
    )
    stored = loads(gateway.serialized_definition)
    connection = next(
        item for item in stored.connections if item.connection_id == wire.start_connection_id
    )
    assert connection.member_tokens == ("fusion-start-token", "second", "third")
    edit_end_members(
        valid_harness.harness_id,
        wire.wire_id,
        "start",
        "replace",
        gateway,
        ("replacement",),
        member_index=1,
        expected_members=3,
    )
    edit_end_members(
        valid_harness.harness_id,
        wire.wire_id,
        "start",
        "remove",
        gateway,
        member_index=0,
        expected_members=3,
    )
    updated = loads(gateway.serialized_definition)
    connection = next(
        item for item in updated.connections if item.connection_id == wire.start_connection_id
    )
    assert connection.member_tokens == ("replacement", "third")
    for count in (2, 1):
        edit_end_members(
            valid_harness.harness_id,
            wire.wire_id,
            "start",
            "remove",
            gateway,
            expected_members=count,
        )
    deleted = loads(gateway.serialized_definition)
    assert deleted.wires == valid_harness.wires
    assert all(item.connection_id != wire.start_connection_id for item in deleted.connections)
    assert (
        next(item for item in deleted.connections if item.connection_id == wire.end_connection_id)
        == valid_harness.connections[1]
    )
    edit_end_members(
        valid_harness.harness_id,
        wire.wire_id,
        "start",
        "add",
        gateway,
        ("restored",),
        expected_members=0,
    )
    restored = loads(gateway.serialized_definition)
    assert next(
        item for item in restored.connections if item.connection_id == wire.start_connection_id
    ).member_tokens == ("restored",)
    assert restored.wires == valid_harness.wires


def test_end_member_edit_rejects_stale_count_and_rolls_back(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Reject stale UI indices and restore metadata after a failed write.
    """
    wire = valid_harness.wires[0]
    gateway = _recording_gateway(valid_harness)
    with pytest.raises(ValueError, match="changed"):
        edit_end_members(
            valid_harness.harness_id, wire.wire_id, "start", "remove", gateway, expected_members=2
        )
    assert gateway.writes == []
    failing = _recording_gateway(valid_harness, (RuntimeError("write failed"),))
    with pytest.raises(RuntimeError, match="write failed"):
        edit_end_members(
            valid_harness.harness_id,
            wire.wire_id,
            "start",
            "replace",
            failing,
            ("new",),
            expected_members=1,
        )
    assert loads(failing.serialized_definition) == valid_harness


def test_end_members_insert_and_reorder(valid_harness: HarnessDefinition) -> None:
    """
    Insert after a row and promote a member to the routing anchor without changing wire identity.
    """
    gateway = _recording_gateway(valid_harness)
    wire = valid_harness.wires[0]
    args = (valid_harness.harness_id, wire.wire_id, "start")
    edit_end_members(*args, "add", gateway, ("second", "third"), expected_members=1)
    edit_end_members(*args, "add", gateway, ("inserted",), expected_members=3)
    edit_end_members(*args, "reorder", gateway, member_index=1, expected_members=4, target_index=0)
    updated = loads(gateway.serialized_definition)
    assert updated.connections[0].member_tokens == (
        "inserted",
        "fusion-start-token",
        "second",
        "third",
    )
    assert updated.wires == valid_harness.wires
    edit_end_members(*args, "reorder", gateway, member_index=0, expected_members=4, target_index=1)
    assert loads(gateway.serialized_definition).connections[0].member_tokens == (
        "fusion-start-token",
        "inserted",
        "second",
        "third",
    )
    before = gateway.serialized_definition
    for target in (-1, 4):
        with pytest.raises(ValueError, match="beyond"):
            edit_end_members(
                *args, "reorder", gateway, member_index=0, expected_members=4, target_index=target
            )
    assert gateway.serialized_definition == before


def test_member_identity_survives_reorder_replace_and_reload(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Keep identities attached to members while their positions and geometry change.
    """
    gateway = _recording_gateway(valid_harness)
    wire = valid_harness.wires[0]
    args = (valid_harness.harness_id, wire.wire_id, "start")
    original_id = valid_harness.connections[0].member_identities[0]
    edit_end_members(*args, "add", gateway, ("second",), expected_members=1)
    identities = loads(gateway.serialized_definition).connections[0].member_identities
    assert identities[0] == original_id
    assert len(set(identities)) == 2
    edit_end_members(*args, "reorder", gateway, member_index=1, target_index=0, expected_members=2)
    edit_end_members(*args, "replace", gateway, ("replacement",), expected_members=2)
    connection = loads(gateway.serialized_definition).connections[0]
    assert connection.member_identities == tuple(reversed(identities))
    assert connection.member_tokens == ("replacement", "fusion-start-token")


def test_gate_drop_inserts_across_multiple_positions(valid_harness: HarnessDefinition) -> None:
    """
    Insert a dragged gate without swapping or disturbing intervening gate order.
    """
    definition = _expanded_harness(valid_harness)
    gateway = _recording_gateway(definition)
    pathway = definition.pathways[0]
    first, second, third = pathway.ordered_control_ids
    moved = move_pathway_gate(definition.harness_id, pathway.pathway_id, first, 2, gateway)
    assert moved.ordered_control_ids == (second, third, first)
    stored = loads(gateway.serialized_definition)
    assert all(wire.ordered_control_ids == (second, third, first) for wire in stored.wires)
    assert stored.controls == definition.controls
    restored = move_pathway_gate(definition.harness_id, pathway.pathway_id, first, -2, gateway)
    assert restored.ordered_control_ids == pathway.ordered_control_ids


def test_interpolation_defaults_only_seed_new_sections(valid_harness: HarnessDefinition) -> None:
    """
    Copy defaults into new pathways, appended gates, and wire ends without retroactive edits.
    """
    gateway = _recording_gateway(valid_harness)
    gates = InterpolationSettings(3, None)
    ends = InterpolationSettings(1, 2)
    set_interpolation(valid_harness.harness_id, "defaults", gates, gateway, end_defaults=ends)
    saved = loads(gateway.serialized_definition)
    assert saved.controls == valid_harness.controls
    assert saved.connections == valid_harness.connections
    pathway = add_pathway(saved.harness_id, "New", saved.routing_mode, ("new-gate",), gateway)
    append_pathway_gates(saved.harness_id, pathway.pathway_id, ("next-gate",), gateway)
    add_wire_batch(saved.harness_id, pathway.pathway_id, ("new-start",), ("new-end",), 1.5, gateway)
    created = loads(gateway.serialized_definition)
    assert all(item.interpolation == gates for item in created.controls[1:])
    assert all(item.interpolation == ends for item in created.connections[2:])
    set_interpolation(
        saved.harness_id,
        "defaults",
        InterpolationSettings(),
        gateway,
        end_defaults=InterpolationSettings(),
    )
    reset = loads(gateway.serialized_definition)
    assert reset.controls == created.controls
    assert reset.connections == created.connections


def test_end_interpolation_survives_member_edits(valid_harness: HarnessDefinition) -> None:
    """
    Retain the section's settings and identity through adding, replacing, and reordering profiles.
    """
    gateway = _recording_gateway(valid_harness)
    settings = InterpolationSettings(2, 4)
    identity = valid_harness.connections[0].connection_id
    set_interpolation(valid_harness.harness_id, "end", settings, gateway, identity)
    wire_id = valid_harness.wires[0].wire_id
    edit_end_members(
        valid_harness.harness_id,
        wire_id,
        "start",
        "add",
        gateway,
        tokens=("guide",),
        expected_members=1,
    )
    edit_end_members(
        valid_harness.harness_id,
        wire_id,
        "start",
        "replace",
        gateway,
        tokens=("new-guide",),
        member_index=1,
        expected_members=2,
    )
    edit_end_members(
        valid_harness.harness_id,
        wire_id,
        "start",
        "reorder",
        gateway,
        member_index=1,
        target_index=0,
        expected_members=2,
    )
    saved = loads(gateway.serialized_definition)
    assert saved.connections[0].interpolation == settings
    assert saved.connections[0].connection_id == identity
    assert saved.connections[0].member_tokens == ("new-guide", "fusion-start-token")
    assert saved.connections[1] == valid_harness.connections[1]


def test_interpolation_edit_rolls_back_and_rejects_missing_targets(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Restore exact metadata on a failed save and reject stale targets before writing.
    """
    gateway = _recording_gateway(valid_harness, (RuntimeError("save failed"),))
    original = gateway.serialized_definition
    with pytest.raises(RuntimeError, match="save failed"):
        set_interpolation(
            valid_harness.harness_id,
            "gate",
            InterpolationSettings(3, 4),
            gateway,
            valid_harness.controls[0].control_id,
        )
    assert gateway.serialized_definition == original
    gateway.writes.clear()
    with pytest.raises(ValueError, match="no longer exists"):
        set_interpolation(
            valid_harness.harness_id, "end", InterpolationSettings(), gateway, UUID(int=999)
        )
    assert not gateway.writes


def test_defaults_preserve_member_and_gate_overrides(valid_harness: HarnessDefinition) -> None:
    """
    Update inherited values while preserving fine tuning across member reorder and replacement.
    """
    gateway = _recording_gateway(valid_harness)
    harness_id = valid_harness.harness_id
    wire_id = valid_harness.wires[0].wire_id
    gate_id = valid_harness.controls[0].control_id
    connection_id = valid_harness.connections[0].connection_id
    edit_end_members(
        harness_id, wire_id, "start", "add", gateway, tokens=("guide",), expected_members=1
    )
    connection = loads(gateway.serialized_definition).connections[0]
    member_id = connection.member_identities[1]
    tuned = InterpolationSettings(4, 6)
    set_interpolation(harness_id, "end", tuned, gateway, connection_id, member_id=member_id)
    set_interpolation(harness_id, "gate", tuned, gateway, gate_id)
    defaults = InterpolationSettings(2, 3)
    set_interpolation(
        harness_id, "defaults", defaults, gateway, end_defaults=defaults, apply_existing=True
    )
    saved = loads(gateway.serialized_definition)
    assert saved.connections[0].member_settings == (defaults, tuned)
    assert saved.controls[0].interpolation == tuned
    edit_end_members(
        harness_id,
        wire_id,
        "start",
        "reorder",
        gateway,
        member_index=1,
        target_index=0,
        expected_members=2,
    )
    edit_end_members(
        harness_id,
        wire_id,
        "start",
        "replace",
        gateway,
        tokens=("replacement",),
        member_index=0,
        expected_members=2,
    )
    saved = loads(gateway.serialized_definition)
    assert saved.connections[0].member_identities[0] == member_id
    assert saved.connections[0].member_settings == (tuned, defaults)
    set_interpolation(
        harness_id, "end", tuned, gateway, connection_id, member_id=member_id, use_defaults=True
    )
    set_interpolation(harness_id, "gate", tuned, gateway, gate_id, use_defaults=True)
    saved = loads(gateway.serialized_definition)
    assert saved.connections[0].member_settings == (defaults, defaults)
    assert saved.controls[0].interpolation == defaults
    assert not saved.controls[0].interpolation_is_override
    assert len(gateway.writes) == 8
