"""Unit tests for MultiTimeframeResampler and completeness engine."""

from datetime import datetime, timedelta, timezone

from xau_quant.data.models import CanonicalCandle
from xau_quant.data.resampler import MultiTimeframeResampler


def make_candle(
    dt: datetime,
    open_p: float = 100.0,
    high_p: float = 105.0,
    low_p: float = 95.0,
    close_p: float = 102.0,
    vol: float = 10.0,
    qvol: float = 1000.0,
    trades: int = 20,
    taker_base: float = 4.0,
    taker_quote: float = 400.0,
    is_complete: bool = True,
    timeframe: str = "1m",
) -> CanonicalCandle:
    return CanonicalCandle(
        timestamp_utc=dt,
        venue="binance",
        instrument="BTCUSDT",
        market_type="spot",
        timeframe=timeframe,
        open=open_p,
        high=high_p,
        low=low_p,
        close=close_p,
        volume=vol,
        quote_volume=qvol,
        trade_count=trades,
        taker_buy_base_volume=taker_base,
        taker_buy_quote_volume=taker_quote,
        is_complete=is_complete,
    )


def test_floor_timestamp_boundaries() -> None:
    dt = datetime(2026, 9, 19, 14, 27, 43, tzinfo=timezone.utc)

    # 5m: 14:25:00
    b_5m = MultiTimeframeResampler.floor_timestamp_to_bucket(dt, "5m")
    assert b_5m == datetime(2026, 9, 19, 14, 25, 0, tzinfo=timezone.utc)

    # 15m: 14:15:00
    b_15m = MultiTimeframeResampler.floor_timestamp_to_bucket(dt, "15m")
    assert b_15m == datetime(2026, 9, 19, 14, 15, 0, tzinfo=timezone.utc)

    # 1h: 14:00:00
    b_1h = MultiTimeframeResampler.floor_timestamp_to_bucket(dt, "1h")
    assert b_1h == datetime(2026, 9, 19, 14, 0, 0, tzinfo=timezone.utc)

    # 4h: 12:00:00
    b_4h = MultiTimeframeResampler.floor_timestamp_to_bucket(dt, "4h")
    assert b_4h == datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)

    # 1d: 00:00:00
    b_1d = MultiTimeframeResampler.floor_timestamp_to_bucket(dt, "1d")
    assert b_1d == datetime(2026, 9, 19, 0, 0, 0, tzinfo=timezone.utc)


def test_5m_resampling_aggregation_math() -> None:
    start = datetime(2026, 9, 19, 10, 0, 0, tzinfo=timezone.utc)
    # Generate 5 consecutive 1m candles
    c0 = make_candle(
        start + timedelta(minutes=0),
        open_p=100.0, high_p=102.0, low_p=99.0, close_p=101.0, vol=10.0, trades=5
    )
    c1 = make_candle(
        start + timedelta(minutes=1),
        open_p=101.0, high_p=106.0, low_p=100.0, close_p=104.0, vol=15.0, trades=8
    )
    c2 = make_candle(
        start + timedelta(minutes=2),
        open_p=104.0, high_p=105.0, low_p=94.0, close_p=96.0, vol=20.0, trades=12
    )
    c3 = make_candle(
        start + timedelta(minutes=3),
        open_p=96.0, high_p=98.0, low_p=95.0, close_p=97.0, vol=5.0, trades=3
    )
    c4 = make_candle(
        start + timedelta(minutes=4),
        open_p=97.0, high_p=103.0, low_p=96.0, close_p=102.5, vol=25.0, trades=15
    )

    candles_1m = [c0, c1, c2, c3, c4]
    result_5m = MultiTimeframeResampler.resample(candles_1m, "5m")

    assert len(result_5m) == 1
    candle_5m = result_5m[0]

    assert candle_5m.timestamp_utc == start
    assert candle_5m.timeframe == "5m"
    assert candle_5m.open == 100.0  # c0 open
    assert candle_5m.high == 106.0  # c1 max high
    assert candle_5m.low == 94.0    # c2 min low
    assert candle_5m.close == 102.5 # c4 close
    assert candle_5m.volume == 75.0 # 10 + 15 + 20 + 5 + 25
    assert candle_5m.trade_count == 43 # 5 + 8 + 12 + 3 + 15
    assert candle_5m.is_complete is True


