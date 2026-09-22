"""Validators for feature engine inputs and outputs."""

import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from xau_quant.features.models import ColumnSpec, FeatureEngineInput


class FeatureValidationError(Exception):
    """Raised when feature engine input or output validation fails."""


class FeatureInputValidator:
    """Validates the input contract before feature computation."""

    @staticmethod
    def validate(payload: FeatureEngineInput) -> None:
        """Enforce strict sorting, completeness, uniqueness, and positive prices."""
        candles = payload.candles_primary
        if not candles:
            raise FeatureValidationError("Primary candle sequence cannot be empty.")

        # Primary candles validation
        prev_ts: Optional[datetime] = None
        for i, c in enumerate(candles):
            # Strict ascending check
            if prev_ts is not None and c.timestamp_utc <= prev_ts:
                raise FeatureValidationError(
                    f"Primary candle index {i} timestamp {c.timestamp_utc} "
                    f"not strictly greater than previous {prev_ts}."
                )
            prev_ts = c.timestamp_utc

            # Price validity
            if c.open <= 0 or c.high <= 0 or c.low <= 0 or c.close <= 0:
                raise FeatureValidationError(
                    f"Primary candle index {i} has non-positive OHLC: "
                    f"O={c.open}, H={c.high}, L={c.low}, C={c.close}."
                )
            if (
                c.high < c.low
                or c.high < c.open
                or c.high < c.close
                or c.low > c.open
                or c.low > c.close
            ):
                raise FeatureValidationError(
                    f"Primary candle index {i} has corrupted OHLC range: "
                    f"O={c.open}, H={c.high}, L={c.low}, C={c.close}."
                )
            if (
                c.volume < 0
                or c.quote_volume < 0
                or c.trade_count < 0
                or c.taker_buy_base_volume < 0
            ):
                raise FeatureValidationError(
                    f"Primary candle index {i} has negative volume/trades."
                )

        # Context candles validation
        for tf, ctx_candles in payload.context_candles.items():
            if not ctx_candles:
                raise FeatureValidationError(
                    f"Context candle sequence for timeframe '{tf}' is empty."
                )
            prev_ctx_ts: Optional[datetime] = None
            for j, cc in enumerate(ctx_candles):
                if prev_ctx_ts is not None and cc.timestamp_utc <= prev_ctx_ts:
                    raise FeatureValidationError(
                        f"Context candle {tf} index {j} timestamp {cc.timestamp_utc} "
                        f"not strictly greater than previous {prev_ctx_ts}."
                    )
                prev_ctx_ts = cc.timestamp_utc


class FeatureOutputValidator:
    """Validates computed feature table rows before serialization."""

    @staticmethod
    def validate_row(
        row: Dict[str, Any],
        column_specs: List[ColumnSpec],
        row_index: int,
    ) -> None:
        """Validate a single computed row against column specifications and mathematical rules."""
        # 1. Check for inf/-inf across all columns
        for col_name, val in row.items():
            if isinstance(val, float):
                if math.isinf(val):
                    raise FeatureValidationError(
                        f"Row {row_index} column '{col_name}' contains infinite value: {val}."
                    )

        # 2. Check Z-score bounds [-10.0, 10.0]
        for col in [
            "vol_zscore_12_96",
            "mr_zscore_24",
            "mr_zscore_48",
            "mr_zscore_96",
            "mtf_1h_mr_zscore_24",
        ]:
            if col in row and row[col] is not None:
                val = row[col]
                if not (math.isnan(val) or -10.0000000001 <= val <= 10.0000000001):
                    raise FeatureValidationError(
                        f"Row {row_index} column '{col}' value {val} out of bounds [-10.0, 10.0]."
                    )

        # 3. Check RSI bounds [0.0, 100.0]
        for col in ["mom_rsi_14", "mom_rsi_28", "mtf_15m_mom_rsi_14", "mtf_1h_mom_rsi_14"]:
            if col in row and row[col] is not None:
                val = row[col]
                if not (math.isnan(val) or -1e-8 <= val <= 100.00000001):
                    raise FeatureValidationError(
                        f"Row {row_index} column '{col}' value {val} out of bounds [0.0, 100.0]."
                    )

        # 4. Check Hurst proxy bounds [0.0, 1.0]
        for col in ["mr_hurst_proxy_48", "mr_hurst_proxy_96"]:
            if col in row and row[col] is not None:
                val = row[col]
                if not (math.isnan(val) or -1e-8 <= val <= 1.00000001):
                    raise FeatureValidationError(
                        f"Row {row_index} column '{col}' value {val} out of bounds [0.0, 1.0]."
                    )

        # 5. Row validity contract:
        # is_valid == (not is_warmup) and (not has_data_gap) and (data_quality_nan_count == 0)
        is_warmup = bool(row.get("is_warmup", False))
        has_data_gap = bool(row.get("has_data_gap", False))
        is_valid = bool(row.get("is_valid", False))

        # Check warm-up consistency with row_index
        if row_index < 311:
            if not is_warmup:
                raise FeatureValidationError(
                    f"Row {row_index} is within warmup period (< 311) but is_warmup is False."
                )
            if is_valid:
                raise FeatureValidationError(
                    f"Row {row_index} is within warmup period (< 311) but is_valid is True."
                )
        else:
            if is_warmup:
                raise FeatureValidationError(
                    f"Row {row_index} is post-warmup (>= 311) but is_warmup is True."
                )

        if is_valid and has_data_gap:
            raise FeatureValidationError(
                f"Row {row_index} has is_valid=True but has_data_gap=True."
            )

        # 6. Pivot event nullable column integrity:
        # If is_pivot is False, timestamp and age MUST be None
        for s in [3, 5]:
            flag_col = f"ms_is_pivot_high_{s}"
            ts_col = f"ms_pivot_high_timestamp_{s}"
            age_col = f"ms_pivot_high_age_bars_{s}"
            if flag_col in row:
                if not row[flag_col]:
                    if row.get(ts_col) is not None or row.get(age_col) is not None:
                        raise FeatureValidationError(
                            f"Row {row_index} pivot high flag {flag_col} is False "
                            "but timestamp or age is not None."
                        )
                else:
                    if row.get(ts_col) is None or row.get(age_col) is None:
                        raise FeatureValidationError(
                            f"Row {row_index} pivot high flag {flag_col} is True "
                            "but timestamp or age is None."
                        )

            low_flag_col = f"ms_is_pivot_low_{s}"
            low_ts_col = f"ms_pivot_low_timestamp_{s}"
            low_age_col = f"ms_pivot_low_age_bars_{s}"
            if low_flag_col in row:
                if not row[low_flag_col]:
                    if row.get(low_ts_col) is not None or row.get(low_age_col) is not None:
                        raise FeatureValidationError(
                            f"Row {row_index} pivot low flag {low_flag_col} is False "
                            "but timestamp or age is not None."
                        )
                else:
                    if row.get(low_ts_col) is None or row.get(low_age_col) is None:
                        raise FeatureValidationError(
                            f"Row {row_index} pivot low flag {low_flag_col} is True "
                            "but timestamp or age is None."
                        )
