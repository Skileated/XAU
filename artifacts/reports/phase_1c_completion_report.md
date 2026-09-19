# Phase 1C Completion Report: 3-Year Historical Dataset Expansion & Dataset Reliability

**Project**: XAU Quantitative Strategy Discovery and Decision Platform

**Phase**: 1C (Historical Dataset Expansion & Dataset Reliability)

**Status**: COMPLETE — 3-YEAR HISTORICAL RESEARCH FOUNDATION VALIDATED

**Execution Date**: 2026-09-19

**Target Instrument**: `BTCUSDT` (Binance Spot Public Market Data)

**Execution Boundary**: Data Engineering Only (Zero Indicators, Zero Regimes, Zero Strategies, Zero Backtesting, Zero ML/Forecasting, Zero Execution)

---

## 1. Exact Historical Interval & Boundary Alignment

- **Requested Research Horizon**: `2023-09-18T00:00:00Z` → `2026-09-18T00:00:00Z` (half-open interval `[start_utc, end_utc)`)
- **Actual Acquired Interval (UTC)**:
  - First Candle Timestamp: `2023-09-18T00:00:00Z`
  - Last Candle Timestamp: `2026-09-17T23:59:00Z`
  - Total Duration: Exactly 1,096 calendar days (1,578,240 contiguous 1m candles)
- **Time Boundary Alignment**: The end timestamp `2026-09-18T00:00:00Z` seamlessly connects to and incorporates the Phase 1B 7-day foundation dataset (`2026-09-11` to `2026-09-18`), establishing continuous historical coverage without boundary discontinuity.
- **Specification Cohesion**: Both `artifacts/reports/phase_1c_design.md` and this completion report are aligned to this exact 3-year horizon (`2023-09-18` to `2026-09-18`).

---

## 2. Partition Breakdown: 37 Monthly Partitions & Boundary Months

The 3-year historical dataset spans **37 monthly partitions** under `data/processed/binance/spot/BTCUSDT/{timeframe}/year=YYYY/month=MM/`. The 37 partitions comprise three distinct operational categories:

1. **Partial Initial Boundary Month (`2023-09`)**:
   - Interval: `2023-09-18T00:00:00Z` → `2023-09-30T23:59:00Z`
   - Active Coverage: 13 calendar days (18,720 minutes).
   - Ingestion: Acquired via 13 daily bulk archives (`BTCUSDT-1m-2023-09-18.zip` through `2023-09-30.zip`) because Binance monthly archives encompass the entire calendar month from day 1. Acquiring daily archives ensured zero unwanted pre-horizon data was fetched.
2. **35 Full Calendar Months (`2023-10` through `2026-08`)**:
   - Interval: `2023-10-01T00:00:00Z` → `2026-08-31T23:59:00Z`
   - Active Coverage: 1,066 calendar days (1,535,040 minutes).
   - Ingestion: Acquired via 35 official monthly bulk archives (`BTCUSDT-1m-YYYY-MM.zip`).
3. **Partial Final Boundary Month (`2026-09`)**:
   - Interval: `2026-09-01T00:00:00Z` → `2026-09-17T23:59:00Z`
   - Active Coverage: 17 calendar days (24,480 minutes).
   - Ingestion: Acquired via 17 daily bulk archives (`BTCUSDT-1m-2026-09-01.zip` through `2026-09-17.zip`), seamlessly merging with the validated Phase 1B 7-day foundation dataset (`2026-09-11` to `2026-09-18`).
- **Mathematical Total**: 18,720 + 1,535,040 + 24,480 = **1,578,240 1m candles**.

---

## 3. Actual Acquisition Sources & Provider Abstraction

- **Bulk Historical Provider**: Decoupled `BinanceVisionArchiveProvider` implementing repository `DataProvider` abstraction:
  - Base URL: `https://data.binance.vision/data/spot`
  - Monthly archives: `monthly/klines/BTCUSDT/1m/BTCUSDT-1m-YYYY-MM.zip`
  - Daily archives: `daily/klines/BTCUSDT/1m/BTCUSDT-1m-YYYY-MM-DD.zip`
