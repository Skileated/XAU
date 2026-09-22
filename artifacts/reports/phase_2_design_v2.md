# Phase 2 Design Specification: Market Feature Engine (Revision 2)

**Project**: XAU Quantitative Strategy Discovery and Decision Platform
**Phase**: 2 (Market Feature Engine)
**Revision**: 2 — incorporating Nishant's 10-point review of Revision 1
**Status**: DESIGN DOCUMENT — Awaiting Final Review and Approval — Zero Implementation Done
**Date**: 2026-09-19
**Primary Target Dataset**: `BTCUSDT` Binance Spot — Phase 1C canonical dataset (`v1.1.0`)
**Research Clock**: 5-minute bars (primary); 1m, 15m, 1h as context timeframes
**Execution Boundary**: Feature Engineering Only — Zero Strategies, Zero Signals, Zero ML, Zero Backtesting, Zero UI

---

## Revision Summary

This document supersedes Revision 1. The following corrections have been applied:

| # | Issue | Resolution |
|---|---|---|
| R1 | MTF alignment introduced look-ahead | Corrected alignment formula: `floor(t − 600s, 15m)` and `floor(t − 3300s, 1h)` |
| R2 | Pivot features stored at pivot timestamp (leakage) | Confirmation-time semantics: stored at detection bar with explicit pivot timestamp field |
| R3 | Feature counts inconsistent; manually maintained | `FeatureRegistry` is now the single source of truth for all counts |
| R4 | MTF warm-up derived incorrectly | Automated warm-up formula; correct maximum is 311 5m bars (~26h), not 288 |
| R5 | Contradictory missing-data policy | Single policy: gap invalidates any feature window crossing it; no window extension |
| R6 | "Bit-identical across machines" too strong | Deterministic on supported runtime; cross-machine numerical equivalence within tolerance |
| R7 | MACD warm-up was based on convergence approximation | SMA-seeded initialization; correct warm-up is 35 bars, not 87 |
| R8 | Registry not authoritative | `FeatureRegistry` schema defined; all downstream artifacts derived from it |
| R9 | Session definitions hardcoded | Sessions defined in `configs/feature_sessions.yaml`; `session_definition_version` in registry |
| R10 | Hurst proxy not clearly qualified | Registry fields `estimator_type` and `interpretation` explicitly mark it as a proxy |

---

## 1. Objective and Scope

### 1.1 Mission Statement

Phase 2 builds a **deterministic, temporally correct, research/live-parity market feature layer** on top of the validated Phase 1C BTCUSDT Spot dataset. Its sole output is a versioned, schema-validated feature dataset that downstream strategy discovery can consume without re-computing or re-validating features.

The feature engine must be:
- **Deterministic**: on a supported runtime environment, identical inputs produce identical results; repeated runs produce identical serialized Parquet output
- **Temporally correct**: zero look-ahead; features at bar `t` use only information available at the close of bar `t`
- **Research/live-parity**: the exact same computation path runs on historical completed bars and on live completed bars without divergence
- **Instrument/provider-agnostic**: architecture accommodates XAUUSD and any future instrument by configuration, not by code modification
- **Registry-driven**: feature counts, warm-up periods, schema, manifest metadata, and validation rules are all derived automatically from the `FeatureRegistry`; no value is maintained in two places

### 1.2 In-Scope

| Item | Detail |
|---|---|
| **Primary research clock** | 5m bars (granularity at which features are indexed) |
| **Context timeframes** | 1m (microstructure), 15m (intraday trend), 1h (session cycle) |
| **Input dataset** | Phase 1C BTCUSDT v1.1.0 canonical partitioned Parquet dataset |
| **Output** | Versioned feature Parquet dataset under `data/features/` |
| **Feature families** | Price/Returns, Momentum, Volatility, Volume/Liquidity, Market Structure, Mean-Reversion, Session/Time, Multi-Timeframe |
| **Quality controls** | NaN/inf handling, gap-invalidation policy, duplicate detection, history guards, numerical stability, validity metadata per row |

### 1.3 Explicit Exclusions

> [!IMPORTANT]
> The following are categorically **out of scope** for Phase 2:
> - No strategy generation of any kind
> - No backtesting or PnL accounting
> - No regime classifier (HMM, clustering, rule-based)
> - No ML/LLM feature generation or learned representations
> - No trading signals (no BUY/SELL/HOLD labels)
> - No execution logic (no order routing, slippage, fill simulation)
> - No UI (no dashboard, no visualization layer)
> - No real-time streaming pipeline (live-parity is a design constraint; streaming is a future phase)
> - No 4h or 1d features in Phase 2.0 (deferred per explicit decision)

### 1.4 Explicit Decisions Recorded

| Decision | Resolution |
|---|---|
| NumPy/pandas dependency | **No new dependency in Phase 2.0** |
| Feature count | **Derived from FeatureRegistry; no manual claim of "82 features"** |
| Hurst proxy | **Include in v2.0.0, marked `estimator_type="rs_proxy"`, `interpretation="research_feature_only"`** |
| Pivot representation | **Confirmation-time semantics required (correction R2)** |
| 4h/1d MTF context | **Deferred to Phase 2.1** |
| Missing-data policy | **Gap invalidates any window crossing it; no backward extension** |
| MTF alignment | **Completed-bar-at-primary-close rule (correction R1)** |
| Feature counts | **Generated automatically from FeatureRegistry (correction R3)** |
| Cross-machine determinism | **Numerical equivalence within tolerance, not absolute bit identity (correction R6)** |
| New Python dependencies | **None for Phase 2.0** |

---

## 2. Feature Taxonomy

### 2.1 Distinction: Raw Observations vs. Derived Features

| Category | Definition |
|---|---|
| **Raw observation** | A field sourced directly from a `CanonicalCandle` without computation: `open`, `high`, `low`, `close`, `volume`, `quote_volume`, `trade_count`, `taker_buy_base_volume`, `taker_buy_quote_volume`, `is_complete` |
| **Derived feature** | Any computation applied to raw observations across one or more bars |

Raw observations are **not** stored in the feature dataset. They remain in the canonical candle dataset. The feature dataset contains only derived features plus the composite primary key (`timestamp_utc`, `venue`, `instrument`, `timeframe`) and validity metadata.

### 2.2 Feature Families

| # | Family | Prefix | Description |
|---|---|---|---|
| 1 | **Price and Returns** | `ret_` / `price_` | Log-returns, bar-body, wick metrics |
| 2 | **Momentum** | `mom_` | Rate-of-change, regression slope, EMA/SMA deviation, RSI, MACD |
| 3 | **Volatility** | `vol_` | ATR, realized volatility, Garman-Klass estimator, vol Z-score |
| 4 | **Volume and Liquidity** | `liq_` | Taker aggression ratio, average trade size, VWAP deviation, volume ratio, delta proxy |
| 5 | **Market Structure** | `ms_` | Rolling high/low, price position, bars-since-extremum, pivot confirmation |
| 6 | **Mean-Reversion** | `mr_` | Z-score of close, mean deviation, Hurst proxy, lag-1 autocorrelation |
| 7 | **Session and Time** | `time_` | UTC hour, day-of-week, cyclic encodings, configurable session flags |
| 8 | **Multi-Timeframe** | `mtf_` | 1m, 15m, 1h features aligned using the completed-bar-at-close rule |

The exact count of features in each family is **authoritative only in the FeatureRegistry** (see Section 7). All references to counts elsewhere in this document are illustrative approximations.

