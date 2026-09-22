# Phase 2 Design Specification: Market Feature Engine (Revision 3)

**Project**: XAU Quantitative Strategy Discovery and Decision Platform  
**Phase**: 2 (Market Feature Engine)  
**Revision**: 3 — resolving all 6 remaining mathematical, temporal, and architectural ambiguities from Nishant's review of Revision 2  
**Status**: DESIGN DOCUMENT — Phase 2 Implementation Approval Gate — Zero Implementation Executed  
**Date**: 2026-09-19  
**Primary Target Dataset**: `BTCUSDT` Binance Spot — Phase 1C canonical dataset (`v1.1.0`)  
**Research Clock**: 5-minute bars (primary); 1m, 15m, 1h as context timeframes  
**Execution Boundary**: Feature Engineering Only — Zero Strategies, Zero Signals, Zero ML, Zero Backtesting, Zero UI  

---

## Revision 3 Summary of Corrections

This document supersedes Revision 2. The following 6 corrections have been applied in strict accordance with the final review:

| # | Issue in Rev 2 | Revision 3 Resolution | Document Section |
|---|---|---|---|
| **C1** | **Warm-up semantics inconsistent** (alternated between $n$ bars, index $n-1$, and formulas requiring $n+1$ observations) | Established ONE unambiguous convention: `required_history_bars = number of input bars required for the first valid output, inclusive`. Every feature is derived strictly from this rule. | Section 4.5, Section 3 |
| **C2** | **MACD re-seeding rule questionable** (re-seeded EMA-12 at bar 25 using bars 14–25, discarding bars 11–24 state) | Replaced with **natural composition**: EMA-12 seeded at bar index 11 and continued recursively; EMA-26 seeded at bar index 25; MACD valid at bar 25; Signal EMA-9 seeded at bars 25..33. `required_history_bars = 34`. | Section 3.2.5, Section 4.4 |
| **C3** | **Universal `+ eps` distorted indicator boundary semantics** (e.g. RSI zero-loss produced $\approx 99.9999999$ instead of exact 100.0) | Disentangled into three explicit classes: (1) numerical-stability epsilon, (2) mathematically defined boundary cases (RSI 100.0/0.0/50.0, zero-std Z-score 0.0), (3) genuinely undefined values (NaN). | Section 3.2.6, Section 3.3, Section 6.1 |
| **C4** | **`is_valid` too strict for warm-up** (first ~311 rows marked invalid because of warm-up NaNs, conflating history with data errors) | Added **`is_warmup: BOOLEAN`** column. `is_warmup = True` when row index $< \text{max\_warm\_up\_bars}$. `is_valid = True` signifies computation validity after warm-up (unbroken data, zero NaNs post-warm-up). | Section 6.3, Section 8.2 |
| **C5** | **Pivot columns conflicted with "all feature columns DOUBLE"** | Schema updated to make `FeatureDefinition` own typed, multi-column emissions via `ColumnSpec`. Registry generates `DOUBLE`, `BOOLEAN`, `TIMESTAMPTZ`, and `SMALLINT` columns cleanly. | Section 7.2, Section 8.2 |
| **C6** | **Hurst proxy formula unverified and non-standard** | Frozen to the classical **Hurst (1951) / Peters (1994) Rescaled Range ($R/S$)** formulation on log-returns over completed bars. Fully specified with reference properties and boundary conditions. | Section 3.6.3, Section 9.1 |

---

## 1. Objective and Scope

### 1.1 Mission Statement

Phase 2 builds a **deterministic, temporally correct, research/live-parity market feature layer** on top of the validated Phase 1C BTCUSDT Spot dataset. Its sole output is a versioned, schema-validated feature dataset that downstream strategy discovery can consume without re-computing or re-validating features.

The feature engine must be:
- **Deterministic**: on a supported runtime environment, identical inputs produce identical results; repeated runs produce identical serialized Parquet output.
- **Temporally correct**: zero look-ahead; features at bar $t$ use only information available at the close of bar $t$.
- **Research/live-parity**: the exact same computation path runs on historical completed bars and on live completed bars without divergence.
- **Instrument/provider-agnostic**: architecture accommodates XAUUSD and any future instrument by configuration, not by code modification.
- **Registry-driven**: feature counts, warm-up periods, typed schemas, manifest metadata, and validation rules are all derived automatically from the `FeatureRegistry`; no value is maintained in two places.

### 1.2 In-Scope

| Item | Detail |
|---|---|
| **Primary research clock** | 5m bars (granularity at which features are indexed) |
| **Context timeframes** | 1m (microstructure), 15m (intraday trend), 1h (session cycle) |
| **Input dataset** | Phase 1C BTCUSDT v1.1.0 canonical partitioned Parquet dataset |
| **Output** | Versioned feature Parquet dataset under `data/features/` |
| **Feature families** | Price/Returns, Momentum, Volatility, Volume/Liquidity, Market Structure, Mean-Reversion, Session/Time, Multi-Timeframe |
| **Quality controls** | Explicit boundary math, gap-invalidation policy, duplicate detection, history guards, `is_warmup` and `is_valid` metadata per row |

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
| Feature count | **Derived strictly from FeatureRegistry; no manual hardcoded claims** |
| Hurst proxy | **Frozen to standard Hurst (1951) R/S formulation on log-returns** |
| Pivot representation | **Confirmation-time semantics with typed multi-column emission (Flag, Timestamp, Age)** |
| 4h/1d MTF context | **Deferred to Phase 2.1** |
| Missing-data policy | **Gap invalidates any window crossing it; no backward extension** |
| MTF alignment | **Completed-HTF-bar-at-primary-close rule: `floor(t-600s, 15m)` and `floor(t-3300s, 1h)`** |
| Cross-machine determinism | **Numerical equivalence within tolerance ($10^{-12}$ / $10^{-10}$), not bit identity across different architectures** |
| Warm-up convention | **Uniform `required_history_bars`: number of input bars required for first valid output, inclusive** |
| MACD initialization | **Natural composition of SMA-seeded EMAs without secondary re-seeding** |
| Zero-denominator handling | **Explicit boundary math (RSI 100.0/0.0/50.0, ATR/C guard) separated from stability epsilon** |
| Row validity flags | **Decoupled into `is_warmup: BOOLEAN` and `is_valid: BOOLEAN`** |

---

## 2. Feature Taxonomy

### 2.1 Distinction: Raw Observations vs. Derived Features

| Category | Definition |
|---|---|
| **Raw observation** | Sourced directly from a `CanonicalCandle`: `open`, `high`, `low`, `close`, `volume`, `quote_volume`, `trade_count`, `taker_buy_base_volume`, `taker_buy_quote_volume`, `is_complete` |
| **Derived feature** | Any deterministic computation applied to raw observations across one or more bars |

