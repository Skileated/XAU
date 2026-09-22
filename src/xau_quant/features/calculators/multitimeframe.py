"""Multi-timeframe (MTF) feature calculators and alignment logic."""

import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from xau_quant.data.models import CanonicalCandle
from xau_quant.features.calculators.momentum import compute_mom_rsi
from xau_quant.features.calculators.returns import compute_ret_log_cc
from xau_quant.features.calculators.structure import compute_ms_price_position
from xau_quant.features.calculators.volatility import (
    compute_vol_atr_pct,
    compute_vol_realized,
)


def align_5m_to_htf_open(t: datetime, htf_seconds: int) -> datetime:
    """Calculate the open timestamp of the latest completed HTF candle as of 5m bar close.

    Formula: floor(t - (htf_seconds - 300s), htf_seconds)
    For 15m (900s): floor(t - 600s, 15m)
    For 1h (3600s): floor(t - 3300s, 1h)
    """
    offset_seconds = htf_seconds - 300
    target_epoch = t.timestamp() - offset_seconds
    aligned_epoch = math.floor(target_epoch / htf_seconds) * htf_seconds
    return datetime.fromtimestamp(aligned_epoch, tz=timezone.utc)


def compute_htf_precomputed_series(
    htf_candles: List[CanonicalCandle],
    timeframe: str,
) -> Dict[str, Dict[datetime, Optional[float]]]:
    """Precompute all HTF features indexed by HTF candle open timestamp.

    This enables O(1) alignment lookups during 5m processing without redundant computations.
    """
    timestamps = [c.timestamp_utc for c in htf_candles]
    highs = [c.high for c in htf_candles]
    lows = [c.low for c in htf_candles]
    closes = [c.close for c in htf_candles]
    volumes = [c.volume for c in htf_candles]
    tb_volumes = [c.taker_buy_base_volume for c in htf_candles]

    results: Dict[str, Dict[datetime, Optional[float]]] = {}

    if timeframe == "15m":
        # Returns
        ret_4 = compute_ret_log_cc(closes, n=4)
        ret_16 = compute_ret_log_cc(closes, n=16)
        # Momentum
        rsi_14 = compute_mom_rsi(closes, n=14)
        # Volatility
        atr_pct_14 = compute_vol_atr_pct(highs, lows, closes, n=14)
        # Structure
        pos_16 = compute_ms_price_position(closes, highs, lows, n=16)

        # Liquidity: taker buy ratio
        taker_ratio: List[Optional[float]] = []
        for tb, v in zip(tb_volumes, volumes):
            if v > 0.0:
                taker_ratio.append(min(max(tb / v, 0.0), 1.0))
            else:
                taker_ratio.append(None)

        # Liquidity: volume ratio 16
        vol_ratio_16: List[Optional[float]] = [None] * len(volumes)
        if len(volumes) >= 16:
            rolling_v = sum(volumes[:15])
            for i in range(15, len(volumes)):
                rolling_v += volumes[i]
                mean_v = rolling_v / 16.0
                if mean_v > 0.0:
                    vol_ratio_16[i] = volumes[i] / mean_v
                else:
                    vol_ratio_16[i] = None
                rolling_v -= volumes[i - 15]

        results["mtf_15m_ret_log_cc_4"] = dict(zip(timestamps, ret_4))
        results["mtf_15m_ret_log_cc_16"] = dict(zip(timestamps, ret_16))
        results["mtf_15m_mom_rsi_14"] = dict(zip(timestamps, rsi_14))
        results["mtf_15m_vol_atr_pct_14"] = dict(zip(timestamps, atr_pct_14))
        results["mtf_15m_price_position_16"] = dict(zip(timestamps, pos_16))
        results["mtf_15m_liq_taker_buy_ratio"] = dict(zip(timestamps, taker_ratio))
        results["mtf_15m_liq_vol_ratio_16"] = dict(zip(timestamps, vol_ratio_16))

    elif timeframe == "1h":
        # Returns
        ret_4 = compute_ret_log_cc(closes, n=4)
        ret_24 = compute_ret_log_cc(closes, n=24)
        # Momentum
        rsi_14 = compute_mom_rsi(closes, n=14)
        # Volatility
        vol_realized_24 = compute_vol_realized(closes, n=24)
        # Structure
        pos_24 = compute_ms_price_position(closes, highs, lows, n=24)

        # Mean Reversion: 1h close Z-score 24
        zscore_24: List[Optional[float]] = [None] * len(closes)
        if len(closes) >= 24:
            for i in range(23, len(closes)):
                w = closes[i - 23 : i + 1]
                mean_c = sum(w) / 24.0
                var_c = sum((c - mean_c) ** 2 for c in w) / 23.0
                sigma_c = math.sqrt(max(var_c, 0.0))
                if sigma_c == 0.0:
                    zscore_24[i] = 0.0
                else:
                    z = (closes[i] - mean_c) / sigma_c
                    zscore_24[i] = min(max(z, -10.0), 10.0)

        # Liquidity: taker buy ratio
        taker_ratio_1h: List[Optional[float]] = []
        for tb, v in zip(tb_volumes, volumes):
            if v > 0.0:
                taker_ratio_1h.append(min(max(tb / v, 0.0), 1.0))
            else:
                taker_ratio_1h.append(None)

        results["mtf_1h_ret_log_cc_4"] = dict(zip(timestamps, ret_4))
        results["mtf_1h_ret_log_cc_24"] = dict(zip(timestamps, ret_24))
        results["mtf_1h_mom_rsi_14"] = dict(zip(timestamps, rsi_14))
        results["mtf_1h_vol_realized_24"] = dict(zip(timestamps, vol_realized_24))
        results["mtf_1h_price_position_24"] = dict(zip(timestamps, pos_24))
        results["mtf_1h_mr_zscore_24"] = dict(zip(timestamps, zscore_24))
        results["mtf_1h_liq_taker_buy_ratio"] = dict(zip(timestamps, taker_ratio_1h))

    return results