- **Fallback / Foundation Integration**: Phase 1B REST-acquired foundation (`binance_spot_btcusdt_1m_20260911_000000_to_20260917_235900.parquet`, SHA-256: `c717bf3f0e1e31a61d374fbe90c008e47840d02b0d57475d30e7970c3381d09e`) integrated into the September 2026 partition.
- **Zero Fabrication**: No synthetic candles, no price interpolation, and no forward-filling were introduced.

---

## 4. Cryptographic SHA-256 Verification Audit Chain

Every bulk archive file downloaded from the Binance Vision repository underwent mandatory cryptographic verification prior to extraction:

```text
Binance Archive URL
       ↓
Fetch Upstream Checksum File ({url}.CHECKSUM)
       ↓
Download Archive (.zip) Byte Stream
       ↓
Calculate Local SHA-256 Hash
       ↓
Assert: actual_sha256 == expected_sha256 (Hard Failure on Mismatch)
       ↓
Extract Uncompressed CSV (.csv)
       ↓
Record in Authoritative Monthly Partition Manifest
```

Across the 37 partitions, **66 authoritative source files** were cryptographically verified and recorded in the partition manifests:
- **35 Monthly Bulk Archive Zips** (`2023-10` to `2026-08`)
- **30 Daily Bulk Archive Zips** (13 for `2023-09`, 17 for `2026-09`)
- **1 Phase 1B Foundation Parquet File**

### Audit Sample Across Dataset Lifecycle

| Source File | Source Type | Verified SHA-256 Checksum | Manifest Location |
|---|:---:|---|---|
| `BTCUSDT-1m-2023-09-18.zip` | Daily Zip | `5ad1d3897b0428c9f9df82ef66fa20f43f557d5ec89f7d3c5962cb0331aac586` | `partitions/binance_spot_btcusdt_1m_202309_manifest.json` |
| `BTCUSDT-1m-2023-10.zip` | Monthly Zip | `9e854972545806398d124571916348238ce39961072730c200cca3c2e0bd50a3` | `partitions/binance_spot_btcusdt_1m_202310_manifest.json` |
| `BTCUSDT-1m-2024-02.zip` | Monthly Zip (Leap) | `d6159ca2a5ea976728ba6c6aeebe98236171887e1488102377a28e9389f5bc56` | `partitions/binance_spot_btcusdt_1m_202402_manifest.json` |
| `BTCUSDT-1m-2025-01.zip` | Monthly Zip | `be1699fe538a728ff206d9d13db9b82144d6dbbc3d6796ee24cc26bb0d8a5719` | `partitions/binance_spot_btcusdt_1m_202501_manifest.json` |
| `BTCUSDT-1m-2026-08.zip` | Monthly Zip | `602220f135b5a2bf3ca2664cb39bb7c24f60f6db9bf572b832b85e913a3036e7` | `partitions/binance_spot_btcusdt_1m_202608_manifest.json` |
| `BTCUSDT-1m-2026-09-17.zip` | Daily Zip | `579972ad0528ae508494db389b802cbde40f0bb8166ef8738fe4587cc731cba1` | `partitions/binance_spot_btcusdt_1m_202609_manifest.json` |
| `Phase 1B Parquet` | Parquet File | `c717bf3f0e1e31a61d374fbe90c008e47840d02b0d57475d30e7970c3381d09e` | `partitions/binance_spot_btcusdt_1m_202609_manifest.json` |

100% of the 66 source archive hashes are permanently recorded in the respective partition manifests under `data/metadata/manifests/partitions/`.

---

## 5. Raw File Count & Retention Reconciliation

The repository preserves **152 raw files** under `data/raw/binance/spot/BTCUSDT/1m/` totaling **320,947,180 bytes (~306.08 MB)**:

| File Type | Extension | Count | Description / Role |
|---|:---:|:---:|---|
| **Bulk Archive Zips** | `.zip` | **65** | Immutable downloaded zip files from Binance Vision (35 monthly + 30 daily). |
| **Extracted Raw CSVs** | `.csv` | **65** | Uncompressed raw kline CSV files extracted from each zip archive. |
| **REST JSON Payloads** | `.json` | **22** | Immutable raw REST API response chunks retained from Phase 1A (5 files) and Phase 1B (17 files). |
| **TOTAL** | — | **152** | **100% cryptographic reproducibility retained on disk.** |

