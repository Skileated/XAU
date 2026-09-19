"""Unit tests for MarketDataValidator using explicitly labeled synthetic test inputs.

NOTICE: These fixtures are purely SYNTHETIC_TEST_INPUT_ONLY constructs used to verify
validator edge-case branch coverage and logic invariants in unit memory.
They are NOT market data, do NOT represent historical BTC prices, and are NEVER stored
under data/raw or data/processed.
"""

from datetime import datetime, timedelta, timezone

from xau_quant.data.models import CanonicalCandle
from xau_quant.data.validator import MarketDataValidator


def _make_synthetic_test_candle(
    index: int,
    open_price: float = 100.0,
    high: float = 105.0,
    low: float = 95.0,
    close: float = 102.0,
    volume: float = 10.0,
    taker_buy_vol: float = 5.0,
    time_offset_minutes: int = 0,
) -> CanonicalCandle:
    """Helper constructing an in-memory synthetic validation input (SYNTHETIC_TEST_INPUT_ONLY)."""
    base_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    candle_time = base_time + timedelta(minutes=time_offset_minutes)
    return CanonicalCandle(
        timestamp_utc=candle_time,
        venue="test_venue",
        instrument="SYNTHETIC_TEST_INPUT_ONLY",
        market_type="test",
        timeframe="1m",
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        quote_volume=volume * close,
        trade_count=10,
        taker_buy_base_volume=taker_buy_vol,
        taker_buy_quote_volume=taker_buy_vol * close,
        is_complete=True,
    )


def test_validator_accepts_valid_series() -> None:
    """Verify clean pass for a structurally consistent synthetic sequence."""
    candles = [
        _make_synthetic_test_candle(0, time_offset_minutes=0),
        _make_synthetic_test_candle(1, time_offset_minutes=1),
        _make_synthetic_test_candle(2, time_offset_minutes=2),
    ]
    validator = MarketDataValidator(expected_timeframe="1m")
    report = validator.validate(candles)

    assert report.is_valid is True
    assert report.total_records == 3
    assert report.valid_records_count == 3
    assert report.invalid_records_count == 0
    assert len(report.issues) == 0
    assert len(report.gaps) == 0


def test_validator_detects_corrupted_ohlc() -> None:
    """Verify detection when high < low or close > high in synthetic inputs."""
    # Case 1: high < low
    corrupted_high = _make_synthetic_test_candle(0, high=90.0, low=95.0)
    validator = MarketDataValidator(expected_timeframe="1m")
    report = validator.validate([corrupted_high])
    assert report.is_valid is False
    assert any(i.issue_type == "OHLC_HIGH_LESS_THAN_LOW" for i in report.issues)

    # Case 2: close > high
    corrupted_close = _make_synthetic_test_candle(0, high=105.0, close=110.0)
    report2 = validator.validate([corrupted_close])
    assert report2.is_valid is False
    assert any(i.issue_type == "OHLC_CLOSE_OUT_OF_RANGE" for i in report2.issues)


def test_validator_detects_zero_or_negative_price() -> None:
    """Verify rejection of zero or negative prices in synthetic validation inputs."""
    # Note: CanonicalCandle model enforces ge=0.0, so open=0 is tested directly
    zero_price_candle = _make_synthetic_test_candle(0, open_price=0.0)
    validator = MarketDataValidator(expected_timeframe="1m")
    report = validator.validate([zero_price_candle])
    assert report.is_valid is False
    assert any(i.issue_type == "NON_POSITIVE_PRICE" for i in report.issues)


def test_validator_detects_taker_volume_exceeding_total() -> None:
    """Verify rejection when taker buy volume exceeds total volume in synthetic input."""
    excess_taker = _make_synthetic_test_candle(0, volume=10.0, taker_buy_vol=15.0)
    validator = MarketDataValidator(expected_timeframe="1m")
    report = validator.validate([excess_taker])
    assert report.is_valid is False
    assert any(i.issue_type == "TAKER_VOLUME_EXCEEDS_TOTAL" for i in report.issues)


def test_validator_detects_exact_and_conflicting_duplicates() -> None:
    """Verify duplicate detection for identical vs conflicting records at same timestamp."""
    c1 = _make_synthetic_test_candle(0, time_offset_minutes=0, close=100.0)
    # Exact duplicate
    c2 = _make_synthetic_test_candle(1, time_offset_minutes=0, close=100.0)
    # Conflicting duplicate
    c3 = _make_synthetic_test_candle(2, time_offset_minutes=0, close=120.0)

    validator = MarketDataValidator(expected_timeframe="1m")
    report = validator.validate([c1, c2, c3])
    assert report.is_valid is False
    assert report.duplicate_count == 1
    assert report.conflicting_duplicate_count == 1
    assert any(i.issue_type == "EXACT_DUPLICATE" for i in report.issues)
    assert any(i.issue_type == "CONFLICTING_DUPLICATE" for i in report.issues)


def test_validator_detects_data_gaps() -> None:
    """Verify gap detection when interval exceeds expected timeframe."""
    c1 = _make_synthetic_test_candle(0, time_offset_minutes=0)
    # 5 minutes later instead of 1 minute -> 4 missing intervals
    c2 = _make_synthetic_test_candle(1, time_offset_minutes=5)

    validator = MarketDataValidator(expected_timeframe="1m")
    report = validator.validate([c1, c2])
    assert len(report.gaps) == 1
    assert report.gaps[0].missing_intervals_count == 4
    assert any(i.issue_type == "DATA_GAP_DETECTED" for i in report.issues)


def test_validator_detects_out_of_order_timestamps() -> None:
    """Verify rejection when timestamps are not strictly ascending."""
    c1 = _make_synthetic_test_candle(0, time_offset_minutes=5)
    c2 = _make_synthetic_test_candle(1, time_offset_minutes=2)

    validator = MarketDataValidator(expected_timeframe="1m")
    report = validator.validate([c1, c2])
    assert report.is_valid is False
    assert any(i.issue_type == "TIMESTAMP_OUT_OF_ORDER" for i in report.issues)
