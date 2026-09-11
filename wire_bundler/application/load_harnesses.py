"""
Discover and decode procedural harness definitions from a host repository.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from ..domain import DefinitionParseError, HarnessDefinition, loads, validate_harness


@dataclass(frozen=True)
class StoredHarness:
    """
    Pair a host component name with its serialized harness definition.
    """

    component_name: str
    serialized_definition: str
    component_handle: Optional[object] = None


@dataclass(frozen=True)
class HarnessLoadResult:
    """
    Report one discovered harness definition or its isolated parse failure.
    """

    component_name: str
    definition: Optional[HarnessDefinition]
    error: Optional[str]
    validation_messages: tuple[str, ...]
    component_handle: Optional[object] = None


class HarnessLibraryGateway(Protocol):
    """
    Describe host access needed to discover persisted harness definitions.
    """

    def list_stored_harnesses(self) -> tuple[StoredHarness, ...]:
        """
        Return every component carrying Wire Bundler definition metadata.
        """


class DamagedHarnessGateway(Protocol):
    """
    Describe host access needed to remove one damaged harness component.
    """

    def delete_stored_harness_component(self, component_handle: object) -> None:
        """
        Delete the exact marked component represented by an opaque host handle.
        """


def load_harnesses(gateway: HarnessLibraryGateway) -> tuple[HarnessLoadResult, ...]:
    """
    Decode each stored harness independently and sort results by component name.
    """
    results: list[HarnessLoadResult] = []
    for stored_harness in gateway.list_stored_harnesses():
        try:
            definition = loads(stored_harness.serialized_definition)
        except (DefinitionParseError, TypeError, ValueError) as error:
            results.append(
                HarnessLoadResult(
                    component_name=stored_harness.component_name,
                    definition=None,
                    error=str(error),
                    validation_messages=(),
                    component_handle=stored_harness.component_handle,
                )
            )
            continue

        issues = validate_harness(definition)
        validation_messages = tuple(f"{issue.path}: {issue.message}" for issue in issues)
        results.append(
            HarnessLoadResult(
                component_name=stored_harness.component_name,
                definition=definition,
                error=None,
                validation_messages=validation_messages,
                component_handle=stored_harness.component_handle,
            )
        )

    results.sort(key=lambda result: result.component_name.casefold())
    return tuple(results)


def delete_damaged_harness(
    result: HarnessLoadResult,
    gateway: DamagedHarnessGateway,
) -> None:
    """
    Delete the exact host component belonging to one unreadable harness.

    Raises:
        ValueError: If the result is readable or has no host identity.
    """
    if result.definition is not None or result.error is None:
        raise ValueError("Only a damaged harness can be deleted through this action.")
    if result.component_handle is None:
        raise ValueError("The damaged harness component is no longer available.")
    gateway.delete_stored_harness_component(result.component_handle)