Raw observations are **not** duplicated in the feature dataset. They remain in the canonical candle dataset. The feature dataset contains derived features plus primary key columns (`timestamp_utc`, `venue`, `instrument`, `timeframe`) and validity metadata.

### 2.2 Feature Families

| # | Family | Prefix | Description |
|---|---|---|---|
| 1 | **Price and Returns** | `ret_` / `price_` | Log-returns, bar-body, wick metrics |
| 2 | **Momentum** | `mom_` | Rate-of-change, regression slope, EMA/SMA deviation, RSI, MACD |
| 3 | **Volatility** | `vol_` | ATR, realized volatility, Garman-Klass estimator, vol Z-score |
| 4 | **Volume and Liquidity** | `liq_` | Taker aggression ratio, average trade size, VWAP deviation, volume ratio, delta proxy |
| 5 | **Market Structure** | `ms_` | Rolling high/low, price position, bars-since-extremum, pivot confirmation |
| 6 | **Mean-Reversion** | `mr_` | Z-score of close, mean deviation, Hurst R/S proxy, lag-1 autocorrelation |
| 7 | **Session and Time** | `time_` | UTC hour, day-of-week, cyclic encodings, configurable session flags |
| 8 | **Multi-Timeframe** | `mtf_` | 1m, 15m, 1h features aligned using completed-bar-at-close rule |

---

## 3. Mathematical Definitions

### 3.0 Warm-Up and Indexing Convention (Correction C1)

To eliminate all ambiguity between bar counts, lookback parameters, and zero-based indexing:

> [!IMPORTANT]
> **Authoritative Convention**:
> `required_history_bars` is defined as the **minimum number of chronologically ordered input bars required to produce the first valid (non-NaN) output, inclusive of the current bar**.
> 
> For an input series indexed $0, 1, 2, \dots$:
> - If `required_history_bars = k`, then output rows at indices $0, 1, \dots, k-2$ are `NaN`.
> - The **first valid output** occurs at index $k-1$.
> - An input array with length $< k$ produces exclusively `NaN`.

**General Rules for Arithmetic & Epsilon (Correction C3)**:
- $C[t], O[t], H[t], L[t]$: prices of 5m bar at open-timestamp $t$.
- $V[t], QV[t], N[t], TB[t]$: volume, quote volume, trade count, taker buy base volume.
- $\ln(\cdot)$: natural logarithm.
- **Epsilon ($\epsilon = 10^{-8}$)**: applied **only** for numerical stability in floating-point divisions where no analytical boundary exists. Epsilon is **never** used to override or approximate mathematically defined limits (such as RSI boundary states or flat series variance).

---

### 3.1 Price and Returns Family

#### 3.1.1 Log-Return (Close-to-Close)
```
ret_log_cc_{n} = ln(C[t]) - ln(C[t-n])
```
- Parameters: $n \in \{1, 3, 6, 12, 24, 48, 96\}$ (5m, 15m, 30m, 1h, 2h, 4h, 8h).
- Observation requirement: requires $C[t]$ and $C[t-n]$. For $n=1$, requires 2 closes ($C[0]$ and $C[1]$).
- **`required_history_bars`**: **$n + 1$** (First valid at index $n$).

#### 3.1.2 Intra-Bar Log-Return (Open-to-Close)
```
ret_log_oc = ln(C[t]) - ln(O[t])
```
- Observation requirement: requires single bar $O[t], C[t]$.
- **`required_history_bars`**: **1** (First valid at index 0).

#### 3.1.3 Bar Body Ratio
```
price_body_ratio = |C[t] - O[t]| / (H[t] - L[t] + eps)
```
- Range: $[0.0, 1.0]$. $\epsilon$ prevents division by zero when $H[t] == L[t]$ (zero tick movement).
- **`required_history_bars`**: **1** (First valid at index 0).

#### 3.1.4 Upper and Lower Wick Ratios
```
price_upper_wick_ratio = (H[t] - max(O[t], C[t])) / (H[t] - L[t] + eps)
price_lower_wick_ratio = (min(O[t], C[t]) - L[t]) / (H[t] - L[t] + eps)
```
- Range: $[0.0, 1.0]$.
- **`required_history_bars`**: **1** (First valid at index 0).

#### 3.1.5 Bar Midpoint
```
price_midpoint = (H[t] + L[t]) / 2.0
```
- Units: USD.
- **`required_history_bars`**: **1** (First valid at index 0).

---

### 3.2 Momentum Family

#### 3.2.1 Rate of Change (ROC)
```
mom_roc_{n} = (C[t] - C[t-n]) / C[t-n]
```
- Parameters: $n \in \{6, 12, 24, 48\}$.
- Requires $C[t]$ and $C[t-n]$ ($n+1$ observations).
- Boundary case: if $C[t-n] \le 0$, output `NaN`.
- **`required_history_bars`**: **$n + 1$** (First valid at index $n$).

#### 3.2.2 Smoothed Close Slope (OLS)
Fit $y[k] = \ln(C[t - n + 1 + k])$ vs $x[k] = k$ for $k = 0, \dots, n-1$:
```
x_bar = (n - 1) / 2.0
S_xx  = sum_{k=0}^{n-1} (k - x_bar)^2 = n * (n^2 - 1) / 12.0   [precomputed constant]
S_xy  = sum_{k=0}^{n-1} (k - x_bar) * y[k]
slope = S_xy / S_xx
mom_slope_{n} = slope * n / (|ln(C[t])| + eps)                  [dimensionless normalized slope]
```
- Parameters: $n \in \{12, 24, 48\}$.
- Requires $n$ consecutive closes ($C[t-n+1 \dots t]$).
- **`required_history_bars`**: **$n$** (First valid at index $n-1$).

#### 3.2.3 SMA Deviation
```
SMA_{n}[t] = (1 / n) * sum_{k=0}^{n-1} C[t-k]
mom_sma_dev_{n} = (C[t] - SMA_{n}[t]) / SMA_{n}[t]
```
- Parameters: $n \in \{12, 24, 48, 96\}$.
- **`required_history_bars`**: **$n$** (First valid at index $n-1$).

#### 3.2.4 EMA Deviation (SMA-Seeded Initialization)
All EMAs in this architecture use **SMA-seeded initialization**:
```
At index i = n - 1 (requiring exactly n bars C[0..n-1]):
  EMA_{n}[n-1] = (1 / n) * sum_{k=0}^{n-1} C[k]

For bar index i >= n:
  alpha = 2.0 / (n + 1.0)
  EMA_{n}[i] = alpha * C[i] + (1.0 - alpha) * EMA_{n}[i-1]

mom_ema_dev_{n} = (C[t] - EMA_{n}[t]) / EMA_{n}[t]
```
- Parameters: $n \in \{12, 26, 50\}$.
- **`required_history_bars`**: **$n$** (First valid at index $n-1$).

