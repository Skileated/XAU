"""Pytest configuration and common fixtures."""

import os
from pathlib import Path
from typing import Generator

import pytest

from xau_quant.common.paths import ProjectPaths


@pytest.fixture
def project_paths_fixture() -> ProjectPaths:
    """Provides standard ProjectPaths instance."""
    return ProjectPaths()


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to test fixtures."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def clean_env() -> Generator[None, None, None]:
    """Preserves environment variables across tests."""
    old_env = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(old_env)
