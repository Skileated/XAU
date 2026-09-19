"""Unit tests for structured logging."""

import concurrent.futures
import tempfile
from pathlib import Path

from xau_quant.common.logging import setup_logger


def test_logger_setup_and_handlers() -> None:
    """Verify logger setup attaches console and rotating file handlers."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_log_dir = Path(temp_dir)
        logger = setup_logger(
            name="test_logger_handlers",
            env="development",
            log_level="DEBUG",
            log_dir=temp_log_dir,
            enable_console=True,
            enable_file=True,
        )

        try:
            assert logger.name == "test_logger_handlers"
            assert len(logger.handlers) == 2

            logger.info("Test event for handler validation")
            log_file = temp_log_dir / "xau_quant.log"
            assert log_file.exists()
            content = log_file.read_text(encoding="utf-8")
            assert "Test event for handler validation" in content
        finally:
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)


def test_logger_thread_safety() -> None:
    """Verify thread-safe logging execution under concurrent threads."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_log_dir = Path(temp_dir)
        logger = setup_logger(
            name="test_logger_threads",
            env="development",
            log_level="INFO",
            log_dir=temp_log_dir,
            enable_console=False,
            enable_file=True,
        )

        try:
            num_messages = 50
            def worker(thread_id: int) -> None:
                for i in range(num_messages):
                    logger.info(f"Thread-{thread_id} message {i}")

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(worker, t) for t in range(5)]
                concurrent.futures.wait(futures)

            log_file = temp_log_dir / "xau_quant.log"
            lines = log_file.read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) == 250  # 5 * 50 messages safely logged
        finally:
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)
