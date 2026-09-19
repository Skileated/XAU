"""Unit tests for historical backfill engine and checkpoint management."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from xau_quant.data.backfill import (
    BackfillCheckpoint,
    BackfillEngine,
    BackfillInterruptedException,
    CheckpointManager,
    ChunkRecord,
)
from xau_quant.data.provider import DataProvider


class MockDataProvider(DataProvider):
    """Deterministic mock provider for unit testing backfill engine logic."""

    def __init__(self, sample_records_per_chunk: int = 1000) -> None:
        self.sample_records_per_chunk = sample_records_per_chunk
        self.fetch_calls: List[Dict[str, Any]] = []

    @property
    def venue_name(self) -> str:
        return "binance"

    def ping(self) -> bool:
        return True

    def get_server_time(self) -> int:
        return 1789800000000

    def fetch_historical_raw(
        self,
        symbol: str,
        interval: str = "1m",
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        limit: int = 500,
        destination_dir: Optional[Path] = None,
    ) -> Tuple[Path, bytes, Dict[str, Any]]:
        self.fetch_calls.append(
            {
                "symbol": symbol,
                "interval": interval,
                "start_time_ms": start_time_ms,
                "end_time_ms": end_time_ms,
                "limit": limit,
            }
        )

        assert start_time_ms is not None
        assert end_time_ms is not None

        # Generate synthetic klines for deterministic test assertion
        # Each minute = 60,000 ms
        klines = []
        curr_ms = start_time_ms
        count = 0
        while curr_ms <= end_time_ms and count < limit:
            close_ms = curr_ms + 59999
            kline = [
                curr_ms,
                "100.0",
                "105.0",
                "99.0",
                "102.0",
                "10.0",
                close_ms,
                "1020.0",
                50,
                "6.0",
                "612.0",
                "0",
            ]
            klines.append(kline)
            curr_ms += 60000
            count += 1

        payload_bytes = json.dumps(klines).encode("utf-8")
        if destination_dir is None:
            destination_dir = Path("data/raw/test")
        destination_dir.mkdir(parents=True, exist_ok=True)

        target_file = destination_dir / f"test_chunk_{start_time_ms}_{end_time_ms}.json"
        target_file.write_bytes(payload_bytes)

        metadata = {
            "venue": "binance",
            "market_type": "spot",
            "instrument": symbol,
            "timeframe": interval,
            "endpoint": "https://api.binance.com/api/v3/klines",
            "actual_records": len(klines),
            "sha256": "mock_sha256_" + str(start_time_ms),
        }
        return target_file, payload_bytes, metadata


def test_chunk_planning_exact_boundaries() -> None:
    start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    # 2500 minutes = 2 full 1000-candle chunks + 1 500-candle chunk
    end = start + timedelta(minutes=2500)

    chunks = BackfillEngine.plan_chunks(start, end, timeframe="1m", chunk_limit=1000)
    assert len(chunks) == 3

    # Chunk 0
    c0_start_ms, c0_end_ms, c0_start_dt, c0_end_dt = chunks[0]
    assert c0_start_dt == start
    assert c0_end_dt == start + timedelta(minutes=1000)
    # 1000th candle open is at 999m, close is at 999m + 59s999ms
    assert c0_end_ms == c0_start_ms + (1000 * 60000) - 1

    # Chunk 1 starts exactly where chunk 0 finished
    c1_start_ms, c1_end_ms, c1_start_dt, c1_end_dt = chunks[1]
    assert c1_start_dt == c0_end_dt
    assert c1_end_dt == start + timedelta(minutes=2000)

    # Chunk 2 has 500 minutes
    c2_start_ms, c2_end_ms, c2_start_dt, c2_end_dt = chunks[2]
    assert c2_start_dt == c1_end_dt
    assert c2_end_dt == end


def test_chunk_planning_invalid_range() -> None:
    start = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, 9, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="strictly after"):
        BackfillEngine.plan_chunks(start, end)


def test_checkpoint_manager_atomic_save_and_load(tmp_path: Path) -> None:
    mgr = CheckpointManager(checkpoints_dir=tmp_path)
    cp = BackfillCheckpoint(
        checkpoint_id="test_cp_01",
        venue="binance",
        instrument="BTCUSDT",
        market_type="spot",
        timeframe="1m",
        requested_start_utc="2026-09-01T00:00:00+00:00",
        requested_end_utc="2026-09-02T00:00:00+00:00",
        total_chunks_planned=2,
        chunks_completed=1,
        completed_until_utc="2026-09-01T16:40:00+00:00",
        status="in_progress",
        chunks=[
            ChunkRecord(
                chunk_index=0,
                start_time_ms=1000,
                end_time_ms=60000000,
                start_time_utc="2026-09-01T00:00:00+00:00",
                end_time_utc="2026-09-01T16:40:00+00:00",
                records_acquired=1000,
                raw_file_path="mock/path.json",
                raw_file_sha256="abc123",
                completed_at_utc="2026-09-01T16:45:00+00:00",
            )
        ],
    )

    path = mgr.save_checkpoint(cp)
    assert path.exists()
    assert not (tmp_path / "test_cp_01.tmp").exists()

    loaded = mgr.load_checkpoint("test_cp_01")
    assert loaded is not None
    assert loaded.checkpoint_id == "test_cp_01"
    assert loaded.chunks_completed == 1
    assert len(loaded.chunks) == 1
    assert loaded.chunks[0].raw_file_sha256 == "abc123"


def test_checkpoint_manager_corrupt_file(tmp_path: Path) -> None:
    mgr = CheckpointManager(checkpoints_dir=tmp_path)
    target = tmp_path / "corrupt_cp.json"
    target.write_text("NOT_JSON_DATA!!!")

    with pytest.raises(RuntimeError, match="Corrupt checkpoint file"):
        mgr.load_checkpoint("corrupt_cp")


def test_backfill_interruption_and_resume(tmp_path: Path) -> None:
    """Test real interruption after chunk 1 and resumption completing chunk 2."""
    cp_dir = tmp_path / "checkpoints"
    cp_mgr = CheckpointManager(checkpoints_dir=cp_dir)
    mock_provider = MockDataProvider()

    engine = BackfillEngine(
        provider=mock_provider,
        checkpoint_manager=cp_mgr,
        rate_limit_delay_seconds=0.0,
    )

    start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    # 2000 minutes = 2 chunks of 1000
    end = start + timedelta(minutes=2000)

    # 1. Start backfill with intentional interruption after chunk 1
    with pytest.raises(BackfillInterruptedException, match="paused after 1 chunks"):
        engine.run(
            symbol="BTCUSDT",
            timeframe="1m",
            start_utc=start,
            end_utc=end,
            chunk_limit=1000,
            resume=True,
            interrupt_after_chunks=1,
        )

    # Verify provider called only once
    assert len(mock_provider.fetch_calls) == 1
    cp_id = engine.generate_checkpoint_id("binance", "BTCUSDT", "1m", start, end)
    cp = cp_mgr.load_checkpoint(cp_id)
    assert cp is not None
    assert cp.status == "interrupted"
    assert cp.chunks_completed == 1

    # 2. Resume backfill without interruption
    result = engine.run(
        symbol="BTCUSDT",
        timeframe="1m",
        start_utc=start,
        end_utc=end,
        chunk_limit=1000,
        resume=True,
        interrupt_after_chunks=None,
    )

    # Verify provider called exactly twice in total (did not re-fetch chunk 0!)
    assert len(mock_provider.fetch_calls) == 2
    assert result.is_complete is True
    assert result.total_records == 2000
    assert result.checkpoint.status == "completed"
    assert result.checkpoint.chunks_completed == 2
    assert result.validation_report.is_valid is True
    assert len(result.validation_report.gaps) == 0
