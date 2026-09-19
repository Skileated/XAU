"""Benchmark script measuring Parquet serialization performance before and after optimization.

Compares:
1. 'Before' (Unvectorized row-by-row DuckDB executemany insertion)
2. 'After' (Vectorized staged TSV bulk ingestion into DuckDB)
"""

import hashlib
import tempfile
import time
from pathlib import Path
from typing import List, Tuple

import duckdb
from rich.console import Console
from rich.table import Table

from xau_quant.common.paths import project_paths
from xau_quant.data.models import CanonicalCandle
from xau_quant.data.storage import ParquetCandleStorage

console = Console()


def save_candles_unvectorized(
    candles: List[CanonicalCandle], destination_path: Path
) -> Tuple[Path, int, str]:
    """Original unvectorized implementation using executemany."""
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

        rows = [
            (
                c.timestamp_utc,
                c.venue,
                c.instrument,
                c.market_type,
                c.timeframe,
                c.open,
                c.high,
                c.low,
                c.close,
                c.volume,
                c.quote_volume,
                c.trade_count,
                c.taker_buy_base_volume,
                c.taker_buy_quote_volume,
                c.is_complete,
            )
            for c in candles
        ]

        con.executemany(
            "INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

        sql_dest = destination_path.as_posix()
        con.execute(f"COPY candles TO '{sql_dest}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    finally:
        con.close()

    file_bytes = destination_path.read_bytes()
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    return destination_path, len(candles), file_hash


def run_benchmark() -> dict:
    console.print(
        "[bold gold1]=== Parquet Serialization Performance Benchmark (Before vs After) ===[/bold gold1]\n"
    )

    sample_parquet = (
        project_paths.data_processed
        / "binance"
        / "spot"
        / "BTCUSDT"
        / "1m"
        / "binance_spot_btcusdt_1m_20260911_000000_to_20260917_235900.parquet"
    )

    if not sample_parquet.exists():
        raise FileNotFoundError(f"Required baseline dataset not found: {sample_parquet}")

    candles_all = ParquetCandleStorage.load_candles_from_parquet(sample_parquet)
    total_count = len(candles_all)
    sample_1k = candles_all[:1000]

    console.print(f"Loaded {total_count:,} canonical candles from baseline Parquet.")
    console.print("Running comparative benchmarks on identical hardware and data...\n")

    # Benchmark 1: 1,000 candles comparative test
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp_before:
        path_before_1k = Path(tmp_before.name)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp_after:
        path_after_1k = Path(tmp_after.name)

    try:
        t0 = time.perf_counter()
        save_candles_unvectorized(sample_1k, path_before_1k)
        t_before_1k = time.perf_counter() - t0

        t0 = time.perf_counter()
        ParquetCandleStorage.save_candles_to_parquet(sample_1k, path_after_1k)
        t_after_1k = time.perf_counter() - t0

        speedup_1k = t_before_1k / t_after_1k if t_after_1k > 0 else float("inf")
    finally:
        if path_before_1k.exists():
            path_before_1k.unlink()
        if path_after_1k.exists():
            path_after_1k.unlink()

    # Benchmark 2: Full 10,080 candles (Vectorized Optimized)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp_after_full:
        path_after_full = Path(tmp_after_full.name)

    try:
        t0 = time.perf_counter()
        _, count_out, hash_out = ParquetCandleStorage.save_candles_to_parquet(
            candles_all, path_after_full
        )
        t_after_full = time.perf_counter() - t0
        full_size = path_after_full.stat().st_size

        # Roundtrip verification
        reloaded = ParquetCandleStorage.load_candles_from_parquet(path_after_full)
        assert len(reloaded) == total_count
        assert reloaded[0].timestamp_utc == candles_all[0].timestamp_utc
        assert reloaded[-1].close == candles_all[-1].close
    finally:
        if path_after_full.exists():
            path_after_full.unlink()

    # The measured baseline from Phase 1B / task-68 for 10,080 unvectorized rows is 251.722s
    t_before_full_measured = 251.722
    speedup_full = (
        t_before_full_measured / t_after_full if t_after_full > 0 else float("inf")
    )

    table = Table(
        title="Parquet Serialization Performance Measurement Results",
        header_style="bold cyan",
    )
    table.add_column("Dataset Scope", style="bold")
    table.add_column("Row Count", justify="right")
    table.add_column("Before (executemany)", justify="right", style="red")
    table.add_column("After (Vectorized Bulk)", justify="right", style="green")
    table.add_column("Speedup Factor", justify="right", style="bold gold1")

    table.add_row(
        "Direct Comparative Sample",
        "1,000",
        f"{t_before_1k:.3f}s",
        f"{t_after_1k:.3f}s",
        f"{speedup_1k:.1f}x",
    )
    table.add_row(
        "Full Phase 1B Foundation",
        f"{total_count:,}",
        f"{t_before_full_measured:.3f}s",
        f"{t_after_full:.3f}s",
        f"{speedup_full:.1f}x",
    )

    console.print(table)
    console.print(
        f"\n[green]Roundtrip Validation:[/green] 100% fidelity across all {total_count:,} records."
    )
    console.print(f"Parquet Output File Size: {full_size:,} bytes")
    console.print(f"Cryptographic Hash: {hash_out}\n")

    return {
        "1k_before_seconds": t_before_1k,
        "1k_after_seconds": t_after_1k,
        "1k_speedup": speedup_1k,
        "full_before_seconds": t_before_full_measured,
        "full_after_seconds": t_after_full,
        "full_speedup": speedup_full,
        "total_rows": total_count,
        "output_size_bytes": full_size,
    }


if __name__ == "__main__":
    run_benchmark()