#### 3.2.5 MACD Histogram (Natural Composition, Correction C2)

> [!IMPORTANT]
> **Correction C2 Resolution: Natural Composition**:
> Revision 2's artificial re-seeding of EMA-12 at bar 25 is removed. EMA-12 and EMA-26 are constructed naturally as independent SMA-seeded recursive filters:
> 1. $\text{EMA}_{12}$ seeds at bar index 11 from $C[0 \dots 11]$ and updates recursively for all subsequent bars.
> 2. $\text{EMA}_{26}$ seeds at bar index 25 from $C[0 \dots 25]$ and updates recursively for all subsequent bars.
> 3. $\text{MACD\_line}$ is first valid at bar index 25:
>    $$\text{MACD\_line}[i] = \text{EMA}_{12}[i] - \text{EMA}_{26}[i] \quad (i \ge 25)$$
> 4. $\text{MACD\_signal}$ is a 9-period SMA-seeded EMA computed over the valid $\text{MACD\_line}$ sequence. Its first 9 observations are $\text{MACD\_line}[25 \dots 33]$.
>    $$\text{MACD\_signal}[33] = \frac{1}{9} \sum_{k=25}^{33} \text{MACD\_line}[k]$$
>    For $i \ge 34$:
>    $$\alpha_9 = \frac{2}{9 + 1} = 0.2, \quad \text{MACD\_signal}[i] = 0.2 \cdot \text{MACD\_line}[i] + 0.8 \cdot \text{MACD\_signal}[i-1]$$
> 5. Normalized Histogram:
>    $$\text{mom\_macd\_hist}[t] = \frac{\text{MACD\_line}[t] - \text{MACD\_signal}[t]}{C[t]}$$

- First valid output occurs at bar index 33 (which requires bars $0 \dots 33$, total 34 bars).
- **`required_history_bars`**: **34** (First valid at index 33).

#### 3.2.6 Relative Strength Index (RSI, Wilder Smoothed, Correction C3)

> [!IMPORTANT]
> **Correction C3 Resolution: Exact Boundary Semantics**:
> Wilder's RSI uses exact mathematical handling for edge cases without adding epsilon:
> 1. $\Delta[i] = C[i] - C[i-1]$ for $i \ge 1$. $U[i] = \max(\Delta[i], 0)$, $D[i] = \max(-\Delta[i], 0)$.
> 2. Seed averages at index $n$ using first $n$ deltas (requiring $n+1$ closes $C[0 \dots n]$):
>    $$\text{AvgU}[n] = \frac{1}{n} \sum_{k=1}^n U[k], \quad \text{AvgD}[n] = \frac{1}{n} \sum_{k=1}^n D[k]$$
> 3. For $i > n$:
>    $$\text{AvgU}[i] = \frac{(n-1) \text{AvgU}[i-1] + U[i]}{n}, \quad \text{AvgD}[i] = \frac{(n-1) \text{AvgD}[i-1] + D[i]}{n}$$
> 4. **Mathematical Boundary Evaluation**:
>    - If $\text{AvgD}[i] == 0.0$ and $\text{AvgU}[i] > 0.0 \implies \mathbf{mom\_rsi_{n} = 100.0}$ (exact).
>    - If $\text{AvgU}[i] == 0.0$ and $\text{AvgD}[i] > 0.0 \implies \mathbf{mom\_rsi_{n} = 0.0}$ (exact).
>    - If $\text{AvgU}[i] == 0.0$ and $\text{AvgD}[i] == 0.0 \implies \mathbf{mom\_rsi_{n} = 50.0}$ (exact, zero volatility neutrality).
>    - Otherwise ($\text{AvgD}[i] > 0.0$ and $\text{AvgU}[i] > 0.0$):
>      $$RS = \frac{\text{AvgU}[i]}{\text{AvgD}[i]}, \quad \mathbf{mom\_rsi_{n} = 100.0 - \frac{100.0}{1.0 + RS}}$$

- Parameters: $n \in \{14, 28\}$.
- Requires $n+1$ bars ($C[0 \dots n]$) for initialization.
- **`required_history_bars`**: **$n + 1$** (First valid at index $n$). For $n=14 \implies 15$; for $n=28 \implies 29$.

---

### 3.3 Volatility Family

#### 3.3.1 Average True Range (ATR, Wilder Smoothed, Correction C3)
True Range requires the previous close:
```
TR[t] = max(H[t] - L[t], |H[t] - C[t-1]|, |L[t] - C[t-1]|)   for t >= 1
```
Because $H[t] \ge L[t]$, $TR[t] \ge 0.0$ always. No division occurs in $TR$ or $ATR$.
```
Initialization at bar index n (using TR[1..n], requiring bars 0..n):
  ATR[n] = (1 / n) * sum_{k=1}^n TR[k]

Update for i > n:
  ATR[i] = ((n - 1) * ATR[i-1] + TR[i]) / n

vol_atr_{n}     = ATR[t]           (USD)
vol_atr_pct_{n} = ATR[t] / C[t]    (dimensionless)
```
- Boundary case: if $C[t] \le 0.0$, `vol_atr_pct` outputs `NaN`. No epsilon distortion.
- Parameters: $n \in \{14, 28\}$.
- **`required_history_bars`**: **$n + 1$** (First valid at index $n$). For $n=14 \implies 15$; for $n=28 \implies 29$.

#### 3.3.2 Realized Volatility (Log-Returns)
```
r[i] = ln(C[i]) - ln(C[i-1])
vol_realized_{n} = std(r[t-n+1 \dots t], ddof=1)   [Welford online algorithm]
```
- $n$ returns require $n+1$ closes ($C[t-n \dots t]$).
- Parameters: $n \in \{12, 24, 48, 96\}$.
- **`required_history_bars`**: **$n + 1$** (First valid at index $n$). For $n=96 \implies 97$.

#### 3.3.3 Garman-Klass Volatility Estimator
```
GK[t] = 0.5 * (ln(H[t] / L[t]))^2 - (2.0 * ln(2.0) - 1.0) * (ln(C[t] / O[t]))^2
vol_gk_realized_{n} = sqrt( (1 / n) * sum_{k=0}^{n-1} GK[t-k] )
```
- Uses single-bar OHLC observations; no cross-bar closes needed.
- Parameters: $n \in \{12, 24\}$.
- **`required_history_bars`**: **$n$** (First valid at index $n-1$).

