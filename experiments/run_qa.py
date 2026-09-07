"""
Command-line entry point for the complete development QA procedure.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.qa_orchestrator import main  # noqa: E402, I001


if __name__ == "__main__":
    raise SystemExit(main())
