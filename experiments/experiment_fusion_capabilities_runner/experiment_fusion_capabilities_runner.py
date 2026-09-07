"""
Fusion script-bundle entry point for the automation capability audit.
"""

from __future__ import annotations

import sys
from pathlib import Path

ADDIN_ROOT = Path(__file__).resolve().parents[2]
if str(ADDIN_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDIN_ROOT))

from experiments.experiment_fusion_capabilities import run as run_capability_audit  # noqa: E402


def run(context: object) -> None:
    """
    Delegate execution to the repository-owned Fusion capability audit.

    Args:
        context: Context supplied by Fusion's script host.
    """
    run_capability_audit(context)
