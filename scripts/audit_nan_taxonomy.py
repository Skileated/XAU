"""Audit NaN taxonomy: warmup, data-quality, domain-defined, and infinities."""

from pathlib import Path

import duckdb

from xau_quant.features.registry import FeatureRegistry

con = duckdb.connect(":memory:")
registry = FeatureRegistry()

feature_files = [p.as_posix() for p in sorted(list(Path("data/features/binance/spot/BTCUSDT/5m/feature_set=v2.0.0").glob("year=*/month=*/*.parquet")))]

print(f"Auditing {len(feature_files)} Parquet partition files...")

# 1. Warmup audit
warmup_stats = con.execute("""
    SELECT
        COUNT(*) AS total_warmup_rows,
        MIN(nan_feature_count) AS min_warmup_nans,
        MAX(nan_feature_count) AS max_warmup_nans
    FROM read_parquet(?)
    WHERE is_warmup = TRUE
""", [feature_files]).fetchone()
print(f"\n1. Warmup NaNs:\n   - Total warmup rows: {warmup_stats[0]} (must be exactly 311)")
print(f"   - Min warmup NaNs per row: {warmup_stats[1]}, Max: {warmup_stats[2]}")

# 2. Data-Quality NaNs (Post-Warmup)
# By contract: data_quality_nan_count = nan_feature_count - domain_nan_feature_count
dq_stats = con.execute("""
    SELECT
        COUNT(*) AS total_post_warmup,
        COUNT(CASE WHEN (nan_feature_count - domain_nan_feature_count) > 0 THEN 1 END) AS rows_with_dq_nans,
        COUNT(CASE WHEN is_valid = FALSE THEN 1 END) AS invalid_post_warmup_rows
    FROM read_parquet(?)
    WHERE is_warmup = FALSE
""", [feature_files]).fetchone()
print(f"\n2. Data-Quality NaNs (Post-Warmup):\n   - Total post-warmup rows: {dq_stats[0]}")
print(f"   - Rows with unexplained data-quality NaNs: {dq_stats[1]} (must be 0)")
print(f"   - Unexplained invalid post-warmup rows: {dq_stats[2]} (must be 0)")


# 3. Domain-Defined NaNs
domain_stats = con.execute("""
    SELECT
        COUNT(*) AS rows_with_domain_nans,
        MIN(domain_nan_feature_count) AS min_domain_nans,
        MAX(domain_nan_feature_count) AS max_domain_nans
    FROM read_parquet(?)
    WHERE is_valid = TRUE AND domain_nan_feature_count > 0
""", [feature_files]).fetchone()
print(f"\n3. Domain-Defined NaNs (on Valid Rows):\n   - Rows with domain NaNs: {domain_stats[0]}")
print(f"   - Min domain NaNs: {domain_stats[1]}, Max: {domain_stats[2]}")

# Breakdown by specific domain-nullable columns
domain_cols = [
    "liq_taker_buy_ratio", "liq_avg_trade_size",
    "vol_gk_realized_12", "vol_gk_realized_24",
    "mtf_15m_liq_taker_buy_ratio", "mtf_1h_liq_taker_buy_ratio"
]

print("\n   Specific column breakdown on valid rows (is_valid = TRUE):")
for col in domain_cols:
    cnt = con.execute(f"SELECT COUNT(*) FROM read_parquet(?) WHERE is_valid = TRUE AND \"{col}\" IS NULL", [feature_files]).fetchone()[0]
    print(f"     * {col}: {cnt} nulls")

# Check nullable pivot columns
pivot_cols = [
    "ms_pivot_high_timestamp_3", "ms_pivot_high_age_bars_3",
    "ms_pivot_low_timestamp_3", "ms_pivot_low_age_bars_3",
    "ms_pivot_high_timestamp_5", "ms_pivot_high_age_bars_5",
    "ms_pivot_low_timestamp_5", "ms_pivot_low_age_bars_5"
]
print("\n   Nullable pivot metadata columns (NULL when is_pivot is FALSE):")
for col in pivot_cols:
    null_cnt = con.execute(f"SELECT COUNT(*) FROM read_parquet(?) WHERE \"{col}\" IS NULL", [feature_files]).fetchone()[0]
    non_null_cnt = con.execute(f"SELECT COUNT(*) FROM read_parquet(?) WHERE \"{col}\" IS NOT NULL", [feature_files]).fetchone()[0]
    print(f"     * {col}: {null_cnt} nulls (confirmed pivots: {non_null_cnt})")

# 4. Infinities Audit
double_cols = [c.name for c in registry.get_all_column_specs() if c.duckdb_type == "DOUBLE"]
inf_clauses = " + ".join([f"COUNT(CASE WHEN isinf(\"{c}\") THEN 1 END)" for c in double_cols])
total_infs = con.execute(f"SELECT {inf_clauses} FROM read_parquet(?)", [feature_files]).fetchone()[0]
print(f"\n4. Infinities Audit:\n   - Checked {len(double_cols)} DOUBLE columns across all 315,648 rows.")
print(f"   - Total infinities (+inf or -inf): {total_infs} (must be 0)")

assert warmup_stats[0] == 311
assert dq_stats[1] == 0
assert dq_stats[2] == 0
assert total_infs == 0
print("\nALL NAN TAXONOMY AND INFINITY CHECKS PASSED!")
