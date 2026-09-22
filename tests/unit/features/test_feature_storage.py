"""Unit tests for FeatureParquetStorage."""

from datetime import datetime, timezone
from pathlib import Path

from xau_quant.features.registry import FeatureRegistry
from xau_quant.features.storage import FeatureParquetStorage


def test_feature_parquet_storage_roundtrip(tmp_path: Path):
    registry = FeatureRegistry()
    storage = FeatureParquetStorage(registry=registry, base_dir=tmp_path)

    # Build 5 dummy rows
    t0 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

    rows = []
    for i in range(5):
        ts = datetime.fromtimestamp(t0.timestamp() + i * 300, tz=timezone.utc)
        row = {
            "timestamp_utc": ts,
            "venue": "binance",
            "instrument": "BTCUSDT",
            "timeframe": "5m",
            "is_warmup": i < 311,
            "has_data_gap": False,
            "is_valid": False,
            "nan_feature_count": 0,
            "domain_nan_feature_count": 0,
            "input_dataset_version": "v1.1.0",
            "feature_set_version": "v2.0.0",
            "session_definition_version": "1.0.0",
        }
        for col in registry.get_all_column_specs():
            if col.nullable:
                row[col.name] = None
            elif col.duckdb_type == "DOUBLE":
                row[col.name] = 100.0 + i
            elif col.duckdb_type == "SMALLINT":
                row[col.name] = 1
            elif col.duckdb_type == "BOOLEAN":
                row[col.name] = False
            else:
                row[col.name] = "val"
        rows.append(row)

    out_path, count, sha256 = storage.save_partition(
        rows=rows,
        year=2024,
        month=1,
        venue="binance",
        market_type="spot",
        instrument="BTCUSDT",
        timeframe="5m",
        feature_set_version="v2.0.0",
    )

    assert out_path.exists()
    assert count == 5
    assert len(sha256) == 64

    # Inspect partition
    info = storage.inspect_partition(out_path)
    assert info["row_count"] == 5
    assert "timestamp_utc" in info["columns"]
    assert "ret_log_cc_1" in info["columns"]

    # Discover partitions
    found = storage.discover_partitions(
        venue="binance",
        market_type="spot",
        instrument="BTCUSDT",
        timeframe="5m",
        feature_set_version="v2.0.0",
    )
    assert len(found) == 1
    assert found[0] == out_path
