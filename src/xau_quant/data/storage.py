"""Parquet storage and DuckDB analytical querying for canonical market data."""

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb

from xau_quant.common.paths import project_paths
from xau_quant.data.models import CanonicalCandle


class ParquetCandleStorage:
    """Manages Parquet storage and DuckDB analytical inspection of canonical candles."""

    @staticmethod
    def save_candles_to_parquet(
        candles: List[CanonicalCandle],
        destination_path: Optional[Path] = None,
        symbol: str = "BTCUSDT",
        timeframe: str = "1m",
    ) -> Tuple[Path, int, str]:
        """Save a list of CanonicalCandle instances to a compressed Parquet file.

        Returns:
            Tuple of (output_file_path, row_count, sha256_hash).
        """
        if not candles:
            raise ValueError("Cannot write empty candle list to Parquet.")

        if destination_path is None:
            first_ts = candles[0].timestamp_utc.strftime("%Y%m%d_%H%M%S")
            last_ts = candles[-1].timestamp_utc.strftime("%Y%m%d_%H%M%S")
            filename = f"binance_spot_{symbol.lower()}_{timeframe}_{first_ts}_to_{last_ts}.parquet"
            target_dir = (
                project_paths.data_processed / "binance" / "spot" / symbol.upper() / timeframe
            )
            target_dir.mkdir(parents=True, exist_ok=True)
            destination_path = target_dir / filename
        else:
            destination_path.parent.mkdir(parents=True, exist_ok=True)

        # Fast vectorized bulk ingestion via staged TSV buffer
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".tsv", delete=False, encoding="utf-8"
        ) as tsv_file:
            tsv_path = Path(tsv_file.name)
            for c in candles:
                is_comp_str = "true" if c.is_complete else "false"
                tsv_file.write(
                    f"{c.timestamp_utc.isoformat()}\t{c.venue}\t{c.instrument}\t{c.market_type}\t"
                    f"{c.timeframe}\t{c.open}\t{c.high}\t{c.low}\t{c.close}\t{c.volume}\t"
                    f"{c.quote_volume}\t{c.trade_count}\t{c.taker_buy_base_volume}\t"
                    f"{c.taker_buy_quote_volume}\t{is_comp_str}\n"
                )

        con = duckdb.connect(":memory:")
        try:
            con.execute(
                """
                CREATE TABLE candles (
                    timestamp_utc TIMESTAMP WITH TIME ZONE,
                    venue VARCHAR,
                    instrument VARCHAR,
                    market_type VARCHAR,
                    timeframe VARCHAR,
                    open DOUBLE,
                    high DOUBLE,
                    low DOUBLE,
                    close DOUBLE,
                    volume DOUBLE,
                    quote_volume DOUBLE,
                    trade_count BIGINT,
                    taker_buy_base_volume DOUBLE,
                    taker_buy_quote_volume DOUBLE,
                    is_complete BOOLEAN
                )
                """
            )

            sql_tsv = tsv_path.as_posix()
            con.execute(f"COPY candles FROM '{sql_tsv}' (DELIMITER '\t', HEADER FALSE)")

            # Normalize path for DuckDB SQL
            sql_dest = destination_path.as_posix()
            con.execute(f"COPY candles TO '{sql_dest}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        finally:
            con.close()
            if tsv_path.exists():
                tsv_path.unlink()

        file_bytes = destination_path.read_bytes()
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        return destination_path, len(candles), file_hash

    @staticmethod
    def get_partition_path(
        symbol: str,
        timeframe: str,
        year: int,
        month: int,
        base_dir: Optional[Path] = None,
    ) -> Path:
        """Get canonical monthly partition path:
        data/processed/binance/spot/{SYMBOL}/{TIMEFRAME}/year={YYYY}/month={MM}/binance_spot_{symbol}_{timeframe}_{YYYYMM}.parquet
        """
        root = base_dir or project_paths.data_processed
        month_str = f"{month:02d}"
        target_dir = (
            root
            / "binance"
            / "spot"
            / symbol.upper()
            / timeframe
            / f"year={year}"
            / f"month={month_str}"
        )
        filename = f"binance_spot_{symbol.lower()}_{timeframe}_{year}{month_str}.parquet"
        return target_dir / filename

    @classmethod
    def save_monthly_partition(
        cls,
        candles: List[CanonicalCandle],
        symbol: str,
        timeframe: str,
        year: int,
        month: int,
        base_dir: Optional[Path] = None,
    ) -> Tuple[Path, int, str]:
        """Save a batch of candles directly into its canonical monthly partition file."""
        dest_path = cls.get_partition_path(symbol, timeframe, year, month, base_dir=base_dir)
        return cls.save_candles_to_parquet(
            candles=candles,
            destination_path=dest_path,
            symbol=symbol,
            timeframe=timeframe,
        )

    @classmethod
    def discover_partition_files(
        cls,
        symbol: str,
        timeframe: str,
        base_dir: Optional[Path] = None,
    ) -> List[Path]:
        """Discover all monthly partition parquet files sorted chronologically."""
        root = base_dir or project_paths.data_processed
        tf_dir = root / "binance" / "spot" / symbol.upper() / timeframe
        if not tf_dir.exists():
            return []
        files = sorted(tf_dir.glob("year=*/month=*/*.parquet"))
        return files

    @staticmethod
    def inspect_parquet(parquet_path: Path) -> Dict[str, Any]:
        """Execute analytical summary queries against a Parquet dataset via DuckDB."""
        if not parquet_path.exists():
            raise FileNotFoundError(f"Parquet file not found: {parquet_path}")

        sql_path = parquet_path.as_posix()
        con = duckdb.connect(":memory:")
        try:
            query = f"""
                SELECT
                    count(*) as total_rows,
                    min(timestamp_utc) as min_timestamp,
                    max(timestamp_utc) as max_timestamp,
                    min(low) as lowest_price,
                    max(high) as highest_price,
                    sum(volume) as total_base_volume,
                    sum(quote_volume) as total_quote_volume,
                    sum(trade_count) as total_trades
                FROM read_parquet('{sql_path}')
            """
            result = con.execute(query).fetchone()

            if result is None:
                raise RuntimeError("Failed to retrieve metrics from Parquet file.")

            return {
                "file_path": str(parquet_path),
                "total_rows": result[0],
                "min_timestamp_utc": str(result[1]),
                "max_timestamp_utc": str(result[2]),
                "lowest_price": result[3],
                "highest_price": result[4],
                "total_base_volume": result[5],
                "total_quote_volume": result[6],
                "total_trades": result[7],
            }
        finally:
            con.close()

    @staticmethod
    def load_candles_from_parquet(parquet_path: Path) -> List[CanonicalCandle]:
        """Read Parquet dataset back into CanonicalCandle objects."""
        if not parquet_path.exists():
            raise FileNotFoundError(f"Parquet file not found: {parquet_path}")

        sql_path = parquet_path.as_posix()
        con = duckdb.connect(":memory:")
        try:
            query = f"SELECT * FROM read_parquet('{sql_path}') ORDER BY timestamp_utc ASC"
            rows = con.execute(query).fetchall()
            candles: List[CanonicalCandle] = []
            for r in rows:
                candles.append(
                    CanonicalCandle(
                        timestamp_utc=r[0],
                        venue=r[1],
                        instrument=r[2],
                        market_type=r[3],
                        timeframe=r[4],
                        open=r[5],
                        high=r[6],
                        low=r[7],
                        close=r[8],
                        volume=r[9],
                        quote_volume=r[10],
                        trade_count=r[11],
                        taker_buy_base_volume=r[12],
                        taker_buy_quote_volume=r[13],
                        is_complete=r[14],
                    )
                )
            return candles
        finally:
            con.close()
