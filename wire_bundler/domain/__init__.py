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
    RefineGeometry,
    RoutingMode,
    StripePattern,
    WireAppearanceReference,
    WireColor,
    WireDefinition,
    WireMaterialOverrides,
    WireMaterialSettings,
    WireProfile,
    WireStripe,
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
    "RefineGeometry",
    "RoutingMode",
    "StripePattern",
    "ValidationIssue",
    "WireAppearanceReference",
    "WireDefinition",
    "WireColor",
    "WireMaterialOverrides",
    "WireMaterialSettings",
    "WireProfile",
    "WireStripe",
    "dumps",
    "loads",
    "next_available_name",
    "validate_harness",
]
