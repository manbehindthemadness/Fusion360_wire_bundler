"""
Tests for deterministic conflict-free harness names.
"""

from __future__ import annotations

import pytest

from wire_bundler.domain import next_available_name


@pytest.mark.parametrize(
    ("requested_name", "unavailable_names", "expected_name"),
    [
        ("Harness_001", (), "Harness_001"),
        ("Harness_001", ("Harness_001",), "Harness_002"),
        ("Harness_001", ("Harness_001", "Harness_002"), "Harness_003"),
        ("Harness", ("Harness",), "Harness_2"),
        ("Harness_009", ("harness_009", "HARNESS_010"), "Harness_011"),
    ],
)
def test_selects_first_available_incremented_name(
    requested_name: str,
    unavailable_names: tuple[str, ...],
    expected_name: str,
) -> None:
    """
    Preserve numeric width and compare conflicts case-insensitively.
    """
    assert next_available_name(requested_name, unavailable_names) == expected_name


def test_rejects_blank_requested_name() -> None:
    """
    Reject a name with no visible characters.
    """
    with pytest.raises(ValueError, match="must not be empty"):
        next_available_name("  ", ())
