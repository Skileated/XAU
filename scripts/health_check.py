#!/usr/bin/env python
"""Standalone health check runner for XAUUSD Quantitative Platform.

Can be run via:
    python scripts/health_check.py
"""

import sys
from pathlib import Path

# Ensure src/ is in sys.path when executed directly as a script
project_root = Path(__file__).resolve().parents[1]
src_dir = project_root / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from xau_quant.cli import SystemHealthChecker  # noqa: E402


def main() -> None:
    checker = SystemHealthChecker()
    success = checker.run_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
