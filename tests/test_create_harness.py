"""
Tests for transactional empty-harness creation.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

import pytest

from wire_bundler.application import (
    HarnessCreationError,
    create_empty_harness,
    suggest_harness_name,
)
from wire_bundler.domain import RoutingMode, loads, next_available_name

HARNESS_ID = UUID("40000000-0000-0000-0000-000000000002")


class _RecordingGateway:
    """
    Record application-service calls without importing Autodesk Fusion.
    """

    def __init__(
        self,
        persistence_error: Optional[Exception] = None,
        rollback_error: Optional[Exception] = None,
        unavailable_names: tuple[str, ...] = (),
    ) -> None:
        """
        Configure optional persistence and rollback failures.
        """
        self.persistence_error = persistence_error
        self.rollback_error = rollback_error
        self.unavailable_names = unavailable_names
        self.requested_names: list[str] = []
        self.created_names: list[str] = []
        self.serialized_definition = ""
        self.deleted_components: list[object] = []
        self.component = object()

    def resolve_harness_name(self, requested_name: str) -> str:
        """
        Resolve and record the requested name against configured conflicts.
        """
        self.requested_names.append(requested_name)
        return next_available_name(requested_name, self.unavailable_names)

    def create_harness_component(self, name: str) -> object:
        """
        Return a stable fake component and record its requested name.
        """
        self.created_names.append(name)
        return self.component

    def write_definition(self, component: object, serialized_definition: str) -> None:
        """
        Record serialized metadata or raise the configured failure.
        """
        assert component is self.component
        if self.persistence_error is not None:
            raise self.persistence_error
        self.serialized_definition = serialized_definition

    def delete_harness_component(self, component: object) -> None:
        """
        Record rollback or raise the configured failure.
        """
        assert component is self.component
        self.deleted_components.append(component)
        if self.rollback_error is not None:
            raise self.rollback_error


def test_creates_and_persists_normalized_empty_harness() -> None:
    """
    Persist the same empty definition returned to the caller.
    """
    gateway = _RecordingGateway()

    definition = create_empty_harness(
        "  Harness_002  ",
        RoutingMode.PROFILE_GATES,
        gateway,
        id_factory=lambda: HARNESS_ID,
    )

    assert gateway.created_names == ["Harness_002"]
    assert gateway.requested_names == ["Harness_002"]
    assert loads(gateway.serialized_definition) == definition
    assert definition.harness_id == HARNESS_ID
    assert definition.routing_mode is RoutingMode.PROFILE_GATES
    assert definition.profiles == ()
    assert definition.connections == ()
    assert definition.controls == ()
    assert definition.wires == ()
    assert gateway.deleted_components == []


def test_increments_conflicting_name_before_serializing_definition() -> None:
    """
    Keep the component name and stored definition name identical after resolution.
    """
    gateway = _RecordingGateway(unavailable_names=("Harness_001", "Harness_002"))

    definition = create_empty_harness(
        "Harness_001",
        RoutingMode.ROUTING_GATES,
        gateway,
        id_factory=lambda: HARNESS_ID,
    )

    assert definition.name == "Harness_003"
    assert gateway.created_names == ["Harness_003"]
    assert loads(gateway.serialized_definition).name == "Harness_003"


def test_suggests_incremented_name_before_harness_creation() -> None:
    """
    Resolve the dialog's initial name without creating a component.
    """
    gateway = _RecordingGateway(unavailable_names=("Harness_001", "Harness_002"))

    suggested_name = suggest_harness_name("Harness_001", gateway)

    assert suggested_name == "Harness_003"
    assert gateway.created_names == []


def test_rejects_empty_name_before_creating_component() -> None:
    """
    Avoid creating host state for a blank harness name.
    """
    gateway = _RecordingGateway()

    with pytest.raises(ValueError, match="must not be empty"):
        create_empty_harness("  ", RoutingMode.ROUTING_GATES, gateway)

    assert gateway.created_names == []


def test_rolls_back_component_when_persistence_fails() -> None:
    """
    Delete a newly created component when its metadata cannot be stored.
    """
    persistence_error = RuntimeError("attribute write failed")
    gateway = _RecordingGateway(persistence_error=persistence_error)

    with pytest.raises(RuntimeError, match="attribute write failed"):
        create_empty_harness("Harness_003", RoutingMode.ROUTING_GATES, gateway)

    assert gateway.deleted_components == [gateway.component]


def test_reports_failed_rollback_without_hiding_persistence_failure() -> None:
    """
    Preserve the persistence failure as the cause when rollback also fails.
    """
    persistence_error = RuntimeError("attribute write failed")
    gateway = _RecordingGateway(
        persistence_error=persistence_error,
        rollback_error=RuntimeError("delete failed"),
    )

    with pytest.raises(HarnessCreationError, match="delete failed") as error_info:
        create_empty_harness("Harness_004", RoutingMode.ROUTING_GATES, gateway)

    assert error_info.value.__cause__ is persistence_error
