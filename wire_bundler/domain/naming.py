"""
Deterministic names for newly created harness definitions.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_TRAILING_NUMBER = re.compile(r"^(.*?)(\d+)$")


def next_available_name(requested_name: str, unavailable_names: Iterable[str]) -> str:
    """
    Return the requested name or its first available incremented form.

    Existing trailing digits retain their width. A conflicting name without a
    numeric suffix receives ``_2`` because the unsuffixed name is the first item.

    Args:
        requested_name: Preferred user-facing name.
        unavailable_names: Names that cannot be reused, compared case-insensitively.

    Returns:
        A non-conflicting name.

    Raises:
        ValueError: If the requested name is blank after trimming.
    """
    normalized_name = requested_name.strip()
    if not normalized_name:
        raise ValueError("Harness name must not be empty.")

    unavailable = {name.casefold() for name in unavailable_names}
    if normalized_name.casefold() not in unavailable:
        return normalized_name

    suffix_match = _TRAILING_NUMBER.fullmatch(normalized_name)
    if suffix_match is None:
        prefix = f"{normalized_name}_"
        number = 2
        width = 1
    else:
        prefix, numeric_suffix = suffix_match.groups()
        number = int(numeric_suffix) + 1
        width = len(numeric_suffix)

    while True:
        candidate = f"{prefix}{number:0{width}d}"
        if candidate.casefold() not in unavailable:
            return candidate
        number += 1
