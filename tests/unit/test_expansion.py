"""Unit tests for HistoricalExpansionEngine planning and checkpointing."""

import tempfile
from pathlib import Path

from xau_quant.data.expansion import ExpansionCheckpoint, HistoricalExpansionEngine, PartitionRecord


def test_expansion_engine_partition_planning() -> None:
    plans = HistoricalExpansionEngine.plan_partitions(
        start_year=2023, start_month=9, end_year=2026, end_month=9
    )
    # 2023: 4 months (9, 10, 11, 12)
    # 2024: 12 months
    # 2025: 12 months
    # 2026: 9 months (1 to 9)
    # Total = 4 + 12 + 12 + 9 = 37 partitions
    assert len(plans) == 37
    assert plans[0]["partition_id"] == "202309"
    assert plans[0]["mode"] == "daily_range"
    assert plans[0]["days"] == list(range(18, 31))

    assert plans[1]["partition_id"] == "202310"
    assert plans[1]["mode"] == "monthly"

    assert plans[-1]["partition_id"] == "202609"
    assert plans[-1]["mode"] == "daily_and_existing"


def test_expansion_checkpoint_serialization() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = HistoricalExpansionEngine(checkpoints_dir=Path(tmpdir))
        cp = ExpansionCheckpoint(
            checkpoint_id="test_expansion_cp",
            symbol="BTCUSDT",
            venue="binance",
            market_type="spot",
            start_utc="2023-09-18T00:00:00Z",
            end_utc="2026-09-18T00:00:00Z",
            total_partitions_planned=37,
            partitions_completed=["202309"],
            partition_records=[
                PartitionRecord(
                    partition_id="202309",
                    year=2023,
                    month=9,
                    row_count=18720,
                    raw_files_count=13,
                    parquet_path="data/processed/.../202309.parquet",
                    parquet_sha256="abc123",
                    completed_at_utc="2026-09-19T00:00:00Z",
                )
            ],
            status="in_progress",
        )

        saved_path = engine.save_checkpoint(cp)
        assert saved_path.exists()

        loaded = engine.load_checkpoint("test_expansion_cp")
        assert loaded is not None
        assert loaded.checkpoint_id == "test_expansion_cp"
        assert loaded.total_partitions_planned == 37
        assert loaded.partitions_completed == ["202309"]
        assert len(loaded.partition_records) == 1
        assert loaded.partition_records[0].row_count == 18720