---

## 6. Rigorous Gap Audit: Full 37-Partition Breakdown

The aggregate report of **0 gaps** across 1,578,240 consecutive minutes was validated through an exhaustive partition-by-partition analytical audit executed natively in DuckDB with strict UTC timezone enforcement:

| Partition | Expected | Actual | Distinct | Missing | Duplicates | UTC Interval Coverage | Boundary Status |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **2023-09** | 18,720 | 18,720 | 18,720 | 0 | 0 | `2023-09-18 00:00Z` to `2023-09-30 23:59Z` | Partial Initial Month (13 days) |
| **2023-10** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2023-10-01 00:00Z` to `2023-10-31 23:59Z` | Full Calendar Month |
| **2023-11** | 43,200 | 43,200 | 43,200 | 0 | 0 | `2023-11-01 00:00Z` to `2023-11-30 23:59Z` | Full Calendar Month |
| **2023-12** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2023-12-01 00:00Z` to `2023-12-31 23:59Z` | Full Calendar Month |
| **2024-01** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2024-01-01 00:00Z` to `2024-01-31 23:59Z` | Full Calendar Month |
| **2024-02** | 41,760 | 41,760 | 41,760 | 0 | 0 | `2024-02-01 00:00Z` to `2024-02-29 23:59Z` | Full Calendar Month (Leap: 29 days) |
| **2024-03** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2024-03-01 00:00Z` to `2024-03-31 23:59Z` | Full Calendar Month |
| **2024-04** | 43,200 | 43,200 | 43,200 | 0 | 0 | `2024-04-01 00:00Z` to `2024-04-30 23:59Z` | Full Calendar Month |
| **2024-05** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2024-05-01 00:00Z` to `2024-05-31 23:59Z` | Full Calendar Month |
| **2024-06** | 43,200 | 43,200 | 43,200 | 0 | 0 | `2024-06-01 00:00Z` to `2024-06-30 23:59Z` | Full Calendar Month |
| **2024-07** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2024-07-01 00:00Z` to `2024-07-31 23:59Z` | Full Calendar Month |
| **2024-08** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2024-08-01 00:00Z` to `2024-08-31 23:59Z` | Full Calendar Month |
| **2024-09** | 43,200 | 43,200 | 43,200 | 0 | 0 | `2024-09-01 00:00Z` to `2024-09-30 23:59Z` | Full Calendar Month |
| **2024-10** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2024-10-01 00:00Z` to `2024-10-31 23:59Z` | Full Calendar Month |
| **2024-11** | 43,200 | 43,200 | 43,200 | 0 | 0 | `2024-11-01 00:00Z` to `2024-11-30 23:59Z` | Full Calendar Month |
| **2024-12** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2024-12-01 00:00Z` to `2024-12-31 23:59Z` | Full Calendar Month |
| **2025-01** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2025-01-01 00:00Z` to `2025-01-31 23:59Z` | Full Calendar Month |
| **2025-02** | 40,320 | 40,320 | 40,320 | 0 | 0 | `2025-02-01 00:00Z` to `2025-02-28 23:59Z` | Full Calendar Month |
| **2025-03** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2025-03-01 00:00Z` to `2025-03-31 23:59Z` | Full Calendar Month |
| **2025-04** | 43,200 | 43,200 | 43,200 | 0 | 0 | `2025-04-01 00:00Z` to `2025-04-30 23:59Z` | Full Calendar Month |
| **2025-05** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2025-05-01 00:00Z` to `2025-05-31 23:59Z` | Full Calendar Month |
| **2025-06** | 43,200 | 43,200 | 43,200 | 0 | 0 | `2025-06-01 00:00Z` to `2025-06-30 23:59Z` | Full Calendar Month |
| **2025-07** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2025-07-01 00:00Z` to `2025-07-31 23:59Z` | Full Calendar Month |
| **2025-08** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2025-08-01 00:00Z` to `2025-08-31 23:59Z` | Full Calendar Month |
| **2025-09** | 43,200 | 43,200 | 43,200 | 0 | 0 | `2025-09-01 00:00Z` to `2025-09-30 23:59Z` | Full Calendar Month |
| **2025-10** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2025-10-01 00:00Z` to `2025-10-31 23:59Z` | Full Calendar Month |
| **2025-11** | 43,200 | 43,200 | 43,200 | 0 | 0 | `2025-11-01 00:00Z` to `2025-11-30 23:59Z` | Full Calendar Month |
| **2025-12** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2025-12-01 00:00Z` to `2025-12-31 23:59Z` | Full Calendar Month |
| **2026-01** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2026-01-01 00:00Z` to `2026-01-31 23:59Z` | Full Calendar Month |
| **2026-02** | 40,320 | 40,320 | 40,320 | 0 | 0 | `2026-02-01 00:00Z` to `2026-02-28 23:59Z` | Full Calendar Month |
| **2026-03** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2026-03-01 00:00Z` to `2026-03-31 23:59Z` | Full Calendar Month |
| **2026-04** | 43,200 | 43,200 | 43,200 | 0 | 0 | `2026-04-01 00:00Z` to `2026-04-30 23:59Z` | Full Calendar Month |
| **2026-05** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2026-05-01 00:00Z` to `2026-05-31 23:59Z` | Full Calendar Month |
| **2026-06** | 43,200 | 43,200 | 43,200 | 0 | 0 | `2026-06-01 00:00Z` to `2026-06-30 23:59Z` | Full Calendar Month |
| **2026-07** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2026-07-01 00:00Z` to `2026-07-31 23:59Z` | Full Calendar Month |
| **2026-08** | 44,640 | 44,640 | 44,640 | 0 | 0 | `2026-08-01 00:00Z` to `2026-08-31 23:59Z` | Full Calendar Month |
| **2026-09** | 24,480 | 24,480 | 24,480 | 0 | 0 | `2026-09-01 00:00Z` to `2026-09-17 23:59Z` | Partial Final Month (17 days) |
| **TOTAL** | **1,578,240** | **1,578,240** | **1,578,240** | **0** | **0** | **`2023-09-18 00:00Z` to `2026-09-17 23:59Z`** | **100.00% Contiguous** |

