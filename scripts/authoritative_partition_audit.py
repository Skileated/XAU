"""Authoritative 37-Row Partition Audit for Phase 2 Market Feature Dataset."""

import hashlib
from datetime import timezone
from pathlib import Path

import duckdb

con = duckdb.connect(":memory:")

feature_root = Path("data/features/binance/spot/BTCUSDT/5m/feature_set=v2.0.0")
p1c_root = Path("data/processed/binance/spot/BTCUSDT/5m")

partition_files = sorted(list(feature_root.glob("year=*/month=*/*.parquet")))
assert len(partition_files) == 37, f"Expected 37 partitions, found {len(partition_files)}"

print("=" * 140)
print(f"{'Year':<5} {'Mo':<3} {'Expected':<9} {'Actual':<8} {'Missing':<8} {'Dupes':<6} {'Min Timestamp (UTC)':<26} {'Max Timestamp (UTC)':<26} {'SHA-256'}")
print("=" * 140)

sum_expected = 0
sum_actual = 0
sum_missing = 0
sum_dupes = 0

audit_rows = []

for p in partition_files:
    file_bytes = p.read_bytes()
    file_sha256 = hashlib.sha256(file_bytes).hexdigest()

    parts = p.parts
    year = int([x for x in parts if x.startswith("year=")][0].split("=")[1])
    month = int([x for x in parts if x.startswith("month=")][0].split("=")[1])

    # Expected rows from Phase 1C canonical 5m partition
    p1c_path = p1c_root / f"year={year}" / f"month={month:02d}" / f"binance_spot_btcusdt_5m_{year}{month:02d}.parquet"
    assert p1c_path.exists(), f"Phase 1C canonical file not found: {p1c_path}"

    p1c_info = con.execute(f"SELECT COUNT(*), MIN(timestamp_utc), MAX(timestamp_utc) FROM read_parquet('{p1c_path.as_posix()}')").fetchone()
    expected_rows = p1c_info[0]

    # Actual rows and duplicates from Phase 2
    p2_info = con.execute(f"""
        SELECT
            COUNT(*),
            COUNT(DISTINCT timestamp_utc),
            MIN(timestamp_utc AT TIME ZONE 'UTC'),
            MAX(timestamp_utc AT TIME ZONE 'UTC')
        FROM read_parquet('{p.as_posix()}')
    """).fetchone()

    actual_rows = p2_info[0]
    distinct_rows = p2_info[1]
    duplicate_rows = actual_rows - distinct_rows
    missing_rows = max(0, expected_rows - actual_rows)

    min_ts_utc = p2_info[2].replace(tzinfo=timezone.utc).isoformat()
    max_ts_utc = p2_info[3].replace(tzinfo=timezone.utc).isoformat()

    sum_expected += expected_rows
    sum_actual += actual_rows
    sum_missing += missing_rows
    sum_dupes += duplicate_rows

    row_data = {
        "year": year,
        "month": month,
        "expected_rows": expected_rows,
        "actual_rows": actual_rows,
        "missing_rows": missing_rows,
        "duplicate_rows": duplicate_rows,
        "min_timestamp": min_ts_utc,
        "max_timestamp": max_ts_utc,
        "sha256": file_sha256,
        "path": p.as_posix()
    }
    audit_rows.append(row_data)

    print(f"{year:<5} {month:<3} {expected_rows:<9} {actual_rows:<8} {missing_rows:<8} {duplicate_rows:<6} {min_ts_utc:<26} {max_ts_utc:<26} {file_sha256[:16]}...")

print("=" * 140)
print(f"{'TOTAL':<8} {sum_expected:<9} {sum_actual:<8} {sum_missing:<8} {sum_dupes:<6}")
print("=" * 140)

# Verifications
assert sum_actual == 315648, f"Expected 315648 total actual rows, got {sum_actual}"
assert sum_missing == 0, f"Expected 0 missing rows, got {sum_missing}"
assert sum_dupes == 0, f"Expected 0 duplicate rows, got {sum_dupes}"
assert audit_rows[0]["min_timestamp"] == "2023-09-18T00:00:00+00:00", f"Start timestamp mismatch: {audit_rows[0]['min_timestamp']}"
assert audit_rows[-1]["max_timestamp"] == "2026-09-17T23:55:00+00:00", f"End timestamp mismatch: {audit_rows[-1]['max_timestamp']}"
print("\nALL AUTHORITATIVE PARTITION CHECKS PASSED: sum=315648, missing=0, dupes=0, exact UTC interval matches Phase 1C!")
