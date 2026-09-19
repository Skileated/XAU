"""Live network integration test for multi-chunk historical backfill and resampling."""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from xau_quant.data.backfill import BackfillEngine, CheckpointManager
from xau_quant.data.binance import BinanceSpotProvider
from xau_quant.data.resampler import MultiTimeframeResampler


@pytest.mark.network
def test_live_backfill_and_resampling_network() -> None:
    """Test real multi-chunk backfill and resampling against Binance Spot public API."""
    provider = BinanceSpotProvider()
    assert provider.ping() is True

    # Use a recent 15-minute window in the past (e.g. 2 hours ago) to ensure closed candles
    now = datetime.now(timezone.utc)
    start_utc = now - timedelta(hours=3)
    start_utc = start_utc.replace(
        minute=(start_utc.minute // 15) * 15, second=0, microsecond=0
    )
    # 15 minutes = 15 1m candles. With chunk_limit=5, this forces exactly 3 chunks!
    end_utc = start_utc + timedelta(minutes=15)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        cp_dir = tmp_path / "checkpoints"
        cp_mgr = CheckpointManager(checkpoints_dir=cp_dir)

        engine = BackfillEngine(
            provider=provider,
            checkpoint_manager=cp_mgr,
            rate_limit_delay_seconds=0.1,
        )

        result = engine.run(
            symbol="BTCUSDT",
            timeframe="1m",
            start_utc=start_utc,
            end_utc=end_utc,
            chunk_limit=5,  # Forces 3 chunks (5, 5, 5)
            resume=True,
        )

        assert result.checkpoint.status == "completed"
        assert result.checkpoint.chunks_completed == 3
        assert len(result.raw_files) == 3
        assert result.total_records == 15
        assert result.validation_report.is_valid is True

        # Resample to 5m
        candles_5m = MultiTimeframeResampler.resample(result.candles, "5m")
        assert len(candles_5m) == 3
        assert all(c.is_complete for c in candles_5m)

        # Resample to 15m
        candles_15m = MultiTimeframeResampler.resample(result.candles, "15m")
        assert len(candles_15m) == 1
        assert candles_15m[0].is_complete is True
