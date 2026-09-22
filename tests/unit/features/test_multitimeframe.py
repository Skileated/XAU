"""Unit tests for multi-timeframe (MTF) alignment and microstructure context."""

from datetime import datetime, timezone

from xau_quant.data.models import CanonicalCandle
from xau_quant.features.calculators.multitimeframe import (
    align_5m_to_htf_open,
    compute_mtf_1m_microstructure,
)


def test_15m_completed_bar_alignment():
    """Verify 5m bar at 14:05 uses completed 15m candle ending at 14:00 (opened 13:45)."""
    t_5m = datetime(2024, 1, 1, 14, 5, tzinfo=timezone.utc)
    # 15m duration is 900s
    aligned_15m = align_5m_to_htf_open(t_5m, 900)
    assert aligned_15m == datetime(2024, 1, 1, 13, 45, tzinfo=timezone.utc)


def test_1h_completed_bar_alignment():
    """Verify 5m bar at 14:05 uses completed 1h candle ending at 14:00 (opened 13:00)."""
    t_5m = datetime(2024, 1, 1, 14, 5, tzinfo=timezone.utc)
    # 1h duration is 3600s
    aligned_1h = align_5m_to_htf_open(t_5m, 3600)
    assert aligned_1h == datetime(2024, 1, 1, 13, 0, tzinfo=timezone.utc)


def test_mtf_sweep_all_day_positions():
    """Verify all 288 intraday 5m positions map strictly to completed HTF candles."""
    t_base = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

    for i in range(288):
        t_5m = datetime.fromtimestamp(t_base.timestamp() + i * 300, tz=timezone.utc)
        close_5m = datetime.fromtimestamp(t_5m.timestamp() + 300, tz=timezone.utc)

        # 15m check
        aligned_15m = align_5m_to_htf_open(t_5m, 900)
        completed_15m = datetime.fromtimestamp(aligned_15m.timestamp() + 900, tz=timezone.utc)
        assert completed_15m <= close_5m, (
            f"Look-ahead at 5m {t_5m}: 15m completed at {completed_15m} > 5m close {close_5m}"
        )

        # 1h check
        aligned_1h = align_5m_to_htf_open(t_5m, 3600)
        completed_1h = datetime.fromtimestamp(aligned_1h.timestamp() + 3600, tz=timezone.utc)
        assert completed_1h <= close_5m, (
            f"Look-ahead at 5m {t_5m}: 1h completed at {completed_1h} > 5m close {close_5m}"
        )


def test_1m_microstructure_flat_neutrality():
    """Flat 1m returns yield return_skew = 0.0 exactly."""
    t0 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    c5 = CanonicalCandle.model_construct(
        timestamp_utc=t0, venue="binance", instrument="BTCUSDT", market_type="spot",
        timeframe="5m", open=100.0, high=100.0, low=100.0, close=100.0,
        volume=50.0, quote_volume=5000.0, trade_count=10,
        taker_buy_base_volume=25.0, taker_buy_quote_volume=2500.0, is_complete=True,
    )

    c1_map = {}
    for step in range(5):
        ts = datetime.fromtimestamp(t0.timestamp() + step * 60, tz=timezone.utc)
        c1_map[ts] = CanonicalCandle.model_construct(
            timestamp_utc=ts, venue="binance", instrument="BTCUSDT", market_type="spot",
            timeframe="1m", open=100.0, high=100.0, low=100.0, close=100.0,
            volume=10.0, quote_volume=1000.0, trade_count=2,
            taker_buy_base_volume=5.0, taker_buy_quote_volume=500.0, is_complete=True,
        )

    res = compute_mtf_1m_microstructure([c5], c1_map)
    assert res["mtf_1m_vol_dispersion"][0] == 0.0
    assert res["mtf_1m_return_skew"][0] == 0.0
