"""
Load searchable wire-material suggestions bundled with the add-in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..domain import StripePattern, WireColor

CATALOG_FILE = (
    Path(__file__).resolve().parents[2] / "resources" / "catalogs" / "wire_materials.json"
)


@dataclass(frozen=True)
class WireMaterialCatalog:
    """
    Provide optional autocomplete values without restricting custom specifications.
    """

    insulation_materials: tuple[str, ...]
    conductor_materials: tuple[str, ...]
    colors: tuple[WireColor, ...]
    stripe_patterns: tuple[StripePattern, ...]


@lru_cache(maxsize=1)
def load_wire_material_catalog() -> WireMaterialCatalog:
    """
    Read and validate the bundled material catalog on first UI use.
    """
    raw = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Wire material catalog must contain one JSON object.")
    insulation = _text_values(raw.get("insulation_materials"), "insulation_materials")
    conductors = _text_values(raw.get("conductor_materials"), "conductor_materials")
    raw_colors = raw.get("colors")
    if not isinstance(raw_colors, list):
        raise ValueError("Wire material catalog colors must be a list.")
    colors: list[WireColor] = []
    for index, value in enumerate(raw_colors):
        if not isinstance(value, dict):
            raise ValueError(f"Wire material catalog color {index} must be an object.")
        try:
            colors.append(
                WireColor(
                    name=value["name"],
                    red=value["red"],
                    green=value["green"],
                    blue=value["blue"],
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Wire material catalog color {index} is invalid: {error}") from error
    raw_patterns = _text_values(raw.get("stripe_patterns"), "stripe_patterns")
    try:
        patterns = tuple(StripePattern(value) for value in raw_patterns)
    except ValueError as error:
        raise ValueError(f"Wire material catalog has an unknown stripe pattern: {error}") from error
    return WireMaterialCatalog(insulation, conductors, tuple(colors), patterns)


def _text_values(raw_value: object, field: str) -> tuple[str, ...]:
    """
    Require an ordered nonempty list of nonempty catalog labels.
    """
    if not isinstance(raw_value, list) or not raw_value:
        raise ValueError(f"Wire material catalog {field} must be a nonempty list.")
    if not all(isinstance(value, str) and value.strip() for value in raw_value):
        raise ValueError(f"Wire material catalog {field} must contain nonempty strings.")
    return tuple(raw_value)
