"""Unit tests for volume and liquidity family calculators."""

import math

from xau_quant.features.calculators.liquidity import (
    compute_liq_avg_trade_size,
    compute_liq_delta_proxy,
    compute_liq_taker_buy_ratio,
    compute_liq_vol_ratio,
    compute_liq_vwap_dev,
)


def test_zero_volume_liquidity_domain_nans():
    """Verify zero-volume bar produces None for domain-defined metrics."""
    volumes = [0.0, 10.0]
    tb = [0.0, 6.0]
    trades = [0, 5]

    # liq_taker_buy_ratio
    tbr = compute_liq_taker_buy_ratio(tb, volumes)
    assert tbr[0] is None
    assert tbr[1] == 0.6

    # liq_avg_trade_size
    ats = compute_liq_avg_trade_size(volumes, trades)
    assert ats[0] is None
    assert ats[1] == 2.0

    # liq_delta_proxy
    dp = compute_liq_delta_proxy(tb, volumes)
    assert dp[0] is None
    # (2*6 - 10) / 10 = 0.2
    assert math.isclose(dp[1], 0.2)


def test_vwap_dev_and_vol_ratio():
    closes = [100.0, 105.0]
    qv = [1000.0, 2100.0]
    v = [10.0, 20.0]

    # n = 2: rolling_qv = 3100, rolling_v = 30 -> vwap = 3100 / 30 = 103.333333
    vwap_dev = compute_liq_vwap_dev(closes, qv, v, n=2)
    assert vwap_dev[0] is None
    assert vwap_dev[1] is not None
    expected_vwap = 3100.0 / 30.0
    assert math.isclose(vwap_dev[1], (105.0 - expected_vwap) / expected_vwap)

    # vol_ratio n=2: mean_v = 15.0 -> v[1] / 15.0 = 20 / 15 = 1.333333
    vr = compute_liq_vol_ratio(v, n=2)
    assert vr[0] is None
    assert math.isclose(vr[1], 20.0 / 15.0)
