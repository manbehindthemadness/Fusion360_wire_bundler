"""
Pure application domain for harness definitions and validation.
"""

from .codec import DefinitionParseError, dumps, loads
from .model import (
    SCHEMA_VERSION,
    Connection,
    ControlKind,
    ControlStructure,
    HarnessDefinition,
    PathwayDefinition,
    RoutingMode,
    WireDefinition,
    WireProfile,
)
from .naming import next_available_name
from .validation import ValidationIssue, validate_harness

__all__ = [
    "SCHEMA_VERSION",
    "Connection",
    "ControlKind",
    "ControlStructure",
    "DefinitionParseError",
    "HarnessDefinition",
    "PathwayDefinition",
    "RoutingMode",
    "ValidationIssue",
    "WireDefinition",
    "WireProfile",
    "dumps",
    "loads",
    "next_available_name",
    "validate_harness",
]
