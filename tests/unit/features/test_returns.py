"""Unit tests for returns family calculators."""

import math

from xau_quant.features.calculators.returns import (
    compute_price_body_ratio,
    compute_price_lower_wick_ratio,
    compute_price_midpoint,
    compute_price_upper_wick_ratio,
    compute_ret_log_cc,
    compute_ret_log_oc,
)


def test_ret_log_cc_lookback_convention():
    closes = [100.0, 105.0, 110.0, 108.0, 112.0]
    res_1 = compute_ret_log_cc(closes, n=1)
    assert res_1[0] is None
    assert math.isclose(res_1[1], math.log(105.0 / 100.0))
    assert math.isclose(res_1[4], math.log(112.0 / 108.0))

    res_3 = compute_ret_log_cc(closes, n=3)
    assert res_3[0] is None
    assert res_3[1] is None
    assert res_3[2] is None
    assert math.isclose(res_3[3], math.log(108.0 / 100.0))
    assert math.isclose(res_3[4], math.log(112.0 / 105.0))


def test_ret_log_oc_single_bar():
    opens = [100.0, 105.0]
    closes = [102.0, 103.0]
    res = compute_ret_log_oc(opens, closes)
    assert math.isclose(res[0], math.log(102.0 / 100.0))
    assert math.isclose(res[1], math.log(103.0 / 105.0))


def test_candle_geometry_ratios():
    opens = [100.0]
    highs = [110.0]
    lows = [90.0]
    closes = [105.0]

    # Range = 20.0, Body = 5.0 -> body_ratio = 5 / 20 = 0.25
    body = compute_price_body_ratio(opens, highs, lows, closes)
    assert math.isclose(body[0], 5.0 / 20.0, abs_tol=1e-6)

    # Upper wick = 110 - 105 = 5.0 -> 5 / 20 = 0.25
    upper = compute_price_upper_wick_ratio(opens, highs, lows, closes)
    assert math.isclose(upper[0], 5.0 / 20.0, abs_tol=1e-6)

    # Lower wick = 100 - 90 = 10.0 -> 10 / 20 = 0.50
    lower = compute_price_lower_wick_ratio(opens, highs, lows, closes)
    assert math.isclose(lower[0], 10.0 / 20.0, abs_tol=1e-6)

    # Midpoint = (110 + 90) / 2 = 100.0
    mid = compute_price_midpoint(highs, lows)
    assert mid[0] == 100.0
