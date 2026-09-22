"""Volatility feature calculators."""

import math
from typing import List, Optional


def compute_vol_atr(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    *,
    n: int = 14,
) -> List[Optional[float]]:
    """Compute Average True Range (ATR) with Wilder smoothing in USD.

    TR[t] = max(H[t] - L[t], |H[t] - C[t-1]|, |L[t] - C[t-1]|) for t >= 1.
    Seed at index n: mean(TR[1..n]).
    Update for i > n: ((n-1)*ATR[i-1] + TR[i]) / n.
    required_history_bars = n + 1 (first valid at index n).
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    if n < 1:
        raise ValueError(f"Lookback n must be >= 1, got {n}")
    if length <= n:
        return result

    # Compute TR for t >= 1
    tr_list: List[float] = []
    for i in range(1, length):
        h = highs[i]
        lo = lows[i]
        c_prev = closes[i - 1]
        tr = max(h - lo, abs(h - c_prev), abs(lo - c_prev))
        tr_list.append(tr)

    # First n TR values correspond to bars 1..n
    atr = sum(tr_list[:n]) / n
    result[n] = atr

    for i in range(n + 1, length):
        tr = tr_list[i - 1]
        atr = ((n - 1) * atr + tr) / n
        result[i] = atr

    return result


def compute_vol_atr_pct(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    *,
    n: int = 14,
) -> List[Optional[float]]:
    """Compute normalized ATR percentage: ATR[t] / C[t].

    required_history_bars = n + 1 (first valid at index n).
    """
    atr_vals = compute_vol_atr(highs, lows, closes, n=n)
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    for i in range(length):
        atr = atr_vals[i]
        c = closes[i]
        if atr is not None and c > 0.0:
            result[i] = atr / c
        else:
            result[i] = None
    return result


def compute_vol_realized(
    closes: List[float],
    *,
    n: int,
    returns: Optional[List[Optional[float]]] = None,
) -> List[Optional[float]]:
    """Compute realized volatility as sample standard deviation (ddof=1) of n log-returns.

    required_history_bars = n + 1 (first valid at index n).
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    if n < 2:
        raise ValueError(f"Lookback n must be >= 2, got {n}")
    if length <= n:
        return result

    if returns is None:
        ret_list: List[Optional[float]] = [None] * length
        for i in range(1, length):
            c_curr = closes[i]
            c_prev = closes[i - 1]
            if c_curr > 0.0 and c_prev > 0.0:
                ret_list[i] = math.log(c_curr) - math.log(c_prev)
            else:
                ret_list[i] = None
    else:
        ret_list = returns

    first_window = ret_list[1 : n + 1]
    has_none = any(r is None for r in first_window)
    if not has_none:
        valid_w = [float(r) for r in first_window if r is not None]
        r_sum = sum(valid_w)
        r_sum_sq = sum(r * r for r in valid_w)
        m = r_sum / n
        var = (r_sum_sq - n * m * m) / (n - 1)
        result[n] = math.sqrt(max(var, 0.0))
    else:
        r_sum = 0.0
        r_sum_sq = 0.0

    for i in range(n + 1, length):
        r_in = ret_list[i]
        r_out = ret_list[i - n]
        if r_in is None or r_out is None or has_none:
            w = ret_list[i - n + 1 : i + 1]
            if any(r is None for r in w):
                result[i] = None
                has_none = True
                continue
            vw = [float(r) for r in w if r is not None]
            r_sum = sum(vw)
            r_sum_sq = sum(r * r for r in vw)
            has_none = False
        else:
            r_sum += r_in - r_out
            r_sum_sq += r_in * r_in - r_out * r_out

        m = r_sum / n
        var = (r_sum_sq - n * m * m) / (n - 1)
        result[i] = math.sqrt(max(var, 0.0))

    return result


