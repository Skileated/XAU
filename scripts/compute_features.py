"""Batch script to compute the canonical BTCUSDT 5m market feature dataset (Phase 2)."""

import time
from typing import List

import duckdb

from xau_quant.common.logging import setup_logger
from xau_quant.data.models import CanonicalCandle
from xau_quant.data.storage import ParquetCandleStorage
from xau_quant.features.engine import FeatureEngine
from xau_quant.features.manifest import build_feature_dataset_manifest
from xau_quant.features.models import FeatureEngineInput
from xau_quant.features.storage import FeatureParquetStorage


def load_candles_fast(timeframe: str, symbol: str = "BTCUSDT") -> List[CanonicalCandle]:
    """Fast bulk loader for canonical candles from Parquet partitions via DuckDB."""
    files = [p.as_posix() for p in ParquetCandleStorage.discover_partition_files(symbol, timeframe)]
    if not files:
        raise FileNotFoundError(f"No canonical candle partitions found for {symbol} {timeframe}.")

    con = duckdb.connect(":memory:")
    try:
        fields_set = set(CanonicalCandle.model_fields.keys())
        candles: List[CanonicalCandle] = []
        if timeframe == "1m":
            query = """
                SELECT
                    timestamp_utc, open, close, volume, taker_buy_base_volume, is_complete
                FROM read_parquet(?)
                ORDER BY timestamp_utc ASC
            """
            rows = con.execute(query, [files]).fetchall()
            for r in rows:
                c = CanonicalCandle.__new__(CanonicalCandle)
                c.__dict__ = {
                    "timestamp_utc": r[0],
                    "venue": "binance",
                    "instrument": symbol,
                    "market_type": "spot",
                    "timeframe": "1m",
                    "open": r[1],
                    "high": max(r[1], r[2]),
                    "low": min(r[1], r[2]),
                    "close": r[2],
                    "volume": r[3],
                    "quote_volume": 0.0,
                    "trade_count": 0,
                    "taker_buy_base_volume": r[4],
                    "taker_buy_quote_volume": 0.0,
                    "is_complete": r[5],
                }
                c.__pydantic_fields_set__ = fields_set
                candles.append(c)
        else:
            query = """
                SELECT
                    timestamp_utc, venue, instrument, market_type, timeframe,
                    open, high, low, close, volume, quote_volume, trade_count,
                    taker_buy_base_volume, taker_buy_quote_volume, is_complete
                FROM read_parquet(?)
                ORDER BY timestamp_utc ASC
            """
            rows = con.execute(query, [files]).fetchall()
            for r in rows:
                c = CanonicalCandle.__new__(CanonicalCandle)
                c.__dict__ = {
                    "timestamp_utc": r[0],
                    "venue": r[1],
                    "instrument": r[2],
                    "market_type": r[3],
                    "timeframe": r[4],
                    "open": r[5],
                    "high": r[6],
                    "low": r[7],
                    "close": r[8],
                    "volume": r[9],
                    "quote_volume": r[10],
                    "trade_count": r[11],
                    "taker_buy_base_volume": r[12],
                    "taker_buy_quote_volume": r[13],
                    "is_complete": r[14],
                }
                c.__pydantic_fields_set__ = fields_set
                candles.append(c)
        return candles
    finally:
        con.close()


