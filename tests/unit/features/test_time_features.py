"""Unit tests for session and time family calculators."""

import math
from datetime import datetime, timezone

from xau_quant.features.calculators.time_features import (
    compute_time_bars_since_midnight,
    compute_time_bars_since_week_open,
    compute_time_dow,
    compute_time_hour_cos,
    compute_time_hour_sin,
    compute_time_hour_utc,
    compute_time_session_flags,
)


def test_time_features_utc():
    # Monday 2024-01-01 07:15 UTC
    # dow = 0 (Monday), hour = 7, minute = 15
    ts = datetime(2024, 1, 1, 7, 15, tzinfo=timezone.utc)
    ts_list = [ts]

    assert compute_time_hour_utc(ts_list)[0] == 7
    assert compute_time_dow(ts_list)[0] == 0

    # cyclic hour: sin(2*pi*7/24), cos(2*pi*7/24)
    expected_h_sin = math.sin(2.0 * math.pi * 7.0 / 24.0)
    expected_h_cos = math.cos(2.0 * math.pi * 7.0 / 24.0)
    assert math.isclose(compute_time_hour_sin(ts_list)[0], expected_h_sin)
    assert math.isclose(compute_time_hour_cos(ts_list)[0], expected_h_cos)

    # session flags: at 07:15 UTC:
    # Asian (0..8) is active (bit 1)
    # London (7..16) is active (bit 2)
    # New York (13..22) is not active
    # Flags = 1 | 2 = 3
    flags = compute_time_session_flags(ts_list)
    assert flags[0] == 3

    # bars since midnight: (7 * 60 + 15) // 5 = 435 // 5 = 87
    assert compute_time_bars_since_midnight(ts_list)[0] == 87

    # bars since week open: dow=0 -> 0 * 288 + 87 = 87
    assert compute_time_bars_since_week_open(ts_list)[0] == 87
