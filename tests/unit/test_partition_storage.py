"""Unit tests for monthly partition storage and discovery."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from xau_quant.data.models import CanonicalCandle
from xau_quant.data.storage import ParquetCandleStorage


def _make_sample_candles(year: int, month: int, count: int = 5) -> list[CanonicalCandle]:
    candles = []
    for i in range(count):
        dt = datetime(year, month, 1, 0, i, tzinfo=timezone.utc)
        candles.append(
            CanonicalCandle(
                timestamp_utc=dt,
                venue="binance",
                instrument="BTCUSDT",
                market_type="spot",
                timeframe="1m",
                open=50000.0 + i,
                high=50010.0 + i,
                low=49990.0 + i,
                close=50005.0 + i,
                volume=10.0 + i,
                quote_volume=500000.0,
                trade_count=100 + i,
                taker_buy_base_volume=5.0,
                taker_buy_quote_volume=250000.0,
                is_complete=True,
            )
        )
    return candles


def test_partition_path_generation() -> None:
    path = ParquetCandleStorage.get_partition_path("BTCUSDT", "1m", 2024, 3)
    posix_str = path.as_posix()
    assert "binance/spot/BTCUSDT/1m/year=2024/month=03" in posix_str
    assert posix_str.endswith("binance_spot_btcusdt_1m_202403.parquet")


def test_save_and_discover_monthly_partitions() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)

        c1 = _make_sample_candles(2024, 1, 10)
        c2 = _make_sample_candles(2024, 2, 10)

        p1_path, rows1, hash1 = ParquetCandleStorage.save_monthly_partition(
            c1, "BTCUSDT", "1m", 2024, 1, base_dir=base_dir
        )
        p2_path, rows2, hash2 = ParquetCandleStorage.save_monthly_partition(
            c2, "BTCUSDT", "1m", 2024, 2, base_dir=base_dir
        )

        assert p1_path.exists()
        assert p2_path.exists()
        assert rows1 == 10
        assert rows2 == 10

        discovered = ParquetCandleStorage.discover_partition_files(
            "BTCUSDT", "1m", base_dir=base_dir
        )
        assert len(discovered) == 2
        assert discovered[0] == p1_path
        assert discovered[1] == p2_path

        # Test cross-partition DuckDB query
        con = duckdb.connect(":memory:")
        glob_path = (
            base_dir / "binance" / "spot" / "BTCUSDT" / "1m" / "year=*" / "month=*" / "*.parquet"
        ).as_posix()
        query_res = con.execute(f"SELECT count(*) FROM read_parquet('{glob_path}')").fetchone()
        assert query_res is not None
        assert query_res[0] == 20
        con.close()
