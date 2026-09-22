"""Unit tests for FeatureRegistry and schema definitions."""

from xau_quant.features.registry import FeatureRegistry


def test_feature_registry_initialization():
    registry = FeatureRegistry()
    assert registry.total_feature_count() == 108
    assert registry.total_column_count() == 128  # 12 metadata + 116 feature columns
    assert registry.max_required_history_bars() == 311


def test_registry_family_counts():
    registry = FeatureRegistry()
    counts = registry.counts_by_family()
    expected = {
        "returns": 12,
        "momentum": 17,
        "volatility": 11,
        "liquidity": 11,
        "structure": 22,
        "mean_reversion": 9,
        "time": 9,
        "mtf": 17,
    }
    assert counts == expected


def test_registry_nullability_rules():
    """Only event attribute columns (pivot timestamps and age) may be nullable."""
    registry = FeatureRegistry()
    specs = registry.get_full_schema_column_specs()

    nullable_cols = [c.name for c in specs if c.nullable]
    expected_nullable = [
        "ms_pivot_high_timestamp_3",
        "ms_pivot_high_age_bars_3",
        "ms_pivot_low_timestamp_3",
        "ms_pivot_low_age_bars_3",
        "ms_pivot_high_timestamp_5",
        "ms_pivot_high_age_bars_5",
        "ms_pivot_low_timestamp_5",
        "ms_pivot_low_age_bars_5",
    ]
    assert sorted(nullable_cols) == sorted(expected_nullable)


def test_fixed_metadata_columns():
    registry = FeatureRegistry()
    meta = registry.get_fixed_metadata_column_specs()
    assert len(meta) == 12
    assert meta[0].name == "timestamp_utc"
    assert meta[4].name == "is_warmup"
    assert meta[5].name == "has_data_gap"
    assert meta[6].name == "is_valid"
    assert meta[7].name == "nan_feature_count"
    assert meta[8].name == "domain_nan_feature_count"
