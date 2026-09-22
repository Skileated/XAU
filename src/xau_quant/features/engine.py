"""Feature calculation engine coordinating all feature families and row validity contracts."""

import math
from typing import Any, Dict, List, Optional

from xau_quant.features.calculators.liquidity import (
    compute_liq_avg_trade_size,
    compute_liq_cum_delta,
    compute_liq_delta_proxy,
    compute_liq_dollar_volume,
    compute_liq_taker_buy_ratio,
    compute_liq_vol_ratio,
    compute_liq_vwap_dev,
)
from xau_quant.features.calculators.meanreversion import (
    compute_mr_autocorr_lag1,
    compute_mr_hurst_proxy,
    compute_mr_mean_dev,
    compute_mr_zscore,
)
from xau_quant.features.calculators.momentum import (
    compute_mom_ema_dev,
    compute_mom_macd_hist,
    compute_mom_roc,
    compute_mom_rsi,
    compute_mom_slope,
    compute_mom_sma_dev,
)
from xau_quant.features.calculators.multitimeframe import (
    align_5m_to_htf_open,
    compute_htf_precomputed_series,
    compute_mtf_1m_microstructure,
)
from xau_quant.features.calculators.returns import (
    compute_price_body_ratio,
    compute_price_lower_wick_ratio,
    compute_price_midpoint,
    compute_price_upper_wick_ratio,
    compute_ret_log_cc,
    compute_ret_log_oc,
)
from xau_quant.features.calculators.structure import (
    compute_ms_bars_since_high,
    compute_ms_bars_since_low,
    compute_ms_consec_down,
    compute_ms_consec_up,
    compute_ms_high,
    compute_ms_low,
    compute_ms_pivot_high,
    compute_ms_pivot_low,
    compute_ms_price_position,
)
from xau_quant.features.calculators.time_features import (
    compute_time_bars_since_midnight,
    compute_time_bars_since_week_open,
    compute_time_dow,
    compute_time_dow_cos,
    compute_time_dow_sin,
    compute_time_hour_cos,
    compute_time_hour_sin,
    compute_time_hour_utc,
    compute_time_session_flags,
)
from xau_quant.features.calculators.volatility import (
    compute_vol_atr,
    compute_vol_atr_pct,
    compute_vol_gk_realized,
    compute_vol_realized,
    compute_vol_zscore_12_96,
)
from xau_quant.features.models import FeatureEngineInput
from xau_quant.features.registry import FeatureRegistry
from xau_quant.features.validators import FeatureInputValidator, FeatureOutputValidator