#### 3.3.4 Volatility Z-Score (Correction C3)
Normalizes the 12-bar realized volatility against its 96-bar rolling history:
```
window = [vol_realized_12[t - 96 + 1], ..., vol_realized_12[t]]
mu     = mean(window)
sigma  = std(window, ddof=1)

If sigma == 0.0:
    vol_zscore_12_96 = 0.0    [exact boundary: constant volatility series]
Else:
    vol_zscore_12_96 = clamp((vol_realized_12[t] - mu) / sigma, -10.0, 10.0)
```
- History calculation: `vol_realized_12` requires 13 bars. Accumulating 96 consecutive values requires $13 + 96 - 1 = 108$ bars.
- **`required_history_bars`**: **108** (First valid at index 107).

---

### 3.4 Volume and Liquidity Family

#### 3.4.1 Taker Aggression Ratio
```
liq_taker_buy_ratio = TB[t] / (V[t] + eps)
```
- Range: $[0.0, 1.0]$. $\epsilon$ prevents zero-volume division.
- **`required_history_bars`**: **1** (First valid at index 0).

#### 3.4.2 Average Trade Size
```
liq_avg_trade_size = V[t] / (N[t] + eps)
```
- Units: BTC/trade.
- **`required_history_bars`**: **1** (First valid at index 0).

#### 3.4.3 Rolling VWAP Deviation
```
VWAP_{n} = sum_{k=0}^{n-1} QV[t-k] / (sum_{k=0}^{n-1} V[t-k] + eps)
liq_vwap_dev_{n} = (C[t] - VWAP_{n}) / VWAP_{n}
```
- Parameters: $n \in \{12, 48\}$.
- **`required_history_bars`**: **$n$** (First valid at index $n-1$).

#### 3.4.4 Volume Ratio
```
liq_vol_ratio_{n} = V[t] / ((1 / n) * sum_{k=0}^{n-1} V[t-k] + eps)
```
- Parameters: $n \in \{12, 24, 48\}$.
- **`required_history_bars`**: **$n$** (First valid at index $n-1$).

#### 3.4.5 Dollar Volume
```
liq_dollar_volume = QV[t]
```
- Re-exposed from raw candle quote volume so consumers avoid candle table joins.
- **`required_history_bars`**: **1** (First valid at index 0).

#### 3.4.6 Cumulative Delta Proxy
```
CD[t] = 2.0 * TB[t] - V[t]
liq_delta_proxy   = CD[t] / (V[t] + eps)                               [single-bar, req_bars = 1]
liq_cum_delta_{n} = sum_{k=0}^{n-1} CD[t-k] / (sum_{k=0}^{n-1} V[t-k] + eps)  [rolling, req_bars = n]
```
- Parameters: $n \in \{12, 48\}$.

---

### 3.5 Market Structure Family

#### 3.5.1 Rolling High and Low
```
ms_high_{n} = max(H[t-n+1 \dots t])
ms_low_{n}  = min(L[t-n+1 \dots t])
```
- Parameters: $n \in \{12, 24, 48, 96\}$.
- **`required_history_bars`**: **$n$** (First valid at index $n-1$).

#### 3.5.2 Price Position within N-Bar Range
```
range_hl = ms_high_{n} - ms_low_{n}
If range_hl == 0.0:
    ms_price_position_{n} = 0.5   [exact boundary: flat range midpoint]
Else:
    ms_price_position_{n} = (C[t] - ms_low_{n}) / range_hl
```
- Range: $[0.0, 1.0]$.
- **`required_history_bars`**: **$n$** (First valid at index $n-1$).

#### 3.5.3 Bars Since N-Bar High/Low
```
ms_bars_since_high_{n} = t - argmax_{i in [t-n+1, t]} H[i]   (ties broken toward most recent bar)
ms_bars_since_low_{n}  = t - argmin_{i in [t-n+1, t]} L[i]
```
- Parameters: $n \in \{24, 96\}$. Range: $[0, n-1]$.
- **`required_history_bars`**: **$n$** (First valid at index $n-1$).

#### 3.5.4 Pivot Confirmation (Confirmation-Time Semantics, Correction C5)

A pivot of strength $s$ at bar $k$ requires $s$ bars to the left and $s$ bars to the right. It is **confirmed at bar $t = k + s$**:
```
Pivot High at k confirmed at t = k + s iff:
  H[k] > H[k-j]  for all j in {1..s}
  H[k] > H[k+j]  for all j in {1..s}
```
Total bar window required: $s$ (left) + $1$ (pivot) + $s$ (right) $= 2s + 1$ bars.

At the confirmation bar $t = k + s$, three typed columns are generated:
- `ms_is_pivot_high_{s}`: `BOOLEAN` (`True` at confirmation bar $t$, `False` otherwise)
- `ms_pivot_high_timestamp_{s}`: `TIMESTAMPTZ` (Open timestamp of pivot bar $k$; `NULL` if `is_pivot` is `False`)
- `ms_pivot_high_age_bars_{s}`: `SMALLINT` (Lag in 5m bars: exactly $s$ when confirmed, `NULL` otherwise)

Analogous columns for pivot lows: `ms_is_pivot_low_{s}`, `ms_pivot_low_timestamp_{s}`, `ms_pivot_low_age_bars_{s}`.
- Parameters: $s \in \{3, 5\}$.
- Window size: $2s + 1$.
- **`required_history_bars`**: **$2s + 1$** (For $s=3 \implies 7$; for $s=5 \implies 11$). First valid at index $2s$.

#### 3.5.5 Consecutive Bar Direction
```
ms_consec_up_{n}   = count of consecutive bars with C[i] > C[i-1] ending at bar t, capped at n
ms_consec_down_{n} = count of consecutive bars with C[i] < C[i-1] ending at bar t, capped at n
```
- Parameter: $n = 5$. Requires $n+1$ closes.
- **`required_history_bars`**: **$n + 1 = 6$** (First valid at index 5).

---

### 3.6 Mean-Reversion Family

#### 3.6.1 Z-Score of Close (Correction C3)
```
mu    = (1 / n) * sum_{k=0}^{n-1} C[t-k]
sigma = std(C[t-n+1 \dots t], ddof=1)

If sigma == 0.0:
    mr_zscore_{n} = 0.0   [exact boundary: flat series zero variance]
Else:
    mr_zscore_{n} = clamp((C[t] - mu) / sigma, -10.0, 10.0)
```
- Parameters: $n \in \{24, 48, 96\}$.
- **`required_history_bars`**: **$n$** (First valid at index $n-1$).

#### 3.6.2 Distance from Rolling Mean
```
mr_mean_dev_{n} = (C[t] - mu_{n}) / (mu_{n} + eps)
```
- Parameters: $n \in \{12, 48\}$.
- **`required_history_bars`**: **$n$** (First valid at index $n-1$).

#### 3.6.3 Hurst Exponent Proxy (Classical Rescaled Range R/S, Correction C6)