---

## 3. Mathematical Definitions

All definitions use **completed-bar semantics** (Section 4). The 5m bar at open-timestamp `t` covers `[t, t + 300s)` and is the atomic unit of the feature dataset.

**Notation**:
- `C[t]`, `O[t]`, `H[t]`, `L[t]` — close, open, high, low of the 5m bar at open-timestamp `t`
- `V[t]`, `QV[t]`, `N[t]`, `TB[t]`, `TQ[t]` — volume, quote volume, trade count, taker buy base/quote volume
- `n` — lookback window in completed 5m bars (inclusive of bar `t` unless stated)
- All logarithms: natural log (`ln`)
- `eps = 1e-8` throughout (numerical stability guard)

---

### 3.1 Price and Returns Family

**3.1.1 Log-Return (Close-to-Close)**
```
ret_log_cc_{n}  =  ln(C[t]) - ln(C[t-n])
```
- `n in {1, 3, 6, 12, 24, 48, 96}` — 5m, 15m, 30m, 1h, 2h, 4h, 8h wall-clock
- Expected range: approx (−0.10, +0.10) under normal conditions
- Warm-up: `n` 5m bars

**3.1.2 Intra-Bar Log-Return (Open-to-Close)**
```
ret_log_oc  =  ln(C[t]) - ln(O[t])
```
- Warm-up: 0

**3.1.3 Bar Body Ratio**
```
price_body_ratio  =  |C[t] - O[t]| / (H[t] - L[t] + eps)
```
- Range: [0, 1]; 1 = full-body candle, 0 = doji. Warm-up: 0

**3.1.4 Upper Wick Ratio**
```
price_upper_wick_ratio  =  (H[t] - max(O[t], C[t])) / (H[t] - L[t] + eps)
```
- Range: [0, 1]. Warm-up: 0

**3.1.5 Lower Wick Ratio**
```
price_lower_wick_ratio  =  (min(O[t], C[t]) - L[t]) / (H[t] - L[t] + eps)
```
- Range: [0, 1]. Warm-up: 0

**3.1.6 Bar Midpoint**
```
price_midpoint  =  (H[t] + L[t]) / 2
```
- Units: USD. Warm-up: 0

---

### 3.2 Momentum Family

**3.2.1 Rate of Change (ROC)**
```
mom_roc_{n}  =  (C[t] - C[t-n]) / C[t-n]
```
- `n in {6, 12, 24, 48}` — 30m, 1h, 2h, 4h. Warm-up: `n` bars.

**3.2.2 Smoothed Close Slope (OLS)**

Fit `y[k] = ln(C[t-n+1+k])` vs `x[k] = k` for `k = 0..n-1` using OLS:
```
x_bar   =  (n-1) / 2
S_xx    =  sum((x[k] - x_bar)^2)   =  n*(n^2-1)/12   [precomputable for fixed n]
S_xy    =  sum((x[k] - x_bar) * y[k])
b       =  S_xy / S_xx              [OLS slope in log-price per bar]
mom_slope_{n}  =  b * n / (|ln(C[t])| + eps)   [normalized]
```
- `n in {12, 24, 48}` — 1h, 2h, 4h. Warm-up: `n` bars.
- Note: `S_xx` is constant for fixed `n` and is precomputed once in the registry.

**3.2.3 SMA Deviation**
```
SMA_{n}  =  mean(C[t-n+1], ..., C[t])
mom_sma_dev_{n}  =  (C[t] - SMA_{n}) / SMA_{n}
```
- `n in {12, 24, 48, 96}`. Warm-up: `n` bars.

**3.2.4 EMA Deviation (SMA-seeded initialization)**

All EMAs in this system use **SMA-seeded initialization**: the EMA state is initialized with the SMA of the first `n` bars at position `n-1` (0-indexed). This gives an exact, well-defined start, not an approximation.

```
Initialization (at bar index n-1, 0-indexed):
  EMA[n-1]  =  mean(C[0], ..., C[n-1])

Update (for bar index i >= n):
  alpha     =  2 / (n + 1)
  EMA[i]    =  alpha * C[i] + (1 - alpha) * EMA[i-1]

mom_ema_dev_{n}  =  (C[t] - EMA[t]) / EMA[t]
```

- `n in {12, 26, 50}`. Warm-up: **`n` bars** (not `3*n`; the SMA seed is exact, not an approximation)
- The `3*n` convergence rule from Revision 1 is **removed**. SMA-seeded EMAs are valid from the first initialized bar.

**3.2.5 MACD Histogram (Normalized, SMA-seeded)**

All component EMAs use SMA-seeded initialization:

```
EMA_12[i]    =  SMA-seeded EMA with n=12     [valid from bar 11, 0-indexed]
EMA_26[i]    =  SMA-seeded EMA with n=26     [valid from bar 25, 0-indexed]
MACD_line[i] =  EMA_12[i] - EMA_26[i]       [valid from bar 25; EMA_12 is re-seeded at bar 25]
```

> [!IMPORTANT]
> When computing MACD, `EMA_12` must be re-seeded at the same bar where `EMA_26` becomes valid (bar 25, 0-indexed), using the SMA of `C[14..25]` (the 12 bars ending at bar 25). This ensures both component EMAs share the same initialization epoch, preventing a spurious MACD_line based on a mismatched EMA_12 seed.

```
MACD_signal[i] =  SMA-seeded EMA of MACD_line with n=9
                   [seeded at bar 25+9-1=33, valid from bar 33, 0-indexed]

mom_macd_hist  =  (MACD_line[t] - MACD_signal[t]) / (C[t] + eps)
```

**Warm-up: 34 bars (0-indexed) = 35 bars from the start of the series.** This is the exact, derivable warm-up from the SMA-seeded initialization procedure.

**3.2.6 RSI (Wilder Smoothed, SMA-seeded)**
```
delta[i]   =  C[i] - C[i-1]
U[i]       =  max(delta[i], 0)
D[i]       =  max(-delta[i], 0)

Initialization (bar index n, 0-indexed, using first n deltas):
  AvgU[n]  =  mean(U[1], ..., U[n])
  AvgD[n]  =  mean(D[1], ..., D[n])

Update (bar index i > n):
  AvgU[i]  =  ((n-1) * AvgU[i-1] + U[i]) / n
  AvgD[i]  =  ((n-1) * AvgD[i-1] + D[i]) / n

RS[i]      =  AvgU[i] / (AvgD[i] + eps)
mom_rsi_{n}  =  100 - 100 / (1 + RS[i])
```
- `n in {14, 28}`. Range: [0, 100]. Warm-up: **`n + 1` bars** (requires `n` deltas to seed the Wilder average).

---

### 3.3 Volatility Family

**3.3.1 Average True Range (ATR, SMA-seeded)**
```
TR[t]     =  max(H[t]-L[t], |H[t]-C[t-1]|, |L[t]-C[t-1]|)

Initialization (at bar n, 0-indexed):
  ATR[n]  =  mean(TR[1], ..., TR[n])

Update (bar i > n):
  ATR[i]  =  ((n-1) * ATR[i-1] + TR[i]) / n

vol_atr_{n}      =  ATR[t]           (USD)
vol_atr_pct_{n}  =  ATR[t] / C[t]    (dimensionless)
```
- `n in {14, 28}`. Warm-up: **`n + 1` bars** (TR[t] requires `C[t-1]`).

