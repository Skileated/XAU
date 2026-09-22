"""Mean-reversion feature calculators."""

import math
from typing import List, Optional


def compute_mr_zscore(
    closes: List[float],
    *,
    n: int,
) -> List[Optional[float]]:
    """Compute rolling Z-score of close price against its n-bar history.

    Boundary: if sigma == 0.0 -> 0.0 (flat series zero variance).
    Clamped to [-10.0, 10.0].
    required_history_bars = n (first valid at index n-1).
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    if n < 2:
        raise ValueError(f"Lookback n must be >= 2, got {n}")
    if length < n:
        return result

    # Rolling sum of C and C^2
    r_sum = sum(closes[:n])
    r_sum_sq = sum(c * c for c in closes[:n])

    mu = r_sum / n
    var = max((r_sum_sq - n * mu * mu) / (n - 1), 0.0)
    sigma = math.sqrt(var)
    result[n - 1] = 0.0 if sigma == 0.0 else min(max((closes[n - 1] - mu) / sigma, -10.0), 10.0)

    for i in range(n, length):
        c_in = closes[i]
        c_out = closes[i - n]
        r_sum += c_in - c_out
        r_sum_sq += c_in * c_in - c_out * c_out

        mu = r_sum / n
        var = max((r_sum_sq - n * mu * mu) / (n - 1), 0.0)
        sigma = math.sqrt(var)
        result[i] = 0.0 if sigma == 0.0 else min(max((c_in - mu) / sigma, -10.0), 10.0)

    return result


def compute_mr_mean_dev(
    closes: List[float],
    *,
    n: int,
    epsilon: float = 1e-8,
) -> List[Optional[float]]:
    """Compute normalized price distance from rolling mean: (C[t] - mu) / (mu + eps).

    required_history_bars = n (first valid at index n-1).
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    if n < 1:
        raise ValueError(f"Lookback n must be >= 1, got {n}")

    rolling_sum = sum(closes[: n - 1]) if length >= n else 0.0
    for i in range(n - 1, length):
        rolling_sum += closes[i]
        mu = rolling_sum / n
        result[i] = (closes[i] - mu) / (mu + epsilon)
        rolling_sum -= closes[i - n + 1]
    return result


def compute_mr_hurst_proxy(
    closes: List[float],
    *,
    n: int,
    log_returns: Optional[List[Optional[float]]] = None,
) -> List[Optional[float]]:
    """Compute single-window Rescaled Range (R/S) Hurst proxy on log-returns.

    Computation:
    1. Returns r[k] = ln(C[t-n+1+k]) - ln(C[t-n+k]) for k = 0..n-1.
    2. Mean return m = mean(r).
    3. Profile Z_j = sum_{k=0}^{j-1} (r_k - m), with Z_0 = 0.0, Z_n = 0.0.
    4. Range R = max(Z) - min(Z).
    5. Sample std S = sqrt(sum((r - m)^2) / (n - 1)).
    6. Boundary: if S == 0.0 or R == 0.0 -> 0.5.
       Else: clamp(ln(R / S) / ln(n), 0.0, 1.0).

    required_history_bars = n + 1 (first valid at index n).
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    if n < 2:
        raise ValueError(f"Lookback n must be >= 2, got {n}")
    if length <= n:
        return result

    log_n = math.log(n)

    lr_list: List[Optional[float]]
    if log_returns is None:
        lr_list = [None] * length
        for k in range(1, length):
            c_curr = closes[k]
            c_prev = closes[k - 1]
            if c_curr > 0.0 and c_prev > 0.0:
                lr_list[k] = math.log(c_curr) - math.log(c_prev)
    else:
        if len(log_returns) == length - 1:
            lr_list = [None]
            lr_list.extend(log_returns)
        else:
            lr_list = list(log_returns)

    for i in range(n, length):
        # Window of n returns ending at bar i: bars i-n+1..i
        window = lr_list[i - n + 1 : i + 1]
        if any(v is None for v in window):
            result[i] = None
            continue

        r = [float(v) for v in window if v is not None]
        m = sum(r) / n

        # Cumulative mean-centered profile Z (scalar tracking without list allocation)
        curr_z = 0.0
        min_z = 0.0
        max_z = 0.0
        var_sum = 0.0
        for val in r:
            curr_z += val - m
            if curr_z > max_z:
                max_z = curr_z
            elif curr_z < min_z:
                min_z = curr_z
            diff = val - m
            var_sum += diff * diff

        rng = max_z - min_z
        var = var_sum / (n - 1)
        s = math.sqrt(max(var, 0.0))

        if s == 0.0 or rng == 0.0:
            result[i] = 0.5
        else:
            rs = rng / s
            val = math.log(rs) / log_n
            result[i] = min(max(val, 0.0), 1.0)

    return result


def compute_mr_autocorr_lag1(
    closes: List[float],
    *,
    n: int,
    log_returns: Optional[List[Optional[float]]] = None,
) -> List[Optional[float]]:
    """Compute lag-1 autocorrelation of log-returns over rolling n returns.

    Requires n+1 returns, which require n+2 closes.
    required_history_bars = n + 2 (first valid at index n+1).
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    if n < 2:
        raise ValueError(f"Lookback n must be >= 2, got {n}")
    if length < n + 2:
        return result

    lr_list: List[Optional[float]]
    if log_returns is None:
        lr_list = [None] * length
        for k in range(1, length):
            c_curr = closes[k]
            c_prev = closes[k - 1]
            if c_curr > 0.0 and c_prev > 0.0:
                lr_list[k] = math.log(c_curr) - math.log(c_prev)
    else:
        if len(log_returns) == length - 1:
            lr_list = [None]
            lr_list.extend(log_returns)
        else:
            lr_list = list(log_returns)

    for i in range(n + 1, length):
        window = lr_list[i - n : i + 1]
        if any(v is None for v in window):
            result[i] = None
            continue

        all_r = [float(v) for v in window if v is not None]
        sum_x = 0.0
        sum_y = 0.0
        sum_xx = 0.0
        sum_yy = 0.0
        sum_xy = 0.0
        for k in range(n):
            yk = all_r[k]
            xk = all_r[k + 1]
            sum_x += xk
            sum_y += yk
            sum_xx += xk * xk
            sum_yy += yk * yk
            sum_xy += xk * yk

        mean_x = sum_x / n
        mean_y = sum_y / n

        cov = sum_xy - n * mean_x * mean_y
        var_x = sum_xx - n * mean_x * mean_x
        var_y = sum_yy - n * mean_y * mean_y

        denom = math.sqrt(max(var_x * var_y, 0.0))
        if denom == 0.0:
            result[i] = 0.0
        else:
            r_val = cov / denom
            result[i] = min(max(r_val, -1.0), 1.0)

    return result
