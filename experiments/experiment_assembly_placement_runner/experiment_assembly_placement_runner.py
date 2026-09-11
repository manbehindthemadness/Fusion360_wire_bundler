"""
Fusion script-bundle entry point for Assembly placement verification.
"""

from __future__ import annotations

import sys
from pathlib import Path

ADDIN_ROOT = Path(__file__).resolve().parents[2]
if str(ADDIN_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDIN_ROOT))

from experiments.experiment_assembly_placement import run as run_assembly_placement  # noqa: E402


def run(context: object) -> None:
    """
    Delegate execution to the repository-owned Assembly placement scenario.
    """
    run_assembly_placement(context)