**3.3.2 Realized Volatility (CC Log-Returns)**
```
r[i]  =  ln(C[i]) - ln(C[i-1])
vol_realized_{n}  =  std(r[t-n+1], ..., r[t], ddof=1)
```
- `n in {12, 24, 48, 96}`. Warm-up: **`n + 1` bars** (`n` returns require `n+1` closes).
- Note: `std(ddof=1)` is sample std, computed via Welford's online algorithm.

**3.3.3 Garman-Klass Volatility Estimator**
```
GK[t]  =  0.5*(ln(H[t]/L[t]))^2 - (2*ln(2)-1)*(ln(C[t]/O[t]))^2
vol_gk_realized_{n}  =  sqrt(mean(GK[t-n+1], ..., GK[t]))
```
- `n in {12, 24}`. Warm-up: `n` bars. Units: dimensionless.

**3.3.4 Volatility Z-Score**
```
vol_zscore_12_96  =  (vol_realized_12[t] - mean(vol_realized_12[t-96+1..t]))
                      / (std(vol_realized_12[t-96+1..t], ddof=1) + eps)
```
- Warm-up: warm-up of `vol_realized_12` + 96 = `(12+1) + 96 = 109` bars.

---

### 3.4 Volume and Liquidity Family

**3.4.1 Taker Aggression Ratio**
```
liq_taker_buy_ratio  =  TB[t] / (V[t] + eps)
```
- Range: [0, 1]. Warm-up: 0.

**3.4.2 Average Trade Size**
```
liq_avg_trade_size  =  V[t] / (N[t] + eps)
```
- Units: BTC/trade. Warm-up: 0.

**3.4.3 Rolling VWAP Deviation**
```
VWAP_{n}  =  sum(QV[t-n+1..t]) / (sum(V[t-n+1..t]) + eps)
liq_vwap_dev_{n}  =  (C[t] - VWAP_{n}) / VWAP_{n}
```
- `n in {12, 48}` — 1h, 4h. Warm-up: `n` bars.

**3.4.4 Volume Ratio**
```
liq_vol_ratio_{n}  =  V[t] / (mean(V[t-n+1..t]) + eps)
```
- `n in {12, 24, 48}`. Warm-up: `n` bars.

**3.4.5 Dollar Volume (Re-exposed)**
```
liq_dollar_volume  =  QV[t]
```
- Units: USD. Warm-up: 0. Re-exposed so downstream consumers never query the raw candle table.

**3.4.6 Cumulative Delta Proxy**
```
CD[t]  =  2*TB[t] - V[t]
liq_delta_proxy     =  CD[t] / (V[t] + eps)                              [single bar]
liq_cum_delta_{n}   =  sum(CD[t-n+1..t]) / (sum(V[t-n+1..t]) + eps)     [rolling]
```
- `n in {12, 48}` for rolling version. Range: [−1, 1]. Warm-up: `n` / 0 respectively.

---

### 3.5 Market Structure Family

> [!NOTE]
> All market structure computations use **completed bars only**.

**3.5.1 Rolling N-Bar High and Low**
```
ms_high_{n}  =  max(H[t-n+1], ..., H[t])
ms_low_{n}   =  min(L[t-n+1], ..., L[t])
```
- `n in {12, 24, 48, 96}`. Units: USD. Warm-up: `n` bars.

**3.5.2 Price Position within N-Bar Range**
```
ms_price_position_{n}  =  (C[t] - ms_low_{n}) / (ms_high_{n} - ms_low_{n} + eps)
```
- Range: [0, 1]. Warm-up: `n` bars.

**3.5.3 Bars Since N-Bar High/Low**
```
ms_bars_since_high_{n}  =  t - argmax_{i in [t-n+1, t]} H[i]   (ties: most recent index)
ms_bars_since_low_{n}   =  t - argmin_{i in [t-n+1, t]} L[i]
```
- `n in {24, 96}`. Range: [0, n−1] in bar count. Warm-up: `n` bars.

**3.5.4 Pivot Confirmation (Confirmation-Time Semantics)**

> [!IMPORTANT]
> **Correction R2**: Pivot features are stored at the **confirmation bar** (bar `t`), not the pivot bar. This ensures the feature is available at the exact time a strategy would first observe it.

A **pivot high of strength s** at bar `k` is confirmed at bar `t = k + s` when:
```
H[k] > H[k-j]  for all j in {1..s}   (s bars to the left — all complete at t=k+s)
H[k] > H[k+j]  for all j in {1..s}   (s bars to the right — all complete at t=k+s)
```

Three output columns are emitted at the **confirmation bar** `t = k + s`:

```
ms_is_pivot_high_{s}         =  True if a pivot high of strength s was confirmed at bar t
ms_pivot_high_timestamp_{s}  =  timestamp of the pivot bar k  (UTC; NaN if no confirmation)
ms_pivot_high_age_bars_{s}   =  s  (constant; the confirmation lag, in 5m bars)
```

Analogous fields for pivot low: `ms_is_pivot_low_{s}`, `ms_pivot_low_timestamp_{s}`, `ms_pivot_low_age_bars_{s}`.

- Strength `s in {3, 5}`.
- At bars where no pivot is confirmed, `ms_is_pivot_high_{s} = False` and the timestamp field = NaN/null.
- Warm-up: `2*s` bars.

A strategy consuming these features at bar `t` knows: a pivot high was confirmed this bar; the pivot occurred at `ms_pivot_high_timestamp_{s}`, `s` bars ago. This is fully temporal-correct — no information from the future is used.

**3.5.5 Consecutive Bar Direction**
```
ms_consec_up_{n}    =  length of current consecutive run of C[i] > C[i-1], at bar t, within n bars
ms_consec_down_{n}  =  analogous
```
- `n = 5`. Range: [0, 5]. Warm-up: `n + 1` bars.

---

### 3.6 Mean-Reversion Family

**3.6.1 Z-Score of Close**
```
mu_{n}  =  mean(C[t-n+1..t])
sg_{n}  =  std(C[t-n+1..t], ddof=1)   [Welford online]
mr_zscore_{n}  =  (C[t] - mu_{n}) / (sg_{n} + eps)
```
- `n in {24, 48, 96}`. Warm-up: `n` bars.

**3.6.2 Distance from Rolling Mean (Normalized)**
```
mr_mean_dev_{n}  =  (C[t] - mu_{n}) / (mu_{n} + eps)
```
- `n in {12, 48}`. Warm-up: `n` bars.

**3.6.3 Hurst Exponent Proxy (RS Method, Single Window)**

> [!NOTE]
> Registry metadata: `estimator_type = "rs_single_window_proxy"`, `interpretation = "research_feature_only"`. This feature must not be treated as a rigorous Hurst estimate or as a regime classifier. Its value is below/above 0.5 provides directional intuition only.

```
X[i]    =  ln(C[t-n+1+i]) - ln(C[t-n])   for i = 0..n-1
mean_X  =  mean(X[0..n-1])
Y[i]    =  X[i] - (i / (n-1)) * (n-1) * mean_X / (n-1)   =  X[i] - i * mean_X / (n-1)
R       =  max(Y) - min(Y)
S       =  std(ln(C[t-n+1..t]) - ln(C[t-n..t-1]), ddof=1)
RS      =  R / (S + eps)
mr_hurst_proxy_{n}  =  ln(RS) / ln(n),  clamped to [0, 1]
```
- `n in {48, 96}`. Warm-up: `n + 1` bars.

