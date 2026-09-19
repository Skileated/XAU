"""Normalization pipeline transforming raw exchange data into CanonicalCandle models."""

import json
from datetime import datetime, timezone
from typing import Any, List, Union

from xau_quant.data.models import CanonicalCandle


class BinanceKlineNormalizer:
    """Normalizes raw Binance kline arrays into CanonicalCandle instances."""

    @staticmethod
    def normalize_kline(
        raw_kline: List[Any],
        instrument: str = "BTCUSDT",
        venue: str = "binance",
        market_type: str = "spot",
        timeframe: str = "1m",
    ) -> CanonicalCandle:
        """Parse a single raw Binance kline record into a CanonicalCandle.

        Binance Kline Index Mapping:
        0: Open time (ms)
        1: Open price
        2: High price
        3: Low price
        4: Close price
        5: Volume (base asset)
        6: Close time (ms)
        7: Quote asset volume
        8: Number of trades
        9: Taker buy base asset volume
        10: Taker buy quote asset volume
        11: Ignore
        """
        if len(raw_kline) < 11:
            raise ValueError(
                f"Malformed Binance kline record, expected >=11 elements, got {len(raw_kline)}"
            )

        open_time_ms = int(raw_kline[0])
        timestamp_utc = datetime.fromtimestamp(open_time_ms / 1000.0, tz=timezone.utc)

        return CanonicalCandle(
            timestamp_utc=timestamp_utc,
            venue=venue.lower(),
            instrument=instrument.upper(),
            market_type=market_type.lower(),
            timeframe=timeframe,
            open=float(raw_kline[1]),
            high=float(raw_kline[2]),
            low=float(raw_kline[3]),
            close=float(raw_kline[4]),
            volume=float(raw_kline[5]),
            quote_volume=float(raw_kline[7]),
            trade_count=int(raw_kline[8]),
            taker_buy_base_volume=float(raw_kline[9]),
            taker_buy_quote_volume=float(raw_kline[10]),
            is_complete=True,
        )

    @classmethod
    def normalize_payload(
        cls,
        raw_payload: Union[bytes, str, List[List[Any]]],
        instrument: str = "BTCUSDT",
        venue: str = "binance",
        market_type: str = "spot",
        timeframe: str = "1m",
    ) -> List[CanonicalCandle]:
        """Parse a full JSON payload of klines into a list of CanonicalCandle objects."""
        if isinstance(raw_payload, bytes):
            records = json.loads(raw_payload.decode("utf-8"))
        elif isinstance(raw_payload, str):
            records = json.loads(raw_payload)
        elif isinstance(raw_payload, list):
            records = raw_payload
        else:
            raise TypeError(f"Unsupported payload type: {type(raw_payload)}")

        if not isinstance(records, list):
            raise ValueError(f"Expected list of records, got {type(records)}")

        candles: List[CanonicalCandle] = []
        for item in records:
            if not isinstance(item, list):
                raise ValueError(f"Expected candle array, got {type(item)}")
            candle = cls.normalize_kline(
                raw_kline=item,
                instrument=instrument,
                venue=venue,
                market_type=market_type,
                timeframe=timeframe,
            )
            candles.append(candle)

        return candles
