"""Unit tests for deterministic path resolution."""

from pathlib import Path

import pytest

from xau_quant.common.exceptions import PathResolutionError
from xau_quant.common.paths import ProjectPaths, project_paths


def test_project_paths_defaults() -> None:
    """Verify default project paths are anchored at repository root."""
    root = project_paths.root
    assert root.exists()
    assert (root / "pyproject.toml").exists()
    assert project_paths.configs.exists()
    assert project_paths.src.exists()
    assert project_paths.data.exists()
    assert project_paths.artifacts.exists()
    assert project_paths.logs.exists()


def test_structural_dirs_coverage() -> None:
    """Verify all structural directories are tracked and verifiable."""
    results = project_paths.verify_structure()
    assert isinstance(results, dict)
    assert len(results) >= 20
    # Every structural directory must exist
    missing = [path for path, exists in results.items() if not exists]
    assert not missing, f"Missing structural directories: {missing}"


def test_writability_check() -> None:
    """Verify non-destructive writability check."""
    assert project_paths.check_writability(project_paths.logs_development) is True


def test_invalid_root_override() -> None:
    """Verify PathResolutionError is raised for non-existent root."""
    fake_path = Path("D:/non_existent_directory_for_testing_12345")
    with pytest.raises(PathResolutionError):
        ProjectPaths(root_override=fake_path)
