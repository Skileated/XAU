"""Deterministic multi-timeframe candle resampler and completeness engine."""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from xau_quant.data.models import CanonicalCandle

logger = logging.getLogger(__name__)


class MultiTimeframeResampler:
    """Aggregates 1m CanonicalCandle series into higher timeframes deterministically.

    Supported target timeframes: '5m', '15m', '1h', '4h', '1d'.
    Enforces strict UTC boundaries and constituent completeness.
    """

    TIMEFRAME_CONFIG: Dict[str, Tuple[int, int]] = {
        # timeframe: (expected_1m_candles, duration_seconds)
        "5m": (5, 300),
        "15m": (15, 900),
        "1h": (60, 3600),
        "4h": (240, 14400),
        "1d": (1440, 86400),
    }

    @staticmethod
    def floor_timestamp_to_bucket(dt: datetime, timeframe: str) -> datetime:
        """Floor a UTC datetime to its enclosing timeframe boundary.

        Conventions:
        - 5m: :00, :05, :10, ..., :55
        - 15m: :00, :15, :30, :45
        - 1h: :00:00
        - 4h: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC
        - 1d: 00:00:00 UTC calendar day
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        if timeframe == "5m":
            minute = (dt.minute // 5) * 5
            return dt.replace(minute=minute, second=0, microsecond=0)
        elif timeframe == "15m":
            minute = (dt.minute // 15) * 15
            return dt.replace(minute=minute, second=0, microsecond=0)
        elif timeframe == "1h":
            return dt.replace(minute=0, second=0, microsecond=0)
        elif timeframe == "4h":
            hour = (dt.hour // 4) * 4
            return dt.replace(hour=hour, minute=0, second=0, microsecond=0)
        elif timeframe == "1d":
            return dt.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            raise ValueError(f"Unsupported timeframe for boundary alignment: {timeframe}")

    @classmethod
    def resample_bucket(
        cls,
        bucket_open_utc: datetime,
        constituent_candles: List[CanonicalCandle],
        timeframe: str,
        expected_count: int,
        duration_seconds: int,
        max_source_time_utc: Optional[datetime] = None,
    ) -> CanonicalCandle:
        """Deterministically aggregate constituent 1m candles into a single higher-timeframe
        candle.
        """
        if not constituent_candles:
            raise ValueError(f"Cannot aggregate empty candle bucket for {bucket_open_utc}")

        # Ensure constituent candles are chronologically ordered
        ordered = sorted(constituent_candles, key=lambda c: c.timestamp_utc)
        first_candle = ordered[0]
        last_candle = ordered[-1]

        # Calculate OHLC extremes and summed metrics
        open_price = first_candle.open
        high_price = max(c.high for c in ordered)
        low_price = min(c.low for c in ordered)
        close_price = last_candle.close

        total_volume = sum(c.volume for c in ordered)
        total_quote_volume = sum(c.quote_volume for c in ordered)
        total_trade_count = sum(c.trade_count for c in ordered)
        total_taker_base = sum(c.taker_buy_base_volume for c in ordered)
        total_taker_quote = sum(c.taker_buy_quote_volume for c in ordered)

        # Completeness Evaluation Invariants:
        # 1. Exactly expected number of 1m constituent candles are present
        has_full_count = len(ordered) == expected_count

        # 2. Every constituent 1m candle must be complete
        all_constituents_complete = all(c.is_complete for c in ordered)

        # 3. Period closure relative to the source series maximum timestamp
        bucket_end_utc = bucket_open_utc + timedelta(seconds=duration_seconds)
        is_period_closed = True
        if max_source_time_utc is not None:
            # For 1m candles, a candle at T covers [T, T + 60s).
            # The bucket covers [bucket_open_utc, bucket_end_utc).
            # The bucket is closed if the source data reaches at least (bucket_end_utc - 60s).
            last_expected_1m_open = bucket_end_utc - timedelta(seconds=60)
            is_period_closed = max_source_time_utc >= last_expected_1m_open

        is_complete = has_full_count and all_constituents_complete and is_period_closed

        return CanonicalCandle(
            timestamp_utc=bucket_open_utc,
            venue=first_candle.venue,
            instrument=first_candle.instrument,
            market_type=first_candle.market_type,
            timeframe=timeframe,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=total_volume,
            quote_volume=total_quote_volume,
            trade_count=total_trade_count,
            taker_buy_base_volume=total_taker_base,
            taker_buy_quote_volume=total_taker_quote,
            is_complete=is_complete,
        )

    @classmethod
    def resample(
        cls,
        candles_1m: List[CanonicalCandle],
        target_timeframe: str,
    ) -> List[CanonicalCandle]:
        """Aggregate a validated 1m candle series into a higher timeframe series.

        Returns chronologically sorted list of CanonicalCandle instances.
        """
        if not candles_1m:
            return []

        if target_timeframe not in cls.TIMEFRAME_CONFIG:
            raise ValueError(
                f"Unsupported target timeframe '{target_timeframe}'. "
                f"Supported: {list(cls.TIMEFRAME_CONFIG.keys())}"
            )

        expected_count, duration_seconds = cls.TIMEFRAME_CONFIG[target_timeframe]
        max_source_time = max(c.timestamp_utc for c in candles_1m)

        # Group 1m candles into buckets
        buckets: Dict[datetime, List[CanonicalCandle]] = defaultdict(list)
        for candle in candles_1m:
            bucket_key = cls.floor_timestamp_to_bucket(candle.timestamp_utc, target_timeframe)
            buckets[bucket_key].append(candle)

        # Construct aggregated candles
        sorted_keys = sorted(buckets.keys())
        aggregated_candles: List[CanonicalCandle] = []

        for bucket_key in sorted_keys:
            constituent = buckets[bucket_key]
            agg = cls.resample_bucket(
                bucket_open_utc=bucket_key,
                constituent_candles=constituent,
                timeframe=target_timeframe,
                expected_count=expected_count,
                duration_seconds=duration_seconds,
                max_source_time_utc=max_source_time,
            )
            aggregated_candles.append(agg)

        return aggregated_candles

    @classmethod
    def resample_all(
        cls,
        candles_1m: List[CanonicalCandle],
        timeframes: Optional[List[str]] = None,
    ) -> Dict[str, List[CanonicalCandle]]:
        """Construct all standard higher timeframes from 1m dataset.

        Default timeframes: ['5m', '15m', '1h', '4h', '1d']
        """
        if timeframes is None:
            timeframes = ["5m", "15m", "1h", "4h", "1d"]

        results: Dict[str, List[CanonicalCandle]] = {}
        for tf in timeframes:
            results[tf] = cls.resample(candles_1m, target_timeframe=tf)

        return results