### Analytical Invariant Audit Checks
- **Timestamp Monotonicity**: 100% strictly ascending (adjacent timestamp difference $\Delta T \equiv 60\text{ seconds}$).
- **Conflicting Duplicate Records**: 0.
- **Exact Duplicate Records**: 0.
- **Zero-Volume Candles**: Preserved faithfully (authentic exchange records with zero trades).
- **Persistent Gap Registry**: Initialized at `data/metadata/gap_registry/binance_spot_btcusdt_gaps.json` with `total_gaps_count: 0`.

---

## 7. Derived Timeframe Completeness & Verification Test

### Derived Timeframe Metrics
Higher timeframes were generated strictly from validated 1m data using pure Python deterministic aggregation:

| Timeframe | Ratio | Total Bars | Complete Bars | Completeness % | Parquet Storage | Price Envelope (Min / Max) | Total Base Volume |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **1m** | 1 | 1,578,240 | 1,578,240 | 100.00% | 65.51 MB | $25,964.01 / $126,200.00 | 29,165,584.22 |
| **5m** | 5 | 315,648 | 315,648 | 100.00% | 13.97 MB | $25,964.01 / $126,200.00 | 29,165,584.22 |
| **15m** | 15 | 105,216 | 105,216 | 100.00% | 4.92 MB | $25,964.01 / $126,200.00 | 29,165,584.22 |
| **1h** | 60 | 26,304 | 26,304 | 100.00% | 1.39 MB | $25,964.01 / $126,200.00 | 29,165,584.22 |
| **4h** | 240 | 6,576 | 6,576 | 100.00% | 0.44 MB | $25,964.01 / $126,200.00 | 29,165,584.22 |
| **1d** | 1,440 | 1,096 | 1,096 | 100.00% | 0.16 MB | $25,964.01 / $126,200.00 | 29,165,584.22 |

*Note: Total Base Volume is strictly conserved across all timeframes down to floating-point precision ($29,165,584.22\text{ BTC}$).*

