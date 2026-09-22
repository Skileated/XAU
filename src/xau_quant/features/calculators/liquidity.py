"""Volume and liquidity feature calculators."""

from typing import List, Optional


def compute_liq_taker_buy_ratio(
    taker_buy_base_volumes: List[float],
    volumes: List[float],
) -> List[Optional[float]]:
    """Compute taker aggression ratio: TB[t] / V[t].

    If V[t] == 0.0 -> None (domain-defined NaN).
    required_history_bars = 1.
    """
    length = len(volumes)
    result: List[Optional[float]] = [None] * length
    for i in range(length):
        v = volumes[i]
        tb = taker_buy_base_volumes[i]
        if v > 0.0:
            result[i] = min(max(tb / v, 0.0), 1.0)
        else:
            result[i] = None
    return result


def compute_liq_avg_trade_size(
    volumes: List[float],
    trade_counts: List[int],
) -> List[Optional[float]]:
    """Compute average trade size in base asset per trade: V[t] / N[t].

    If N[t] == 0 or V[t] == 0.0 -> None (domain-defined NaN).
    required_history_bars = 1.
    """
    length = len(volumes)
    result: List[Optional[float]] = [None] * length
    for i in range(length):
        n = trade_counts[i]
        v = volumes[i]
        if n > 0 and v > 0.0:
            result[i] = v / n
        else:
            result[i] = None
    return result


def compute_liq_vwap_dev(
    closes: List[float],
    quote_volumes: List[float],
    volumes: List[float],
    *,
    n: int,
) -> List[Optional[float]]:
    """Compute normalized price deviation from rolling VWAP: (C[t] - VWAP_n) / VWAP_n.

    If sum(V) == 0.0 -> None (domain-defined NaN).
    required_history_bars = n (first valid at index n-1).
    """
    length = len(closes)
    result: List[Optional[float]] = [None] * length
    if n < 1:
        raise ValueError(f"Lookback n must be >= 1, got {n}")

    rolling_qv = sum(quote_volumes[: n - 1]) if length >= n else 0.0
    rolling_v = sum(volumes[: n - 1]) if length >= n else 0.0

    for i in range(n - 1, length):
        rolling_qv += quote_volumes[i]
        rolling_v += volumes[i]

        if rolling_v > 0.0:
            vwap = rolling_qv / rolling_v
            if vwap > 0.0:
                result[i] = (closes[i] - vwap) / vwap
            else:
                result[i] = None
        else:
            result[i] = None

        rolling_qv -= quote_volumes[i - n + 1]
        rolling_v -= volumes[i - n + 1]

    return result


def compute_liq_vol_ratio(
    volumes: List[float],
    *,
    n: int,
) -> List[Optional[float]]:
    """Compute volume ratio relative to rolling n-bar average: V[t] / mean(V).

    If mean(V) == 0.0 -> None (domain-defined NaN).
    required_history_bars = n (first valid at index n-1).
    """
    length = len(volumes)
    result: List[Optional[float]] = [None] * length
    if n < 1:
        raise ValueError(f"Lookback n must be >= 1, got {n}")

    rolling_v = sum(volumes[: n - 1]) if length >= n else 0.0
    for i in range(n - 1, length):
        rolling_v += volumes[i]
        mean_v = rolling_v / n
        if mean_v > 0.0:
            result[i] = volumes[i] / mean_v
        else:
            result[i] = None
        rolling_v -= volumes[i - n + 1]

    return result


def compute_liq_dollar_volume(
    quote_volumes: List[float],
) -> List[Optional[float]]:
    """Re-expose bar quote volume in USD.

    required_history_bars = 1.
    """
    return [float(qv) for qv in quote_volumes]


def compute_liq_delta_proxy(
    taker_buy_base_volumes: List[float],
    volumes: List[float],
) -> List[Optional[float]]:
    """Compute single-bar cumulative delta proxy: (2*TB - V) / V.

    If V[t] == 0.0 -> None (domain-defined NaN).
    required_history_bars = 1.
    """
    length = len(volumes)
    result: List[Optional[float]] = [None] * length
    for i in range(length):
        v = volumes[i]
        tb = taker_buy_base_volumes[i]
        if v > 0.0:
            cd = 2.0 * tb - v
            result[i] = min(max(cd / v, -1.0), 1.0)
        else:
            result[i] = None
    return result


def compute_liq_cum_delta(
    taker_buy_base_volumes: List[float],
    volumes: List[float],
    *,
    n: int,
) -> List[Optional[float]]:
    """Compute normalized cumulative delta proxy over rolling n bars: sum(2*TB - V) / sum(V).

    If sum(V) == 0.0 -> None (domain-defined NaN).
    required_history_bars = n (first valid at index n-1).
    """
    length = len(volumes)
    result: List[Optional[float]] = [None] * length
    if n < 1:
        raise ValueError(f"Lookback n must be >= 1, got {n}")

    cd_series = [2.0 * tb - v for tb, v in zip(taker_buy_base_volumes, volumes)]
    rolling_cd = sum(cd_series[: n - 1]) if length >= n else 0.0
    rolling_v = sum(volumes[: n - 1]) if length >= n else 0.0

    for i in range(n - 1, length):
        rolling_cd += cd_series[i]
        rolling_v += volumes[i]

        if rolling_v > 0.0:
            result[i] = min(max(rolling_cd / rolling_v, -1.0), 1.0)
        else:
            result[i] = None

        rolling_cd -= cd_series[i - n + 1]
        rolling_v -= volumes[i - n + 1]

    return result
