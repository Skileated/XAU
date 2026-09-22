"""Momentum feature calculators."""

import math
from typing import List, Optional


def compute_mom_roc(
    closes: List[float],
    *,
    n: int,
) -> List[Optional[float]]:
    """Compute Rate of Change (ROC).

    Formula: (C[t] - C[t-n]) / C[t-n]
    required_history_bars = n + 1 (first valid at index n).
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    if n < 1:
        raise ValueError(f"Lookback n must be >= 1, got {n}")

    for i in range(n, length):
        c_curr = closes[i]
        c_prev = closes[i - n]
        if c_prev > 0.0:
            result[i] = (c_curr - c_prev) / c_prev
        else:
            result[i] = None
    return result


def compute_mom_slope(
    closes: List[float],
    *,
    n: int,
    log_closes: Optional[List[float]] = None,
    epsilon: float = 1e-8,
) -> List[Optional[float]]:
    """Compute OLS log-price slope over rolling n bars.

    Formula: slope * n / (|ln(C[t])| + eps)
    required_history_bars = n (first valid at index n-1).
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    if n < 2:
        raise ValueError(f"Lookback n must be >= 2 for OLS slope, got {n}")
    if length < n:
        return result

    if log_closes is None:
        lc = [math.log(c) if c > 0.0 else float("nan") for c in closes]
    else:
        lc = log_closes

    x_bar = (n - 1) / 2.0
    s_xx = n * (n * n - 1) / 12.0
    weights = [k - x_bar for k in range(n)]

    for i in range(n - 1, length):
        c_curr = closes[i]
        if c_curr <= 0.0:
            result[i] = None
            continue

        log_window = lc[i - n + 1 : i + 1]
        if any(math.isnan(v) for v in log_window):
            result[i] = None
            continue

        s_xy = sum(w * y for w, y in zip(weights, log_window))
        slope = s_xy / s_xx

        denom = abs(lc[i]) + epsilon
        result[i] = (slope * n) / denom
    return result


def compute_mom_sma_dev(
    closes: List[float],
    *,
    n: int,
) -> List[Optional[float]]:
    """Compute deviation from rolling Simple Moving Average.

    Formula: (C[t] - SMA_n[t]) / SMA_n[t]
    required_history_bars = n (first valid at index n-1).
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    if n < 1:
        raise ValueError(f"Lookback n must be >= 1, got {n}")

    rolling_sum = sum(closes[: n - 1]) if length >= n else 0.0
    for i in range(n - 1, length):
        rolling_sum += closes[i]
        sma = rolling_sum / n
        if sma > 0.0:
            result[i] = (closes[i] - sma) / sma
        else:
            result[i] = None
        rolling_sum -= closes[i - n + 1]
    return result


def compute_mom_ema_dev(
    closes: List[float],
    *,
    n: int,
) -> List[Optional[float]]:
    """Compute deviation from SMA-seeded Exponential Moving Average.

    Initialization at index n-1: mean(C[0..n-1]).
    Update for i >= n: alpha * C[i] + (1 - alpha) * EMA[i-1].
    required_history_bars = n (first valid at index n-1).
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    if n < 1:
        raise ValueError(f"Lookback n must be >= 1, got {n}")
    if length < n:
        return result

    # SMA seed at index n-1
    ema = sum(closes[:n]) / n
    if ema > 0.0:
        result[n - 1] = (closes[n - 1] - ema) / ema

    alpha = 2.0 / (n + 1.0)
    for i in range(n, length):
        ema = alpha * closes[i] + (1.0 - alpha) * ema
        if ema > 0.0:
            result[i] = (closes[i] - ema) / ema
        else:
            result[i] = None
    return result