> [!IMPORTANT]
> **Correction C6 Resolution: Frozen Hurst Formulation**:
> The Hurst exponent proxy is frozen to the textbook **Hurst (1951) / Peters (1994) Rescaled Range ($R/S$)** estimator on log-returns over a single rolling window of $n$ returns.
> 
> Let $r_k = \ln(C[t - n + 1 + k]) - \ln(C[t - n + k])$ for $k = 0, \dots, n-1$ be the $n$ log-returns.
> 
> 1. **Mean return**:
>    $$m = \frac{1}{n} \sum_{k=0}^{n-1} r_k$$
> 2. **Mean-centered cumulative deviations (profile)**:
>    $$Z_0 = 0.0, \quad Z_j = \sum_{k=0}^{j-1} (r_k - m) \quad \text{for } j = 1, \dots, n \quad (\text{Note: } Z_n = 0.0)$$
> 3. **Range**:
>    $$R = \max(Z_0, Z_1, \dots, Z_n) - \min(Z_0, Z_1, \dots, Z_n)$$
> 4. **Standard deviation (sample, ddof=1)**:
>    $$S = \sqrt{\frac{1}{n-1} \sum_{k=0}^{n-1} (r_k - m)^2}$$
> 5. **Rescaled Range and Hurst Proxy**:
>    - If $S == 0.0$ or $R == 0.0$: $\mathbf{mr\_hurst\_proxy_{n} = 0.5}$ (exact boundary: uninformative flat series).
>    - Else:
>      $$\frac{R}{S} = \frac{R}{S}, \quad \mathbf{mr\_hurst\_proxy_{n} = \text{clamp}\left( \frac{\ln(R / S)}{\ln(n)}, 0.0, 1.0 \right)}$$

- Interpretation metadata: `estimator_type = "rs_single_window_proxy"`, `interpretation = "research_feature_only"`. Provides empirical persistence/anti-persistence proxy without multi-scale fitting.
- Parameters: $n \in \{48, 96\}$.
- $n$ log-returns require $n+1$ closes.
- **`required_history_bars`**: **$n + 1$** (For $n=48 \implies 49$; for $n=96 \implies 97$). First valid at index $n$.

#### 3.6.4 Lag-1 Autocorrelation of Log-Returns
Pearson correlation between returns $r[t-n+1 \dots t]$ and $r[t-n \dots t-1]$:
- Requires $n+1$ returns ($r[t-n \dots t]$), which in turn require $n+2$ closes ($C[t-n-1 \dots t]$).
- If variance of either lag is $0.0$, outputs `0.0`.
- Parameters: $n \in \{24, 96\}$.
- **`required_history_bars`**: **$n + 2$** (For $n=24 \implies 26$; for $n=96 \implies 98$). First valid at index $n+1$.

---

### 3.7 Session and Time Features

All time features derive from the bar's UTC timestamp. **`required_history_bars` = 1** for all (valid immediately on bar 0).

- `time_hour_utc`: UTC hour in $\{0 \dots 23\}$.
- `time_dow`: Day of week in $\{0=\text{Mon} \dots 6=\text{Sun}\}$.
- `time_hour_sin`, `time_hour_cos`: $\sin(2\pi \cdot \text{hour} / 24)$, $\cos(2\pi \cdot \text{hour} / 24)$.
- `time_dow_sin`, `time_dow_cos`: $\sin(2\pi \cdot \text{dow} / 7)$, $\cos(2\pi \cdot \text{dow} / 7)$.
- `time_session_flags`: Bitwise OR of active sessions defined in `configs/feature_sessions.yaml` (Asian=1, London=2, New York=4).
- `time_bars_since_midnight`: $(\text{hour} \times 60 + \text{minute}) // 5 \in [0, 287]$.
- `time_bars_since_week_open`: $\text{dow} \times 288 + \text{bars\_since\_midnight} \in [0, 2015]$.

---

### 3.8 Multi-Timeframe (MTF) Features

#### 3.8.1 Completed-Bar-at-Close Alignment Rule

A 5m bar opens at $t$ and closes at $t + 300\text{s}$. A higher-timeframe bar of duration $D_{\text{TF}}$ opening at $t_{\text{TF}}$ completes at $t_{\text{TF}} + D_{\text{TF}}$.
For the HTF bar to be **complete** at or before the 5m bar's close:
$$t_{\text{TF}} + D_{\text{TF}} \le t + 300\text{s} \implies t_{\text{TF}} \le t - (D_{\text{TF}} - 300\text{s})$$

The latest completed HTF bar open timestamp:
$$t_{\text{TF\_aligned}} = \text{floor}(t - (D_{\text{TF}} - 300\text{s}), D_{\text{TF}})$$

- **15m ($D_{\text{TF}} = 900\text{s}$)**:
  $$t_{15\text{m}} = \text{floor}(t - 600\text{s}, 15\text{m})$$
- **1h ($D_{\text{TF}} = 3600\text{s}$)**:
  $$t_{1\text{h}} = \text{floor}(t - 3300\text{s}, 1\text{h})$$

#### 3.8.2 Derivation of MTF `required_history_bars` (Correction C1)

Let an HTF feature require $K$ completed HTF bars.
The earliest required HTF bar opens at:
$$t_{\text{earliest}} = t_{\text{TF\_aligned}} - (K - 1) \cdot D_{\text{TF}}$$
The worst-case alignment (maximum elapsed 5m bars between $t_{\text{earliest}}$ and $t$) occurs when $t$ is at the maximum offset before a new HTF bar completes:
- For 15m: at $t = X:10$ (close $X:15$), $t_{15\text{m}} = X:00$. Span from $X:00$ to $X:10$ is two 5m steps. Including the bar at $t$, the offset is $3 \times K + 2$ bars.
- For 1h: at $t = X:50$ (close $X:55$), $t_{1\text{h}} = (X-1):00$. Span from $(X-1):00$ to $X:50$ is 22 5m intervals ($23$ bars).
  In general, for $K$ completed 1h bars:
  $$\text{required\_5m\_bars} = 12 \cdot (K - 1) + 23 = \mathbf{12 \cdot K + 11}$$

**Verification of MTF Lookbacks**:
1. `mtf_15m_ret_log_cc_4`: 4 15m log-returns require 5 15m bars ($K=5$). $\text{req} = 3 \cdot 5 + 2 = \mathbf{17}$ 5m bars.
2. `mtf_15m_mom_rsi_14`: Wilder RSI-14 requires 15 15m bars ($K=15$). $\text{req} = 3 \cdot 15 + 2 = \mathbf{47}$ 5m bars.
3. `mtf_15m_vol_atr_pct_14`: ATR-14 requires 15 15m bars ($K=15$). $\text{req} = 3 \cdot 15 + 2 = \mathbf{47}$ 5m bars.
4. `mtf_1h_ret_log_cc_24`: 24 1h log-returns require 25 1h bars ($K=25$). $\text{req} = 12 \cdot 25 + 11 = \mathbf{311}$ 5m bars.
5. `mtf_1h_vol_realized_24`: 24 1h returns require 25 1h bars ($K=25$). $\text{req} = 12 \cdot 25 + 11 = \mathbf{311}$ 5m bars.
6. `mtf_1h_mom_rsi_14`: RSI-14 requires 15 1h bars ($K=15$). $\text{req} = 12 \cdot 15 + 11 = \mathbf{191}$ 5m bars.