**3.6.4 Lag-1 Autocorrelation of Log-Returns**
```
r[i]  =  ln(C[i]) - ln(C[i-1])
mr_autocorr_lag1_{n}  =  Pearson(r[t-n+1..t], r[t-n..t-1])
```
- `n in {24, 96}`. Range: [−1, 1]. Warm-up: `n + 1` bars.

---

### 3.7 Session and Time Features

All time features are derived from the bar's UTC timestamp. **Warm-up: 0 for all.**

**3.7.1 UTC Hour**: `time_hour_utc = timestamp_utc.hour` in {0..23}

**3.7.2 Day of Week**: `time_dow = timestamp_utc.weekday()` in {0=Mon..6=Sun}

**3.7.3 Hour-of-Day Cyclic Encoding**:
```
time_hour_sin  =  sin(2*pi * time_hour_utc / 24)
time_hour_cos  =  cos(2*pi * time_hour_utc / 24)
```

**3.7.4 Day-of-Week Cyclic Encoding**:
```
time_dow_sin  =  sin(2*pi * time_dow / 7)
time_dow_cos  =  cos(2*pi * time_dow / 7)
```

**3.7.5 Session Flags (Configurable)**

> [!IMPORTANT]
> **Correction R9**: Session definitions are **not hardcoded** in the calculator. They are loaded from `configs/feature_sessions.yaml` and referenced via `session_definition_version` in the feature registry.

```yaml
# configs/feature_sessions.yaml
schema_version: "1.0.0"
sessions:
  - name: asian
    utc_start_hour: 0
    utc_end_hour: 8    # exclusive
    bit: 1
  - name: london
    utc_start_hour: 7
    utc_end_hour: 16
    bit: 2
  - name: new_york
    utc_start_hour: 13
    utc_end_hour: 22
    bit: 4
```

```
time_session_flags  =  bitwise OR of bit values for active sessions at time_hour_utc
```

Range: integer in {0..7} depending on active sessions. `session_definition_version = "1.0.0"` recorded in the feature manifest.

**3.7.6 Bars Since UTC Midnight**:
```
time_bars_since_midnight  =  (hour*60 + minute) // 5
```
Range: [0, 287].

**3.7.7 Bars Since Monday Midnight**:
```
time_bars_since_week_open  =  time_dow * 288 + time_bars_since_midnight
```
Range: [0, 2015].

---

### 3.8 Multi-Timeframe Features

> [!IMPORTANT]
> **Correction R1**: The alignment rule has been corrected. The v1 rule `t_TF = floor(t, TF)` was incorrect because it could reference a higher-timeframe bar that had not yet closed when the 5m bar closed. The corrected rule follows.

#### 3.8.1 Corrected MTF Alignment Rule (Derived)

A 5m bar opens at `t` and closes at `t + 300s`. A higher-timeframe bar at open-timestamp `t_TF` covers `[t_TF, t_TF + D_TF)` and is complete at `t_TF + D_TF`.

For the HTF bar to be **complete** at or before the 5m bar's close:
```
t_TF + D_TF  <=  t + 300s
t_TF         <=  t + 300s - D_TF  =  t - (D_TF - 300s)
```

The latest completed HTF bar at the close of 5m bar `t`:
```
t_TF_aligned  =  floor(t - (D_TF - 300s), D_TF)
               =  floor(t - (D_TF - 300s), D_TF)
```

**For 15m (D_TF = 900s):**
```
t_15m_aligned  =  floor(t - (900 - 300), 15m)
               =  floor(t - 600s, 15m)
```

**For 1h (D_TF = 3600s):**
```
t_1h_aligned   =  floor(t - (3600 - 300), 1h)
               =  floor(t - 3300s, 1h)
```

**Verification using the user's example:**

5m bar opens at `t = 14:05 UTC`, closes at `14:10 UTC`:
- Latest completed 15m bar: `floor(14:05 - 600s, 15m) = floor(13:55, 15m) = 13:45` ✓ (the 13:45–14:00 15m bar)
- Latest completed 1h bar: `floor(14:05 - 3300s, 1h) = floor(13:10, 1h) = 13:00` ✓ (the 13:00–14:00 1h bar)

Both are correct — the 14:00 15m bar and the 14:00 1h bar have not yet closed at 14:10 and are therefore excluded.

The alignment formula must be applied to **every** 5m bar at its open-timestamp `t`.

#### 3.8.2 MTF Features: 15m Timeframe

Aligned 15m bar: `t_15m = floor(t − 600s, 15m)`. All lookbacks are in completed 15m bars.

| Feature | Definition | 15m Lookback |
|---|---|---|
| `mtf_15m_ret_log_cc_4` | `ln(C_15[t_15m]) - ln(C_15[t_15m - 4*900s])` | 4 bars (1h) |
| `mtf_15m_ret_log_cc_16` | 16-bar 15m log-return | 16 bars (4h) |
| `mtf_15m_mom_rsi_14` | Wilder RSI-14 on 15m closes | 15 bars |
| `mtf_15m_vol_atr_pct_14` | Wilder ATR-14 % on 15m OHLC | 15 bars |
| `mtf_15m_price_position_16` | Close position in 16-bar 15m range | 16 bars |
| `mtf_15m_liq_taker_buy_ratio` | Single 15m bar taker ratio | 0 bars |
| `mtf_15m_liq_vol_ratio_16` | Volume ratio over 16 15m bars | 16 bars |

#### 3.8.3 MTF Features: 1h Timeframe

Aligned 1h bar: `t_1h = floor(t − 3300s, 1h)`.

| Feature | Definition | 1h Lookback |
|---|---|---|
| `mtf_1h_ret_log_cc_4` | 4-bar 1h log-return (4h) | 4 bars |
| `mtf_1h_ret_log_cc_24` | 24-bar 1h log-return (24h) | 24 bars |
| `mtf_1h_mom_rsi_14` | Wilder RSI-14 on 1h closes | 15 bars |
| `mtf_1h_vol_realized_24` | 24-bar realized vol on 1h closes | **25 bars** (24 returns need 25 closes) |
| `mtf_1h_price_position_24` | Close position in 24-bar 1h range | 24 bars |
| `mtf_1h_mr_zscore_24` | Z-score of 1h close over 24 bars | 24 bars |
| `mtf_1h_liq_taker_buy_ratio` | Single 1h bar taker ratio | 0 bars |

#### 3.8.4 MTF Features: 1m Microstructure Context

For each 5m bar at `t`, the 5 constituent 1m bars `{t, t+60s, t+120s, t+180s, t+240s}` yield (warm-up: 0):

| Feature | Definition |
|---|---|
| `mtf_1m_vol_dispersion` | `std(V_1m[0:5]) / (mean(V_1m[0:5]) + eps)` — coefficient of variation |
| `mtf_1m_taker_trend` | OLS slope of `TB_1m[i]/(V_1m[i]+eps)` over 5 bars, normalized by n |
| `mtf_1m_return_skew` | `(r_last - r_first) / (sum(|r_i|) + eps)` — momentum concentration |

---

## 4. Temporal Correctness

### 4.1 No Look-Ahead Principle

A feature is **look-ahead-free** if and only if its computation at bar `t` uses exclusively the information set:
```
I(t)  =  { C[s], O[s], H[s], L[s], V[s], QV[s], N[s], TB[s], TQ[s]
           : s <= t  AND  is_complete(s) = True }
```

No feature references bars `s > t` or any bar where `is_complete = False`.

### 4.2 Completed-Bar Semantics

