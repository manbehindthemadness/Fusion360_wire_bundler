"""
Fusion script-bundle entry point for generated-solid verification.
"""

from __future__ import annotations

import sys
from pathlib import Path

ADDIN_ROOT = Path(__file__).resolve().parents[2]
if str(ADDIN_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDIN_ROOT))

from experiments.experiment_generated_solids import run as run_generated_solids  # noqa: E402


def run(context: object) -> None:
    """
    Delegate execution to the repository-owned generated-solid scenario.
    """
    run_generated_solids(context)