**Maximum warm-up threshold across all features: exactly 311 5m bars** ($\approx 25.9$ hours).

#### 3.8.3 MTF 1m Microstructure Context
For 5m bar at $t$, the 5 constituent 1m bars $\{t, t+60\text{s}, t+120\text{s}, t+180\text{s}, t+240\text{s}\}$ yield:
- `mtf_1m_vol_dispersion`: $\text{std}(V_{1\text{m}}) / (\text{mean}(V_{1\text{m}}) + \epsilon)$
- `mtf_1m_taker_trend`: Normalized OLS slope of taker aggression across the 5 1m bars.
- `mtf_1m_return_skew`: Normalized momentum concentration $(r_{\text{last}} - r_{\text{first}}) / (\sum |r_i| + \epsilon)$.
- **`required_history_bars`**: **1** (Available immediately on completion of the 5m bar).

---

## 4. Master Feature Registry Specification & Warm-Up Catalog

Every feature in the system is derived strictly from the `required_history_bars` convention.

| Feature Identifier | Family | Type | `required_history_bars` | First Valid Index | Notes |
|---|---|---|---|---|---|
| `ret_log_cc_1` | returns | DOUBLE | 2 | 1 | $n+1$ closes |
| `ret_log_cc_{3,6,12,24,48,96}` | returns | DOUBLE | $n+1$ | $n$ | $n+1$ closes |
| `ret_log_oc` | returns | DOUBLE | 1 | 0 | Single bar OHLC |
| `price_body_ratio` | returns | DOUBLE | 1 | 0 | Single bar OHLC |
| `price_{upper,lower}_wick_ratio` | returns | DOUBLE | 1 | 0 | Single bar OHLC |
| `price_midpoint` | returns | DOUBLE | 1 | 0 | Single bar OHLC |
| `mom_roc_{6,12,24,48}` | momentum | DOUBLE | $n+1$ | $n$ | $n+1$ closes |
| `mom_slope_{12,24,48}` | momentum | DOUBLE | $n$ | $n-1$ | $n$ closes OLS |
| `mom_sma_dev_{12,24,48,96}` | momentum | DOUBLE | $n$ | $n-1$ | $n$ closes SMA |
| `mom_ema_dev_{12,26,50}` | momentum | DOUBLE | $n$ | $n-1$ | SMA-seeded EMA |
| `mom_macd_hist` | momentum | DOUBLE | 34 | 33 | Natural composition (12/26/9) |
| `mom_rsi_{14,28}` | momentum | DOUBLE | $n+1$ | $n$ | Exact boundary Wilder |
| `vol_atr_{14,28}` | volatility | DOUBLE | $n+1$ | $n$ | TR requires prior close |
| `vol_atr_pct_{14,28}` | volatility | DOUBLE | $n+1$ | $n$ | ATR / Close |
| `vol_realized_{12,24,48,96}` | volatility | DOUBLE | $n+1$ | $n$ | $n$ returns = $n+1$ closes |
| `vol_gk_realized_{12,24}` | volatility | DOUBLE | $n$ | $n-1$ | Single-bar GK variance |
| `vol_zscore_12_96` | volatility | DOUBLE | 108 | 107 | $13 + 96 - 1$ |
| `liq_taker_buy_ratio` | liquidity | DOUBLE | 1 | 0 | Single bar TB/V |
| `liq_avg_trade_size` | liquidity | DOUBLE | 1 | 0 | Single bar V/N |
| `liq_vwap_dev_{12,48}` | liquidity | DOUBLE | $n$ | $n-1$ | Rolling QV/V |
| `liq_vol_ratio_{12,24,48}` | liquidity | DOUBLE | $n$ | $n-1$ | Rolling mean V |
| `liq_dollar_volume` | liquidity | DOUBLE | 1 | 0 | Re-exposed quote volume |
| `liq_delta_proxy` | liquidity | DOUBLE | 1 | 0 | Single bar delta proxy |
| `liq_cum_delta_{12,48}` | liquidity | DOUBLE | $n$ | $n-1$ | Rolling delta proxy |
| `ms_high_{12,24,48,96}` | structure | DOUBLE | $n$ | $n-1$ | Rolling high |
| `ms_low_{12,24,48,96}` | structure | DOUBLE | $n$ | $n-1$ | Rolling low |
| `ms_price_position_{12,24,48,96}` | structure | DOUBLE | $n$ | $n-1$ | Range position |
| `ms_bars_since_high_{24,96}` | structure | SMALLINT | $n$ | $n-1$ | Lag in bars |
| `ms_bars_since_low_{24,96}` | structure | SMALLINT | $n$ | $n-1$ | Lag in bars |
| `ms_is_pivot_high_{3,5}` | structure | BOOLEAN | $2s+1$ | $2s$ | Confirmed at $k+s$ |
| `ms_pivot_high_timestamp_{3,5}` | structure | TIMESTAMPTZ | $2s+1$ | $2s$ | Timestamp of bar $k$ |
| `ms_pivot_high_age_bars_{3,5}` | structure | SMALLINT | $2s+1$ | $2s$ | Lag = $s$ bars |
| `ms_is_pivot_low_{3,5}` | structure | BOOLEAN | $2s+1$ | $2s$ | Confirmed at $k+s$ |
| `ms_pivot_low_timestamp_{3,5}` | structure | TIMESTAMPTZ | $2s+1$ | $2s$ | Timestamp of bar $k$ |
| `ms_pivot_low_age_bars_{3,5}` | structure | SMALLINT | $2s+1$ | $2s$ | Lag = $s$ bars |
| `ms_consec_{up,down}_5` | structure | SMALLINT | 6 | 5 | 5 comparisons = 6 closes |
| `mr_zscore_{24,48,96}` | mean_reversion | DOUBLE | $n$ | $n-1$ | Rolling close Z-score |
| `mr_mean_dev_{12,48}` | mean_reversion | DOUBLE | $n$ | $n-1$ | Distance from mean |
| `mr_hurst_proxy_{48,96}` | mean_reversion | DOUBLE | $n+1$ | $n$ | Frozen R/S formulation |
| `mr_autocorr_lag1_{24,96}` | mean_reversion | DOUBLE | $n+2$ | $n+1$ | $n+1$ returns = $n+2$ closes |
| `time_*` (all session/time) | time | Various | 1 | 0 | Derived from timestamp |
| `mtf_15m_ret_log_cc_{4,16}` | mtf | DOUBLE | 17, 53 | 16, 52 | $3 \cdot K + 2$ ($K \in \{5, 17\}$) |
| `mtf_15m_mom_rsi_14` | mtf | DOUBLE | 47 | 46 | $3 \cdot 15 + 2$ |
| `mtf_15m_vol_atr_pct_14` | mtf | DOUBLE | 47 | 46 | $3 \cdot 15 + 2$ |
| `mtf_15m_price_position_16` | mtf | DOUBLE | 50 | 49 | $3 \cdot 16 + 2$ |
| `mtf_15m_liq_taker_buy_ratio` | mtf | DOUBLE | 5 | 4 | $3 \cdot 1 + 2$ |
| `mtf_15m_liq_vol_ratio_16` | mtf | DOUBLE | 50 | 49 | $3 \cdot 16 + 2$ |
| `mtf_1h_ret_log_cc_{4,24}` | mtf | DOUBLE | 71, 311 | 70, 310 | $12 \cdot K + 11$ ($K \in \{5, 25\}$) |
| `mtf_1h_mom_rsi_14` | mtf | DOUBLE | 191 | 190 | $12 \cdot 15 + 11$ |
| `mtf_1h_vol_realized_24` | mtf | DOUBLE | 311 | 310 | $12 \cdot 25 + 11$ (Max warm-up) |
| `mtf_1h_price_position_24` | mtf | DOUBLE | 299 | 298 | $12 \cdot 24 + 11$ |
| `mtf_1h_mr_zscore_24` | mtf | DOUBLE | 299 | 298 | $12 \cdot 24 + 11$ |
| `mtf_1h_liq_taker_buy_ratio` | mtf | DOUBLE | 23 | 22 | $12 \cdot 1 + 11$ |
| `mtf_1m_*` (all 3 microstructure) | mtf | DOUBLE | 1 | 0 | 5 constituent 1m bars |

