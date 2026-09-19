"""Live integration test for Binance Spot public market data pilot.

NOTE: Explicitly marked with @pytest.mark.network so the default test suite remains
completely deterministic and offline (-m "not network").
"""

import tempfile
from pathlib import Path

import pytest

from xau_quant.data.binance import BinanceSpotProvider
from xau_quant.data.manifest import ProvenanceManifest
from xau_quant.data.normalizer import BinanceKlineNormalizer
from xau_quant.data.storage import ParquetCandleStorage
from xau_quant.data.validator import MarketDataValidator


@pytest.mark.network
def test_live_binance_pilot_end_to_end() -> None:
    """Acquire tiny live sample from Binance, normalize, validate, and verify Parquet via DuckDB."""
    provider = BinanceSpotProvider()
    assert provider.ping() is True

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_dir = tmp_path / "raw"
        processed_dir = tmp_path / "processed"
        meta_dir = tmp_path / "metadata"

        # 1. Acquire 5 genuine live BTCUSDT candles
        raw_file, raw_bytes, meta = provider.fetch_historical_raw(
            symbol="BTCUSDT",
            interval="1m",
            limit=5,
            destination_dir=raw_dir,
        )
        assert raw_file.exists()
        assert len(raw_bytes) > 0
        assert meta["http_status"] == 200
        assert meta["actual_records"] == 5

        # 2. Normalize
        candles = BinanceKlineNormalizer.normalize_payload(
            raw_bytes, instrument="BTCUSDT", timeframe="1m"
        )
        assert len(candles) == 5
        assert candles[0].instrument == "BTCUSDT"

        # 3. Validate
        validator = MarketDataValidator(expected_timeframe="1m")
        report = validator.validate(candles)
        assert report.is_valid is True
        assert report.valid_records_count == 5

        # 4. Store in Parquet
        parquet_file = processed_dir / "test.parquet"
        out_path, row_count, p_hash = ParquetCandleStorage.save_candles_to_parquet(
            candles, destination_path=parquet_file, symbol="BTCUSDT", timeframe="1m"
        )
        assert out_path.exists()
        assert row_count == 5

        # 5. Inspect with DuckDB
        summary = ParquetCandleStorage.inspect_parquet(parquet_file)
        assert summary["total_rows"] == 5
        assert summary["lowest_price"] > 0
        assert summary["highest_price"] >= summary["lowest_price"]

        # 6. Provenance manifest
        manifest = ProvenanceManifest.build(
            dataset_id="test_pilot_dataset",
            venue="binance",
            instrument="BTCUSDT",
            market_type="spot",
            timeframe="1m",
            source_endpoint=meta["endpoint"],
            raw_file_path=raw_file,
            normalized_file_path=parquet_file,
            raw_row_count=5,
            normalized_row_count=5,
            validation_report=report,
        )
        auth_path, auth_hash = manifest.save_authoritative(output_dir=meta_dir)
        assert auth_path.exists()
        assert len(auth_hash) == 64
