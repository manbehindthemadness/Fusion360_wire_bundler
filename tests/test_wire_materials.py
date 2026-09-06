"""
Tests for wire-material inheritance and the bundled suggestion catalog.
"""

from dataclasses import replace

from wire_bundler.application import load_wire_material_catalog
from wire_bundler.domain import (
    HarnessDefinition,
    WireAppearanceReference,
    WireColor,
    WireMaterialOverrides,
    WireMaterialSettings,
)


def test_wire_resolves_each_override_independently(valid_harness: HarnessDefinition) -> None:
    """
    Inherit parent fields unless that field has an explicit wire value.
    """
    defaults = WireMaterialSettings(
        insulation_material="PTFE",
        main_color=WireColor("Blue", 0, 0, 255),
        manufacturer="Parent maker",
        notes="Parent note",
    )
    overrides = WireMaterialOverrides(
        main_color=WireColor("Red", 255, 0, 0),
        manufacturer="",
    )
    definition = replace(valid_harness, material_defaults=defaults)
    wire = replace(valid_harness.wires[0], material_overrides=overrides)

    resolved = definition.wire_materials(wire)

    assert resolved.insulation_material == "PTFE"
    assert resolved.main_color.name == "Red"
    assert resolved.manufacturer == ""
    assert resolved.notes == "Parent note"


def test_base_visual_override_replaces_or_inherits_library_appearance(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Pair the optional Fusion appearance with the existing main-color override.
    """
    parent_appearance = WireAppearanceReference("lib", "Library", "blue", "Blue Rubber")
    defaults = WireMaterialSettings(
        main_color=WireColor("Blue", 0, 0, 255), appearance=parent_appearance
    )

    inherited = WireMaterialOverrides().resolve(defaults)
    plain_red = WireMaterialOverrides(main_color=WireColor("Red", 255, 0, 0)).resolve(defaults)

    assert inherited.appearance == parent_appearance
    assert plain_red.appearance is None


def test_catalog_provides_search_suggestions_without_owning_values() -> None:
    """
    Load bundled materials, conductors, colors, and supported stripe patterns.
    """
    catalog = load_wire_material_catalog()

    assert "ETFE" in catalog.insulation_materials
    assert "Tinned Copper" in catalog.conductor_materials
    assert any(color.name == "Blue" for color in catalog.colors)
    assert {pattern.value for pattern in catalog.stripe_patterns} == {
        "longitudinal",
        "dashed",
        "helical",
    }