class FeatureEngine:
    """Orchestrates batch market feature computation over primary and context candles."""

    def __init__(self, registry: Optional[FeatureRegistry] = None) -> None:
        self.registry = registry or FeatureRegistry()

    def compute(self, payload: FeatureEngineInput) -> List[Dict[str, Any]]:
        """Compute full feature dataset satisfying the Revision 5.1 specification contract.

        Returns:
            List of dictionary rows matching the registry schema exactly.
        """
        # 1. Validate inputs
        FeatureInputValidator.validate(payload)

        candles_5m = list(payload.candles_primary)
        n_bars = len(candles_5m)

        # Extract series
        timestamps = [c.timestamp_utc for c in candles_5m]
        opens = [c.open for c in candles_5m]
        highs = [c.high for c in candles_5m]
        lows = [c.low for c in candles_5m]
        closes = [c.close for c in candles_5m]
        volumes = [c.volume for c in candles_5m]
        quote_volumes = [c.quote_volume for c in candles_5m]
        trades = [c.trade_count for c in candles_5m]
        tb_volumes = [c.taker_buy_base_volume for c in candles_5m]

        log_closes = [math.log(c) if c > 0.0 else float("nan") for c in closes]
        log_returns = compute_ret_log_cc(closes, n=1)

        features_data: Dict[str, List[Any]] = {}

        # -------------------------------------------------------------
        # 1. Returns Family
        # -------------------------------------------------------------
        features_data["ret_log_cc_1"] = log_returns
        for n in [3, 6, 12, 24, 48, 96]:
            features_data[f"ret_log_cc_{n}"] = compute_ret_log_cc(closes, n=n)

        features_data["ret_log_oc"] = compute_ret_log_oc(opens, closes)
        features_data["price_body_ratio"] = compute_price_body_ratio(opens, highs, lows, closes)
        features_data["price_upper_wick_ratio"] = compute_price_upper_wick_ratio(
            opens, highs, lows, closes
        )
        features_data["price_lower_wick_ratio"] = compute_price_lower_wick_ratio(
            opens, highs, lows, closes
        )
        features_data["price_midpoint"] = compute_price_midpoint(highs, lows)

        # -------------------------------------------------------------
        # 2. Momentum Family
        # -------------------------------------------------------------
        for n in [6, 12, 24, 48]:
            features_data[f"mom_roc_{n}"] = compute_mom_roc(closes, n=n)

        for n in [12, 24, 48]:
            features_data[f"mom_slope_{n}"] = compute_mom_slope(
                closes, n=n, log_closes=log_closes
            )

        for n in [12, 24, 48, 96]:
            features_data[f"mom_sma_dev_{n}"] = compute_mom_sma_dev(closes, n=n)

        for n in [12, 26, 50]:
            features_data[f"mom_ema_dev_{n}"] = compute_mom_ema_dev(closes, n=n)

        features_data["mom_macd_hist"] = compute_mom_macd_hist(
            closes, n_fast=12, n_slow=26, n_signal=9
        )

        for n in [14, 28]:
            features_data[f"mom_rsi_{n}"] = compute_mom_rsi(closes, n=n)

        # -------------------------------------------------------------
        # 3. Volatility Family
        # -------------------------------------------------------------
        for n in [14, 28]:
            features_data[f"vol_atr_{n}"] = compute_vol_atr(highs, lows, closes, n=n)
            features_data[f"vol_atr_pct_{n}"] = compute_vol_atr_pct(highs, lows, closes, n=n)

        for n in [12, 24, 48, 96]:
            features_data[f"vol_realized_{n}"] = compute_vol_realized(
                closes, n=n, returns=log_returns
            )

        for n in [12, 24]:
            features_data[f"vol_gk_realized_{n}"] = compute_vol_gk_realized(
                opens, highs, lows, closes, n=n
            )

        features_data["vol_zscore_12_96"] = compute_vol_zscore_12_96(
            features_data["vol_realized_12"], window_len=96
        )

        # -------------------------------------------------------------
        # 4. Liquidity Family
        # -------------------------------------------------------------
        features_data["liq_taker_buy_ratio"] = compute_liq_taker_buy_ratio(tb_volumes, volumes)
        features_data["liq_avg_trade_size"] = compute_liq_avg_trade_size(volumes, trades)
        features_data["liq_dollar_volume"] = compute_liq_dollar_volume(quote_volumes)
        features_data["liq_delta_proxy"] = compute_liq_delta_proxy(tb_volumes, volumes)

        for n in [12, 48]:
            features_data[f"liq_vwap_dev_{n}"] = compute_liq_vwap_dev(
                closes, quote_volumes, volumes, n=n
            )

        for n in [12, 24, 48]:
            features_data[f"liq_vol_ratio_{n}"] = compute_liq_vol_ratio(volumes, n=n)

        for n in [12, 48]:
            features_data[f"liq_cum_delta_{n}"] = compute_liq_cum_delta(tb_volumes, volumes, n=n)

        # -------------------------------------------------------------
        # 5. Market Structure Family
        # -------------------------------------------------------------
        for n in [12, 24, 48, 96]:
            h_series = compute_ms_high(highs, n=n)
            l_series = compute_ms_low(lows, n=n)
            features_data[f"ms_high_{n}"] = h_series
            features_data[f"ms_low_{n}"] = l_series
            features_data[f"ms_price_position_{n}"] = compute_ms_price_position(
                closes,
                highs,
                lows,
                n=n,
                precomputed_highs=h_series,
                precomputed_lows=l_series,
            )

        for n in [24, 96]:
            features_data[f"ms_bars_since_high_{n}"] = compute_ms_bars_since_high(highs, n=n)
            features_data[f"ms_bars_since_low_{n}"] = compute_ms_bars_since_low(lows, n=n)

        for s in [3, 5]:
            h_flags, h_ts, h_ages = compute_ms_pivot_high(timestamps, highs, s=s)
            features_data[f"ms_is_pivot_high_{s}"] = h_flags
            features_data[f"ms_pivot_high_timestamp_{s}"] = h_ts
            features_data[f"ms_pivot_high_age_bars_{s}"] = h_ages

            l_flags, l_ts, l_ages = compute_ms_pivot_low(timestamps, lows, s=s)
            features_data[f"ms_is_pivot_low_{s}"] = l_flags
            features_data[f"ms_pivot_low_timestamp_{s}"] = l_ts
            features_data[f"ms_pivot_low_age_bars_{s}"] = l_ages

        features_data["ms_consec_up_5"] = compute_ms_consec_up(closes, n=5)
        features_data["ms_consec_down_5"] = compute_ms_consec_down(closes, n=5)

        # -------------------------------------------------------------
        # 6. Mean-Reversion Family
        # -------------------------------------------------------------
        for n in [24, 48, 96]:
            features_data[f"mr_zscore_{n}"] = compute_mr_zscore(closes, n=n)

        for n in [12, 48]:
            features_data[f"mr_mean_dev_{n}"] = compute_mr_mean_dev(closes, n=n)

        for n in [48, 96]:
            features_data[f"mr_hurst_proxy_{n}"] = compute_mr_hurst_proxy(
                closes, n=n, log_returns=log_returns
            )

        for n in [24, 96]:
            features_data[f"mr_autocorr_lag1_{n}"] = compute_mr_autocorr_lag1(
                closes, n=n, log_returns=log_returns
            )

        # -------------------------------------------------------------
        # 7. Session and Time Family
        # -------------------------------------------------------------
        features_data["time_hour_utc"] = compute_time_hour_utc(timestamps)
        features_data["time_dow"] = compute_time_dow(timestamps)
        features_data["time_hour_sin"] = compute_time_hour_sin(timestamps)
        features_data["time_hour_cos"] = compute_time_hour_cos(timestamps)
        features_data["time_dow_sin"] = compute_time_dow_sin(timestamps)
        features_data["time_dow_cos"] = compute_time_dow_cos(timestamps)
        features_data["time_session_flags"] = compute_time_session_flags(timestamps)
        features_data["time_bars_since_midnight"] = compute_time_bars_since_midnight(timestamps)
        features_data["time_bars_since_week_open"] = compute_time_bars_since_week_open(timestamps)

        # -------------------------------------------------------------
        # 8. Multi-Timeframe (MTF) Family
        # -------------------------------------------------------------
        # 15m HTF Context
        ctx_15m = list(payload.context_candles.get("15m", ()))
        htf_15m_map = compute_htf_precomputed_series(ctx_15m, "15m") if ctx_15m else {}
        for feat_name in [
            "mtf_15m_ret_log_cc_4",
            "mtf_15m_ret_log_cc_16",
            "mtf_15m_mom_rsi_14",
            "mtf_15m_vol_atr_pct_14",
            "mtf_15m_price_position_16",
            "mtf_15m_liq_taker_buy_ratio",
            "mtf_15m_liq_vol_ratio_16",
        ]:
            val_map = htf_15m_map.get(feat_name, {})
            feat_series: List[Optional[float]] = []
            for t in timestamps:
                t_15m = align_5m_to_htf_open(t, 900)
                feat_series.append(val_map.get(t_15m))
            features_data[feat_name] = feat_series

        # 1h HTF Context
        ctx_1h = list(payload.context_candles.get("1h", ()))
        htf_1h_map = compute_htf_precomputed_series(ctx_1h, "1h") if ctx_1h else {}
        for feat_name in [
            "mtf_1h_ret_log_cc_4",
            "mtf_1h_ret_log_cc_24",
            "mtf_1h_mom_rsi_14",
            "mtf_1h_vol_realized_24",
            "mtf_1h_price_position_24",
            "mtf_1h_mr_zscore_24",
            "mtf_1h_liq_taker_buy_ratio",
        ]:
            val_map = htf_1h_map.get(feat_name, {})
            feat_series = []
            for t in timestamps:
                t_1h = align_5m_to_htf_open(t, 3600)
                feat_series.append(val_map.get(t_1h))
            features_data[feat_name] = feat_series

        # 1m Microstructure Context
        ctx_1m = list(payload.context_candles.get("1m", ()))
        candles_1m_map = {c.timestamp_utc: c for c in ctx_1m}
        micro_data = compute_mtf_1m_microstructure(candles_5m, candles_1m_map)
        features_data.update(micro_data)

        # -------------------------------------------------------------
        # 9. Assemble Rows and Apply Validity & Decoupling Contracts
        # -------------------------------------------------------------
        all_feature_cols = self.registry.get_all_column_specs()
        non_nullable_col_names = [col.name for col in all_feature_cols if not col.nullable]

        # Track gaps in primary data
        # Consecutive-bar check: standard 5m bar gap is 300 seconds
        has_gap_series: List[bool] = [False] * n_bars
        bars_since_gap = 999999
        for i in range(1, n_bars):
            dt = (timestamps[i] - timestamps[i - 1]).total_seconds()
            if dt > 300.0:
                bars_since_gap = 0
            else:
                bars_since_gap += 1

            # Window of 311 bars crossing a gap
            if bars_since_gap < 311:
                has_gap_series[i] = True

        feature_names = [col.name for col in all_feature_cols]
        feature_series = [features_data[name] for name in feature_names]
        num_features = len(feature_names)

        rows: List[Dict[str, Any]] = []

        for i in range(n_bars):
            is_warmup = i < 311
            has_data_gap = has_gap_series[i]

            # Domain-defined NaN detection for bar i
            domain_nan_count = 0
            v_i = volumes[i]
            if v_i == 0.0:
                # Zero-volume liquidity domain NaNs
                # liq_taker_buy_ratio, liq_avg_trade_size, liq_delta_proxy
                domain_nan_count += 3

            # Check Garman-Klass domain NaN
            for gk_col in ["vol_gk_realized_12", "vol_gk_realized_24"]:
                if features_data[gk_col][i] is None and not is_warmup and not has_data_gap:
                    domain_nan_count += 1

            # Check 1m microstructure domain NaN
            if (
                features_data["mtf_1m_vol_dispersion"][i] is None
                and not is_warmup
                and not has_data_gap
            ):
                domain_nan_count += 1
            if (
                features_data["mtf_1m_taker_trend"][i] is None
                and not is_warmup
                and not has_data_gap
            ):
                domain_nan_count += 1

            # Count total NaNs across non-nullable columns
            if is_warmup or has_data_gap or domain_nan_count > 0:
                nan_feature_count = sum(
                    1
                    for c_name in non_nullable_col_names
                    if (
                        features_data[c_name][i] is None
                        or (
                            type(features_data[c_name][i]) is float
                            and math.isnan(features_data[c_name][i])
                        )
                    )
                )
            else:
                # Fast check for unexpected nulls (e.g. missing MTF or source failure)
                has_null = any(
                    features_data[c_name][i] is None
                    or (
                        type(features_data[c_name][i]) is float
                        and math.isnan(features_data[c_name][i])
                    )
                    for c_name in [
                        "vol_gk_realized_12",
                        "vol_gk_realized_24",
                        "mtf_1m_vol_dispersion",
                        "mtf_1m_taker_trend",
                        "mtf_1m_return_skew",
                        "mtf_15m_ret_log_cc_4",
                        "mtf_1h_ret_log_cc_4",
                        "liq_taker_buy_ratio",
                        "liq_avg_trade_size",
                        "liq_delta_proxy",
                    ]
                )
                if has_null:
                    nan_feature_count = sum(
                        1
                        for c_name in non_nullable_col_names
                        if (
                            features_data[c_name][i] is None
                            or (
                                type(features_data[c_name][i]) is float
                                and math.isnan(features_data[c_name][i])
                            )
                        )
                    )
                else:
                    nan_feature_count = 0

            data_quality_nan_count = max(0, nan_feature_count - domain_nan_count)

            # Row validity contract
            is_valid = (not is_warmup) and (not has_data_gap) and (data_quality_nan_count == 0)

            row: Dict[str, Any] = {
                # Fixed Metadata
                "timestamp_utc": timestamps[i],
                "venue": payload.venue,
                "instrument": payload.instrument,
                "timeframe": payload.primary_timeframe,
                "is_warmup": is_warmup,
                "has_data_gap": has_data_gap,
                "is_valid": is_valid,
                "nan_feature_count": nan_feature_count,
                "domain_nan_feature_count": domain_nan_count,
                "input_dataset_version": payload.input_dataset_version,
                "feature_set_version": "v2.0.0",
                "session_definition_version": payload.session_definition_version,
            }

            # Add all feature columns
            for j in range(num_features):
                row[feature_names[j]] = feature_series[j][i]

            # Exhaustive row-level validator on warmup period, boundary rows,
            # gap crossings, and samples
            if (
                i < 320
                or i >= n_bars - 50
                or i % 500 == 0
                or has_data_gap
                or domain_nan_count > 0
            ):
                FeatureOutputValidator.validate_row(row, all_feature_cols, i)

            rows.append(row)

        return rows
