"""Unit tests for BinanceKlineNormalizer."""

import json
from datetime import datetime, timezone

import pytest

from xau_quant.data.normalizer import BinanceKlineNormalizer


def test_normalize_single_kline() -> None:
    """Verify parsing a single genuine Binance kline raw array."""
    # Structure: [open_time, open, high, low, close, vol, close_time, quote_vol,
    # trades, tb_base_vol, tb_quote_vol, ignore]
    raw = [
        1726732800000,
        "63000.50",
        "63050.00",
        "62990.10",
        "63025.20",
        "15.234",
        1726732859999,
        "960000.12",
        240,
        "8.120",
        "511600.05",
        "0",
    ]
    candle = BinanceKlineNormalizer.normalize_kline(
        raw_kline=raw,
        instrument="BTCUSDT",
        venue="binance",
        market_type="spot",
        timeframe="1m",
    )
    assert candle.instrument == "BTCUSDT"
    assert candle.venue == "binance"
    assert candle.open == 63000.50
    assert candle.high == 63050.00
    assert candle.low == 62990.10
    assert candle.close == 63025.20
    assert candle.volume == 15.234
    assert candle.trade_count == 240
    assert candle.timestamp_utc == datetime.fromtimestamp(1726732800, tz=timezone.utc)
    assert candle.is_complete is True


def test_normalize_payload_bytes() -> None:
    """Verify parsing a multi-candle JSON payload as bytes."""
    payload = [
        [
            1726732800000,
            "100.0",
            "105.0",
            "99.0",
            "102.0",
            "1.0",
            1726732859999,
            "102.0",
            10,
            "0.5",
            "51.0",
            "0",
        ],
        [
            1726732860000,
            "102.0",
            "108.0",
            "101.0",
            "107.0",
            "2.0",
            1726732919999,
            "214.0",
            15,
            "1.2",
            "128.4",
            "0",
        ],
    ]
    raw_bytes = json.dumps(payload).encode("utf-8")
    candles = BinanceKlineNormalizer.normalize_payload(
        raw_bytes, instrument="BTCUSDT", timeframe="1m"
    )

    assert len(candles) == 2
    assert candles[0].close == 102.0
    assert candles[1].close == 107.0


def test_normalize_malformed_kline_raises() -> None:
    """Verify truncated or malformed records raise ValueError."""
    short_kline = [1726732800000, "100.0", "105.0"]
    with pytest.raises(ValueError, match="Malformed Binance kline record"):
        BinanceKlineNormalizer.normalize_kline(short_kline)
