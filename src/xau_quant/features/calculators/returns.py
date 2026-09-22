"""Price and returns feature calculators."""

import math
from typing import List, Optional


def compute_ret_log_cc(
    closes: List[float],
    *,
    n: int,
) -> List[Optional[float]]:
    """Compute close-to-close log return over lookback n.

    Formula: ln(C[t]) - ln(C[t-n])
    required_history_bars = n + 1 (first valid at index n).
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    if n < 1:
        raise ValueError(f"Lookback n must be >= 1, got {n}")

    for i in range(n, length):
        c_curr = closes[i]
        c_prev = closes[i - n]
        if c_curr > 0.0 and c_prev > 0.0:
            result[i] = math.log(c_curr) - math.log(c_prev)
        else:
            result[i] = None
    return result


def compute_ret_log_oc(
    opens: List[float],
    closes: List[float],
) -> List[Optional[float]]:
    """Compute intra-bar open-to-close log return.

    Formula: ln(C[t]) - ln(O[t])
    required_history_bars = 1 (first valid at index 0).
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    for i in range(length):
        o = opens[i]
        c = closes[i]
        if o > 0.0 and c > 0.0:
            result[i] = math.log(c) - math.log(o)
        else:
            result[i] = None
    return result


def compute_price_body_ratio(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    *,
    epsilon: float = 1e-8,
) -> List[Optional[float]]:
    """Compute bar body ratio.

    Formula: |C[t] - O[t]| / (H[t] - L[t] + eps)
    required_history_bars = 1.
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    for i in range(length):
        o = opens[i]
        h = highs[i]
        lo = lows[i]
        c = closes[i]
        denom = h - lo + epsilon
        if denom > 0.0:
            val = abs(c - o) / denom
            result[i] = min(max(val, 0.0), 1.0)
        else:
            result[i] = None
    return result


def compute_price_upper_wick_ratio(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    *,
    epsilon: float = 1e-8,
) -> List[Optional[float]]:
    """Compute upper wick ratio.

    Formula: (H[t] - max(O[t], C[t])) / (H[t] - L[t] + eps)
    required_history_bars = 1.
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    for i in range(length):
        o = opens[i]
        h = highs[i]
        lo = lows[i]
        c = closes[i]
        denom = h - lo + epsilon
        if denom > 0.0:
            val = (h - max(o, c)) / denom
            result[i] = min(max(val, 0.0), 1.0)
        else:
            result[i] = None
    return result


def compute_price_lower_wick_ratio(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    *,
    epsilon: float = 1e-8,
) -> List[Optional[float]]:
    """Compute lower wick ratio.

    Formula: (min(O[t], C[t]) - L[t]) / (H[t] - L[t] + eps)
    required_history_bars = 1.
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    for i in range(length):
        o = opens[i]
        h = highs[i]
        lo = lows[i]
        c = closes[i]
        denom = h - lo + epsilon
        if denom > 0.0:
            val = (min(o, c) - lo) / denom
            result[i] = min(max(val, 0.0), 1.0)
        else:
            result[i] = None
    return result


def compute_price_midpoint(
    highs: List[float],
    lows: List[float],
) -> List[Optional[float]]:
    """Compute bar midpoint price in USD.

    Formula: (H[t] + L[t]) / 2.0
    required_history_bars = 1.
    """
    length = len(highs)
    result: List[Optional[float]] = [None] * length
    for i in range(length):
        result[i] = (highs[i] + lows[i]) / 2.0
    return result
