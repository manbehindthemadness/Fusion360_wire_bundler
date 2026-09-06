"""
Fusion script-bundle entry point for the circular Sweep scenario matrix.
"""

from __future__ import annotations

import sys
from pathlib import Path

ADDIN_ROOT = Path(__file__).resolve().parents[2]
if str(ADDIN_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDIN_ROOT))

from experiments.experiment_sweep_matrix import run as run_sweep_matrix  # noqa: E402


def run(context: object) -> None:
    """
    Delegate execution to the repository-owned Sweep matrix.
    """
    run_sweep_matrix(context)