### Incomplete Bar Marking Verification Test
While the 3-year historical Binance dataset contained 0 gaps, future updates or other instruments may encounter gaps. The system implements the following invariant:
> If any constituent 1m candle is missing within a bucket, the higher-timeframe candle is constructed from the available constituent candles (preserving OHLC and volume), but **must be marked `is_complete=False`**.

To verify this behavior, an automated unit test was added and executed:
- **Test Symbol**: `tests/unit/test_resampler.py::test_missing_constituent_marks_all_derived_timeframes_incomplete`
- **Methodology**: Synthesizes a 1-day series of 1,440 1m candles with minute `00:03:00` omitted (1,439 candles present).
- **Assertions Verified**:
  - `5m`: Bar for `00:00:00` has 4 constituents and `is_complete == False`; all other 287 bars have `is_complete == True`.
  - `15m`: Bar for `00:00:00` has 14 constituents and `is_complete == False`; all other 95 bars have `is_complete == True`.
  - `1h`: Bar for `00:00:00` has 59 constituents and `is_complete == False`; all other 23 bars have `is_complete == True`.
  - `4h`: Bar for `00:00:00` has 239 constituents and `is_complete == False`; all other 5 bars have `is_complete == True`.
  - `1d`: Bar for `00:00:00` has 1,439 constituents and `is_complete == False`.
- **Result**: **PASS**.

---

## 8. Storage Performance: Benchmark vs Actual Full-Dataset Scaling

### Empirical Micro-Benchmark on Isolated Write Path
To diagnose and resolve the 251.7-second Phase 1B write bottleneck, an empirical benchmark script (`scripts/benchmark_parquet_storage.py`) was executed on the identical 10,080-row foundation dataset:

| Dataset Scope | Row Count | Before (`con.executemany`) | After (Vectorized Bulk Staged COPY) | Measured Speedup Factor |
|---|:---:|:---:|:---:|:---:|
| **Sample Chunk** | 1,000 rows | 22.189s | 0.306s | **72.6x** |
| **Full Phase 1B Foundation** | 10,080 rows | 251.722s | 0.398s | **632.7x** |

### Actual 3-Year End-to-End Scaling Evidence
The isolated micro-benchmark speedup (632.7x) is specific to the Parquet serialization step. The actual full 3-year execution encompasses the entire data engineering pipeline:
- Network download of 65 bulk archives + checksum files
- Upstream SHA-256 cryptographic verification
- In-memory zip decompression and CSV extraction
- High-throughput CSV parsing and `CanonicalCandle` instantiation
- Full mathematical validation via `MarketDataValidator`
- Vectorized Parquet writing across 37 partitioned directories
- Multi-timeframe resampling across 5 derived timeframes (5m, 15m, 1h, 4h, 1d)
- Writing partitioned Parquet files for all derived timeframes
- Partition manifest generation and checkpoint updates

**Measured Full-Pipeline Results**:
- **Total Runtime**: **345.46 seconds** (~5.75 minutes)
- **Total Rows Processed (1m Base)**: 1,578,240 candles
- **Total Higher-Timeframe Rows Resampled**: 454,840 candles
- **End-to-End Ingestion Throughput**: **~4,568 canonical 1m candles per second** (including all network I/O, extraction, validation, resampling, and partitioned storage)
- **Parquet Write Time per Monthly Partition (~44,640 rows)**: ~1.17 seconds

---

## 9. Controlled Interruption & Idempotency Operational Verification

1. **Controlled Interruption Test**:
   - The engine was initiated with `interrupt_after_partitions=16`.
   - Interruption occurred after writing partition `202412`.
   - The durable checkpoint file `data/metadata/checkpoints/expansion_btcusdt_1m_202309_202609.json` was inspected:
     - `status`: `"interrupted"`
     - `partitions_completed`: 16 partitions recorded with hashes and row counts.
2. **Resumption Verification**:
   - The engine was resumed with `resume=True`.
   - Partitions 1 through 16 were identified on disk, validated, and skipped without issuing redundant network calls.
   - Partitions 17 through 37 proceeded to completion seamlessly.
3. **Idempotency Verification**:
   - Re-running `HistoricalExpansionEngine.run(resume=True)` on the finished dataset completed in **0.48 seconds**, confirming that existing validated partitions are detected idempotently without rewriting or duplicate generation.

