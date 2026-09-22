"""Unit tests for market structure family calculators."""

from datetime import datetime, timezone

from xau_quant.features.calculators.structure import (
    compute_ms_consec_down,
    compute_ms_consec_up,
    compute_ms_pivot_high,
)


def test_pivot_typed_emission():
    """Verify pivot high/low emit typed (bool, timestamp, age) at confirmation time t = k + s."""
    # Build 10 timestamps
    t0 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    timestamps = [
        datetime.fromtimestamp(t0.timestamp() + i * 300, tz=timezone.utc) for i in range(10)
    ]

    # s = 3: requires 2s + 1 = 7 bars. First valid at index 2s = 6 (bar 6).
    # Pivot at k = 3 -> confirmed at t = 3 + 3 = 6.
    # highs: k=3 is the highest among k-3..k-1 and k+1..k+3
    highs = [10.0, 11.0, 12.0, 20.0, 15.0, 14.0, 13.0, 12.0, 11.0, 10.0]

    is_pivot, pivot_ts, pivot_age = compute_ms_pivot_high(timestamps, highs, s=3)

    # Indices 0..5 must be None (warm-up < 2s)
    for i in range(6):
        assert is_pivot[i] is None
        assert pivot_ts[i] is None
        assert pivot_age[i] is None

    # At bar index 6: pivot at k=3 is confirmed!
    assert is_pivot[6] is True
    assert pivot_ts[6] == timestamps[3]
    assert pivot_age[6] == 3

    # At bar index 7: k=4 has high=15, which is NOT > high[3]=20 -> False
    assert is_pivot[7] is False
    assert pivot_ts[7] is None
    assert pivot_age[7] is None


def test_ms_consec_up_down():
    closes = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 14.0]
    up = compute_ms_consec_up(closes, n=5)
    # First valid at index 5: 5 comparisons (10->11, 11->12, 12->13, 13->14, 14->15) -> 5
    assert up[0] is None
    assert up[4] is None
    assert up[5] == 5
    # Index 6: 15 -> 14 is down, so consecutive up broken -> 0
    assert up[6] == 0

    down = compute_ms_consec_down(closes, n=5)
    assert down[5] == 0
    assert down[6] == 1