A 5m bar at open-timestamp `t` is **complete** when:
1. Wall-clock time has passed `t + 300s`, AND
2. All 5 constituent 1m bars `{t, t+60s, t+120s, t+180s, t+240s}` have `is_complete = True`

**Historical (batch)**: all Phase 1C bars are `is_complete = True` by construction.
**Live (future phase)**: the engine must never emit a feature row before both conditions hold.

### 4.3 MTF Alignment Rule (Corrected)

See Section 3.8.1 for the full derivation. Summary:

| HTF | Duration `D_TF` | Alignment offset `D_TF - 300s` | Alignment formula |
|---|---|---|---|
| 15m | 900s | 600s | `floor(t - 600s, 15m)` |
| 1h | 3600s | 3300s | `floor(t - 3300s, 1h)` |

### 4.4 EMA Initialization (SMA-Seeded, Exact)

All EMAs in this system use **SMA-seeded initialization**, not a convergence approximation. This gives an exact, derivable warm-up and bit-stable results:

```
Initialization: EMA[n-1] = mean(C[0..n-1])
Update (i >= n): EMA[i] = alpha*C[i] + (1-alpha)*EMA[i-1]
```

Warm-up for any SMA-seeded EMA of span `n`: **`n` bars** (0-indexed: valid from bar `n-1`).

### 4.5 Warm-Up Derivation Rules (Automated in FeatureRegistry)

The `FeatureRegistry` computes `required_history_bars` for each feature automatically using these rules:

**Rule W1 — Primary-clock features**:
```
required_history_bars  =  max_lookback_bars + initialization_overhead
```
where `initialization_overhead` is 0 for SMA/rolling-mean features, 1 for features requiring a prior close (ATR, log-returns), and 0 for SMA-seeded EMAs.

**Rule W2 — MTF features**:
```
alignment_offset_bars  =  ceil((D_TF - 300) / 300)
                          [15m: ceil(600/300) = 2; 1h: ceil(3300/300) = 11]

required_5m_bars  =  alignment_offset_bars  +  htf_lookback_bars * (D_TF / 300)
                      +  htf_initialization_overhead * (D_TF / 300)
```

**Warm-up examples (derived, not manually entered):**

| Feature | Computation | Warm-up (5m bars) |
|---|---|---|
| `ret_log_cc_1` | `1 + 0` | 1 |
| `ret_log_cc_96` | `96 + 0` | 96 |
| `mom_roc_48` | `48 + 0` | 48 |
| `mom_ema_dev_50` | `50 + 0` (SMA-seeded) | 50 |
| `mom_macd_hist` | `26 + 9 - 1 = 34` | 35 |
| `mom_rsi_28` | `28 + 1` | 29 |
| `vol_atr_pct_28` | `28 + 1` | 29 |
| `vol_realized_96` | `96 + 1` | 97 |
| `vol_zscore_12_96` | `(12+1) + 96` | 109 |
| `ms_is_pivot_high_5` | `2*5` | 10 |
| `mr_hurst_proxy_96` | `96 + 1` | 97 |
| `mtf_15m_vol_atr_pct_14` | `2 + (15) * 3` | 47 |
| `mtf_1h_vol_realized_24` | `11 + (25) * 12` | **311** |
| `mtf_1h_ret_log_cc_24` | `11 + (24+1) * 12` | 311 |
| `mtf_1h_mom_rsi_14` | `11 + (15) * 12` | 191 |

**Maximum warm-up across all features: 311 5m bars ≈ 26 hours.** (Revised from the incorrect 288 bars in Revision 1.)

### 4.6 Missing Candle Behavior (Single Unified Policy)

> [!IMPORTANT]
> **Correction R5**: The contradictory dual-policy from Revision 1 is replaced with a single rule.

**Policy**: A gap in any candle used within a feature's computation window **invalidates that feature** for that bar. The feature output is NaN. The window is **not** extended backwards to find additional real bars.

Rationale: extending the window backwards silently changes the temporal meaning of the lookback (e.g., a "48-bar" window would no longer cover 4 hours of wall-clock time). This violates the geometric and temporal semantics of every lookback-based feature.

Specific mechanics:
1. If a 5m bar is entirely absent from the dataset (no timestamp entry), no feature row is emitted for that timestamp.
2. If any bar in a rolling window of `n` bars is absent (gap), all features that reference that window output NaN for the current bar.
3. EMA/ATR state: if a gap bar is encountered, the state is NOT updated for that bar, the feature outputs NaN, and the state resumes updating on the next present bar. This is the only valid exception — stateful features skip gaps without window-back-filling.
4. `is_valid = False` for any feature row where any computation window includes a gap bar.
5. MTF features: if the aligned HTF bar for a given 5m close is absent or incomplete, all MTF features for that 5m bar output NaN.

### 4.7 Duplicate Timestamp Handling

`FeatureInputValidator` raises `FeatureInputError` on duplicate timestamps before any computation. The event is logged as a critical data quality anomaly. No feature row is produced.

---

## 5. Research/Live Parity

### 5.1 Parity Requirement

The same `FeatureEngine` class and identical formulas operate in both:
- **Batch mode** (historical): sorted arrays of completed `CanonicalCandle` objects
- **Incremental mode** (future live): one newly-completed bar at a time, updating rolling state, emitting one feature row

No separate "research-only formula" that differs from the live formula is permitted.

### 5.2 Input Contract

```python
@dataclass(frozen=True)
class FeatureEngineInput:
    candles_primary: tuple[CanonicalCandle, ...]   # 5m bars, sorted ASC, all is_complete=True
    context_candles: dict[str, tuple[CanonicalCandle, ...]]  # {"1m": ..., "15m": ..., "1h": ...}
    venue: str
    instrument: str
    primary_timeframe: str                          # "5m"
    input_dataset_version: str                      # "v1.1.0"
    session_definition_version: str                 # "1.0.0"
```

Preconditions enforced by `FeatureInputValidator` before any computation:
- All candles have `is_complete = True`
- Strict chronological sort (no ties)
- Zero duplicate timestamps
- Consistent `(venue, instrument, timeframe)` throughout the list

### 5.3 Determinism Definition (Corrected)

> [!IMPORTANT]
> **Correction R6**: "Bit-identical across arbitrary machines" is too strong. The corrected definition:

**Within the same runtime environment** (Python 3.12, same duckdb version, same OS): repeated runs produce **identical serialized Parquet output** (same bytes, same SHA-256).

**Across different machines or OS versions**: outputs are **numerically equivalent** within defined tolerance:
- General features: `abs(a - b) <= 1e-12`
- EMA/ATR/RSI (iterative, potentially exhibiting floating-point accumulation differences): `abs(a - b) <= 1e-10`
- Z-scores with clamping: `abs(a - b) <= 1e-10`
- Time features (exact integer/trig computation): `a == b`

The determinism test suite must verify both same-machine identity and cross-Python-version numerical equivalence.

### 5.4 State Model for Incremental Operation

The engine maintains serializable per-instrument state:
- Bounded deque of the most recent `max_warm_up` (= 311) completed 5m bars
- Current SMA-seeded EMA values keyed by `(feature_name, n)`
- Current Wilder ATR values per `n`
- Current Wilder RSI AvgU/AvgD per `n`

State serialized to JSON so a live engine can resume after restart without reprocessing history.

---

## 6. Feature Quality Controls

### 6.1 NaN and Infinity Handling

