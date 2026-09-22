"""Unit tests for FeatureEngine, validators, and row validity contracts."""

from datetime import datetime, timezone

from xau_quant.data.models import CanonicalCandle
from xau_quant.features.engine import FeatureEngine
from xau_quant.features.models import FeatureEngineInput


def make_test_candle(
    ts: datetime,
    close: float = 100.0,
    volume: float = 10.0,
    timeframe: str = "5m",
) -> CanonicalCandle:
    return CanonicalCandle.model_construct(
        timestamp_utc=ts,
        venue="binance",
        instrument="BTCUSDT",
        market_type="spot",
        timeframe=timeframe,
        open=close - 0.5,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=volume,
        quote_volume=volume * close,
        trade_count=10,
        taker_buy_base_volume=volume * 0.5,
        taker_buy_quote_volume=volume * close * 0.5,
        is_complete=True,
    )


def test_is_warmup_boundary_and_validity():
    """Verify rows 0..310 have is_warmup=True and is_valid=False; row 311 has is_warmup=False."""
    t0 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    # Generate 320 5m candles
    candles_5m = [
        make_test_candle(
            datetime.fromtimestamp(t0.timestamp() + i * 300, tz=timezone.utc),
            close=100.0 + i * 0.1,
        )
        for i in range(320)
    ]
    # Start context early to ensure all MTF lookbacks are satisfied
    t_start_ctx = datetime.fromtimestamp(t0.timestamp() - 3600 * 50, tz=timezone.utc)
    candles_15m = [
        make_test_candle(
            datetime.fromtimestamp(t_start_ctx.timestamp() + j * 900, tz=timezone.utc),
            timeframe="15m",
        )
        for j in range(500)
    ]
    candles_1h = [
        make_test_candle(
            datetime.fromtimestamp(t_start_ctx.timestamp() + k * 3600, tz=timezone.utc),
            timeframe="1h",
        )
        for k in range(100)
    ]
    candles_1m = [
        make_test_candle(
            datetime.fromtimestamp(t0.timestamp() + m * 60, tz=timezone.utc),
            timeframe="1m",
        )
        for m in range(1600)
    ]

    payload = FeatureEngineInput(
        candles_primary=tuple(candles_5m),
        context_candles={
            "1m": tuple(candles_1m),
            "15m": tuple(candles_15m),
            "1h": tuple(candles_1h),
        },
        venue="binance",
        instrument="BTCUSDT",
    )

    engine = FeatureEngine()
    rows = engine.compute(payload)

    assert len(rows) == 320
    # Rows 0..310: is_warmup = True, is_valid = False
    for i in range(311):
        assert rows[i]["is_warmup"] is True
        assert rows[i]["is_valid"] is False

    # Row 311: is_warmup = False, is_valid = True
    assert rows[311]["is_warmup"] is False
    assert rows[311]["is_valid"] is True


def test_nan_feature_count_excludes_nullable_pivots():
    """Verify non-pivot row has nullable pivot columns as None without incrementing nan count."""
    t0 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    candles_5m = [
        make_test_candle(
            datetime.fromtimestamp(t0.timestamp() + i * 300, tz=timezone.utc),
            close=100.0,
        )
        for i in range(320)
    ]
    t_start_ctx = datetime.fromtimestamp(t0.timestamp() - 3600 * 50, tz=timezone.utc)
    candles_15m = [
        make_test_candle(
            datetime.fromtimestamp(t_start_ctx.timestamp() + j * 900, tz=timezone.utc),
            timeframe="15m",
        )
        for j in range(500)
    ]
    candles_1h = [
        make_test_candle(
            datetime.fromtimestamp(t_start_ctx.timestamp() + k * 3600, tz=timezone.utc),
            timeframe="1h",
        )
        for k in range(100)
    ]
    candles_1m = [
        make_test_candle(
            datetime.fromtimestamp(t0.timestamp() + m * 60, tz=timezone.utc),
            timeframe="1m",
        )
        for m in range(1600)
    ]

    payload = FeatureEngineInput(
        candles_primary=tuple(candles_5m),
        context_candles={
            "1m": tuple(candles_1m),
            "15m": tuple(candles_15m),
            "1h": tuple(candles_1h),
        },
        venue="binance",
        instrument="BTCUSDT",
    )

    engine = FeatureEngine()
    rows = engine.compute(payload)

    row315 = rows[315]
    # For flat series, pivots are False
    assert row315["ms_is_pivot_high_3"] is False
    assert row315["ms_pivot_high_timestamp_3"] is None
    assert row315["ms_pivot_high_age_bars_3"] is None
    # Pivots being None should NOT increment nan_feature_count
    assert row315["nan_feature_count"] == 0
    assert row315["is_valid"] is True


def test_mtf_missing_htf_availability():
    """Verify row index >= 311 with missing HTF context evaluates to is_valid = False."""
    t0 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    candles_5m = [
        make_test_candle(
            datetime.fromtimestamp(t0.timestamp() + i * 300, tz=timezone.utc),
            close=100.0,
        )
        for i in range(320)
    ]
    t_start_ctx = datetime.fromtimestamp(t0.timestamp() - 3600 * 50, tz=timezone.utc)
    # Intentionally provide only 100 15m candles so later 5m bars have missing 15m context
    candles_15m_truncated = [
        make_test_candle(
            datetime.fromtimestamp(t_start_ctx.timestamp() + j * 900, tz=timezone.utc),
            timeframe="15m",
        )
        for j in range(100)
    ]
    candles_1h = [
        make_test_candle(
            datetime.fromtimestamp(t_start_ctx.timestamp() + k * 3600, tz=timezone.utc),
            timeframe="1h",
        )
        for k in range(100)
    ]
    candles_1m = [
        make_test_candle(
            datetime.fromtimestamp(t0.timestamp() + m * 60, tz=timezone.utc),
            timeframe="1m",
        )
        for m in range(1600)
    ]

    payload = FeatureEngineInput(
        candles_primary=tuple(candles_5m),
        context_candles={
            "1m": tuple(candles_1m),
            "15m": tuple(candles_15m_truncated),
            "1h": tuple(candles_1h),
        },
        venue="binance",
        instrument="BTCUSDT",
    )

    engine = FeatureEngine()
    rows = engine.compute(payload)

    row315 = rows[315]
    # Post-warmup threshold is satisfied
    assert row315["is_warmup"] is False
    # But because 15m context is missing, row is INVALID
    assert row315["is_valid"] is False
    assert row315["nan_feature_count"] > 0