def test_higher_timeframe_completeness_missing_constituent() -> None:
    start = datetime(2026, 9, 19, 10, 0, 0, tzinfo=timezone.utc)
    # Only 4 candles present in 5m period (10:02 missing gap)
    c0 = make_candle(start + timedelta(minutes=0))
    c1 = make_candle(start + timedelta(minutes=1))
    c3 = make_candle(start + timedelta(minutes=3))
    c4 = make_candle(start + timedelta(minutes=4))

    candles_1m = [c0, c1, c3, c4]
    result_5m = MultiTimeframeResampler.resample(candles_1m, "5m")

    assert len(result_5m) == 1
    # MUST NOT be marked complete due to missing constituent candle
    assert result_5m[0].is_complete is False


def test_higher_timeframe_completeness_incomplete_constituent() -> None:
    start = datetime(2026, 9, 19, 10, 0, 0, tzinfo=timezone.utc)
    # 5 candles, but one is marked is_complete=False
    candles = [
        make_candle(start + timedelta(minutes=i), is_complete=(i != 2))
        for i in range(5)
    ]

    result_5m = MultiTimeframeResampler.resample(candles, "5m")
    assert len(result_5m) == 1
    assert result_5m[0].is_complete is False


def test_resample_all_standard_timeframes() -> None:
    start = datetime(2026, 9, 19, 0, 0, 0, tzinfo=timezone.utc)
    # Generate 1440 1m candles = 1 full UTC day
    candles_1m = [
        make_candle(start + timedelta(minutes=i))
        for i in range(1440)
    ]

    results = MultiTimeframeResampler.resample_all(candles_1m)

    # 1440 / 5 = 288
    assert len(results["5m"]) == 288
    assert all(c.is_complete for c in results["5m"])

    # 1440 / 15 = 96
    assert len(results["15m"]) == 96
    assert all(c.is_complete for c in results["15m"])

    # 1440 / 60 = 24
    assert len(results["1h"]) == 24
    assert all(c.is_complete for c in results["1h"])

    # 1440 / 240 = 6
    assert len(results["4h"]) == 6
    assert all(c.is_complete for c in results["4h"])

    # 1 full day = 1
    assert len(results["1d"]) == 1
    assert results["1d"][0].is_complete is True
    assert results["1d"][0].timestamp_utc == start


def test_missing_constituent_marks_all_derived_timeframes_incomplete() -> None:
    """Verify invariant: when a 1m candle is missing, every derived timeframe (5m, 15m, 1h, 4h, 1d)
    enclosing that minute is constructed from available candles with is_complete=False.
    """
    start = datetime(2026, 9, 19, 0, 0, 0, tzinfo=timezone.utc)
    # Generate 1440 1m candles for 1 full day, but delete minute 3 (00:03:00)
    candles_1m = [
        make_candle(start + timedelta(minutes=i))
        for i in range(1440)
        if i != 3  # Gap at 00:03:00
    ]
    assert len(candles_1m) == 1439

    results = MultiTimeframeResampler.resample_all(candles_1m)

    # 5m: bucket 00:00 (4 candles) is incomplete; all other 287 buckets are complete
    assert len(results["5m"]) == 288
    assert results["5m"][0].is_complete is False
    assert results["5m"][0].timestamp_utc == start
    assert all(c.is_complete for c in results["5m"][1:])

    # 15m: bucket 00:00 (14 candles) is incomplete; all other 95 buckets are complete
    assert len(results["15m"]) == 96
    assert results["15m"][0].is_complete is False
    assert results["15m"][0].timestamp_utc == start
    assert all(c.is_complete for c in results["15m"][1:])

    # 1h: bucket 00:00 (59 candles) is incomplete; all other 23 buckets are complete
    assert len(results["1h"]) == 24
    assert results["1h"][0].is_complete is False
    assert results["1h"][0].timestamp_utc == start
    assert all(c.is_complete for c in results["1h"][1:])

    # 4h: bucket 00:00 (239 candles) is incomplete; all other 5 buckets are complete
    assert len(results["4h"]) == 6
    assert results["4h"][0].is_complete is False
    assert results["4h"][0].timestamp_utc == start
    assert all(c.is_complete for c in results["4h"][1:])

    # 1d: bucket 00:00 (1439 candles) is incomplete
    assert len(results["1d"]) == 1
    assert results["1d"][0].is_complete is False
    assert results["1d"][0].timestamp_utc == start