def compute_mom_macd_hist(
    closes: List[float],
    *,
    n_fast: int = 12,
    n_slow: int = 26,
    n_signal: int = 9,
) -> List[Optional[float]]:
    """Compute normalized MACD Histogram using natural composition of SMA-seeded EMAs.

    - EMA_fast (12): seeded at index 11, updated recursively through all bars.
    - EMA_slow (26): seeded at index 25, updated recursively through all bars.
    - MACD_line: first valid at index 25 = EMA_fast[i] - EMA_slow[i].
    - MACD_signal: 9-period SMA-seeded EMA of MACD_line, seeded over MACD_line[25..33].
    - MACD_hist: (MACD_line[t] - MACD_signal[t]) / C[t].
    required_history_bars = 34 (first valid at index 33).
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    if length < 34:
        return result

    # Compute full EMA_fast series (valid from index 11)
    ema_fast: List[Optional[float]] = [None] * length
    curr_fast = sum(closes[:n_fast]) / n_fast
    ema_fast[n_fast - 1] = curr_fast
    alpha_fast = 2.0 / (n_fast + 1.0)
    for i in range(n_fast, length):
        curr_fast = alpha_fast * closes[i] + (1.0 - alpha_fast) * curr_fast
        ema_fast[i] = curr_fast

    # Compute full EMA_slow series (valid from index 25)
    ema_slow: List[Optional[float]] = [None] * length
    curr_slow = sum(closes[:n_slow]) / n_slow
    ema_slow[n_slow - 1] = curr_slow
    alpha_slow = 2.0 / (n_slow + 1.0)
    for i in range(n_slow, length):
        curr_slow = alpha_slow * closes[i] + (1.0 - alpha_slow) * curr_slow
        ema_slow[i] = curr_slow

    # MACD Line (valid from index 25)
    macd_line: List[Optional[float]] = [None] * length
    for i in range(n_slow - 1, length):
        f = ema_fast[i]
        s = ema_slow[i]
        if f is not None and s is not None:
            macd_line[i] = f - s

    # Signal Line: 9-period SMA-seeded EMA of MACD_line
    # Seed uses macd_line[25..33] (indices 25 to 25 + 9 - 1 = 33)
    seed_start = n_slow - 1
    seed_end = seed_start + n_signal  # 25 + 9 = 34 (slice index)
    signal_seed_vals = macd_line[seed_start:seed_end]
    if any(v is None for v in signal_seed_vals):
        return result

    signal = sum(v for v in signal_seed_vals if v is not None) / n_signal
    c33 = closes[seed_end - 1]
    line33 = macd_line[seed_end - 1]
    if c33 > 0.0 and line33 is not None:
        result[seed_end - 1] = (line33 - signal) / c33

    alpha_signal = 2.0 / (n_signal + 1.0)
    for i in range(seed_end, length):
        curr_line = macd_line[i]
        if curr_line is not None:
            signal = alpha_signal * curr_line + (1.0 - alpha_signal) * signal
            c = closes[i]
            if c > 0.0:
                result[i] = (curr_line - signal) / c
            else:
                result[i] = None
        else:
            result[i] = None

    return result


def compute_mom_rsi(
    closes: List[float],
    *,
    n: int = 14,
) -> List[Optional[float]]:
    """Compute Relative Strength Index (RSI) with Wilder smoothing and exact boundary semantics.

    Boundaries:
    - AvgD == 0.0 and AvgU > 0.0 -> 100.0 exactly
    - AvgU == 0.0 and AvgD > 0.0 -> 0.0 exactly
    - AvgU == 0.0 and AvgD == 0.0 -> 50.0 exactly (flat neutrality)
    - Else: 100.0 - 100.0 / (1.0 + AvgU / AvgD)
    required_history_bars = n + 1 (first valid at index n).
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    if n < 1:
        raise ValueError(f"Lookback n must be >= 1, got {n}")
    if length <= n:
        return result

    # Compute initial deltas
    deltas = [closes[i] - closes[i - 1] for i in range(1, length)]
    # First n deltas are deltas[0..n-1], corresponding to closes[0..n]
    avg_u = sum(max(d, 0.0) for d in deltas[:n]) / n
    avg_d = sum(max(-d, 0.0) for d in deltas[:n]) / n

    def _eval_rsi(u: float, d: float) -> float:
        if d == 0.0 and u > 0.0:
            return 100.0
        if u == 0.0 and d > 0.0:
            return 0.0
        if u == 0.0 and d == 0.0:
            return 50.0
        rs = u / d
        return 100.0 - (100.0 / (1.0 + rs))

    result[n] = _eval_rsi(avg_u, avg_d)

    # Wilder update
    for i in range(n + 1, length):
        delta = deltas[i - 1]
        u = max(delta, 0.0)
        d = max(-delta, 0.0)
        avg_u = ((n - 1) * avg_u + u) / n
        avg_d = ((n - 1) * avg_d + d) / n
        result[i] = _eval_rsi(avg_u, avg_d)

    return result
