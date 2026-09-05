"""
Fusion script-bundle entry point for the reference harness experiment.
"""

from __future__ import annotations

import sys
from pathlib import Path

ADDIN_ROOT = Path(__file__).resolve().parents[2]
if str(ADDIN_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDIN_ROOT))

from experiments.experiment_reference_harness import run as run_reference_harness  # noqa: E402


def run(context: object) -> None:
    """
    Delegate execution to the repository-owned reference scenario.

    Args:
        context: Context supplied by Fusion's script host.
    """
    run_reference_harness(context)
