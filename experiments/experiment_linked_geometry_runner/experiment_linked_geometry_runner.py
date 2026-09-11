"""
Fusion script-bundle entry point for linked-geometry verification.
"""

from __future__ import annotations

import sys
from pathlib import Path

ADDIN_ROOT = Path(__file__).resolve().parents[2]
if str(ADDIN_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDIN_ROOT))

from experiments.experiment_linked_geometry import run as run_linked_geometry  # noqa: E402


def run(context: object) -> None:
    """
    Delegate execution to the repository-owned linked-geometry scenario.
    """
    run_linked_geometry(context)
