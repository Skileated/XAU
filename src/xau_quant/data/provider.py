"""Abstract base provider interface for market data acquisition."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


class DataProvider(ABC):
    """Abstract interface decoupling data acquisition from specific exchange APIs."""

    @property
    @abstractmethod
    def venue_name(self) -> str:
        """Name of the data venue (e.g. 'binance')."""
        pass

    @abstractmethod
    def ping(self) -> bool:
        """Verify endpoint reachability and service health."""
        pass

    @abstractmethod
    def get_server_time(self) -> int:
        """Retrieve current server time in epoch milliseconds."""
        pass

    @abstractmethod
    def fetch_historical_raw(
        self,
        symbol: str,
        interval: str = "1m",
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        limit: int = 500,
        destination_dir: Optional[Path] = None,
    ) -> Tuple[Path, bytes, Dict[str, Any]]:
        """Acquire raw historical market data and preserve it immutably.

        Returns:
            Tuple of (saved_raw_file_path, raw_bytes, metadata_dict).
        """
        pass
