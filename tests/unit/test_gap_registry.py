"""Unit tests for the persistent Gap Registry subsystem."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from xau_quant.data.gap_registry import GapCategory, GapRecord, GapRegistry


def test_gap_record_creation_and_to_dict() -> None:
    dt1 = datetime(2024, 2, 15, 6, 0, tzinfo=timezone.utc)
    dt2 = datetime(2024, 2, 15, 7, 0, tzinfo=timezone.utc)
    record = GapRecord(
        gap_id="gap_btcusdt_1m_20240215_0600",
        instrument="BTCUSDT",
        venue="binance",
        timeframe="1m",
        expected_start_utc=dt1,
        expected_end_utc=dt2,
        actual_missing_start_utc=dt1,
        actual_missing_end_utc=dt2,
        duration_seconds=3600,
        missing_candles_count=60,
        acquisition_source="binance_vision_monthly",
        category=GapCategory.EXCHANGE_MAINTENANCE_CONFIRMED,
        evidence="Maintenance notice #12345",
    )

    d = record.to_dict()
    assert d["gap_id"] == "gap_btcusdt_1m_20240215_0600"
    assert d["category"] == "EXCHANGE_MAINTENANCE_CONFIRMED"
    assert d["missing_candles_count"] == 60


def test_gap_registry_atomic_persistence_and_reload() -> None:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        reg_path = Path(tmp.name)

    try:
        registry = GapRegistry(registry_path=reg_path)
        assert registry.total_gaps == 0

        dt1 = datetime(2024, 2, 15, 6, 0, tzinfo=timezone.utc)
        dt2 = datetime(2024, 2, 15, 7, 0, tzinfo=timezone.utc)
        record = GapRecord(
            gap_id="gap_1",
            instrument="BTCUSDT",
            venue="binance",
            timeframe="1m",
            expected_start_utc=dt1,
            expected_end_utc=dt2,
            actual_missing_start_utc=dt1,
            actual_missing_end_utc=dt2,
            duration_seconds=3600,
            missing_candles_count=60,
            acquisition_source="archive",
            category=GapCategory.PROVIDER_GAP,
            evidence="No records in upstream file",
        )

        registry.register_gap(record)
        assert registry.total_gaps == 1
        assert registry.total_missing_candles == 60

        # Reload from disk
        reloaded = GapRegistry(registry_path=reg_path)
        assert reloaded.total_gaps == 1
        gap_loaded = reloaded.get_gap("gap_1")
        assert gap_loaded is not None
        assert gap_loaded.category == GapCategory.PROVIDER_GAP
        assert gap_loaded.missing_candles_count == 60

        summary = reloaded.to_summary_dict()
        assert summary["total_gaps_count"] == 1
        assert summary["by_category"]["PROVIDER_GAP"] == 1
    finally:
        if reg_path.exists():
            reg_path.unlink()