| Condition | Action |
|---|---|
| Fewer bars available than `required_history_bars` | Return `float('nan')` |
| Denominator evaluates to 0 | Add `eps = 1e-8`; never return `inf` |
| Rolling std evaluates to 0 (constant series) | Z-score = 0.0; annotate in row metadata |
| Any input price is NaN or non-finite | Propagate NaN; do not crash |
| Result is `inf` or `-inf` after computation | Replace with NaN; log as data anomaly |

**Invariant**: zero `inf` or `-inf` in any output Parquet column.

### 6.2 Missing-Data Propagation

As defined in Section 4.6: one policy — gap invalidates. No exceptions except stateful accumulator skip (no window back-fill).

### 6.3 Feature Validity Metadata Columns

| Column | DuckDB Type | Description |
|---|---|---|
| `is_valid` | BOOLEAN | True if all features are non-NaN and no anomaly |
| `nan_feature_count` | SMALLINT | Count of NaN-valued feature columns in this row |
| `input_dataset_version` | VARCHAR | `"v1.1.0"` — links to Phase 1C root manifest |
| `feature_set_version` | VARCHAR | `"v2.0.0"` — links to FeatureRegistry version |
| `session_definition_version` | VARCHAR | `"1.0.0"` — links to session config version |

### 6.4 Numerical Stability

- Rolling variance and std use **Welford's online algorithm** throughout
- Log-price differences preferred over arithmetic differences
- Z-scores clamped to `[−10, +10]`; clamping logged as a data anomaly

---

## 7. Architecture and the FeatureRegistry

### 7.1 FeatureRegistry: Single Source of Truth

> [!IMPORTANT]
> **Correction R3 and R8**: `FeatureRegistry` is the authoritative source for all feature metadata. The following artifacts are **derived from the registry**, never manually maintained:
> - Feature count (total and per-family)
> - `required_history_bars` (warm-up) for each feature
> - Parquet schema (column list and types)
> - Feature manifest catalog section
> - Test parametrization (no-lookahead tests, boundary tests run over the registry)

### 7.2 FeatureRegistry Entry Schema

Each entry in the registry is a `FeatureDefinition` dataclass:

```python
@dataclass(frozen=True)
class FeatureDefinition:
    name: str                       # e.g. "mtf_1h_vol_realized_24"
    family: str                     # e.g. "mtf"
    calculator: str                 # e.g. "calculators.multitimeframe.compute_1h_vol_realized"
    parameters: dict                # e.g. {"n": 24}
    required_history_bars: int      # derived by FeatureRegistry at registration time
    units: str                      # e.g. "dimensionless", "USD", "bool"
    valid_range: tuple | None       # e.g. (0.0, 1.0) or None for unbounded
    temporal_semantics: str         # "point_in_time", "confirmation_lag_s" (for pivots)
    mtf_timeframe: str | None       # e.g. "15m", "1h", None for primary-clock features
    estimator_type: str             # e.g. "exact", "wilder_smoothed", "rs_proxy"
    interpretation: str             # e.g. "standard", "research_feature_only"
    session_definition_version: str | None  # e.g. "1.0.0" for session features, None otherwise
    version: str                    # e.g. "2.0.0"
```

The registry computes `required_history_bars` automatically using Rules W1 and W2 from Section 4.5 when a `FeatureDefinition` is registered.

### 7.3 Module Structure

```
src/xau_quant/
├── data/                            # Phase 1C — unchanged
│   ├── models.py                    # CanonicalCandle (consumed by features layer)
│   ├── storage.py                   # DuckDB Parquet I/O (pattern reused)
│   └── ...
└── features/                        # NEW — Phase 2
    ├── __init__.py
    ├── models.py                    # FeatureRow, FeatureDatasetManifest (Pydantic)
    ├── registry.py                  # FeatureRegistry + FeatureDefinition — single source of truth
    ├── engine.py                    # FeatureEngine — orchestration entry point
    ├── storage.py                   # FeatureParquetStorage — read/write
    ├── validators.py                # FeatureInputValidator, FeatureOutputValidator
    └── calculators/
        ├── __init__.py
        ├── returns.py
        ├── momentum.py
        ├── volatility.py
        ├── liquidity.py
        ├── structure.py
        ├── meanreversion.py
        ├── time_features.py
        └── multitimeframe.py

configs/
├── development.yaml
├── research.yaml
└── feature_sessions.yaml            # NEW — configurable session definitions

scripts/
└── compute_features.py              # CLI: compute and persist feature dataset

tests/
├── unit/features/
│   ├── test_returns.py
│   ├── test_momentum.py
│   ├── test_volatility.py
│   ├── test_liquidity.py
│   ├── test_structure.py
│   ├── test_meanreversion.py
│   ├── test_time_features.py
│   ├── test_multitimeframe.py
│   ├── test_registry.py            # NEW — registry consistency and warm-up derivation
│   ├── test_feature_engine.py
│   └── test_feature_storage.py
└── integration/features/
    └── test_feature_pipeline_integration.py
```

### 7.4 Component Responsibilities

| Component | Responsibility | Does NOT |
|---|---|---|
| `registry.py` | Single source of truth: defines all features; computes warm-up; derives schema and manifest | Compute feature values |
| `calculators/*.py` | Pure-function formula implementations | Access disk, manage state, validate inputs, compute warm-up |
| `engine.py` | Orchestrate: validate -> load aligned candles -> compute -> assemble rows -> validate output | Write disk, manage manifests |
| `storage.py` | Read/write feature Parquet; manage partitioning; compute SHA-256 | Compute features |
| `validators.py` | Validate input contracts; validate output rows (no inf, NaN policy, range) | Compute features |
| `models.py` | Pydantic schemas for `FeatureRow`, `FeatureDatasetManifest` | Business logic |

### 7.5 Calculator Interface Contract

```python
def compute_ret_log_cc(
    closes: list[float],
    *,
    n: int,
    epsilon: float = 1e-8,
) -> list[float | None]:
    """
    Pure function. Returns list of same length as closes.
    Index i is None if insufficient history (i < n).
    None converted to float('nan') by engine.
    No side effects. No I/O. No global state.
    """
```

### 7.6 Infrastructure Reuse Decision

**DuckDB reused** for feature storage. The vectorized TSV bulk-write pipeline from Phase 1C (`ParquetCandleStorage`) is the direct template for `FeatureParquetStorage`. No new Python dependencies.

> [!IMPORTANT]
> **Dependency decision confirmed**: NumPy and pandas excluded from Phase 2.0. Escalation path (no new dependencies): DuckDB SQL window functions.

---

## 8. Storage and Versioning

### 8.1 Feature Dataset Directory Layout

```
data/
└── features/
    └── binance/
        └── spot/
            └── BTCUSDT/
                └── 5m/
                    └── feature_set=v2.0.0/
                        ├── year=2023/month=09/
                        │   └── btcusdt_5m_features_v2.0.0_202309.parquet
                        └── ...

data/metadata/manifests/
└── btcusdt_5m_features_v2.0.0_manifest.json
```

### 8.2 Feature Row Parquet Schema

Schema is **derived from the FeatureRegistry** at build time. Manual column lists are not maintained.

**Fixed columns** (always present, independent of registry):

