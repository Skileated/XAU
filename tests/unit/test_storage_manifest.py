"""Unit tests for ParquetCandleStorage and ProvenanceManifest."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from xau_quant.data.manifest import ProvenanceManifest
from xau_quant.data.models import CanonicalCandle
from xau_quant.data.storage import ParquetCandleStorage
from xau_quant.data.validator import ValidationReport


def _make_sample_candle(i: int) -> CanonicalCandle:
    """Make sample candle in memory for testing storage/manifest mechanics."""
    return CanonicalCandle(
        timestamp_utc=datetime(2026, 1, 1, 0, i, 0, tzinfo=timezone.utc),
        venue="binance",
        instrument="BTCUSDT",
        market_type="spot",
        timeframe="1m",
        open=100.0 + i,
        high=105.0 + i,
        low=95.0 + i,
        close=102.0 + i,
        volume=1.0,
        quote_volume=100.0,
        trade_count=10,
        taker_buy_base_volume=0.5,
        taker_buy_quote_volume=50.0,
        is_complete=True,
    )


def test_parquet_storage_roundtrip() -> None:
    """Verify writing candles to Parquet and reading back with DuckDB inspection."""
    candles = [_make_sample_candle(0), _make_sample_candle(1), _make_sample_candle(2)]

    with tempfile.TemporaryDirectory() as tmp_dir:
        dest_file = Path(tmp_dir) / "test.parquet"
        out_path, count, sha = ParquetCandleStorage.save_candles_to_parquet(
            candles, destination_path=dest_file
        )

        assert out_path == dest_file
        assert count == 3
        assert len(sha) == 64

        # Inspect
        summary = ParquetCandleStorage.inspect_parquet(dest_file)
        assert summary["total_rows"] == 3
        assert summary["lowest_price"] == 95.0
        assert summary["highest_price"] == 107.0

        # Load back
        loaded = ParquetCandleStorage.load_candles_from_parquet(dest_file)
        assert len(loaded) == 3
        assert loaded[0].open == 100.0
        assert loaded[2].open == 102.0


def test_provenance_manifest_build_and_save() -> None:
    """Verify manifest creation, saving authoritative copy, and creating research artifact copy."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_file = tmp_path / "raw.json"
        raw_file.write_text("{}", encoding="utf-8")

        norm_file = tmp_path / "norm.parquet"
        norm_file.write_text("parquet_mock_content", encoding="utf-8")

        val_report = ValidationReport(
            is_valid=True,
            total_records=1,
            valid_records_count=1,
            invalid_records_count=0,
            issues=[],
            gaps=[],
        )

        manifest = ProvenanceManifest.build(
            dataset_id="test_dataset_123",
            venue="binance",
            instrument="BTCUSDT",
            market_type="spot",
            timeframe="1m",
            source_endpoint="https://api.binance.com/api/v3/klines",
            raw_file_path=raw_file,
            normalized_file_path=norm_file,
            raw_row_count=1,
            normalized_row_count=1,
            validation_report=val_report,
        )

        # Save authoritative
        auth_dir = tmp_path / "metadata"
        auth_path, auth_hash = manifest.save_authoritative(output_dir=auth_dir)
        assert auth_path.exists()
        assert len(auth_hash) == 64

        # Create research artifact copy
        artifact_dir = tmp_path / "artifacts"
        copy_path, copy_hash = ProvenanceManifest.create_artifact_copy(
            auth_path, artifact_dir=artifact_dir
        )
        assert copy_path.exists()
        assert copy_hash == auth_hash