---

## 5. Temporal Correctness and Missing Data Policy

### 5.1 No Look-Ahead Principle
Information set at bar $t$ (open $t$, close $t+300\text{s}$):
$$I(t) = \{ \text{Bar}(s) : s \le t \text{ and } \text{is\_complete}(s) = \text{True} \}$$
No feature references $s > t$ or any incomplete bar.

### 5.2 Completed-Bar Semantics
A 5m bar at open-timestamp $t$ is complete when wall-clock time passes $t + 300\text{s}$ and all 5 constituent 1m bars are marked complete.

### 5.3 Missing Candle & Gap-Invalidation Policy
1. **Zero Backward Extension**: A lookback window of $n$ bars strictly covers $n \times 300\text{s}$ of wall-clock time. If any bar within the window is absent from the canonical dataset, the feature evaluates to `NaN`. Windows are never extended backwards to find older bars.
2. **Stateful Accumulator Reset**: If a gap is encountered, recursive filters (EMA, ATR, Wilder RSI) pause updates and output `NaN` until re-seeded with a fresh continuous block of $n$ bars.
3. **Absence of Aligned HTF Candle**: If the completed HTF candle required by the alignment rule is missing or incomplete, all dependent MTF features evaluate to `NaN`.

---

## 6. Feature Quality Controls & Row Validity Flags (Correction C4)

### 6.1 NaN, Infinity, and Boundary Arithmetic Policy
- **Zero Infinity Guarantee**: No `inf` or `-inf` is ever written to Parquet. Any division by zero evaluates to an explicit mathematical boundary (e.g. RSI 100.0/0.0/50.0) or uses $\epsilon$ where mathematically appropriate. Uncomputable operations output `float('nan')`.
- **Z-Score Clamping**: Standardized values are clamped to $[-10.0, 10.0]$ to guard against extreme outliers.

### 6.2 Decoupled Validity Model: `is_warmup` vs. `is_valid` (Correction C4)

To prevent conflating insufficient historical warm-up with corrupt market data:

> [!IMPORTANT]
> **Correction C4 Resolution: Decoupled Flags**:
> - **`is_warmup: BOOLEAN`**:
>   - `True` for row index $< 311$ (the dataset-level maximum required history).
>   - `False` for row index $\ge 311$.
> - **`is_valid: BOOLEAN`**:
>   - Defined as: `is_warmup == False` **AND** `nan_feature_count == 0` **AND** `has_data_gap == False`.
>   - Indicates that the row has sufficient history AND all registry features computed successfully without encountering data gaps or corrupt inputs.
> - **Downstream Query Standard**:
>   Research and strategy discovery query clean post-warm-up rows via:
>   ```sql
>   SELECT * FROM features WHERE is_warmup = FALSE AND is_valid = TRUE;
>   ```
>   If a row has `is_warmup = FALSE` and `is_valid = FALSE`, it immediately and unambiguously signals **bad market data or a gap event**, not warm-up.

---

## 7. Architecture and FeatureRegistry

### 7.1 Typed Multi-Column Registry Architecture (Correction C5)

The `FeatureRegistry` is the sole source of truth for feature definitions, column typing, warm-up derivation, and schema generation.

```python
@dataclass(frozen=True)
class ColumnSpec:
    """Explicitly typed column definition emitted by a feature."""
    name: str
    duckdb_type: str        # 'DOUBLE', 'BOOLEAN', 'TIMESTAMPTZ', 'SMALLINT', 'VARCHAR'
    nullable: bool = True
    description: str = ""

@dataclass(frozen=True)
class FeatureDefinition:
    """Registry entry owning metadata and typed column specifications."""
    name: str
    family: str
    calculator: str
    parameters: dict
    required_history_bars: int   # Derived automatically from registration rules
    columns: tuple[ColumnSpec, ...] # One or more typed output columns
    temporal_semantics: str      # 'point_in_time', 'confirmation_lag_s'
    mtf_timeframe: str | None    # '1m', '15m', '1h', or None
    estimator_type: str          # 'exact', 'wilder_smoothed', 'rs_proxy'
    interpretation: str          # 'standard', 'research_feature_only'
    session_definition_version: str | None
    version: str = "2.0.0"
```

For standard scalar features, `columns` contains a single `ColumnSpec` with `duckdb_type="DOUBLE"`.
For pivot features (`ms_pivot_high_3`), `columns` contains:
1. `ColumnSpec("ms_is_pivot_high_3", "BOOLEAN")`
2. `ColumnSpec("ms_pivot_high_timestamp_3", "TIMESTAMPTZ")`
3. `ColumnSpec("ms_pivot_high_age_bars_3", "SMALLINT")`