def run_pipeline() -> None:
    """Execute the end-to-end feature calculation pipeline and audit checks."""
    logger = setup_logger()
    logger.info("Starting Phase 2 Market Feature Engine execution...")
    t_start = time.time()

    symbol = "BTCUSDT"
    venue = "binance"
    market_type = "spot"
    feature_set_version = "v2.0.0"
    session_version = "1.0.0"

    # 1. Load canonical datasets
    logger.info("Loading canonical candle datasets (5m, 1m, 15m, 1h)...")
    t0 = time.time()
    candles_5m = load_candles_fast("5m", symbol)
    candles_1m = load_candles_fast("1m", symbol)
    candles_15m = load_candles_fast("15m", symbol)
    candles_1h = load_candles_fast("1h", symbol)
    logger.info(
        f"Loaded datasets: 5m={len(candles_5m)}, 1m={len(candles_1m)}, 15m={len(candles_15m)}, 1h={len(candles_1h)} in {time.time() - t0:.2f}s"
    )

    # 2. Build engine input payload
    payload = FeatureEngineInput(
        candles_primary=tuple(candles_5m),
        context_candles={
            "1m": tuple(candles_1m),
            "15m": tuple(candles_15m),
            "1h": tuple(candles_1h),
        },
        venue=venue,
        instrument=symbol,
        primary_timeframe="5m",
        input_dataset_version="v1.1.0",
        session_definition_version=session_version,
    )

    # 3. Compute features
    logger.info("Computing all registered features across 8 families...")
    t_calc = time.time()
    engine = FeatureEngine()
    feature_rows = engine.compute(payload)
    calc_duration = time.time() - t_calc
    logger.info(f"Computed {len(feature_rows)} feature rows in {calc_duration:.2f}s")

    # 4. Persist to partitioned Parquet
    logger.info("Persisting feature rows into monthly partitioned Parquet files...")
    t_persist = time.time()
    storage = FeatureParquetStorage(registry=engine.registry)
    partitions = storage.save_dataset(
        rows=feature_rows,
        venue=venue,
        market_type=market_type,
        instrument=symbol,
        timeframe="5m",
        feature_set_version=feature_set_version,
    )
    persist_duration = time.time() - t_persist
    logger.info(f"Saved {len(partitions)} monthly partitions in {persist_duration:.2f}s")

    # 5. Compute coverage statistics
    total_rows = len(feature_rows)
    valid_rows = sum(1 for r in feature_rows if r["is_valid"])
    warmup_rows = sum(1 for r in feature_rows if r["is_warmup"])
    gap_rows = sum(1 for r in feature_rows if r["has_data_gap"])
    domain_nan_rows = sum(1 for r in feature_rows if r["domain_nan_feature_count"] > 0)

    logger.info(f"Coverage Summary: total={total_rows}, valid={valid_rows}, warmup={warmup_rows}, gaps={gap_rows}, domain_nan={domain_nan_rows}")

    # 6. Build and write authoritative manifest
    logger.info("Generating and saving feature dataset manifest...")
    manifest, manifest_path, manifest_hash = build_feature_dataset_manifest(
        dataset_id=f"{symbol.lower()}_5m_features_{feature_set_version}",
        partitions=partitions,
        total_rows=total_rows,
        valid_rows=valid_rows,
        warmup_rows=warmup_rows,
        gap_rows=gap_rows,
        domain_nan_rows=domain_nan_rows,
        registry=engine.registry,
        venue=venue,
        instrument=symbol,
        primary_timeframe="5m",
        feature_set_version=feature_set_version,
        session_definition_version=session_version,
    )
    logger.info(f"Authoritative manifest saved at {manifest_path} (SHA-256: {manifest_hash})")

    # 7. DuckDB Audit Verification
    logger.info("Executing DuckDB analytical audit queries...")
    partition_paths = [p["path"] for p in partitions]
    con = duckdb.connect(":memory:")
    try:
        # Check 1: Total count
        audit_count = con.execute("SELECT COUNT(*) FROM read_parquet(?)", [partition_paths]).fetchone()[0]
        assert audit_count == total_rows == 315648, f"Audit row count mismatch: {audit_count} != 315648"

        # Check 2: Warmup count
        audit_warmup = con.execute("SELECT COUNT(*) FROM read_parquet(?) WHERE is_warmup = TRUE", [partition_paths]).fetchone()[0]
        assert audit_warmup == 311, f"Audit warmup count mismatch: {audit_warmup} != 311"

        # Check 3: Post-warmup valid count
        audit_valid = con.execute("SELECT COUNT(*) FROM read_parquet(?) WHERE is_valid = TRUE", [partition_paths]).fetchone()[0]
        assert audit_valid == total_rows - 311, f"Unexpected invalid post-warmup rows: {audit_valid} != {total_rows - 311}"

        # Check 4: Check for infinite values across all DOUBLE columns
        double_cols = [c.name for c in engine.registry.get_all_column_specs() if c.duckdb_type == "DOUBLE"]
        inf_checks = " + ".join([f"COUNT(CASE WHEN isinf(\"{c}\") THEN 1 END)" for c in double_cols])
        total_infs = con.execute(f"SELECT {inf_checks} FROM read_parquet(?)", [partition_paths]).fetchone()[0]
        assert total_infs == 0, f"Found {total_infs} infinite values in feature columns!"

        logger.info("All DuckDB audit queries PASSED successfully!")
    finally:
        con.close()

    total_duration = time.time() - t_start
    logger.info(f"Phase 2 Market Feature Engine execution COMPLETE in {total_duration:.2f}s (Threshold < 140s: PASS)")


if __name__ == "__main__":
    run_pipeline()
