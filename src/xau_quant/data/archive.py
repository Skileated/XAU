"""Binance Vision Historical Bulk Archive Provider.

Acquires official monthly and daily kline zip archives from data.binance.vision,
verifies cryptographic checksums, preserves raw archives and uncompressed CSVs,
and normalizes records into CanonicalCandle format.
"""

import hashlib
import logging
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from xau_quant.common.paths import project_paths
from xau_quant.data.models import CanonicalCandle
from xau_quant.data.provider import DataProvider

logger = logging.getLogger(__name__)


class BinanceVisionArchiveProvider(DataProvider):
    """Acquires and validates official historical bulk archives from data.binance.vision."""

    ARCHIVE_BASE_URL = "https://data.binance.vision/data/spot"

    def __init__(
        self,
        base_url: str = ARCHIVE_BASE_URL,
        timeout_seconds: float = 30.0,
        max_retries: int = 4,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_seconds
        self.max_retries = max_retries
        self._user_agent = "xau-quant-platform/0.1.0"
        self._ssl_ctx = ssl.create_default_context()

    @property
    def venue_name(self) -> str:
        return "binance"

    def _fetch_url_bytes(self, url: str) -> bytes:
        """Fetch raw bytes from URL with exponential retry on transient failures."""
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "*/*",
            },
        )

        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with urllib.request.urlopen(
                    req, context=self._ssl_ctx, timeout=self.timeout
                ) as resp:
                    if resp.status == 200:
                        body = resp.read()
                        return bytes(body)
                    raise RuntimeError(f"HTTP {resp.status} for {url}")
            except urllib.error.HTTPError as exc:
                last_err = exc
                if exc.code == 404:
                    raise FileNotFoundError(f"Archive not found (HTTP 404): {url}") from exc
                logger.warning(
                    f"HTTP error {exc.code} for {url} (attempt {attempt}/{self.max_retries})"
                )
            except Exception as exc:
                last_err = exc
                logger.warning(
                    f"Network error {exc} for {url} (attempt {attempt}/{self.max_retries})"
                )

            if attempt < self.max_retries:
                time.sleep(1.0 * (2 ** (attempt - 1)))

        raise RuntimeError(
            f"Failed to fetch {url} after {self.max_retries} attempts: {last_err}"
        ) from last_err

    def ping(self) -> bool:
        """Verify archive repository reachability."""
        probe_url = f"{self.base_url}/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2023-10.zip.CHECKSUM"
        try:
            content = self._fetch_url_bytes(probe_url).decode("utf-8")
            return len(content.strip().split()) >= 2
        except Exception:
            return False

    def get_server_time(self) -> int:
        """Fallback to current UTC epoch milliseconds."""
        return int(datetime.now(timezone.utc).timestamp() * 1000)

    def fetch_archive_checksum(self, archive_url: str) -> str:
        """Fetch authoritative SHA-256 checksum from .CHECKSUM metadata file."""
        checksum_url = f"{archive_url}.CHECKSUM"
        content = self._fetch_url_bytes(checksum_url).decode("utf-8").strip()
        parts = content.split()
        if not parts:
            raise ValueError(f"Empty checksum response for {checksum_url}")
        return parts[0].strip().lower()

    def download_and_verify_zip(
        self,
        archive_url: str,
        destination_zip: Path,
    ) -> Tuple[Path, str]:
        """Download archive zip, verify SHA-256 against official checksum, and persist."""
        destination_zip.parent.mkdir(parents=True, exist_ok=True)

        expected_hash = self.fetch_archive_checksum(archive_url)
        raw_zip_bytes = self._fetch_url_bytes(archive_url)

        actual_hash = hashlib.sha256(raw_zip_bytes).hexdigest().lower()
        if actual_hash != expected_hash:
            raise ValueError(
                f"Checksum mismatch for {archive_url}!\n"
                f"  Expected: {expected_hash}\n"
                f"  Actual:   {actual_hash}"
            )

        destination_zip.write_bytes(raw_zip_bytes)
        return destination_zip, actual_hash

    @staticmethod
    def extract_csv(zip_path: Path, destination_csv: Path) -> Path:
        """Extract CSV file from zip archive."""
        destination_csv.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as z:
            namelist = z.namelist()
            csv_names = [n for n in namelist if n.endswith(".csv")]
            if not csv_names:
                raise ValueError(f"No CSV file found in archive {zip_path}")
            csv_content = z.read(csv_names[0])
            destination_csv.write_bytes(csv_content)
        return destination_csv

    @classmethod
    def parse_archive_csv(
        cls,
        csv_path: Path,
        symbol: str = "BTCUSDT",
        timeframe: str = "1m",
    ) -> List[CanonicalCandle]:
        """Parse uncompressed Binance archive CSV into CanonicalCandle objects.

        Column mapping:
        0: Open time (ms)
        1: Open price
        2: High price
        3: Low price
        4: Close price
        5: Volume (base)
        6: Close time (ms)
        7: Quote asset volume
        8: Number of trades
        9: Taker buy base volume
        10: Taker buy quote volume
        11: Ignore
        """
        candles: List[CanonicalCandle] = []
        with csv_path.open("r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str or line_str.startswith("open_time"):
                    continue

                parts = line_str.split(",")
                if len(parts) < 11:
                    continue

                open_time_raw = int(parts[0])
                if open_time_raw > 10**17:
                    ts_seconds = open_time_raw / 1_000_000_000.0
                elif open_time_raw > 10**14:
                    ts_seconds = open_time_raw / 1_000_000.0
                elif open_time_raw > 10**11:
                    ts_seconds = open_time_raw / 1_000.0
                else:
                    ts_seconds = float(open_time_raw)
                ts_utc = datetime.fromtimestamp(ts_seconds, tz=timezone.utc)

                candle = CanonicalCandle(
                    timestamp_utc=ts_utc,
                    venue="binance",
                    instrument=symbol.upper(),
                    market_type="spot",
                    timeframe=timeframe,
                    open=float(parts[1]),
                    high=float(parts[2]),
                    low=float(parts[3]),
                    close=float(parts[4]),
                    volume=float(parts[5]),
                    quote_volume=float(parts[7]),
                    trade_count=int(parts[8]),
                    taker_buy_base_volume=float(parts[9]),
                    taker_buy_quote_volume=float(parts[10]),
                    is_complete=True,
                )
                candles.append(candle)

        return sorted(candles, key=lambda c: c.timestamp_utc)

    def fetch_monthly_archive(
        self,
        symbol: str,
        timeframe: str,
        year: int,
        month: int,
        target_raw_dir: Optional[Path] = None,
    ) -> Tuple[Path, Path, str, List[CanonicalCandle]]:
        """Fetch full monthly archive, extract CSV, and parse candles."""
        month_str = f"{month:02d}"
        filename_base = f"{symbol.upper()}-{timeframe}-{year}-{month_str}"
        archive_url = (
            f"{self.base_url}/monthly/klines/{symbol.upper()}/{timeframe}/{filename_base}.zip"
        )

        raw_dir = (
            target_raw_dir
            or project_paths.data_raw
            / "binance"
            / "spot"
            / symbol.upper()
            / timeframe
            / f"{year}-{month_str}"
        )
        zip_path = raw_dir / f"{filename_base}.zip"
        csv_path = raw_dir / f"{filename_base}.csv"

        if not zip_path.exists():
            zip_path, sha256_hash = self.download_and_verify_zip(archive_url, zip_path)
        else:
            sha256_hash = hashlib.sha256(zip_path.read_bytes()).hexdigest()

        if not csv_path.exists():
            self.extract_csv(zip_path, csv_path)

        candles = self.parse_archive_csv(csv_path, symbol=symbol, timeframe=timeframe)
        return zip_path, csv_path, sha256_hash, candles

    def fetch_daily_archive(
        self,
        symbol: str,
        timeframe: str,
        year: int,
        month: int,
        day: int,
        target_raw_dir: Optional[Path] = None,
    ) -> Tuple[Path, Path, str, List[CanonicalCandle]]:
        """Fetch single daily archive, extract CSV, and parse candles."""
        month_str = f"{month:02d}"
        day_str = f"{day:02d}"
        filename_base = f"{symbol.upper()}-{timeframe}-{year}-{month_str}-{day_str}"
        archive_url = (
            f"{self.base_url}/daily/klines/{symbol.upper()}/{timeframe}/{filename_base}.zip"
        )

        raw_dir = (
            target_raw_dir
            or project_paths.data_raw
            / "binance"
            / "spot"
            / symbol.upper()
            / timeframe
            / f"{year}-{month_str}"
        )
        zip_path = raw_dir / f"{filename_base}.zip"
        csv_path = raw_dir / f"{filename_base}.csv"

        if not zip_path.exists():
            zip_path, sha256_hash = self.download_and_verify_zip(archive_url, zip_path)
        else:
            sha256_hash = hashlib.sha256(zip_path.read_bytes()).hexdigest()

        if not csv_path.exists():
            self.extract_csv(zip_path, csv_path)

        candles = self.parse_archive_csv(csv_path, symbol=symbol, timeframe=timeframe)
        return zip_path, csv_path, sha256_hash, candles

    def fetch_historical_raw(
        self,
        symbol: str,
        interval: str = "1m",
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        limit: int = 500,
        destination_dir: Optional[Path] = None,
    ) -> Tuple[Path, bytes, Dict[str, Any]]:
        """Fallback adapter for DataProvider interface compatibility."""
        raise NotImplementedError(
            "Use fetch_monthly_archive or fetch_daily_archive for bulk historical data."
        )