def compute_vol_gk_realized(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    *,
    n: int,
) -> List[Optional[float]]:
    """Compute Garman-Klass volatility estimator with two-tier negative variance handling.

    - If input prices are invalid (H < L or non-positive): None (data quality failure).
    - If raw_variance >= 0.0: sqrt(raw_variance).
    - If |raw_variance| <= 1e-12: 0.0 (numerical roundoff guard).
    - If raw_variance < -1e-12: None (domain-defined NaN).
    required_history_bars = n (first valid at index n-1).
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    if n < 1:
        raise ValueError(f"Lookback n must be >= 1, got {n}")
    if length < n:
        return result

    coeff = 2.0 * math.log(2.0) - 1.0  # ~0.386294
    gk_series: List[Optional[float]] = [None] * length

    for i in range(length):
        o = opens[i]
        h = highs[i]
        lo = lows[i]
        c = closes[i]
        if h >= lo > 0.0 and o > 0.0 and c > 0.0:
            term1 = 0.5 * (math.log(h / lo) ** 2)
            term2 = coeff * (math.log(c / o) ** 2)
            gk_series[i] = term1 - term2
        else:
            gk_series[i] = None

    rolling_sum = sum(v for v in gk_series[: n - 1] if v is not None) if length >= n else 0.0
    has_none = any(v is None for v in gk_series[: n - 1])

    for i in range(n - 1, length):
        v_in = gk_series[i]
        v_out = gk_series[i - n + 1] if i >= n else None

        if i == n - 1:
            w = gk_series[:n]
            if any(v is None for v in w):
                result[i] = None
                continue
            raw_var = sum(float(v) for v in w if v is not None) / n
        else:
            if v_in is None or v_out is None or has_none:
                w = gk_series[i - n + 1 : i + 1]
                if any(v is None for v in w):
                    result[i] = None
                    has_none = True
                    continue
                raw_var = sum(float(v) for v in w if v is not None) / n
                has_none = False
            else:
                rolling_sum += v_in - v_out
                raw_var = rolling_sum / n

        if raw_var >= 0.0:
            result[i] = math.sqrt(raw_var)
        elif abs(raw_var) <= 1e-12:
            result[i] = 0.0
        else:
            result[i] = None

    return result


def compute_vol_zscore_12_96(
    vol_12_series: List[Optional[float]],
    *,
    window_len: int = 96,
) -> List[Optional[float]]:
    """Compute volatility Z-score of 12-bar realized vol against 96-bar rolling history.

    Boundaries:
    - If sigma == 0.0 -> 0.0
    - Else: clamp((vol_12 - mu) / sigma, -10.0, 10.0)
    required_history_bars = 108 (13 + 96 - 1).
    """
    length = len(vol_12_series)
    result: List[Optional[float]] = [None] * length
    if window_len < 2:
        raise ValueError(f"window_len must be >= 2, got {window_len}")

    start_idx = window_len - 1
    if length < window_len:
        return result

    first_w = vol_12_series[:window_len]
    has_none = any(v is None for v in first_w)
    if not has_none:
        vw = [float(v) for v in first_w if v is not None]
        r_sum = sum(vw)
        r_sum_sq = sum(v * v for v in vw)
        mu = r_sum / window_len
        var = (r_sum_sq - window_len * mu * mu) / (window_len - 1)
        sigma = math.sqrt(max(var, 0.0))
        c_vol = vol_12_series[start_idx]
        if c_vol is not None:
            z = (c_vol - mu) / sigma if sigma > 0.0 else 0.0
            result[start_idx] = min(max(z, -10.0), 10.0)
    else:
        r_sum = 0.0
        r_sum_sq = 0.0

    for i in range(window_len, length):
        v_in = vol_12_series[i]
        v_out = vol_12_series[i - window_len]
        if v_in is None or v_out is None or has_none:
            w = vol_12_series[i - window_len + 1 : i + 1]
            if any(v is None for v in w):
                result[i] = None
                has_none = True
                continue
            vw = [float(v) for v in w if v is not None]
            r_sum = sum(vw)
            r_sum_sq = sum(v * v for v in vw)
            has_none = False
        else:
            r_sum += v_in - v_out
            r_sum_sq += v_in * v_in - v_out * v_out

        mu = r_sum / window_len
        var = (r_sum_sq - window_len * mu * mu) / (window_len - 1)
        sigma = math.sqrt(max(var, 0.0))
        if v_in is not None:
            z = (v_in - mu) / sigma if sigma > 0.0 else 0.0
            result[i] = min(max(z, -10.0), 10.0)

    return result