| Column | DuckDB Type | Description |
|---|---|---|
| `timestamp_utc` | TIMESTAMPTZ | 5m bar open timestamp (primary key) |
| `venue` | VARCHAR | e.g. `"binance"` |
| `instrument` | VARCHAR | e.g. `"BTCUSDT"` |
| `timeframe` | VARCHAR | `"5m"` |
| `is_valid` | BOOLEAN | True if all features non-NaN |
| `nan_feature_count` | SMALLINT | Count of NaN values |
| `input_dataset_version` | VARCHAR | `"v1.1.0"` |
| `feature_set_version` | VARCHAR | `"v2.0.0"` |
| `session_definition_version` | VARCHAR | `"1.0.0"` |

**Feature columns**: all DOUBLE, ordered by family then name, ordered generated from `FeatureRegistry.get_ordered_features()`. Exact count is the registry count at `v2.0.0` (determined at implementation time, not prescribed here).

**Pivot columns**: pivot features produce three DOUBLE/TIMESTAMPTZ/SMALLINT columns per entry:
- `ms_is_pivot_high_{s}` — BOOLEAN
- `ms_pivot_high_timestamp_{s}` — TIMESTAMPTZ (nullable)
- `ms_pivot_high_age_bars_{s}` — SMALLINT (constant `s` when pivot confirmed, null otherwise)

### 8.3 Feature Dataset Manifest Schema

```json
{
  "schema_version": "2.0.0",
  "feature_set_version": "v2.0.0",
  "dataset_id": "btcusdt_5m_features_v2.0.0",
  "created_at_utc": "<ISO timestamp>",
  "input_dataset": {
    "dataset_id": "binance_spot_btcusdt_canonical_v1.1.0",
    "dataset_version": "v1.1.0",
    "root_manifest_sha256": "<sha256>"
  },
  "engine": {
    "module": "xau_quant.features.engine",
    "commit_hash": "<git_sha>",
    "python_version": "3.12.x"
  },
  "session_definition_version": "1.0.0",
  "feature_clock": {
    "primary_timeframe": "5m",
    "context_timeframes": ["1m", "15m", "1h"],
    "mtf_alignment": {
      "15m": "floor(t - 600s, 15m)",
      "1h": "floor(t - 3300s, 1h)"
    }
  },
  "coverage": {
    "start_utc": "2023-09-18T00:00:00Z",
    "end_utc": "2026-09-18T00:00:00Z",
    "total_5m_bars": 315648,
    "max_warm_up_bars": 311,
    "valid_rows": "<derived>",
    "invalid_rows": "<derived>"
  },
  "feature_catalog": {
    "total_features": "<registry count>",
    "families": "<registry-derived per-family counts>"
  },
  "determinism": {
    "policy": "identical_serialized_parquet_on_same_runtime",
    "cross_machine_tolerance_abs": 1e-12
  },
  "storage": {
    "partition_unit": "month",
    "total_partitions": 37,
    "root_path": "data/features/binance/spot/BTCUSDT/5m/feature_set=v2.0.0/",
    "combined_parquet_sha256": "<sha256>"
  }
}
```

### 8.4 Feature Set Versioning

| Version | Trigger |
|---|---|
| `v2.0.0` | Initial Phase 2 feature set |
| `v2.1.0` | New feature columns added (schema change) |
| `v2.0.1` | Bug fix to existing formula (same schema, different values) |
| `v3.0.0` | Major taxonomy or schema redesign |

### 8.5 Provenance Chain

```
Phase 1C Raw JSON Chunks         (SHA-256 per chunk)
  -> Phase 1C Partition Manifests  (SHA-256 per partition)
       -> Root Dataset Manifest v1.1.0  (SHA-256)
            -> Feature Dataset Manifest v2.0.0  (links root manifest SHA-256)
                 -> Feature Parquet Partitions  (SHA-256 per partition)
```

---

## 9. Testing

### 9.1 Unit Tests: Mathematical Correctness

- `test_ret_log_cc_known_values`: `ln(110) - ln(100) = 0.09531` to 10 decimal places
- `test_rsi_all_up_approaches_100`: monotonically increasing -> RSI approaches 100
- `test_rsi_all_down_approaches_0`: monotonically decreasing -> RSI approaches 0
- `test_atr_constant_hl_range`: fixed H-L bars -> ATR converges to that range (Wilder)
- `test_garman_klass_doji`: O=H=L=C -> GK = 0.0
- `test_zscore_constant_series`: constant close -> numerator = 0, denominator = 0 -> return 0.0
- `test_hurst_proxy_brownian_motion`: 1000-bar BM -> proxy in (0.35, 0.65)
- `test_taker_buy_ratio_bounded`: `liq_taker_buy_ratio in [0, 1]`
- `test_session_flags_overlap_hours`: 14:00 UTC with standard config -> flags = 6
- `test_vwap_dev_zero_when_c_equals_vwap`: synthetic case -> deviation = 0.0
- `test_macd_warmup_exact`: verify MACD outputs NaN for bars 0-33 and non-NaN at bar 34
- `test_ema_sma_seed_exact`: verify EMA[n-1] exactly equals SMA(C[0..n-1])
- `test_pivot_stored_at_confirmation_bar`: pivot at bar k confirmed at bar k+s; feature emitted at k+s, not k
- `test_pivot_timestamp_field_matches_pivot_bar`: `ms_pivot_high_timestamp_3` at detection bar = open timestamp of pivot bar

### 9.2 Registry Consistency Tests (`test_registry.py`)

- `test_all_warm_ups_derived_not_hardcoded`: programmatically verify that `required_history_bars` for each feature matches the rule derivation
- `test_family_counts_from_registry`: verify that per-family counts from `FeatureRegistry.counts_by_family()` are consistent
- `test_schema_derived_from_registry`: verify that `FeatureParquetStorage.get_schema()` equals the column list from registry
- `test_no_duplicate_feature_names`: all feature names in the registry are unique

### 9.3 Boundary and Warm-Up Tests (Parametrized over All Features)

For every feature with `required_history_bars = w`:
- `test_insufficient_history_is_nan`: `w-1` bars -> all outputs NaN
- `test_exact_warmup_first_valid`: exactly `w` bars -> last output non-NaN; all preceding NaN

### 9.4 Missing-Candle Tests (Gap-Invalidation Policy)

Using a synthetic 100-bar series with a 10-bar gap at positions 40-49:
- No feature row emitted for timestamps 40-49
- Features at positions 50-59 that have lookback > 1 are NaN (window crosses gap)
- Features at position 70+ with lookback <= 20 recover to valid (NaN-free)
- `is_valid = False` for all rows whose computation window includes a gap bar
- **No backward-extended windows**: verify that lookback windows do not silently extend past gaps

### 9.5 No-Lookahead Tests (Critical, Parametrized over All Features)

```python
def test_no_lookahead(feature_fn, n_param, candles_100):
    result_full  = feature_fn(candles_100, n=n_param)
    result_trunc = feature_fn(candles_100[:-1], n=n_param)
    assert result_trunc[-1] == result_full[-2]  # or both NaN
```

Run parametrized over every `FeatureDefinition` in the registry.

**MTF alignment look-ahead test**:
- Verify that `mtf_15m_*` for 5m bar at `14:05 UTC` uses data from the 15m bar that closed at `14:00 UTC` (opened `13:45`), not from the 15m bar opening at `14:00` (which closes at `14:15`)
- Verify that `mtf_1h_*` for 5m bar at `14:05 UTC` uses data from the 1h bar that closed at `14:00 UTC`

**Pivot confirmation look-ahead test**:
- A pivot at bar `k` with strength `s=3` is NOT present in any output row before bar `k+3`
- Verify `ms_pivot_high_timestamp_3` at bar `k+3` equals the timestamp of bar `k`

