"""Integration tests for CLI and scripts execution."""

import subprocess
import sys

from xau_quant.common.paths import project_paths


def test_cli_health_command_subprocess() -> None:
    """Run CLI health command in a subprocess and verify exit code 0."""
    result = subprocess.run(
        [sys.executable, "-m", "xau_quant.cli", "health"],
        cwd=str(project_paths.root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "ALL HEALTH CHECKS PASSED" in result.stdout or "Health Check" in result.stdout


def test_standalone_health_script_subprocess() -> None:
    """Run standalone scripts/health_check.py in a subprocess and verify exit code 0."""
    script_path = project_paths.scripts / "health_check.py"
    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(project_paths.root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "ALL HEALTH CHECKS PASSED" in result.stdout or "Health Check" in result.stdout
