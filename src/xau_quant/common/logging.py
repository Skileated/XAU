"""Structured logging infrastructure.

Features:
- Thread-safe standard library logging.
- Dual-sink: Console stream handler and Rotating file handler.
- Environment-aware log directory routing (logs/<environment>/xau_quant.log).
- Configurable log levels and message formatting.

Note:
Multi-process safe logging will be explicitly designed and benchmarked in future
phases when worker pipelines and distributed processing are introduced.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from xau_quant.common.paths import project_paths

DEFAULT_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logger(
    name: str = "xau_quant",
    env: str = "development",
    log_level: str = "INFO",
    log_dir: Optional[Path] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
    enable_console: bool = True,
    enable_file: bool = True,
) -> logging.Logger:
    """Configures and returns a thread-safe logger with console and rotating file sinks.

    Args:
        name: Logger name.
        env: Active environment ('development', 'research', 'paper').
        log_level: Minimum logging level ('DEBUG', 'INFO', 'WARNING', 'ERROR').
        log_dir: Directory for log files. Defaults to logs/<env>.
        max_bytes: Max size per rotating log file before rollover.
        backup_count: Number of rotated log archives to retain.
        enable_console: Whether to attach console StreamHandler.
        enable_file: Whether to attach RotatingFileHandler.

    Returns:
        Configured logging.Logger instance.
    """
    logger = logging.getLogger(name)
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(numeric_level)

    # Avoid duplicate handlers if setup_logger is invoked repeatedly
    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter(fmt=DEFAULT_LOG_FORMAT, datefmt=DEFAULT_DATE_FORMAT)

    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if enable_file:
        if log_dir is None:
            if env == "research":
                target_dir = project_paths.logs_research
            elif env == "paper":
                target_dir = project_paths.logs_paper
            else:
                target_dir = project_paths.logs_development
        else:
            target_dir = Path(log_dir)

        target_dir.mkdir(parents=True, exist_ok=True)
        log_file = target_dir / "xau_quant.log"

        file_handler = RotatingFileHandler(
            filename=str(log_file),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger


def get_logger(name: str = "xau_quant") -> logging.Logger:
    """Retrieves an existing logger or initializes a default instance."""
    logger = logging.getLogger(name)
    if not logger.hasHandlers():
        return setup_logger(name=name)
    return logger
