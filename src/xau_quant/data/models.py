"""Canonical market data models for xau_quant platform."""

from datetime import datetime, timezone
from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CanonicalCandle(BaseModel):
    """Canonical representation of an OHLCV market candle.

    Preserves genuinely supplied market data without inventing missing fields.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp_utc: datetime = Field(description="Candle open timestamp in UTC timezone.")
    venue: str = Field(description="Exchange or data provider venue identifier (e.g. 'binance').")
    instrument: str = Field(description="Trading pair symbol (e.g. 'BTCUSDT').")
    market_type: str = Field(
        default="spot", description="Market type classification (e.g. 'spot', 'futures')."
    )
    timeframe: str = Field(
        default="1m", description="Candle aggregation interval (e.g. '1m', '5m', '1h')."
    )
    open: float = Field(ge=0.0, description="Opening price.")
    high: float = Field(ge=0.0, description="Highest price during interval.")
    low: float = Field(ge=0.0, description="Lowest price during interval.")
    close: float = Field(ge=0.0, description="Closing price.")
    volume: float = Field(ge=0.0, description="Base asset trading volume.")
    quote_volume: float = Field(ge=0.0, description="Quote asset trading volume.")
    trade_count: int = Field(ge=0, description="Number of completed trades in interval.")
    taker_buy_base_volume: float = Field(
        ge=0.0, description="Base asset volume executed by taker buy orders."
    )
    taker_buy_quote_volume: float = Field(
        ge=0.0, description="Quote asset volume executed by taker buy orders."
    )
    is_complete: bool = Field(
        default=True, description="True if the candle interval has closed and is immutable."
    )

    @field_validator("timestamp_utc")
    @classmethod
    def validate_utc_timezone(cls, v: datetime) -> datetime:
        """Enforce explicit UTC timezone."""
        if v.tzinfo is None:
            raise ValueError("timestamp_utc must be timezone-aware (UTC)")
        if v.tzinfo != timezone.utc:
            return v.astimezone(timezone.utc)
        return v

    def to_dict(self) -> Dict[str, Any]:
        """Convert candle model to dictionary with ISO-formatted timestamp."""
        d = self.model_dump()
        d["timestamp_utc"] = self.timestamp_utc.isoformat()
        return d
