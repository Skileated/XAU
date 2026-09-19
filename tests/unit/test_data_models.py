"""Unit tests for CanonicalCandle data model."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from xau_quant.data.models import CanonicalCandle


def test_canonical_candle_valid_construction() -> None:
    """Verify standard valid CanonicalCandle construction."""
    ts = datetime(2026, 9, 19, 8, 0, 0, tzinfo=timezone.utc)
    candle = CanonicalCandle(
        timestamp_utc=ts,
        venue="binance",
        instrument="BTCUSDT",
        market_type="spot",
        timeframe="1m",
        open=80000.0,
        high=80100.0,
        low=79950.0,
        close=80050.0,
        volume=10.5,
        quote_volume=840000.0,
        trade_count=150,
        taker_buy_base_volume=5.2,
        taker_buy_quote_volume=416000.0,
        is_complete=True,
    )
    assert candle.venue == "binance"
    assert candle.instrument == "BTCUSDT"
    assert candle.open == 80000.0
    assert candle.timestamp_utc == ts
    assert candle.is_complete is True


def test_canonical_candle_immutability() -> None:
    """Verify CanonicalCandle instances are frozen/immutable."""
    ts = datetime(2026, 9, 19, 8, 0, 0, tzinfo=timezone.utc)
    candle = CanonicalCandle(
        timestamp_utc=ts,
        venue="binance",
        instrument="BTCUSDT",
        market_type="spot",
        timeframe="1m",
        open=80000.0,
        high=80100.0,
        low=79950.0,
        close=80050.0,
        volume=10.5,
        quote_volume=840000.0,
        trade_count=150,
        taker_buy_base_volume=5.2,
        taker_buy_quote_volume=416000.0,
        is_complete=True,
    )
    with pytest.raises(ValidationError):
        # Trying to mutate frozen model attribute should raise ValidationError
        candle.close = 80100.0  # type: ignore[misc]


def test_canonical_candle_negative_price_rejection() -> None:
    """Verify CanonicalCandle rejects negative prices."""
    ts = datetime(2026, 9, 19, 8, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValidationError):
        CanonicalCandle(
            timestamp_utc=ts,
            venue="binance",
            instrument="BTCUSDT",
            market_type="spot",
            timeframe="1m",
            open=-100.0,
            high=80100.0,
            low=79950.0,
            close=80050.0,
            volume=10.5,
            quote_volume=840000.0,
            trade_count=150,
            taker_buy_base_volume=5.2,
            taker_buy_quote_volume=416000.0,
            is_complete=True,
        )


def test_canonical_candle_to_dict() -> None:
    """Verify to_dict produces expected ISO formatted timestamp."""
    ts = datetime(2026, 9, 19, 8, 0, 0, tzinfo=timezone.utc)
    candle = CanonicalCandle(
        timestamp_utc=ts,
        venue="binance",
        instrument="BTCUSDT",
        market_type="spot",
        timeframe="1m",
        open=80000.0,
        high=80100.0,
        low=79950.0,
        close=80050.0,
        volume=10.5,
        quote_volume=840000.0,
        trade_count=150,
        taker_buy_base_volume=5.2,
        taker_buy_quote_volume=416000.0,
        is_complete=True,
    )
    d = candle.to_dict()
    assert d["timestamp_utc"] == "2026-09-19T08:00:00+00:00"
    assert d["open"] == 80000.0
