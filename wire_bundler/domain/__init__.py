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
    JunctionDefinition,
    JunctionPathwayRelationship,
    PathwayDefinition,
    PathwayEndpoint,
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
    route_control_ids,
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
    "JunctionDefinition",
    "JunctionPathwayRelationship",
    "PathwayDefinition",
    "PathwayEndpoint",
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
    "route_control_ids",
    "validate_harness",
]