### 9.6 MTF Alignment Tests

- `test_15m_alignment_rule`: 5m bar at `14:05` -> aligned 15m bar at `13:45` (not `14:00`)
- `test_1h_alignment_rule`: 5m bar at `14:05` -> aligned 1h bar at `13:00` (not `14:00`)
- `test_mtf_alignment_all_5m_bars`: sweep all 288 positions within a UTC day; verify alignment formula
- `test_mtf_nan_when_htf_bar_absent`: absent aligned HTF bar -> all MTF features = NaN

### 9.7 Determinism Tests

```python
def test_same_runtime_determinism(candles_1000):
    r1 = FeatureEngine().compute(candles_1000)
    r2 = FeatureEngine().compute(candles_1000)
    assert r1 == r2   # byte-identical on same runtime

def test_cross_process_numerical_equivalence(candles_1000, tmp_path):
    # Write result from subprocess; compare to in-process result within tolerance
    ...
```

### 9.8 Integration Tests Against Phase 1C Dataset

Tagged `@pytest.mark.integration`:

- `test_row_count_matches_candle_count`: 315,648 5m bars -> 315,648 feature rows
- `test_no_inf_in_output`: DuckDB scan -> zero `inf` values
- `test_valid_row_ratio_post_warmup`: `valid_rows / (total - 311) >= 0.999`
- `test_manifest_sha256_stable`: two runs -> identical `combined_parquet_sha256`
- `test_rsi_range_sanity`: all `mom_rsi_*` -> [0, 100] where non-NaN
- `test_body_ratio_range_sanity`: `price_body_ratio` -> [0, 1]
- `test_taker_ratio_range_sanity`: `liq_taker_buy_ratio` -> [0, 1]
- `test_mtf_15m_changes_only_at_15m_boundaries`: `mtf_15m_ret_log_cc_4` changes value only when a new 15m bar completes
- `test_mtf_1h_changes_only_at_1h_boundaries`: analogous for 1h
- `test_pivot_confirmation_lag`: `ms_is_pivot_high_5` is True only at bar `k+5`; `ms_pivot_high_timestamp_5` at that row equals timestamp of bar `k`

---

## 10. Performance

### 10.1 Benchmark Expectations (315,648 5m bars)

| Stage | Target | Risk |
|---|---|---|
| Load 5m candles (DuckDB) | < 5s | Low |
| Load 15m context candles | < 2s | Low |
| Load 1h context candles | < 1s | Low |
| Feature computation (all families, pure Python) | < 120s | Moderate |
| Feature Parquet write (vectorized TSV bulk) | < 10s | Low |
| Manifest generation | < 2s | Low |
| **End-to-end total** | **< 140s** | |

### 10.2 Computationally Expensive Features

| Feature | Why | Mitigation |
|---|---|---|
| `mr_hurst_proxy_96` | RS range over 96 elements | Incremental deque max/min; incremental cumulative sum |
| `mom_slope_48` | OLS solve per bar | Precompute `S_xx` once (constant for fixed `n`); reduce to dot product per bar |
| `mr_autocorr_lag1_96` | Pearson corr of 96-element arrays | Welford-style incremental covariance: O(1) per bar |
| Pivot detection | Symmetric neighborhood scan | O(n) monotone deque sliding maximum |
| MTF alignment | Cross-index join 5m -> 15m/1h | Sort-merge join O(n); never O(n^2) |

### 10.3 Escalation Path (No New Dependencies)

If profiling shows pure Python cannot meet 140s: escalate to DuckDB SQL window functions:

```sql
SELECT
  timestamp_utc,
  LN(close) - LAG(LN(close), 1) OVER w AS ret_log_cc_1,
  AVG(close) OVER (w ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS sma_12,
  ...
FROM feature_input
WINDOW w AS (ORDER BY timestamp_utc)
```

This requires explicit approval and is out of scope for Phase 2.0.

---

## 11. Dependency Decision

**Zero new Python packages in Phase 2.0.**

Existing: `pydantic >= 2.7.0`, `duckdb >= 1.0.0`, `pyyaml >= 6.0.1`, `rich >= 13.7.0`, `websockets >= 13.0.0`, `pytz >= 2024.1`, Python 3.12 stdlib.

---

## 12. Deliverables

| Deliverable | Description | Location |
|---|---|---|
| `xau_quant.features` package | FeatureRegistry + calculators + engine + storage + validators | `src/xau_quant/features/` |
| `configs/feature_sessions.yaml` | Configurable session definitions v1.0.0 | `configs/feature_sessions.yaml` |
| Feature dataset v2.0.0 | Versioned, partitioned, validated Parquet | `data/features/binance/spot/BTCUSDT/5m/feature_set=v2.0.0/` |
| Feature dataset manifest | JSON provenance with SHA-256 chain; all counts registry-derived | `data/metadata/manifests/btcusdt_5m_features_v2.0.0_manifest.json` |
| `compute_features.py` | Reproducible CLI pipeline: Phase 1C -> feature Parquet | `scripts/compute_features.py` |
| Unit test suite | All features + edge cases + registry consistency tests | `tests/unit/features/` |
| Integration test | End-to-end pipeline against Phase 1C dataset | `tests/integration/features/` |
| Phase 2 completion report | Validation summary, timing, registry catalog | `artifacts/reports/phase_2_completion_report.md` |

---

## 13. Acceptance Criteria

Phase 2 is complete when **all** of the following hold:

| # | Criterion | Verification |
|---|---|---|
| AC-1 | All unit tests pass | `pytest tests/unit/features/ -v` -> 0 failures |
| AC-2 | All integration tests pass | `pytest tests/integration/features/ -v` -> 0 failures |
| AC-3 | Feature row count = 5m candle count | `SELECT COUNT(*)` = 315,648 |
| AC-4 | Zero `inf` or `-inf` in any feature column | DuckDB `IS INFINITE` scan |
| AC-5 | >= 99.9% of post-warm-up rows have `is_valid = True` | Manifest coverage field |
| AC-6 | Manifest SHA-256 stable across two runs on same machine | Compare `combined_parquet_sha256` |
| AC-7 | All no-lookahead tests pass for every feature | Parametrized pytest over FeatureRegistry |
| AC-8 | All warm-up boundary tests pass for every feature | Parametrized pytest over FeatureRegistry |
| AC-9 | MTF alignment tests pass for all 288 intra-day positions | Parametrized pytest |
| AC-10 | Pivot confirmation tests pass: no pivot stored at pivot bar | Dedicated test suite |
| AC-11 | Registry-derived feature counts match manifest | `FeatureRegistry.total_count()` == `manifest.feature_catalog.total_features` |
| AC-12 | End-to-end computation < 140 seconds | `time python scripts/compute_features.py` |
| AC-13 | Zero mypy errors | `mypy src/xau_quant/features/ --strict` |
| AC-14 | Zero ruff violations | `ruff check src/xau_quant/features/` |
| AC-15 | Zero new entries in `pyproject.toml` dependencies | `git diff pyproject.toml` |
| AC-16 | Feature manifest `input_dataset.root_manifest_sha256` matches Phase 1C root | Manual inspection |

---

> [!CAUTION]
> **GATE ENFORCEMENT**: This is a design-only document (Revision 2). Zero implementation has been executed. No feature code has been written. No data has been downloaded, modified, or processed. No commits or pushes have been made. The working tree is unchanged. Awaiting formal review and explicit approval from Nishant before Phase 2 implementation begins.
