"""
Tests for host-independent discovery and decoding of harness definitions.
"""

from __future__ import annotations

from dataclasses import replace

from wire_bundler.application import StoredHarness, load_harnesses
from wire_bundler.domain import HarnessDefinition, dumps


class _LibraryGateway:
    """
    Return deterministic stored definitions without importing Fusion.
    """

    def __init__(self, stored_harnesses: tuple[StoredHarness, ...]) -> None:
        """
        Retain the stored harnesses in host enumeration order.
        """
        self._stored_harnesses = stored_harnesses

    def list_stored_harnesses(self) -> tuple[StoredHarness, ...]:
        """
        Return configured stored harnesses.
        """
        return self._stored_harnesses


def test_loads_and_sorts_discovered_harnesses(valid_harness: HarnessDefinition) -> None:
    """
    Decode definitions and present them in stable component-name order.
    """
    second_definition = replace(valid_harness, name="Harness_002")
    gateway = _LibraryGateway(
        (
            StoredHarness("Harness_002", dumps(second_definition)),
            StoredHarness("Harness_001", dumps(valid_harness)),
        )
    )

    results = load_harnesses(gateway)

    assert tuple(result.component_name for result in results) == (
        "Harness_001",
        "Harness_002",
    )
    assert results[0].definition == valid_harness
    assert results[0].error is None
    assert results[0].validation_messages == ()


def test_isolates_damaged_definition_from_valid_harness(
    valid_harness: HarnessDefinition,
) -> None:
    """
    Keep a malformed component visible without hiding valid neighbors.
    """
    gateway = _LibraryGateway(
        (
            StoredHarness("Broken", "{not-json"),
            StoredHarness("Harness_001", dumps(valid_harness)),
        )
    )

    results = load_harnesses(gateway)

    assert results[0].component_name == "Broken"
    assert results[0].definition is None
    assert results[0].error is not None
    assert results[1].definition == valid_harness


def test_reports_draft_validation_findings(valid_harness: HarnessDefinition) -> None:
    """
    Distinguish a parseable draft from a generation-ready harness.
    """
    draft = replace(valid_harness, profiles=(), connections=(), controls=(), wires=())
    gateway = _LibraryGateway((StoredHarness("Draft", dumps(draft)),))

    result = load_harnesses(gateway)[0]

    assert result.definition == draft
    assert result.error is None
    assert result.validation_messages