---

## 10. Dependency Boundary: Preserving Lean Architecture (No PyArrow)

- **Architectural Evaluation**: DuckDB's native bulk engine (`COPY FROM ... DELIMITER '\t'` / replacement scan) fully eliminated the serialization bottleneck, writing 10,080 rows in 0.398s and an entire month of 44,640 rows in 1.17s.
- **Decision**: `pyarrow` is **not added** to `pyproject.toml`. Keeping PyArrow out preserves the lean dependency boundary established in Phase 0 while satisfying all performance and type-safety requirements.

---

## 11. Test Suite, Linting, Type Safety & Health Check Results

All verification suites were run against the updated codebase:

1. **Automated Unit & Integration Tests**:
   - Command: `.venv\Scripts\python.exe -m pytest -m "not network"`
   - Output: **50 passed, 2 deselected in 5.82s** (including the new derived timeframe completeness test).
2. **Code Quality & Linter**:
   - Command: `.venv\Scripts\ruff.exe check .`
   - Output: **All checks passed!** (0 errors, 0 warnings).
3. **Static Type Checker**:
   - Command: `.venv\Scripts\mypy.exe src tests`
   - Output: **Success: no issues found in 42 source files**.
4. **Repository Health Check**:
   - Command: `.venv\Scripts\python.exe scripts/health_check.py`
   - Output: **ALL 7 SUBSYSTEMS PASSED** (Python 3.12, venv, layout, dependencies, config, logging, git).

---

## 12. Dataset Version & Manifest Lineage

- **Canonical Dataset Version**: `v1.1.0`
- **Canonical Dataset ID**: `binance_spot_btcusdt_canonical_v1.1.0`
- **Parent Dataset**: `v1.0.0` (Phase 1B 7-day foundation)
- **Root Dataset Manifest**:
  - Path: `data/metadata/manifests/binance_spot_btcusdt_canonical_v1.1.0_manifest.json`
  - Research Copy: `artifacts/datasets/binance_spot_btcusdt_canonical_v1.1.0_manifest.json`
  - SHA-256: `bbed6aea4b69a90f2b8b6f7886a8cc74b3f8da6095ed66b7736531fefbab9c5a`
- **Monthly Partition Manifests**: 37 individual manifests under `data/metadata/manifests/partitions/`
- **Derived Timeframe Manifests**:
  - `5m`: `data/metadata/manifests/binance_spot_btcusdt_5m_v1.1.0_manifest.json`
  - `15m`: `data/metadata/manifests/binance_spot_btcusdt_15m_v1.1.0_manifest.json`
  - `1h`: `data/metadata/manifests/binance_spot_btcusdt_1h_v1.1.0_manifest.json`
  - `4h`: `data/metadata/manifests/binance_spot_btcusdt_4h_v1.1.0_manifest.json`
  - `1d`: `data/metadata/manifests/binance_spot_btcusdt_1d_v1.1.0_manifest.json`

---

## 13. Phase 1A Legacy Manifest Disposition

The two previously untracked Phase 1A pilot manifests have been organized and retained for historical provenance:
- Primary location: `data/metadata/manifests/legacy/binance_spot_btcusdt_1m_202609190654_202609190853_manifest.json`
- Research copy: `artifacts/datasets/legacy/binance_spot_btcusdt_1m_202609190654_202609190853_manifest.json`
- The `.gitignore` rules have been updated (`!data/metadata/manifests/**/` and `!artifacts/datasets/**/`) so that legacy provenance directories remain tracked by git rather than accidentally ignored.

---

## 14. Explicit Non-Goals & Scope Enforcement

Phase 1C was strictly confined to historical data engineering:
- **Zero Technical Indicators**: No SMA, EMA, RSI, MACD, Bollinger Bands, ATR.
- **Zero Market Regimes**: No HMM, clustering, volatility state modeling.
- **Zero Strategy Discovery**: No rules, triggers, or signal engines.
- **Zero Backtesting**: No fills, slippage, trade simulation, or PnL accounting.
- **Zero Machine Learning / TimesFM**: No model training or forecasting.
- **Zero Git Changes Beyond Working Tree**: No commits, pushes, merges, or remote changes have been performed.

