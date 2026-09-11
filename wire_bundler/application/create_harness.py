"""
Create and persist an empty harness definition as one transaction.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol
from uuid import UUID, uuid4

from ..domain import SCHEMA_VERSION, HarnessDefinition, RoutingMode, dumps


class HarnessGateway(Protocol):
    """
    Describe the host operations needed to create a harness component.
    """

    def resolve_harness_name(self, requested_name: str) -> str:
        """
        Return an available host name for the new harness.
        """

    def create_harness_component(self, name: str) -> object:
        """
        Create and return an empty child component handle.
        """

    def write_definition(self, component: object, serialized_definition: str) -> None:
        """
        Persist a serialized definition on a child component.
        """

    def delete_harness_component(self, component: object) -> None:
        """
        Delete a child component created by this transaction.
        """


class HarnessCreationError(RuntimeError):
    """
    Report a harness creation failure that could not be rolled back cleanly.
    """


def suggest_harness_name(name: str, gateway: HarnessGateway) -> str:
    """
    Normalize a requested name and resolve it against the active host context.

    Raises:
        ValueError: If the requested or resolved name is empty.
    """
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Harness name must not be empty.")

    resolved_name = gateway.resolve_harness_name(normalized_name).strip()
    if not resolved_name:
        raise ValueError("Harness gateway returned an empty resolved name.")
    return resolved_name


def create_empty_harness(
    name: str,
    routing_mode: RoutingMode,
    gateway: HarnessGateway,
    id_factory: Callable[[], UUID] = uuid4,
) -> HarnessDefinition:
    """
    Create an empty draft definition and persist it on a new host component.

    The empty definition is intentionally a draft and is not generation-valid until
    connections, profiles, controls, and wires are added. If metadata persistence
    fails after component creation, the component is deleted before the original
    error is re-raised.

    Raises:
        ValueError: If the normalized harness name is empty.
        HarnessCreationError: If persistence and rollback both fail.
    """
    resolved_name = suggest_harness_name(name, gateway)

    definition = HarnessDefinition(
        schema_version=SCHEMA_VERSION,
        harness_id=id_factory(),
        name=resolved_name,
        routing_mode=routing_mode,
        profiles=(),
        connections=(),
        controls=(),
        pathways=(),
        wires=(),
    )
    serialized_definition = dumps(definition)
    component = gateway.create_harness_component(resolved_name)

    try:
        gateway.write_definition(component, serialized_definition)
    except Exception as persistence_error:
        try:
            gateway.delete_harness_component(component)
        except Exception as rollback_error:
            message = (
                "Failed to persist the harness definition and could not delete "
                f"the incomplete component: {rollback_error}"
            )
            raise HarnessCreationError(message) from persistence_error
        raise

    return definition
