"""Unit tests for momentum family calculators."""

import math

from xau_quant.features.calculators.momentum import (
    compute_mom_macd_hist,
    compute_mom_roc,
    compute_mom_rsi,
    compute_mom_slope,
    compute_mom_sma_dev,
)


def test_macd_natural_composition():
    """Verify MACD histogram uses natural composition and is first valid at index 33 (34 bars)."""
    # Create synthetic series of 50 closes
    closes = [100.0 + i * 0.5 for i in range(50)]
    hist = compute_mom_macd_hist(closes, n_fast=12, n_slow=26, n_signal=9)

    assert len(hist) == 50
    # First 33 bars (indices 0..32) must be None
    for i in range(33):
        assert hist[i] is None, f"Expected None at index {i}, got {hist[i]}"
    # Bar index 33 must be valid
    assert hist[33] is not None
    assert isinstance(hist[33], float)


def test_rsi_boundary_zero_loss_is_100():
    """Monotonically increasing prices produce RSI = 100.0 exactly."""
    closes = [100.0 + i * 2.0 for i in range(30)]
    rsi = compute_mom_rsi(closes, n=14)

    # First valid at index 14
    for i in range(14):
        assert rsi[i] is None
    for i in range(14, 30):
        assert rsi[i] == 100.0, f"Expected 100.0, got {rsi[i]}"


def test_rsi_boundary_zero_gain_is_0():
    """Monotonically decreasing prices produce RSI = 0.0 exactly."""
    closes = [100.0 - i * 2.0 for i in range(30)]
    rsi = compute_mom_rsi(closes, n=14)

    for i in range(14):
        assert rsi[i] is None
    for i in range(14, 30):
        assert rsi[i] == 0.0, f"Expected 0.0, got {rsi[i]}"


def test_rsi_boundary_flat_price_is_50():
    """Flat price series produces RSI = 50.0 exactly (flat neutrality)."""
    closes = [100.0] * 30
    rsi = compute_mom_rsi(closes, n=14)

    for i in range(14):
        assert rsi[i] is None
    for i in range(14, 30):
        assert rsi[i] == 50.0, f"Expected 50.0, got {rsi[i]}"


def test_mom_roc():
    closes = [100.0, 105.0, 110.0, 115.0, 120.0, 125.0, 130.0]
    roc = compute_mom_roc(closes, n=6)
    assert roc[0] is None
    assert roc[5] is None
    # Index 6: (130 - 100) / 100 = 0.3
    assert math.isclose(roc[6], 0.3)


def test_mom_slope_and_sma():
    closes = [10.0, 11.0, 12.0, 13.0, 14.0]
    slope = compute_mom_slope(closes, n=4)
    assert slope[0] is None
    assert slope[1] is None
    assert slope[2] is None
    assert slope[3] is not None

    sma = compute_mom_sma_dev(closes, n=4)
    # mean of [10, 11, 12, 13] is 11.5. C[3]=13 -> (13 - 11.5) / 11.5
    assert math.isclose(sma[3], (13.0 - 11.5) / 11.5)