DELTAS = (
    timedelta(seconds=0),
    timedelta(seconds=60),
    timedelta(seconds=120),
    timedelta(seconds=180),
    timedelta(seconds=240),
)


def compute_mtf_1m_microstructure(
    primary_candles_5m: List[CanonicalCandle],
    candles_1m_by_timestamp: Dict[datetime, CanonicalCandle],
) -> Dict[str, List[Optional[float]]]:
    """Compute 1m microstructure context features across each 5m bar's 5 constituent 1m bars.

    The 5 constituent 1m bars have open timestamps {t, t+60s, t+120s, t+180s, t+240s}.
    All 5 complete by t+300s (when the 5m bar closes).
    """
    dispersion: List[Optional[float]] = []
    taker_trend: List[Optional[float]] = []
    return_skew: List[Optional[float]] = []

    for c5 in primary_candles_5m:
        t0 = c5.timestamp_utc
        constituents = [candles_1m_by_timestamp.get(t0 + d) for d in DELTAS]

        if any(c is None or not c.is_complete for c in constituents):
            dispersion.append(None)
            taker_trend.append(None)
            return_skew.append(None)
            continue

        c_1m = [c for c in constituents if c is not None]
        vols = [c.volume for c in c_1m]
        tbs = [c.taker_buy_base_volume for c in c_1m]

        # 1. Volume Dispersion: std(V_1m) / mean(V_1m)
        mean_v = sum(vols) / 5.0
        if mean_v > 0.0:
            var_v = sum((v - mean_v) ** 2 for v in vols) / 4.0  # sample std
            std_v = math.sqrt(max(var_v, 0.0))
            dispersion.append(std_v / mean_v)
        else:
            dispersion.append(None)  # Domain NaN: zero volume

        # 2. Taker Trend: OLS slope of TB / V over 5 bars
        if any(v == 0.0 for v in vols):
            taker_trend.append(None)  # Domain NaN if any constituent has zero volume
        else:
            ratios = [tb / v for tb, v in zip(tbs, vols)]
            # OLS slope over x = 0..4 (x_bar = 2.0, S_xx = 5 * (25 - 1) / 12 = 10.0)
            x_bar = 2.0
            s_xx = 10.0
            s_xy = sum((k - x_bar) * ratios[k] for k in range(5))
            slope = s_xy / s_xx
            # Normalized slope per bar
            taker_trend.append(slope)

        # 3. Return Skew: (r_last - r_first) / sum(|r_i|)
        # 1m returns from candle opens/closes: r_k = ln(C_k / O_k)
        r_list = [
            math.log(c.close / c.open) for c in c_1m if c.close > 0.0 and c.open > 0.0
        ]
        if len(r_list) == 5:
            denom = sum(abs(r) for r in r_list)
            if denom == 0.0:
                return_skew.append(0.0)  # Exact boundary: flat microstructure zero skew
            else:
                skew = (r_list[-1] - r_list[0]) / denom
                return_skew.append(min(max(skew, -1.0), 1.0))
        else:
            return_skew.append(None)

    return {
        "mtf_1m_vol_dispersion": dispersion,
        "mtf_1m_taker_trend": taker_trend,
        "mtf_1m_return_skew": return_skew,
    }
