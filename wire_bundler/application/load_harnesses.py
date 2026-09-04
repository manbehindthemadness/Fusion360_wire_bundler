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

    Args:
        component_name: Current name of the owning Fusion component.
        serialized_definition: JSON stored in the component attribute.
    """

    component_name: str
    serialized_definition: str


@dataclass(frozen=True)
class HarnessLoadResult:
    """
    Report one discovered harness definition or its isolated parse failure.

    Args:
        component_name: Current name of the owning Fusion component.
        definition: Parsed definition when decoding succeeds.
        error: Parse failure text when decoding fails.
        validation_messages: Logical validation findings for a parsed definition.
    """

    component_name: str
    definition: Optional[HarnessDefinition]
    error: Optional[str]
    validation_messages: tuple[str, ...]


class HarnessLibraryGateway(Protocol):
    """
    Describe host access needed to discover persisted harness definitions.
    """

    def list_stored_harnesses(self) -> tuple[StoredHarness, ...]:
        """
        Return every component carrying Wire Bundler definition metadata.
        """


def load_harnesses(gateway: HarnessLibraryGateway) -> tuple[HarnessLoadResult, ...]:
    """
    Decode every stored harness without allowing one damaged entry to hide others.

    Args:
        gateway: Host boundary that enumerates persisted definitions.

    Returns:
        Results sorted case-insensitively by component name.
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
            )
        )

    results.sort(key=lambda result: result.component_name.casefold())
    return tuple(results)
