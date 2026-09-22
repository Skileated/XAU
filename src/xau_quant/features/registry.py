"""Feature registry defining all feature specifications and schema derivations."""

from typing import Dict, List

from xau_quant.features.models import ColumnSpec, FeatureDefinition


class FeatureRegistry:
    """Central registry and single source of truth for all feature definitions."""

    def __init__(self) -> None:
        self._features: Dict[str, FeatureDefinition] = {}
        self._register_all_features()

    def register(self, feature: FeatureDefinition) -> None:
        """Register a feature definition."""
        if feature.name in self._features:
            raise ValueError(f"Feature '{feature.name}' is already registered.")
        self._features[feature.name] = feature

    def get(self, name: str) -> FeatureDefinition:
        """Retrieve a feature definition by name."""
        if name not in self._features:
            raise KeyError(f"Feature '{name}' not found in registry.")
        return self._features[name]

    def get_ordered_features(self) -> List[FeatureDefinition]:
        """Return all registered features in registered order."""
        return list(self._features.values())

    def get_all_column_specs(self) -> List[ColumnSpec]:
        """Return all column specifications (flattened) emitted by all features."""
        cols: List[ColumnSpec] = []
        for feat in self._features.values():
            cols.extend(feat.columns)
        return cols

    def get_fixed_metadata_column_specs(self) -> List[ColumnSpec]:
        """Return the fixed metadata columns in schema order."""
        return [
            ColumnSpec("timestamp_utc", "TIMESTAMPTZ", False, "5m bar open timestamp (PK)"),
            ColumnSpec("venue", "VARCHAR", False, "Exchange venue"),
            ColumnSpec("instrument", "VARCHAR", False, "Trading pair symbol"),
            ColumnSpec("timeframe", "VARCHAR", False, "Primary research clock timeframe"),
            ColumnSpec(
                "is_warmup", "BOOLEAN", False, "True if row_index < 311 history requirement"
            ),
            ColumnSpec(
                "has_data_gap", "BOOLEAN", False, "True if window crosses an input data gap"
            ),
            ColumnSpec(
                "is_valid",
                "BOOLEAN",
                False,
                "True if post-warmup, gap-free, zero data-quality NaNs",
            ),
            ColumnSpec(
                "nan_feature_count",
                "SMALLINT",
                False,
                "Total NaNs across all non-nullable numeric features",
            ),
            ColumnSpec(
                "domain_nan_feature_count",
                "SMALLINT",
                False,
                "Count of domain-defined NaNs (e.g. zero volume)",
            ),
            ColumnSpec(
                "input_dataset_version", "VARCHAR", False, "Source canonical candle dataset version"
            ),
            ColumnSpec("feature_set_version", "VARCHAR", False, "Feature engine version"),
            ColumnSpec(
                "session_definition_version", "VARCHAR", False, "Trading session config version"
            ),
        ]

    def get_full_schema_column_specs(self) -> List[ColumnSpec]:
        """Return all columns (fixed metadata + feature columns) in exact schema order."""
        return self.get_fixed_metadata_column_specs() + self.get_all_column_specs()

    def get_parquet_schema_dict(self) -> Dict[str, str]:
        """Return dictionary mapping column names to DuckDB types."""
        return {col.name: col.duckdb_type for col in self.get_full_schema_column_specs()}

    def total_feature_count(self) -> int:
        """Total number of registered feature definitions."""
        return len(self._features)

    def total_column_count(self) -> int:
        """Total number of columns in full Parquet schema."""
        return len(self.get_full_schema_column_specs())

    def max_required_history_bars(self) -> int:
        """Maximum required primary 5m history bars across all features."""
        if not self._features:
            return 0
        return max(f.required_history_bars for f in self._features.values())

    def counts_by_family(self) -> Dict[str, int]:
        """Return feature counts grouped by family."""
        counts: Dict[str, int] = {}
        for feat in self._features.values():
            counts[feat.family] = counts.get(feat.family, 0) + 1
        return counts

    def _register_all_features(self) -> None:
        """Register all Phase 2 features per Revision 5.1 specification."""
        self._register_returns()
        self._register_momentum()
        self._register_volatility()
        self._register_liquidity()
        self._register_structure()
        self._register_mean_reversion()
        self._register_time_features()
        self._register_multitimeframe()

    def _register_returns(self) -> None:
        # Close-to-close log returns: req = n + 1
        for n in [1, 3, 6, 12, 24, 48, 96]:
            self.register(
                FeatureDefinition(
                    name=f"ret_log_cc_{n}",
                    family="returns",
                    calculator="compute_ret_log_cc",
                    parameters={"n": n},
                    required_history_bars=n + 1,
                    columns=(
                        ColumnSpec(
                            f"ret_log_cc_{n}",
                            "DOUBLE",
                            False,
                            f"Close-to-close log return over {n} bars",
                        ),
                    ),
                )
            )

        # Single bar returns & geometry: req = 1
        self.register(
            FeatureDefinition(
                name="ret_log_oc",
                family="returns",
                calculator="compute_ret_log_oc",
                parameters={},
                required_history_bars=1,
                columns=(
                    ColumnSpec(
                        "ret_log_oc", "DOUBLE", False, "Intra-bar log return: ln(close/open)"
                    ),
                ),
            )
        )
        self.register(
            FeatureDefinition(
                name="price_body_ratio",
                family="returns",
                calculator="compute_price_body_ratio",
                parameters={},
                required_history_bars=1,
                columns=(
                    ColumnSpec(
                        "price_body_ratio", "DOUBLE", False, "|close - open| / (high - low)"
                    ),
                ),
            )
        )
        self.register(
            FeatureDefinition(
                name="price_upper_wick_ratio",
                family="returns",
                calculator="compute_price_upper_wick_ratio",
                parameters={},
                required_history_bars=1,
                columns=(
                    ColumnSpec(
                        "price_upper_wick_ratio",
                        "DOUBLE",
                        False,
                        "(high - max(O,C)) / (high - low)",
                    ),
                ),
            )
        )
        self.register(
            FeatureDefinition(
                name="price_lower_wick_ratio",
                family="returns",
                calculator="compute_price_lower_wick_ratio",
                parameters={},
                required_history_bars=1,
                columns=(
                    ColumnSpec(
                        "price_lower_wick_ratio", "DOUBLE", False, "(min(O,C) - low) / (high - low)"
                    ),
                ),
            )
        )
        self.register(
            FeatureDefinition(
                name="price_midpoint",
                family="returns",
                calculator="compute_price_midpoint",
                parameters={},
                required_history_bars=1,
                columns=(ColumnSpec("price_midpoint", "DOUBLE", False, "(high + low) / 2.0"),),
            )
        )

    def _register_momentum(self) -> None:
        # ROC: req = n + 1
        for n in [6, 12, 24, 48]:
            self.register(
                FeatureDefinition(
                    name=f"mom_roc_{n}",
                    family="momentum",
                    calculator="compute_mom_roc",
                    parameters={"n": n},
                    required_history_bars=n + 1,
                    columns=(
                        ColumnSpec(
                            f"mom_roc_{n}",
                            "DOUBLE",
                            False,
                            "Rate of change: (C[t] - C[t-n]) / C[t-n]",
                        ),
                    ),
                )
            )

        # Slope: req = n
        for n in [12, 24, 48]:
            self.register(
                FeatureDefinition(
                    name=f"mom_slope_{n}",
                    family="momentum",
                    calculator="compute_mom_slope",
                    parameters={"n": n},
                    required_history_bars=n,
                    columns=(
                        ColumnSpec(
                            f"mom_slope_{n}",
                            "DOUBLE",
                            False,
                            f"OLS slope of close over {n} bars / C[t]",
                        ),
                    ),
                )
            )

        # SMA dev: req = n
        for n in [12, 24, 48, 96]:
            self.register(
                FeatureDefinition(
                    name=f"mom_sma_dev_{n}",
                    family="momentum",
                    calculator="compute_mom_sma_dev",
                    parameters={"n": n},
                    required_history_bars=n,
                    columns=(
                        ColumnSpec(
                            f"mom_sma_dev_{n}", "DOUBLE", False, f"(C[t] - SMA_{n}) / SMA_{n}"
                        ),
                    ),
                )
            )

        # EMA dev: req = n
        for n in [12, 26, 50]:
            self.register(
                FeatureDefinition(
                    name=f"mom_ema_dev_{n}",
                    family="momentum",
                    calculator="compute_mom_ema_dev",
                    parameters={"n": n},
                    required_history_bars=n,
                    columns=(
                        ColumnSpec(
                            f"mom_ema_dev_{n}", "DOUBLE", False, f"(C[t] - EMA_{n}) / EMA_{n}"
                        ),
                    ),
                )
            )

        # MACD histogram: natural composition (12, 26, 9) -> 26 + 9 - 1 = 34 bars
        self.register(
            FeatureDefinition(
                name="mom_macd_hist",
                family="momentum",
                calculator="compute_mom_macd_hist",
                parameters={"fast_period": 12, "slow_period": 26, "signal_period": 9},
                required_history_bars=34,
                columns=(
                    ColumnSpec(
                        "mom_macd_hist",
                        "DOUBLE",
                        False,
                        "MACD Histogram (12,26,9 natural composition)",
                    ),
                ),
            )
        )

        # RSI: Wilder smoothed -> req = n + 1
        for n in [14, 28]:
            self.register(
                FeatureDefinition(
                    name=f"mom_rsi_{n}",
                    family="momentum",
                    calculator="compute_mom_rsi",
                    parameters={"n": n},
                    required_history_bars=n + 1,
                    estimator_type="wilder_smoothed",
                    columns=(
                        ColumnSpec(
                            f"mom_rsi_{n}", "DOUBLE", False, f"Wilder RSI {n} with exact boundaries"
                        ),
                    ),
                )
            )

    def _register_volatility(self) -> None:
        # ATR & ATR Pct: Wilder smoothed -> req = n + 1
        for n in [14, 28]:
            self.register(
                FeatureDefinition(
                    name=f"vol_atr_{n}",
                    family="volatility",
                    calculator="compute_vol_atr",
                    parameters={"n": n},
                    required_history_bars=n + 1,
                    estimator_type="wilder_smoothed",
                    columns=(
                        ColumnSpec(f"vol_atr_{n}", "DOUBLE", False, f"Average True Range ({n})"),
                    ),
                )
            )
            self.register(
                FeatureDefinition(
                    name=f"vol_atr_pct_{n}",
                    family="volatility",
                    calculator="compute_vol_atr_pct",
                    parameters={"n": n},
                    required_history_bars=n + 1,
                    estimator_type="wilder_smoothed",
                    columns=(ColumnSpec(f"vol_atr_pct_{n}", "DOUBLE", False, f"ATR {n} / Close"),),
                )
            )

        # Realized vol: req = n + 1
        for n in [12, 24, 48, 96]:
            self.register(
                FeatureDefinition(
                    name=f"vol_realized_{n}",
                    family="volatility",
                    calculator="compute_vol_realized",
                    parameters={"n": n},
                    required_history_bars=n + 1,
                    columns=(
                        ColumnSpec(
                            f"vol_realized_{n}",
                            "DOUBLE",
                            False,
                            f"Sample std dev of {n} log returns",
                        ),
                    ),
                )
            )

        # GK Realized: req = n
        for n in [12, 24]:
            self.register(
                FeatureDefinition(
                    name=f"vol_gk_realized_{n}",
                    family="volatility",
                    calculator="compute_vol_gk_realized",
                    parameters={"n": n},
                    required_history_bars=n,
                    columns=(
                        ColumnSpec(
                            f"vol_gk_realized_{n}",
                            "DOUBLE",
                            False,
                            f"Garman-Klass volatility ({n} bars)",
                        ),
                    ),
                )
            )

        # Vol Z-Score (12, 96): 13 + 96 - 1 = 108
        self.register(
            FeatureDefinition(
                name="vol_zscore_12_96",
                family="volatility",
                calculator="compute_vol_zscore_12_96",
                parameters={"fast_n": 12, "slow_n": 96},
                required_history_bars=108,
                columns=(
                    ColumnSpec(
                        "vol_zscore_12_96",
                        "DOUBLE",
                        False,
                        "Z-score of 12-bar vol over 96-bar window",
                    ),
                ),
            )
        )

    def _register_liquidity(self) -> None:
        # Single bar liquidity: req = 1
        self.register(
            FeatureDefinition(
                name="liq_taker_buy_ratio",
                family="liquidity",
                calculator="compute_liq_taker_buy_ratio",
                parameters={},
                required_history_bars=1,
                columns=(
                    ColumnSpec(
                        "liq_taker_buy_ratio", "DOUBLE", False, "Taker buy volume / total volume"
                    ),
                ),
            )
        )
        self.register(
            FeatureDefinition(
                name="liq_avg_trade_size",
                family="liquidity",
                calculator="compute_liq_avg_trade_size",
                parameters={},
                required_history_bars=1,
                columns=(
                    ColumnSpec("liq_avg_trade_size", "DOUBLE", False, "Volume / trade count"),
                ),
            )
        )
        self.register(
            FeatureDefinition(
                name="liq_dollar_volume",
                family="liquidity",
                calculator="compute_liq_dollar_volume",
                parameters={},
                required_history_bars=1,
                columns=(ColumnSpec("liq_dollar_volume", "DOUBLE", False, "Quote asset volume"),),
            )
        )
        self.register(
            FeatureDefinition(
                name="liq_delta_proxy",
                family="liquidity",
                calculator="compute_liq_delta_proxy",
                parameters={},
                required_history_bars=1,
                columns=(
                    ColumnSpec("liq_delta_proxy", "DOUBLE", False, "2 * taker_buy_vol - total_vol"),
                ),
            )
        )

        # Rolling VWAP dev: req = n
        for n in [12, 48]:
            self.register(
                FeatureDefinition(
                    name=f"liq_vwap_dev_{n}",
                    family="liquidity",
                    calculator="compute_liq_vwap_dev",
                    parameters={"n": n},
                    required_history_bars=n,
                    columns=(
                        ColumnSpec(
                            f"liq_vwap_dev_{n}", "DOUBLE", False, f"(C[t] - VWAP_{n}) / VWAP_{n}"
                        ),
                    ),
                )
            )

        # Rolling Vol ratio: req = n
        for n in [12, 24, 48]:
            self.register(
                FeatureDefinition(
                    name=f"liq_vol_ratio_{n}",
                    family="liquidity",
                    calculator="compute_liq_vol_ratio",
                    parameters={"n": n},
                    required_history_bars=n,
                    columns=(
                        ColumnSpec(f"liq_vol_ratio_{n}", "DOUBLE", False, f"V[t] / mean(V_{n})"),
                    ),
                )
            )

        # Rolling Cum delta: req = n
        for n in [12, 48]:
            self.register(
                FeatureDefinition(
                    name=f"liq_cum_delta_{n}",
                    family="liquidity",
                    calculator="compute_liq_cum_delta",
                    parameters={"n": n},
                    required_history_bars=n,
                    columns=(
                        ColumnSpec(
                            f"liq_cum_delta_{n}",
                            "DOUBLE",
                            False,
                            f"Sum of delta proxy over {n} bars",
                        ),
                    ),
                )
            )

    def _register_structure(self) -> None:
        # High, Low, Price Position: req = n
        for n in [12, 24, 48, 96]:
            self.register(
                FeatureDefinition(
                    name=f"ms_high_{n}",
                    family="structure",
                    calculator="compute_ms_high",
                    parameters={"n": n},
                    required_history_bars=n,
                    columns=(ColumnSpec(f"ms_high_{n}", "DOUBLE", False, f"Rolling {n}-bar high"),),
                )
            )
            self.register(
                FeatureDefinition(
                    name=f"ms_low_{n}",
                    family="structure",
                    calculator="compute_ms_low",
                    parameters={"n": n},
                    required_history_bars=n,
                    columns=(ColumnSpec(f"ms_low_{n}", "DOUBLE", False, f"Rolling {n}-bar low"),),
                )
            )
            self.register(
                FeatureDefinition(
                    name=f"ms_price_position_{n}",
                    family="structure",
                    calculator="compute_ms_price_position",
                    parameters={"n": n},
                    required_history_bars=n,
                    columns=(
                        ColumnSpec(
                            f"ms_price_position_{n}",
                            "DOUBLE",
                            False,
                            f"Price position in {n}-bar range",
                        ),
                    ),
                )
            )

        # Bars since high/low: req = n
        for n in [24, 96]:
            self.register(
                FeatureDefinition(
                    name=f"ms_bars_since_high_{n}",
                    family="structure",
                    calculator="compute_ms_bars_since_high",
                    parameters={"n": n},
                    required_history_bars=n,
                    columns=(
                        ColumnSpec(
                            f"ms_bars_since_high_{n}", "SMALLINT", False, f"Bars since {n}-bar high"
                        ),
                    ),
                )
            )
            self.register(
                FeatureDefinition(
                    name=f"ms_bars_since_low_{n}",
                    family="structure",
                    calculator="compute_ms_bars_since_low",
                    parameters={"n": n},
                    required_history_bars=n,
                    columns=(
                        ColumnSpec(
                            f"ms_bars_since_low_{n}", "SMALLINT", False, f"Bars since {n}-bar low"
                        ),
                    ),
                )
            )

        # Pivots: req = 2*s + 1 (confirmation lag s)
        for s in [3, 5]:
            req = 2 * s + 1
            self.register(
                FeatureDefinition(
                    name=f"ms_pivot_high_{s}",
                    family="structure",
                    calculator="compute_ms_pivot_high",
                    parameters={"s": s},
                    required_history_bars=req,
                    temporal_semantics="confirmation_lag_s",
                    columns=(
                        ColumnSpec(
                            f"ms_is_pivot_high_{s}",
                            "BOOLEAN",
                            False,
                            f"Pivot high confirmed at lag {s}",
                        ),
                        ColumnSpec(
                            f"ms_pivot_high_timestamp_{s}",
                            "TIMESTAMPTZ",
                            True,
                            f"Timestamp of pivot high at lag {s}",
                        ),
                        ColumnSpec(
                            f"ms_pivot_high_age_bars_{s}",
                            "SMALLINT",
                            True,
                            f"Age in bars of confirmed pivot high ({s})",
                        ),
                    ),
                )
            )
            self.register(
                FeatureDefinition(
                    name=f"ms_pivot_low_{s}",
                    family="structure",
                    calculator="compute_ms_pivot_low",
                    parameters={"s": s},
                    required_history_bars=req,
                    temporal_semantics="confirmation_lag_s",
                    columns=(
                        ColumnSpec(
                            f"ms_is_pivot_low_{s}",
                            "BOOLEAN",
                            False,
                            f"Pivot low confirmed at lag {s}",
                        ),
                        ColumnSpec(
                            f"ms_pivot_low_timestamp_{s}",
                            "TIMESTAMPTZ",
                            True,
                            f"Timestamp of pivot low at lag {s}",
                        ),
                        ColumnSpec(
                            f"ms_pivot_low_age_bars_{s}",
                            "SMALLINT",
                            True,
                            f"Age in bars of confirmed pivot low ({s})",
                        ),
                    ),
                )
            )

        # Consecutive bar directions: req = 6 (5 comparisons)
        self.register(
            FeatureDefinition(
                name="ms_consec_up_5",
                family="structure",
                calculator="compute_ms_consec_up_5",
                parameters={"n": 5},
                required_history_bars=6,
                columns=(
                    ColumnSpec(
                        "ms_consec_up_5",
                        "SMALLINT",
                        False,
                        "Count of consecutive up closes (max 5)",
                    ),
                ),
            )
        )
        self.register(
            FeatureDefinition(
                name="ms_consec_down_5",
                family="structure",
                calculator="compute_ms_consec_down_5",
                parameters={"n": 5},
                required_history_bars=6,
                columns=(
                    ColumnSpec(
                        "ms_consec_down_5",
                        "SMALLINT",
                        False,
                        "Count of consecutive down closes (max 5)",
                    ),
                ),
            )
        )

    def _register_mean_reversion(self) -> None:
        # Z-Score: req = n
        for n in [24, 48, 96]:
            self.register(
                FeatureDefinition(
                    name=f"mr_zscore_{n}",
                    family="mean_reversion",
                    calculator="compute_mr_zscore",
                    parameters={"n": n},
                    required_history_bars=n,
                    columns=(
                        ColumnSpec(
                            f"mr_zscore_{n}",
                            "DOUBLE",
                            False,
                            f"Rolling Z-score of close over {n} bars",
                        ),
                    ),
                )
            )

        # Mean deviation: req = n
        for n in [12, 48]:
            self.register(
                FeatureDefinition(
                    name=f"mr_mean_dev_{n}",
                    family="mean_reversion",
                    calculator="compute_mr_mean_dev",
                    parameters={"n": n},
                    required_history_bars=n,
                    columns=(
                        ColumnSpec(
                            f"mr_mean_dev_{n}", "DOUBLE", False, f"(C[t] - mean_{n}) / mean_{n}"
                        ),
                    ),
                )
            )

        # Hurst single-window R/S proxy (frozen): req = n + 1
        for n in [48, 96]:
            self.register(
                FeatureDefinition(
                    name=f"mr_hurst_proxy_{n}",
                    family="mean_reversion",
                    calculator="compute_mr_hurst_proxy",
                    parameters={"n": n},
                    required_history_bars=n + 1,
                    estimator_type="rs_single_window_proxy",
                    interpretation="research_feature_only",
                    columns=(
                        ColumnSpec(
                            f"mr_hurst_proxy_{n}",
                            "DOUBLE",
                            False,
                            f"Single-window R/S Hurst proxy ({n} returns)",
                        ),
                    ),
                )
            )

        # Autocorrelation lag 1: req = n + 2
        for n in [24, 96]:
            self.register(
                FeatureDefinition(
                    name=f"mr_autocorr_lag1_{n}",
                    family="mean_reversion",
                    calculator="compute_mr_autocorr_lag1",
                    parameters={"n": n},
                    required_history_bars=n + 2,
                    columns=(
                        ColumnSpec(
                            f"mr_autocorr_lag1_{n}",
                            "DOUBLE",
                            False,
                            f"Lag-1 autocorrelation over {n} returns",
                        ),
                    ),
                )
            )

    def _register_time_features(self) -> None:
        time_cols = [
            ("time_hour_utc", "SMALLINT", "UTC hour (0..23)"),
            ("time_dow", "SMALLINT", "Day of week (0=Mon..6=Sun)"),
            ("time_hour_sin", "DOUBLE", "sin(2pi * hour / 24)"),
            ("time_hour_cos", "DOUBLE", "cos(2pi * hour / 24)"),
            ("time_dow_sin", "DOUBLE", "sin(2pi * dow / 7)"),
            ("time_dow_cos", "DOUBLE", "cos(2pi * dow / 7)"),
            ("time_session_flags", "SMALLINT", "Bitwise OR active session flags"),
            ("time_bars_since_midnight", "SMALLINT", "5m bars since UTC midnight (0..287)"),
            ("time_bars_since_week_open", "SMALLINT", "5m bars since Monday 00:00 UTC (0..2015)"),
        ]
        for col_name, dtype, desc in time_cols:
            self.register(
                FeatureDefinition(
                    name=col_name,
                    family="time",
                    calculator="compute_time_features",
                    parameters={},
                    required_history_bars=1,
                    session_definition_version="1.0.0",
                    columns=(ColumnSpec(col_name, dtype, False, desc),),
                )
            )

    def _register_multitimeframe(self) -> None:
        # 15m MTF (D=3, req = 3*K + 2)
        # mtf_15m_ret_log_cc_4: K=5 -> 17
        self.register(
            FeatureDefinition(
                name="mtf_15m_ret_log_cc_4",
                family="mtf",
                calculator="compute_mtf_15m_ret_log_cc_4",
                parameters={"n": 4},
                required_history_bars=17,
                mtf_timeframe="15m",
                columns=(
                    ColumnSpec(
                        "mtf_15m_ret_log_cc_4",
                        "DOUBLE",
                        False,
                        "15m close-to-close log return (4 bars)",
                    ),
                ),
            )
        )
        # mtf_15m_ret_log_cc_16: K=17 -> 53
        self.register(
            FeatureDefinition(
                name="mtf_15m_ret_log_cc_16",
                family="mtf",
                calculator="compute_mtf_15m_ret_log_cc_16",
                parameters={"n": 16},
                required_history_bars=53,
                mtf_timeframe="15m",
                columns=(
                    ColumnSpec(
                        "mtf_15m_ret_log_cc_16",
                        "DOUBLE",
                        False,
                        "15m close-to-close log return (16 bars)",
                    ),
                ),
            )
        )
        # mtf_15m_mom_rsi_14: K=15 -> 47
        self.register(
            FeatureDefinition(
                name="mtf_15m_mom_rsi_14",
                family="mtf",
                calculator="compute_mtf_15m_mom_rsi_14",
                parameters={"n": 14},
                required_history_bars=47,
                mtf_timeframe="15m",
                estimator_type="wilder_smoothed",
                columns=(
                    ColumnSpec("mtf_15m_mom_rsi_14", "DOUBLE", False, "15m Wilder RSI (14 bars)"),
                ),
            )
        )
        # mtf_15m_vol_atr_pct_14: K=15 -> 47
        self.register(
            FeatureDefinition(
                name="mtf_15m_vol_atr_pct_14",
                family="mtf",
                calculator="compute_mtf_15m_vol_atr_pct_14",
                parameters={"n": 14},
                required_history_bars=47,
                mtf_timeframe="15m",
                estimator_type="wilder_smoothed",
                columns=(
                    ColumnSpec("mtf_15m_vol_atr_pct_14", "DOUBLE", False, "15m ATR Pct (14 bars)"),
                ),
            )
        )
        # mtf_15m_price_position_16: K=16 -> 50
        self.register(
            FeatureDefinition(
                name="mtf_15m_price_position_16",
                family="mtf",
                calculator="compute_mtf_15m_price_position_16",
                parameters={"n": 16},
                required_history_bars=50,
                mtf_timeframe="15m",
                columns=(
                    ColumnSpec(
                        "mtf_15m_price_position_16",
                        "DOUBLE",
                        False,
                        "15m price position in 16-bar range",
                    ),
                ),
            )
        )
        # mtf_15m_liq_taker_buy_ratio: K=1 -> 5
        self.register(
            FeatureDefinition(
                name="mtf_15m_liq_taker_buy_ratio",
                family="mtf",
                calculator="compute_mtf_15m_liq_taker_buy_ratio",
                parameters={},
                required_history_bars=5,
                mtf_timeframe="15m",
                columns=(
                    ColumnSpec(
                        "mtf_15m_liq_taker_buy_ratio", "DOUBLE", False, "15m taker buy ratio"
                    ),
                ),
            )
        )
        # mtf_15m_liq_vol_ratio_16: K=16 -> 50
        self.register(
            FeatureDefinition(
                name="mtf_15m_liq_vol_ratio_16",
                family="mtf",
                calculator="compute_mtf_15m_liq_vol_ratio_16",
                parameters={"n": 16},
                required_history_bars=50,
                mtf_timeframe="15m",
                columns=(
                    ColumnSpec(
                        "mtf_15m_liq_vol_ratio_16",
                        "DOUBLE",
                        False,
                        "15m volume ratio to 16-bar mean",
                    ),
                ),
            )
        )

        # 1h MTF (D=12, req = 12*K + 11)
        # mtf_1h_ret_log_cc_4: K=5 -> 71
        self.register(
            FeatureDefinition(
                name="mtf_1h_ret_log_cc_4",
                family="mtf",
                calculator="compute_mtf_1h_ret_log_cc_4",
                parameters={"n": 4},
                required_history_bars=71,
                mtf_timeframe="1h",
                columns=(
                    ColumnSpec(
                        "mtf_1h_ret_log_cc_4",
                        "DOUBLE",
                        False,
                        "1h close-to-close log return (4 bars)",
                    ),
                ),
            )
        )
        # mtf_1h_ret_log_cc_24: K=25 -> 311
        self.register(
            FeatureDefinition(
                name="mtf_1h_ret_log_cc_24",
                family="mtf",
                calculator="compute_mtf_1h_ret_log_cc_24",
                parameters={"n": 24},
                required_history_bars=311,
                mtf_timeframe="1h",
                columns=(
                    ColumnSpec(
                        "mtf_1h_ret_log_cc_24",
                        "DOUBLE",
                        False,
                        "1h close-to-close log return (24 bars)",
                    ),
                ),
            )
        )
        # mtf_1h_mom_rsi_14: K=15 -> 191
        self.register(
            FeatureDefinition(
                name="mtf_1h_mom_rsi_14",
                family="mtf",
                calculator="compute_mtf_1h_mom_rsi_14",
                parameters={"n": 14},
                required_history_bars=191,
                mtf_timeframe="1h",
                estimator_type="wilder_smoothed",
                columns=(
                    ColumnSpec("mtf_1h_mom_rsi_14", "DOUBLE", False, "1h Wilder RSI (14 bars)"),
                ),
            )
        )
        # mtf_1h_vol_realized_24: K=25 -> 311
        self.register(
            FeatureDefinition(
                name="mtf_1h_vol_realized_24",
                family="mtf",
                calculator="compute_mtf_1h_vol_realized_24",
                parameters={"n": 24},
                required_history_bars=311,
                mtf_timeframe="1h",
                columns=(
                    ColumnSpec(
                        "mtf_1h_vol_realized_24",
                        "DOUBLE",
                        False,
                        "1h realized volatility (24 bars)",
                    ),
                ),
            )
        )
        # mtf_1h_price_position_24: K=24 -> 299
        self.register(
            FeatureDefinition(
                name="mtf_1h_price_position_24",
                family="mtf",
                calculator="compute_mtf_1h_price_position_24",
                parameters={"n": 24},
                required_history_bars=299,
                mtf_timeframe="1h",
                columns=(
                    ColumnSpec(
                        "mtf_1h_price_position_24",
                        "DOUBLE",
                        False,
                        "1h price position in 24-bar range",
                    ),
                ),
            )
        )
        # mtf_1h_mr_zscore_24: K=24 -> 299
        self.register(
            FeatureDefinition(
                name="mtf_1h_mr_zscore_24",
                family="mtf",
                calculator="compute_mtf_1h_mr_zscore_24",
                parameters={"n": 24},
                required_history_bars=299,
                mtf_timeframe="1h",
                columns=(
                    ColumnSpec(
                        "mtf_1h_mr_zscore_24",
                        "DOUBLE",
                        False,
                        "1h rolling Z-score of close (24 bars)",
                    ),
                ),
            )
        )
        # mtf_1h_liq_taker_buy_ratio: K=1 -> 23
        self.register(
            FeatureDefinition(
                name="mtf_1h_liq_taker_buy_ratio",
                family="mtf",
                calculator="compute_mtf_1h_liq_taker_buy_ratio",
                parameters={},
                required_history_bars=23,
                mtf_timeframe="1h",
                columns=(
                    ColumnSpec("mtf_1h_liq_taker_buy_ratio", "DOUBLE", False, "1h taker buy ratio"),
                ),
            )
        )

        # 1m Microstructure (5 constituent bars available at 5m completion): req = 1
        self.register(
            FeatureDefinition(
                name="mtf_1m_vol_dispersion",
                family="mtf",
                calculator="compute_mtf_1m_vol_dispersion",
                parameters={},
                required_history_bars=1,
                mtf_timeframe="1m",
                columns=(
                    ColumnSpec(
                        "mtf_1m_vol_dispersion",
                        "DOUBLE",
                        False,
                        "1m volume coefficient of variation within 5m bar",
                    ),
                ),
            )
        )
        self.register(
            FeatureDefinition(
                name="mtf_1m_taker_trend",
                family="mtf",
                calculator="compute_mtf_1m_taker_trend",
                parameters={},
                required_history_bars=1,
                mtf_timeframe="1m",
                columns=(
                    ColumnSpec(
                        "mtf_1m_taker_trend",
                        "DOUBLE",
                        False,
                        "OLS slope of 1m taker aggression across 5 constituent bars",
                    ),
                ),
            )
        )
        self.register(
            FeatureDefinition(
                name="mtf_1m_return_skew",
                family="mtf",
                calculator="compute_mtf_1m_return_skew",
                parameters={},
                required_history_bars=1,
                mtf_timeframe="1m",
                columns=(
                    ColumnSpec(
                        "mtf_1m_return_skew",
                        "DOUBLE",
                        False,
                        "Normalized return concentration (r_last - r_first) / sum(|r|)",
                    ),
                ),
            )
        )
