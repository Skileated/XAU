"""Common utilities, deterministic paths, and logging infrastructure."""

from xau_quant.common.exceptions import (
    ConfigurationError,
    EnvironmentIntegrityError,
    LoggingError,
    PathResolutionError,
    XAUQuantError,
)
from xau_quant.common.logging import get_logger, setup_logger
from xau_quant.common.paths import ProjectPaths, project_paths

__all__ = [
    "XAUQuantError",
    "ConfigurationError",
    "EnvironmentIntegrityError",
    "PathResolutionError",
    "LoggingError",
    "ProjectPaths",
    "project_paths",
    "setup_logger",
    "get_logger",
]
