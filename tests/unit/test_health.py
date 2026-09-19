"""Unit tests for system health checker diagnostics."""

from rich.console import Console

from xau_quant.cli import SystemHealthChecker


def test_health_checker_individual_checks() -> None:
    """Verify each individual health check returns valid boolean and diagnostic message."""
    checker = SystemHealthChecker(console=Console(quiet=True))

    py_valid, py_msg = checker.check_python_version()
    assert py_valid is True
    assert "Expected: >=3.12, <3.13" in py_msg
    assert "Actual: Python 3.12" in py_msg

    dirs_valid, dirs_msg = checker.check_directory_structure()
    assert dirs_valid is True
    assert "present and verified writable" in dirs_msg

    deps_valid, deps_msg = checker.check_dependencies()
    assert deps_valid is True
    assert "duckdb" in deps_msg
    assert "pydantic" in deps_msg

    cfg_valid, cfg_msg = checker.check_configurations()
    assert cfg_valid is True
    assert "development: OK" in cfg_msg

    log_valid, log_msg = checker.check_logging()
    assert log_valid is True

    git_valid, git_msg = checker.check_git_status()
    assert git_valid is True
    assert "Working tree:" in git_msg


def test_health_checker_run_all() -> None:
    """Verify run_all runs without raising and returns True."""
    checker = SystemHealthChecker(console=Console(quiet=True))
    success = checker.run_all()
    assert success is True
    assert len(checker.results) == 7
