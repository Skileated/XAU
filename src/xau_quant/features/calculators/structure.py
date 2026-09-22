"""Market structure feature calculators."""

from datetime import datetime
from typing import List, Optional, Tuple


def compute_ms_high(
    highs: List[float],
    *,
    n: int,
) -> List[Optional[float]]:
    """Compute rolling n-bar maximum high.

    required_history_bars = n (first valid at index n-1).
    """
    length = len(highs)
    result: List[Optional[float]] = [None] * length
    if n < 1:
        raise ValueError(f"Lookback n must be >= 1, got {n}")

    for i in range(n - 1, length):
        result[i] = max(highs[i - n + 1 : i + 1])
    return result


def compute_ms_low(
    lows: List[float],
    *,
    n: int,
) -> List[Optional[float]]:
    """Compute rolling n-bar minimum low.

    required_history_bars = n (first valid at index n-1).
    """
    length = len(lows)
    result: List[Optional[float]] = [None] * length
    if n < 1:
        raise ValueError(f"Lookback n must be >= 1, got {n}")

    for i in range(n - 1, length):
        result[i] = min(lows[i - n + 1 : i + 1])
    return result


def compute_ms_price_position(
    closes: List[float],
    highs: List[float],
    lows: List[float],
    *,
    n: int,
    precomputed_highs: Optional[List[Optional[float]]] = None,
    precomputed_lows: Optional[List[Optional[float]]] = None,
) -> List[Optional[float]]:
    """Compute price position within rolling n-bar range: (C - Low) / (High - Low).

    Boundary: if High == Low -> 0.5 (flat range midpoint).
    required_history_bars = n (first valid at index n-1).
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    if n < 1:
        raise ValueError(f"Lookback n must be >= 1, got {n}")

    if precomputed_highs is not None and precomputed_lows is not None:
        for i in range(n - 1, length):
            h = precomputed_highs[i]
            min_val = precomputed_lows[i]
            if h is None or min_val is None:
                result[i] = None
                continue
            rng = h - min_val
            if rng == 0.0:
                result[i] = 0.5
            else:
                val = (closes[i] - min_val) / rng
                result[i] = min(max(val, 0.0), 1.0)
        return result

    for i in range(n - 1, length):
        h = max(highs[i - n + 1 : i + 1])
        min_val = min(lows[i - n + 1 : i + 1])
        rng = h - min_val
        if rng == 0.0:
            result[i] = 0.5
        else:
            val = (closes[i] - min_val) / rng
            result[i] = min(max(val, 0.0), 1.0)
    return result


def compute_ms_bars_since_high(
    highs: List[float],
    *,
    n: int,
) -> List[Optional[int]]:
    """Compute bars elapsed since rolling n-bar high. Ties broken toward most recent.

    required_history_bars = n (first valid at index n-1).
    """
    length = len(highs)
    result: List[Optional[int]] = [None] * length
    if n < 1:
        raise ValueError(f"Lookback n must be >= 1, got {n}")

    for i in range(n - 1, length):
        window = highs[i - n + 1 : i + 1]
        max_val = max(window)
        # Find latest occurrence in window
        lag = 0
        for offset in range(n):
            if window[n - 1 - offset] == max_val:
                lag = offset
                break
        result[i] = lag
    return result


def compute_ms_bars_since_low(
    lows: List[float],
    *,
    n: int,
) -> List[Optional[int]]:
    """Compute bars elapsed since rolling n-bar low. Ties broken toward most recent.

    required_history_bars = n (first valid at index n-1).
    """
    length = len(lows)
    result: List[Optional[int]] = [None] * length
    if n < 1:
        raise ValueError(f"Lookback n must be >= 1, got {n}")

    for i in range(n - 1, length):
        window = lows[i - n + 1 : i + 1]
        min_val = min(window)
        lag = 0
        for offset in range(n):
            if window[n - 1 - offset] == min_val:
                lag = offset
                break
        result[i] = lag
    return result


def compute_ms_pivot_high(
    timestamps: List[datetime],
    highs: List[float],
    *,
    s: int,
) -> Tuple[List[Optional[bool]], List[Optional[datetime]], List[Optional[int]]]:
    """Compute pivot high indicators with confirmation-time semantics.

    Pivot high at bar k is confirmed at bar t = k + s iff:
    H[k] > H[k-j] for all j in 1..s and H[k] > H[k+j] for all j in 1..s.

    Returns tuple of (is_pivot_high, pivot_high_timestamp, pivot_high_age_bars):
    - is_pivot_high: True if confirmed at bar t, False if valid, None if < 2s.
    - pivot_high_timestamp: timestamp of bar k if confirmed, None otherwise.
    - pivot_high_age_bars: s if confirmed, None otherwise.
    required_history_bars = 2s + 1 (first valid at index 2s).
    """
    length = len(highs)
    is_pivot: List[Optional[bool]] = [None] * length
    pivot_ts: List[Optional[datetime]] = [None] * length
    pivot_age: List[Optional[int]] = [None] * length

    if s < 1:
        raise ValueError(f"Pivot strength s must be >= 1, got {s}")

    for t in range(2 * s, length):
        k = t - s
        h_k = highs[k]
        # Check left s bars: k-s .. k-1
        left_ok = all(h_k > highs[k - j] for j in range(1, s + 1))
        # Check right s bars: k+1 .. k+s = t
        right_ok = all(h_k > highs[k + j] for j in range(1, s + 1))

        if left_ok and right_ok:
            is_pivot[t] = True
            pivot_ts[t] = timestamps[k]
            pivot_age[t] = s
        else:
            is_pivot[t] = False
            pivot_ts[t] = None
            pivot_age[t] = None

    return is_pivot, pivot_ts, pivot_age


def compute_ms_pivot_low(
    timestamps: List[datetime],
    lows: List[float],
    *,
    s: int,
) -> Tuple[List[Optional[bool]], List[Optional[datetime]], List[Optional[int]]]:
    """Compute pivot low indicators with confirmation-time semantics.

    Pivot low at bar k is confirmed at bar t = k + s iff:
    L[k] < L[k-j] for all j in 1..s and L[k] < L[k+j] for all j in 1..s.
    required_history_bars = 2s + 1 (first valid at index 2s).
    """
    length = len(lows)
    is_pivot: List[Optional[bool]] = [None] * length
    pivot_ts: List[Optional[datetime]] = [None] * length
    pivot_age: List[Optional[int]] = [None] * length

    if s < 1:
        raise ValueError(f"Pivot strength s must be >= 1, got {s}")

    for t in range(2 * s, length):
        k = t - s
        l_k = lows[k]
        left_ok = all(l_k < lows[k - j] for j in range(1, s + 1))
        right_ok = all(l_k < lows[k + j] for j in range(1, s + 1))

        if left_ok and right_ok:
            is_pivot[t] = True
            pivot_ts[t] = timestamps[k]
            pivot_age[t] = s
        else:
            is_pivot[t] = False
            pivot_ts[t] = None
            pivot_age[t] = None

    return is_pivot, pivot_ts, pivot_age


def compute_ms_consec_up(
    closes: List[float],
    *,
    n: int = 5,
) -> List[Optional[int]]:
    """Compute count of consecutive bars where C[i] > C[i-1] ending at bar t, capped at n.

    required_history_bars = n + 1 (first valid at index n).
    """
    length = len(closes)
    result: List[Optional[int]] = [None] * length
    for i in range(n, length):
        count = 0
        for j in range(n):
            idx = i - j
            if closes[idx] > closes[idx - 1]:
                count += 1
            else:
                break
        result[i] = count
    return result


def compute_ms_consec_down(
    closes: List[float],
    *,
    n: int = 5,
) -> List[Optional[int]]:
    """Compute count of consecutive bars where C[i] < C[i-1] ending at bar t, capped at n.

    required_history_bars = n + 1 (first valid at index n).
    """
    length = len(closes)
    result: List[Optional[int]] = [None] * length
    for i in range(n, length):
        count = 0
        for j in range(n):
            idx = i - j
            if closes[idx] < closes[idx - 1]:
                count += 1
            else:
                break
        result[i] = count
    return result
