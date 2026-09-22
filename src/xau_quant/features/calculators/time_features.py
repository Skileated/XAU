"""Session and time feature calculators."""

import math
from datetime import datetime
from typing import Any, Dict, List, Optional


def load_session_definitions(config_data: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Return active session definitions from config or standard default."""
    if config_data and "sessions" in config_data:
        return list(config_data["sessions"])
    return [
        {"name": "asian", "utc_start_hour": 0, "utc_end_hour": 8, "bit": 1},
        {"name": "london", "utc_start_hour": 7, "utc_end_hour": 16, "bit": 2},
        {"name": "new_york", "utc_start_hour": 13, "utc_end_hour": 22, "bit": 4},
    ]


def compute_time_hour_utc(timestamps: List[datetime]) -> List[int]:
    """UTC hour in {0..23}."""
    return [ts.hour for ts in timestamps]


def compute_time_dow(timestamps: List[datetime]) -> List[int]:
    """Day of week in {0=Mon..6=Sun}."""
    return [ts.weekday() for ts in timestamps]


def compute_time_hour_sin(timestamps: List[datetime]) -> List[float]:
    """Cyclic sine encoding of hour of day: sin(2*pi * hour / 24)."""
    return [math.sin(2.0 * math.pi * ts.hour / 24.0) for ts in timestamps]


def compute_time_hour_cos(timestamps: List[datetime]) -> List[float]:
    """Cyclic cosine encoding of hour of day: cos(2*pi * hour / 24)."""
    return [math.cos(2.0 * math.pi * ts.hour / 24.0) for ts in timestamps]


def compute_time_dow_sin(timestamps: List[datetime]) -> List[float]:
    """Cyclic sine encoding of day of week: sin(2*pi * dow / 7)."""
    return [math.sin(2.0 * math.pi * ts.weekday() / 7.0) for ts in timestamps]


def compute_time_dow_cos(timestamps: List[datetime]) -> List[float]:
    """Cyclic cosine encoding of day of week: cos(2*pi * dow / 7)."""
    return [math.cos(2.0 * math.pi * ts.weekday() / 7.0) for ts in timestamps]


def compute_time_session_flags(
    timestamps: List[datetime],
    *,
    sessions: Optional[List[Dict[str, Any]]] = None,
) -> List[int]:
    """Compute active session bitwise flags from configurable definitions.

    Asian = 1, London = 2, New York = 4.
    """
    defs = sessions or load_session_definitions()
    result: List[int] = []
    for ts in timestamps:
        hour = ts.hour
        flags = 0
        for s in defs:
            start = s["utc_start_hour"]
            end = s["utc_end_hour"]
            bit = s["bit"]
            if start <= hour < end:
                flags |= bit
        result.append(flags)
    return result


def compute_time_bars_since_midnight(timestamps: List[datetime]) -> List[int]:
    """5m bar index since UTC midnight: (hour * 60 + minute) // 5 in [0, 287]."""
    return [(ts.hour * 60 + ts.minute) // 5 for ts in timestamps]


def compute_time_bars_since_week_open(timestamps: List[datetime]) -> List[int]:
    """5m bar index since Monday 00:00 UTC: dow * 288 + bars_since_midnight in [0, 2015]."""
    return [ts.weekday() * 288 + ((ts.hour * 60 + ts.minute) // 5) for ts in timestamps]