The registry method `get_parquet_schema()` iterates over all registered features and emits the complete, strongly typed schema dynamically.

---

## 8. Storage Schema and Manifest

### 8.1 Partitioned Directory Structure
```
data/features/binance/spot/BTCUSDT/5m/feature_set=v2.0.0/
    ├── year=2023/month=09/btcusdt_5m_features_v2.0.0_202309.parquet
    ├── year=2023/month=10/btcusdt_5m_features_v2.0.0_202310.parquet
    └── ...
```

### 8.2 Parquet Schema
Derived directly from the registry:

**Fixed Metadata Columns**:
- `timestamp_utc`: `TIMESTAMPTZ` (5m bar open timestamp, Primary Key)
- `venue`: `VARCHAR` (`"binance"`)
- `instrument`: `VARCHAR` (`"BTCUSDT"`)
- `timeframe`: `VARCHAR` (`"5m"`)
- `is_warmup`: `BOOLEAN` (True if row index $< 311$)
- `is_valid`: `BOOLEAN` (True if post-warm-up, gap-free, zero NaNs)
- `nan_feature_count`: `SMALLINT` (Count of NaN values in feature columns)
- `input_dataset_version`: `VARCHAR` (`"v1.1.0"`)
- `feature_set_version`: `VARCHAR` (`"v2.0.0"`)
- `session_definition_version`: `VARCHAR` (`"1.0.0"`)

**Feature Columns**:
- Typed dynamically by registry: `DOUBLE` for continuous metrics, `BOOLEAN` for pivot flags, `TIMESTAMPTZ` for pivot timestamps, `SMALLINT` for pivot age and bar counts.

---

## 9. Comprehensive Testing Plan

The test suite enforces all mathematical definitions, boundary conditions, and temporal invariants:

### 9.1 Mathematical Correctness Tests (`tests/unit/features/`)
- `test_required_history_bars_convention`: programmatic check that every registered feature emits non-NaN at index `required_history_bars - 1` and NaN at prior indices.
- `test_macd_natural_composition`: verify EMA-12 continues recursively without re-seeding; verify MACD histogram first valid at bar index 33 (requiring 34 bars).
- `test_rsi_boundary_zero_loss_is_100`: monotonically increasing prices produce `RSI = 100.0` exactly (not $99.9999999$).
- `test_rsi_boundary_zero_gain_is_0`: monotonically decreasing prices produce `RSI = 0.0` exactly.
- `test_rsi_boundary_flat_price_is_50`: zero price change across window produces `RSI = 50.0` exactly.
- `test_atr_exact_boundary`: verify ATR calculation produces exact values without epsilon skew; verify `vol_atr_pct` handles non-positive close with NaN.
- `test_zscore_zero_variance_is_zero`: constant close series yields Z-score = $0.0$.
- `test_hurst_known_series`: evaluate frozen R/S formula on synthetic persistent series ($H > 0.5$) and random walk ($H \approx 0.5$).
- `test_pivot_typed_emission`: verify confirmation at $t = k + s$, verifying emitted `BOOLEAN`, `TIMESTAMPTZ`, and `SMALLINT` values.

### 9.2 Validity & Decoupling Tests
- `test_is_warmup_boundary`: verify rows $0 \dots 310$ have `is_warmup = True`, row $311$ has `is_warmup = False`.
- `test_is_valid_warmup_separation`: verify post-warm-up row with synthetic gap has `is_warmup = False` and `is_valid = False`.

### 9.3 Temporal Invariance & MTF Alignment Tests
- `test_no_lookahead_all_features`: verify truncating series does not alter prior bar feature values.
- `test_15m_completed_bar_alignment`: verify 5m bar at 14:05 uses completed 15m candle ending at 14:00 (opened 13:45).
- `test_1h_completed_bar_alignment`: verify 5m bar at 14:05 uses completed 1h candle ending at 14:00 (opened 13:00).
- `test_mtf_sweep_all_day_positions`: verify all 288 intraday 5m positions map strictly to completed HTF candles.

---

## 10. Deliverables

1. `src/xau_quant/features/`: complete feature engine package (registry, calculators, engine, storage, validators).
2. `configs/feature_sessions.yaml`: configurable session specifications (version 1.0.0).
3. `scripts/compute_features.py`: reproducible batch execution pipeline.
4. `data/features/binance/spot/BTCUSDT/5m/feature_set=v2.0.0/`: canonical Parquet dataset.
5. `data/metadata/manifests/btcusdt_5m_features_v2.0.0_manifest.json`: dataset manifest with SHA-256 provenance linked to Phase 1C root.
6. `tests/unit/features/` & `tests/integration/features/`: full test coverage.

---

## 11. Acceptance Criteria

| # | Criterion | Verification |
|---|---|---|
| AC-1 | All unit and registry consistency tests pass | `pytest tests/unit/features/ -v` (0 failures) |
| AC-2 | All integration tests pass | `pytest tests/integration/features/ -v` (0 failures) |
| AC-3 | Feature row count matches 5m candle count exactly | `SELECT COUNT(*)` = 315,648 |
| AC-4 | Zero `inf` or `-inf` across all columns | DuckDB scan across Parquet partitions |
| AC-5 | Rows $0 \dots 310$ have `is_warmup = True`; rows $\ge 311$ have `is_warmup = False` | DuckDB verification query |
| AC-6 | $\ge 99.9\%$ of post-warm-up rows have `is_valid = True` | DuckDB verification query |
| AC-7 | Identical serialized Parquet output across repeated runs | Byte-level SHA-256 comparison |
| AC-8 | All no-lookahead parametrized tests pass | Pytest suite over all registry features |
| AC-9 | MTF alignment verified for all 288 daily positions | Dedicated alignment test suite |
| AC-10 | Pivot features emitted at confirmation time with typed columns | Unit tests verifying confirmation lag $s$ |
| AC-11 | RSI/ATR boundary tests pass without epsilon distortion | Dedicated boundary test suite |
| AC-12 | MACD natural composition verified | Unit test verifying bar 33 first valid |
| AC-13 | End-to-end execution $< 140$ seconds | Execution benchmark |
| AC-14 | Zero mypy and ruff violations | `mypy --strict` and `ruff check` |
| AC-15 | Zero new dependencies in `pyproject.toml` | `git diff pyproject.toml` |
| AC-16 | Provenance hash linked to Phase 1C root manifest | Manifest inspection |

---

> [!CAUTION]
> **GATE ENFORCEMENT**: This is a design-only document (Revision 3). Zero implementation has been executed. No feature code has been written. No data has been downloaded, modified, or processed. No commits or pushes have been made. The working tree is unchanged. Awaiting formal review and explicit approval from Nishant before Phase 2 implementation begins.
