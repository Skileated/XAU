"""Unit tests for mean-reversion family calculators."""

import math

from xau_quant.features.calculators.meanreversion import (
    compute_mr_autocorr_lag1,
    compute_mr_hurst_proxy,
    compute_mr_zscore,
)


def test_hurst_proxy_known_answer():
    """Verify frozen R/S single-window Hurst proxy matches the exact known-answer value:

    r = [0.01, -0.02, 0.03, -0.01, 0.02, -0.03, 0.01, 0.00] (n=8)
    R = 0.03625
    S = 0.020310096011589902
    R/S = 1.7848266192003244
    H = ln(R/S) / ln(8) = 0.2785946451494484
    Tested within 1e-12 tolerance.
    """
    # Construct 9 closes whose log-returns match r exactly:
    # C[0] = 100.0, C[k+1] = C[k] * exp(r[k])
    r_target = [0.01, -0.02, 0.03, -0.01, 0.02, -0.03, 0.01, 0.00]
    closes = [100.0]
    for ret in r_target:
        closes.append(closes[-1] * math.exp(ret))

    # Lookback n = 8: required_history_bars = 8 + 1 = 9. First valid at index 8.
    hurst = compute_mr_hurst_proxy(closes, n=8)

    assert len(hurst) == 9
    for i in range(8):
        assert hurst[i] is None, f"Index {i} should be None during warmup"

    expected_h = 0.2785946451494484
    assert hurst[8] is not None
    assert abs(hurst[8] - expected_h) <= 1e-12, (
        f"Hurst proxy value {hurst[8]:.16f} deviates from expected {expected_h:.16f} "
        f"by {abs(hurst[8] - expected_h)}"
    )


def test_hurst_proxy_constant_boundary():
    """Flat prices (S=0 or R=0) yield exactly the defined 0.5 boundary value."""
    closes = [100.0] * 15
    hurst = compute_mr_hurst_proxy(closes, n=8)
    assert hurst[8] == 0.5


def test_zscore_zero_variance_is_zero():
    """Flat close series yields Z-score = 0.0 exactly."""
    closes = [50.0] * 30
    z = compute_mr_zscore(closes, n=24)
    assert z[22] is None
    assert z[23] == 0.0


def test_mr_autocorr_lag1():
    # Constant alternating returns
    closes = [100.0, 101.0, 100.0, 101.0, 100.0, 101.0]
    ac = compute_mr_autocorr_lag1(closes, n=4)
    # n=4 requires n+2=6 bars -> first valid at index 5
    for i in range(5):
        assert ac[i] is None
    assert ac[5] is not None
    assert isinstance(ac[5], float)
