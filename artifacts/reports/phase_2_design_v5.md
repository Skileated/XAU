# Phase 2 Design Specification: Market Feature Engine (Revision 5.1)

**Project**: XAU Quantitative Strategy Discovery and Decision Platform  
**Phase**: 2 (Market Feature Engine)  
**Revision**: 5.1 — final specification cleanup correcting Hurst known-answer precision, qualifying MTF history vs. aligned availability, and refining consecutive-bar lookback integrity  
**Status**: DESIGN DOCUMENT — Phase 2 Implementation Approval Gate — Zero Implementation Executed  
**Date**: 2026-09-19  
**Primary Target Dataset**: `BTCUSDT` Binance Spot — Phase 1C canonical dataset (`v1.1.0`)  
**Research Clock**: 5-minute bars (primary); 1m, 15m, 1h as context timeframes  
**Execution Boundary**: Feature Engineering Only — Zero Strategies, Zero Signals, Zero ML, Zero Backtesting, Zero UI  

---

## Revision 5.1 Summary of Final Refinements

This document supersedes Revision 5. The following three final refinements have been applied in strict accordance with the final review:

| # | Item | Revision 5.1 Resolution | Document Section |
|---|---|---|---|
| **C1** | **Hurst known-answer precision discrepancy** | Corrected the precalculated reference value from intermediate-rounded `0.278594344446` to exact double-precision **`0.278594645149448`** (exact double: `0.2785946451494484`, derived from $\ln(R/S) / \ln(8)$ where $R/S = 0.03625 / \sqrt{0.0004125}$), asserted within $10^{-12}$ tolerance. | Section 3.6.3, Section 9.1 |
| **C2** | **"Exactly 311 bars" language qualification** | Explicitly designated 311 bars as the **maximum registry-derived history requirement**. Clarified that this is a history requirement, not an unconditional guarantee of feature validity; missing/incomplete aligned HTF observations independently make MTF features unavailable (`is_valid = False`). Reinforced clean decoupling between `is_warmup` and `is_valid`. | Section 3.8.2, Section 6.2, Section 8.2, Section 9.2, Section 11 (AC-5) |
| **C3** | **Gap-window definition precision** | Replaced wall-clock duration phrasing with strict consecutive-bar integrity: **"Lookback windows consist of exactly the registered number of consecutive primary bars. No missing primary bar may occur between the earliest and latest constituent bar. No backward extension is permitted to compensate for a missing bar."** | Section 1.4, Section 5.2, Section 5.4 |

---

## 1. Objective and Scope

### 1.1 Mission Statement

Phase 2 builds a **deterministic, temporally correct, research/live-parity market feature layer** on top of the validated Phase 1C BTCUSDT Spot dataset. Its sole output is a versioned, schema-validated feature dataset that downstream strategy discovery can consume without re-computing or re-validating features.

The feature engine must be:
- **Deterministic**: on a supported runtime environment, identical inputs produce identical results; repeated runs produce identical serialized Parquet output.
- **Temporally correct**: zero look-ahead; features for a 5m bar closing at $t + 300\text{s}$ use only information whose completion timestamp is $\le t + 300\text{s}$.
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
| **Quality controls** | Explicit boundary math, gap-invalidation policy, duplicate detection, history guards, `is_warmup`, `has_data_gap`, `domain_nan_feature_count`, and `is_valid` metadata per row |

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
| Hurst proxy | **Frozen to standard single-window R/S formulation on log-returns (`mr_hurst_proxy_n`)** |
| Pivot representation | **Confirmation-time semantics with typed multi-column emission (Flag, Timestamp, Age)** |
| 4h/1d MTF context | **Deferred to Phase 2.1** |
| Missing-data policy | **Consecutive-bar integrity; gap invalidates window; zero backward extension** |
| MTF alignment | **Completed-HTF-bar-at-primary-close rule: `floor(t-600s, 15m)` and `floor(t-3300s, 1h)`** |
| Determinism contract | **Byte-identical on same runtime; schema/order identity and float numerical tolerance ($10^{-12}$ / $10^{-10}$) cross-runtime** |
| Warm-up convention | **Uniform `required_history_bars`: number of input bars required for first valid output, inclusive** |
| MACD initialization | **Natural composition of SMA-seeded EMAs without secondary re-seeding** |
| Zero-denominator handling | **Explicit semantic boundary tables (RSI 100/0/50, zero-volume NaNs) without silent epsilon distortion** |
| Row validity flags | **Decoupled into `is_warmup`, `has_data_gap`, `domain_nan_feature_count`, and `is_valid`** |
| Data-quality standard | **Exact validity accounting tied to registered gaps; zero unexplained failure budget** |

---

## 2. Feature Taxonomy

### 2.1 Distinction: Raw Observations vs. Derived Features

| Category | Definition |
|---|---|
| **Raw observation** | Sourced directly from a `CanonicalCandle`: `open`, `high`, `low`, `close`, `volume`, `quote_volume`, `trade_count`, `taker_buy_base_volume`, `taker_buy_quote_volume`, `is_complete` |
| **Derived feature** | Any deterministic computation applied to raw observations across one or more bars |

Raw observations remain in the canonical candle dataset. The feature dataset contains derived features plus primary key columns (`timestamp_utc`, `venue`, `instrument`, `timeframe`) and validity metadata.

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

### 3.0 Warm-Up and Indexing Convention

> [!IMPORTANT]
> **Authoritative Convention**:
> `required_history_bars` is defined as the **minimum number of chronologically ordered input bars required to produce the first valid (non-NaN) output, inclusive of the current bar**.
> 
> For an input series indexed $0, 1, 2, \dots$:
> - If `required_history_bars = k`, then output rows at indices $0, 1, \dots, k-2$ are `NaN`.
> - The **first valid output** occurs at index $k-1$.
> - An input array with length $< k$ produces exclusively `NaN`.

---

### 3.1 Price and Returns Family

#### 3.1.1 Log-Return (Close-to-Close)
```
ret_log_cc_{n} = ln(C[t]) - ln(C[t-n])
```
- Parameters: $n \in \{1, 3, 6, 12, 24, 48, 96\}$ (5m, 15m, 30m, 1h, 2h, 4h, 8h).
- Requires $C[t]$ and $C[t-n]$ ($n+1$ observations).
- **`required_history_bars`**: **$n + 1$** (First valid at index $n$).

#### 3.1.2 Intra-Bar Log-Return (Open-to-Close)
```
ret_log_oc = ln(C[t]) - ln(O[t])
```
- Requires single bar $O[t], C[t]$.
- **`required_history_bars`**: **1** (First valid at index 0).

#### 3.1.3 Bar Body Ratio
```
price_body_ratio = |C[t] - O[t]| / (H[t] - L[t] + eps)
```
- Range: $[0.0, 1.0]$. $\epsilon = 10^{-8}$ prevents division by zero only when $H[t] == L[t]$ (zero price range).
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
- Boundary case: if $C[t-n] \le 0.0$, output `NaN`.
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
- **`required_history_bars`**: **$n$** (First valid at index $n-1$).

#### 3.2.3 SMA Deviation
```
SMA_{n}[t] = (1 / n) * sum_{k=0}^{n-1} C[t-k]
mom_sma_dev_{n} = (C[t] - SMA_{n}[t]) / SMA_{n}[t]
```
- Parameters: $n \in \{12, 24, 48, 96\}$.
- **`required_history_bars`**: **$n$** (First valid at index $n-1$).

#### 3.2.4 EMA Deviation (SMA-Seeded Initialization)
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

#### 3.2.5 MACD Histogram (Natural Composition)
Independent SMA-seeded recursive filters:
1. $\text{EMA}_{12}$ seeds at bar index 11 from $C[0 \dots 11]$ and updates recursively for all subsequent bars.
2. $\text{EMA}_{26}$ seeds at bar index 25 from $C[0 \dots 25]$ and updates recursively for all subsequent bars.
3. $\text{MACD\_line}$ is first valid at bar index 25:
   $$\text{MACD\_line}[i] = \text{EMA}_{12}[i] - \text{EMA}_{26}[i] \quad (i \ge 25)$$
4. $\text{MACD\_signal}$ is a 9-period SMA-seeded EMA of $\text{MACD\_line}$, seeded over $\text{MACD\_line}[25 \dots 33]$:
   $$\text{MACD\_signal}[33] = \frac{1}{9} \sum_{k=25}^{33} \text{MACD\_line}[k]$$
   For $i \ge 34$:
   $$\text{MACD\_signal}[i] = 0.2 \cdot \text{MACD\_line}[i] + 0.8 \cdot \text{MACD\_signal}[i-1]$$
5. Normalized Histogram:
   $$\text{mom\_macd\_hist}[t] = \frac{\text{MACD\_line}[t] - \text{MACD\_signal}[t]}{C[t]}$$
- **`required_history_bars`**: **34** (First valid at index 33).

#### 3.2.6 Relative Strength Index (RSI, Wilder Smoothed)
1. $\Delta[i] = C[i] - C[i-1]$ for $i \ge 1$. $U[i] = \max(\Delta[i], 0)$, $D[i] = \max(-\Delta[i], 0)$.
2. Seed averages at index $n$ using first $n$ deltas (requiring $n+1$ closes $C[0 \dots n]$):
   $$\text{AvgU}[n] = \frac{1}{n} \sum_{k=1}^n U[k], \quad \text{AvgD}[n] = \frac{1}{n} \sum_{k=1}^n D[k]$$
3. Update for $i > n$:
   $$\text{AvgU}[i] = \frac{(n-1) \text{AvgU}[i-1] + U[i]}{n}, \quad \text{AvgD}[i] = \frac{(n-1) \text{AvgD}[i-1] + D[i]}{n}$$
4. **Exact Mathematical Boundaries**:
   - If $\text{AvgD}[i] == 0.0$ and $\text{AvgU}[i] > 0.0 \implies \mathbf{mom\_rsi_{n} = 100.0}$ (exact).
   - If $\text{AvgU}[i] == 0.0$ and $\text{AvgD}[i] > 0.0 \implies \mathbf{mom\_rsi_{n} = 0.0}$ (exact).
   - If $\text{AvgU}[i] == 0.0$ and $\text{AvgD}[i] == 0.0 \implies \mathbf{mom\_rsi_{n} = 50.0}$ (exact, flat price neutrality).
   - Otherwise ($\text{AvgD}[i] > 0.0$ and $\text{AvgU}[i] > 0.0$):
     $$RS = \frac{\text{AvgU}[i]}{\text{AvgD}[i]}, \quad \mathbf{mom\_rsi_{n} = 100.0 - \frac{100.0}{1.0 + RS}}$$
- Parameters: $n \in \{14, 28\}$.
- **`required_history_bars`**: **$n + 1$** (For $n=14 \implies 15$; for $n=28 \implies 29$).

---

### 3.3 Volatility Family

#### 3.3.1 Average True Range (ATR, Wilder Smoothed)
```
TR[t] = max(H[t] - L[t], |H[t] - C[t-1]|, |L[t] - C[t-1]|)   for t >= 1
```
Because $H[t] \ge L[t]$, $TR[t] \ge 0.0$ always.
```
Initialization at bar index n:
  ATR[n] = (1 / n) * sum_{k=1}^n TR[k]

Update for i > n:
  ATR[i] = ((n - 1) * ATR[i-1] + TR[i]) / n

vol_atr_{n}     = ATR[t]           (USD)
vol_atr_pct_{n} = ATR[t] / C[t]    (dimensionless; NaN if C[t] <= 0.0)
```
- Parameters: $n \in \{14, 28\}$.
- **`required_history_bars`**: **$n + 1$** (For $n=14 \implies 15$; for $n=28 \implies 29$).

#### 3.3.2 Realized Volatility (Log-Returns)
```
r[i] = ln(C[i]) - ln(C[i-1])
vol_realized_{n} = std(r[t-n+1 \dots t], ddof=1)   [Welford online algorithm]
```
- Parameters: $n \in \{12, 24, 48, 96\}$.
- **`required_history_bars`**: **$n + 1$** (First valid at index $n$). For $n=96 \implies 97$.

#### 3.3.3 Garman-Klass Volatility Estimator (Non-Negative Variance Guard & Domain Handling)

For an individual bar $t$:
$$GK[t] = 0.5 \left(\ln\frac{H[t]}{L[t]}\right)^2 - (2\ln 2 - 1)\left(\ln\frac{C[t]}{O[t]}\right)^2$$
Note that $2\ln 2 - 1 \approx 0.38629$. For candles with large bodies and very small wicks, the second term can exceed the first, meaning an **individual bar's $GK[t]$ can legitimately be negative**.

The rolling estimator averages $n$ bars:
$$\text{raw\_variance} = \frac{1}{n} \sum_{k=0}^{n-1} GK[t-k]$$

The engine evaluates:
```python
if not (H[t] >= L[t] > 0.0 and O[t] > 0.0 and C[t] > 0.0):
    vol_gk_realized = float("nan")  # Data-quality failure: corrupt OHLC input
elif raw_variance >= 0.0:
    vol_gk_realized = math.sqrt(raw_variance)
elif abs(raw_variance) <= 1e-12:
    # Numerical roundoff guard near zero
    vol_gk_realized = 0.0
else:
    # Materially negative estimator (raw_variance < -1e-12):
    # Domain boundary: cannot take sqrt of negative number
    vol_gk_realized = float("nan")
    # Handled as domain_defined_nan, not a data-quality failure
```
- Parameters: $n \in \{12, 24\}$.
- **`required_history_bars`**: **$n$** (First valid at index $n-1$).

#### 3.3.4 Volatility Z-Score
```
window = [vol_realized_12[t - 96 + 1], ..., vol_realized_12[t]]
mu     = mean(window)
sigma  = std(window, ddof=1)

If sigma == 0.0:
    vol_zscore_12_96 = 0.0    [exact boundary: constant volatility series]
Else:
    vol_zscore_12_96 = clamp((vol_realized_12[t] - mu) / sigma, -10.0, 10.0)
```
- **`required_history_bars`**: **108** ($13 + 96 - 1$, first valid at index 107).

---

### 3.4 Volume and Liquidity Family (Explicit Zero-Volume Policy)

When trading volume is zero, metrics evaluate deterministically according to the following specification:

| Feature Identifier | Formula | Zero Denominator Condition | Output | Rationale |
|---|---|---|---|---|
| `liq_taker_buy_ratio` | $TB[t] / V[t]$ | $V[t] == 0.0$ | `NaN` | No trades occurred; taker proportion is undefined. |
| `liq_avg_trade_size` | $V[t] / N[t]$ | $N[t] == 0 \text{ or } V[t] == 0.0$ | `NaN` | Zero trades yields undefined trade size. |
| `liq_vwap_dev_{n}` | $(C[t] - \text{VWAP}_{n}) / \text{VWAP}_{n}$ | $\sum V[t-n+1 \dots t] == 0.0$ | `NaN` | Zero volume across window yields undefined VWAP. |
| `liq_vol_ratio_{n}` | $V[t] / \text{mean}(V)$ | $\text{mean}(V) == 0.0$ | `NaN` | Relative volume undefined when rolling average is zero. |
| `liq_dollar_volume` | $QV[t]$ | None (always valid) | $QV[t]$ | Re-exposed quote volume (valid at $0.0$). |
| `liq_delta_proxy` | $(2 \cdot TB[t] - V[t]) / V[t]$ | $V[t] == 0.0$ | `NaN` | Normalized delta undefined with zero volume. |
| `liq_cum_delta_{n}` | $\sum CD / \sum V$ | $\sum V[t-n+1 \dots t] == 0.0$ | `NaN` | Normalized cumulative delta undefined with zero volume. |

**Required History**:
- `liq_taker_buy_ratio`, `liq_avg_trade_size`, `liq_dollar_volume`, `liq_delta_proxy`: **`required_history_bars` = 1** (valid at index 0).
- `liq_vwap_dev_{12,48}`, `liq_vol_ratio_{12,24,48}`, `liq_cum_delta_{12,48}`: **`required_history_bars` = $n$** (valid at index $n-1$).

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

#### 3.5.4 Pivot Confirmation (Confirmation-Time Semantics)
A pivot of strength $s$ at bar $k$ requires $s$ bars to the left and $s$ bars to the right. It is **confirmed at bar $t = k + s$**:
```
Pivot High at k confirmed at t = k + s iff:
  H[k] > H[k-j]  for all j in {1..s}
  H[k] > H[k+j]  for all j in {1..s}
```
Window required: $s$ (left) + $1$ (pivot) + $s$ (right) $= 2s + 1$ bars.

At confirmation bar $t = k + s$, three typed columns are generated:
- `ms_is_pivot_high_{s}`: `BOOLEAN` (`True` at confirmation bar $t$, `False` otherwise)
- `ms_pivot_high_timestamp_{s}`: `TIMESTAMPTZ` (Open timestamp of pivot bar $k$; `NULL` if `is_pivot` is `False`)
- `ms_pivot_high_age_bars_{s}`: `SMALLINT` (Lag in 5m bars: exactly $s$ when confirmed, `NULL` otherwise)

Analogous columns for pivot lows: `ms_is_pivot_low_{s}`, `ms_pivot_low_timestamp_{s}`, `ms_pivot_low_age_bars_{s}`.
- Parameters: $s \in \{3, 5\}$.
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

#### 3.6.1 Z-Score of Close
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

#### 3.6.3 Single-Window Rescaled Range (R/S) Hurst Proxy (Refinement C1)

> [!IMPORTANT]
> **Single-Window R/S Proxy Definition & Known-Answer Verification**:
> This indicator is explicitly qualified and registered as a **single-window $R/S$ proxy** (`mr_hurst_proxy_n`), **not** a full multi-scale Hurst exponent. It evaluates persistence within a fixed lookback window:
> - Registry metadata: `estimator_type = "rs_single_window_proxy"`, `interpretation = "research_feature_only"`.
> - Downstream usage: Research indicator only; must not be used as a standalone regime classifier.

**Frozen Computation**:
Let $r_k = \ln(C[t - n + 1 + k]) - \ln(C[t - n + k])$ for $k = 0, \dots, n-1$ be the $n$ log-returns.
1. Mean return: $m = \frac{1}{n} \sum_{k=0}^{n-1} r_k$
2. Mean-centered cumulative deviations:
   $$Z_0 = 0.0, \quad Z_j = \sum_{k=0}^{j-1} (r_k - m) \quad \text{for } j = 1, \dots, n \quad (\text{Note: } Z_n = 0.0)$$
3. Range: $R = \max(Z_0, Z_1, \dots, Z_n) - \min(Z_0, Z_1, \dots, Z_n)$
4. Sample standard deviation: $S = \sqrt{\frac{1}{n-1} \sum_{k=0}^{n-1} (r_k - m)^2}$
5. Rescaled Range Proxy:
   - If $S == 0.0$ or $R == 0.0$: $\mathbf{mr\_hurst\_proxy_{n} = 0.5}$ (exact boundary: uninformative flat series).
   - Else:
     $$\mathbf{mr\_hurst\_proxy_{n} = \text{clamp}\left( \frac{\ln(R / S)}{\ln(n)}, 0.0, 1.0 \right)}$$

**Reference Test Vector (Exact Known-Answer, Correction C1)**:
For $n = 8$ and return vector:
$$r = [0.01, -0.02, 0.03, -0.01, 0.02, -0.03, 0.01, 0.00]$$
- Mean: $m = 0.00125$
- Cumulative Profile: $Z = [0.0, 0.00875, -0.0125, 0.01625, 0.005, 0.02375, -0.0075, 0.00125, 0.0]$
- $R = \max(Z) - \min(Z) = 0.02375 - (-0.0125) = 0.03625$
- Sample variance: $S^2 = 0.0028875 / 7 = 0.0004125 \implies S = \sqrt{0.0004125} \approx 0.020310096011589897$
- $R / S = 0.03625 / \sqrt{0.0004125} \approx 1.7848266192003244$
- $\mathbf{mr\_hurst\_proxy_{8}} = \frac{\ln(1.7848266192003244)}{\ln(8)} \approx \mathbf{0.278594645149448}$ (exact double-precision reference value: **`0.2785946451494484`**).
- Parameters: $n \in \{48, 96\}$.
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

- **15m ($D_{\text{TF}} = 900\text{s}$)**: $t_{15\text{m}} = \text{floor}(t - 600\text{s}, 15\text{m})$
- **1h ($D_{\text{TF}} = 3600\text{s}$)**: $t_{1\text{h}} = \text{floor}(t - 3300\text{s}, 1\text{h})$

#### 3.8.2 Derivation of MTF `required_history_bars` (Refinement C2)
For $K$ completed HTF bars:
- 15m: $\text{required\_5m\_bars} = 3 \cdot K + 2$
- 1h: $\text{required\_5m\_bars} = 12 \cdot K + 11$

**Lookbacks**:
1. `mtf_15m_ret_log_cc_4`: $K=5 \implies \text{req} = 3 \cdot 5 + 2 = \mathbf{17}$ 5m bars.
2. `mtf_15m_mom_rsi_14`: $K=15 \implies \text{req} = 3 \cdot 15 + 2 = \mathbf{47}$ 5m bars.
3. `mtf_15m_vol_atr_pct_14`: $K=15 \implies \text{req} = 3 \cdot 15 + 2 = \mathbf{47}$ 5m bars.
4. `mtf_15m_price_position_16`: $K=16 \implies \text{req} = 3 \cdot 16 + 2 = \mathbf{50}$ 5m bars.
5. `mtf_15m_liq_taker_buy_ratio`: $K=1 \implies \text{req} = 3 \cdot 1 + 2 = \mathbf{5}$ 5m bars (outputs `NaN` if $V_{\text{15m}} == 0.0$).
6. `mtf_15m_liq_vol_ratio_16`: $K=16 \implies \text{req} = 3 \cdot 16 + 2 = \mathbf{50}$ 5m bars (outputs `NaN` if $\text{mean}(V) == 0.0$).
7. `mtf_1h_ret_log_cc_24`: $K=25 \implies \text{req} = 12 \cdot 25 + 11 = \mathbf{311}$ 5m bars.
8. `mtf_1h_vol_realized_24`: $K=25 \implies \text{req} = 12 \cdot 25 + 11 = \mathbf{311}$ 5m bars.
9. `mtf_1h_mom_rsi_14`: $K=15 \implies \text{req} = 12 \cdot 15 + 11 = \mathbf{191}$ 5m bars.
10. `mtf_1h_liq_taker_buy_ratio`: $K=1 \implies \text{req} = 12 \cdot 1 + 11 = \mathbf{23}$ 5m bars (outputs `NaN` if $V_{\text{1h}} == 0.0$).

> [!IMPORTANT]
> **Refinement C2: Qualification of History Requirement vs. Aligned MTF Availability**:
> **Maximum registry-derived history requirement is 311 primary 5m bars.**  
> That is a history requirement, not a guarantee that every MTF feature becomes valid at that exact row. Missing/incomplete aligned HTF observations can independently make a feature unavailable.
> 
> This distinction is reflected in `is_warmup` versus `is_valid`:
> - **`is_warmup: BOOLEAN`**: Evaluated strictly against the declared global history requirement (`row_index < 311`). Rows $0 \dots 310$ have `is_warmup = True`; rows $\ge 311$ have `is_warmup = False`.
> - **`is_valid: BOOLEAN`**: Additionally verifies actual data integrity, gap absence, zero data-quality NaNs, and availability of aligned HTF observations. Reaching row $\ge 311$ satisfies the history requirement (`is_warmup = False`), but does not guarantee `is_valid = True` if aligned HTF candles are missing or incomplete.

#### 3.8.3 MTF 1m Microstructure Context
For a 5m bar at $t$, the 5 constituent 1m bars have open timestamps $\{t, t+60\text{s}, t+120\text{s}, t+180\text{s}, t+240\text{s}\}$ and close timestamps $\{t+60\text{s}, \dots, t+300\text{s}\}$.
- `mtf_1m_vol_dispersion`: $\text{std}(V_{1\text{m}}) / \text{mean}(V_{1\text{m}})$. If $\text{mean}(V_{1\text{m}}) == 0.0 \implies \mathbf{NaN}$.
- `mtf_1m_taker_trend`: Normalized OLS slope of taker aggression across the 5 1m bars. If any $V_{1\text{m}}[i] == 0.0 \implies \mathbf{NaN}$.
- `mtf_1m_return_skew`: Normalized momentum concentration $(r_{\text{last}} - r_{\text{first}}) / \sum |r_i|$. If $\sum |r_i| == 0.0 \implies \mathbf{0.0}$ (exact boundary: flat microstructure).
- **`required_history_bars`**: **1** (Available immediately when the 5m bar completes at $t + 300\text{s}$).

---

## 4. Master Feature Registry Specification & Warm-Up Catalog

Every feature is derived strictly from the `required_history_bars` convention.

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
| `vol_gk_realized_{12,24}` | volatility | DOUBLE | $n$ | $n-1$ | Two-tier variance guard |
| `vol_zscore_12_96` | volatility | DOUBLE | 108 | 107 | $13 + 96 - 1$ |
| `liq_taker_buy_ratio` | liquidity | DOUBLE | 1 | 0 | Single bar TB/V (domain NaN if V=0) |
| `liq_avg_trade_size` | liquidity | DOUBLE | 1 | 0 | Single bar V/N (domain NaN if N=0 or V=0) |
| `liq_vwap_dev_{12,48}` | liquidity | DOUBLE | $n$ | $n-1$ | Rolling QV/V (domain NaN if sum(V)=0) |
| `liq_vol_ratio_{12,24,48}` | liquidity | DOUBLE | $n$ | $n-1$ | Rolling mean V (domain NaN if mean(V)=0) |
| `liq_dollar_volume` | liquidity | DOUBLE | 1 | 0 | Re-exposed quote volume |
| `liq_delta_proxy` | liquidity | DOUBLE | 1 | 0 | Single bar delta (domain NaN if V=0) |
| `liq_cum_delta_{12,48}` | liquidity | DOUBLE | $n$ | $n-1$ | Rolling delta (domain NaN if sum(V)=0) |
| `ms_high_{12,24,48,96}` | structure | DOUBLE | $n$ | $n-1$ | Rolling high |
| `ms_low_{12,24,48,96}` | structure | DOUBLE | $n$ | $n-1$ | Rolling low |
| `ms_price_position_{12,24,48,96}` | structure | DOUBLE | $n$ | $n-1$ | Range position |
| `ms_bars_since_high_{24,96}` | structure | SMALLINT | $n$ | $n-1$ | Lag in bars |
| `ms_bars_since_low_{24,96}` | structure | SMALLINT | $n$ | $n-1$ | Lag in bars |
| `ms_is_pivot_high_{3,5}` | structure | BOOLEAN | $2s+1$ | $2s$ | Confirmed at $k+s$ |
| `ms_pivot_high_timestamp_{3,5}` | structure | TIMESTAMPTZ | $2s+1$ | $2s$ | Timestamp of bar $k$ (nullable event) |
| `ms_pivot_high_age_bars_{3,5}` | structure | SMALLINT | $2s+1$ | $2s$ | Lag = $s$ bars (nullable event) |
| `ms_is_pivot_low_{3,5}` | structure | BOOLEAN | $2s+1$ | $2s$ | Confirmed at $k+s$ |
| `ms_pivot_low_timestamp_{3,5}` | structure | TIMESTAMPTZ | $2s+1$ | $2s$ | Timestamp of bar $k$ (nullable event) |
| `ms_pivot_low_age_bars_{3,5}` | structure | SMALLINT | $2s+1$ | $2s$ | Lag = $s$ bars (nullable event) |
| `ms_consec_{up,down}_5` | structure | SMALLINT | 6 | 5 | 5 comparisons = 6 closes |
| `mr_zscore_{24,48,96}` | mean_reversion | DOUBLE | $n$ | $n-1$ | Rolling close Z-score |
| `mr_mean_dev_{12,48}` | mean_reversion | DOUBLE | $n$ | $n-1$ | Distance from mean |
| `mr_hurst_proxy_{48,96}` | mean_reversion | DOUBLE | $n+1$ | $n$ | Single-window R/S proxy (research-only) |
| `mr_autocorr_lag1_{24,96}` | mean_reversion | DOUBLE | $n+2$ | $n+1$ | $n+1$ returns = $n+2$ closes |
| `time_*` (all session/time) | time | Various | 1 | 0 | Derived from timestamp |
| `mtf_15m_ret_log_cc_{4,16}` | mtf | DOUBLE | 17, 53 | 16, 52 | $3 \cdot K + 2$ ($K \in \{5, 17\}$) |
| `mtf_15m_mom_rsi_14` | mtf | DOUBLE | 47 | 46 | $3 \cdot 15 + 2$ |
| `mtf_15m_vol_atr_pct_14` | mtf | DOUBLE | 47 | 46 | $3 \cdot 15 + 2$ |
| `mtf_15m_price_position_16` | mtf | DOUBLE | 50 | 49 | $3 \cdot 16 + 2$ |
| `mtf_15m_liq_taker_buy_ratio` | mtf | DOUBLE | 5 | 4 | $3 \cdot 1 + 2$ (domain NaN if $V_{\text{15m}}=0$) |
| `mtf_15m_liq_vol_ratio_16` | mtf | DOUBLE | 50 | 49 | $3 \cdot 16 + 2$ (domain NaN if $\text{mean}(V)=0$) |
| `mtf_1h_ret_log_cc_{4,24}` | mtf | DOUBLE | 71, 311 | 70, 310 | $12 \cdot K + 11$ ($K \in \{5, 25\}$, Max registry history) |
| `mtf_1h_mom_rsi_14` | mtf | DOUBLE | 191 | 190 | $12 \cdot 15 + 11$ |
| `mtf_1h_vol_realized_24` | mtf | DOUBLE | 311 | 310 | $12 \cdot 25 + 11$ (Max registry history) |
| `mtf_1h_price_position_24` | mtf | DOUBLE | 299 | 298 | $12 \cdot 24 + 11$ |
| `mtf_1h_mr_zscore_24` | mtf | DOUBLE | 299 | 298 | $12 \cdot 24 + 11$ |
| `mtf_1h_liq_taker_buy_ratio` | mtf | DOUBLE | 23 | 22 | $12 \cdot 1 + 11$ (domain NaN if $V_{\text{1h}}=0$) |
| `mtf_1m_*` (all 3 microstructure) | mtf | DOUBLE | 1 | 0 | 5 constituent 1m bars (completion $\le t+300\text{s}$) |

---

## 5. Temporal Correctness and Determinism

### 5.1 No Look-Ahead Principle
For a primary 5m bar with open timestamp $t$ and close timestamp $t + 300\text{s}$, the information set $I(t)$ consists of all observations whose **completion timestamp is less than or equal to $t + 300\text{s}$**:
$$I(t) = \{ \text{Observation}(s) : \text{completion\_timestamp}(s) \le t + 300\text{s} \text{ and } \text{is\_complete}(s) = \text{True} \}$$

**Explicit 1m MTF Resolution**:
The five constituent 1m bars have open timestamps $\{t, t+60\text{s}, t+120\text{s}, t+180\text{s}, t+240\text{s}\}$ and completion timestamps $\{t+60\text{s}, t+120\text{s}, t+180\text{s}, t+240\text{s}, t+300\text{s}\}$. Because every constituent 1m bar's completion timestamp is $\le t + 300\text{s}$, all five are legitimate members of $I(t)$ and are strictly look-ahead-free when the 5m bar completes.

### 5.2 Completed-Bar Semantics
A 5m bar at open-timestamp $t$ is complete at close-timestamp $t + 300\text{s}$ when all 5 constituent 1m bars $[t, t+60\text{s}, \dots, t+240\text{s}]$ are marked complete (in a live streaming environment, once wall-clock time passes $t + 300\text{s}$).

### 5.3 Determinism and Reproducibility

The engine enforces two distinct determinism targets:
1. **Same Supported Runtime + Writer Configuration**:
   - Environment: Python 3.12, identical DuckDB version, identical operating system architecture.
   - Requirement: **Byte-identical serialized Parquet output**, producing matching file-level and dataset-level SHA-256 digests across repeated runs.
2. **Cross-Architecture / Cross-Runtime Equivalence**:
   - Environment: Differing operating systems (Windows vs Linux) or differing Python micro-versions.
   - Requirement:
     - Column names, column order, DuckDB logical types, row ordering, timestamps, categorical values, and discrete integer/boolean values **must be identical**.
     - Floating-point values must satisfy the specified numerical tolerances:
       - General scalar features: $|a - b| \le 10^{-12}$
       - Recursive accumulators (EMA, ATR, Wilder RSI, Welford std): $|a - b| \le 10^{-10}$
     - **Byte-level Parquet identity is NOT required across runtimes/architectures** (cross-platform floating-point representation nuances and Parquet compressor variations preclude identical serialized byte hashes).

### 5.4 Missing Candle & Gap-Invalidation Policy (Refinement C3)

> [!IMPORTANT]
> **Refinement C3: Consecutive-Bar Lookback Integrity**:
> 1. **Strict Consecutive-Bar Integrity**: Lookback windows consist of exactly the registered number of consecutive primary bars. No missing primary bar may occur between the earliest and latest constituent bar. No backward extension is permitted to compensate for a missing bar. If any bar within the registered lookback window is absent from the canonical dataset, the feature outputs `NaN`.
> 2. **Stateful Accumulator Reset**: If a gap occurs, recursive filters pause updates and output `NaN` until re-seeded with a continuous block of $n$ consecutive primary bars.
> 3. **Absence of Aligned HTF Candle**: If the completed HTF candle required by the alignment rule is missing or incomplete, all dependent MTF features evaluate to `NaN`.

---

## 6. Feature Quality Controls & Three-Tier NaN Decoupling

### 6.1 NaN, Infinity, and Boundary Arithmetic Policy
- **Zero Infinity Guarantee**: No `inf` or `-inf` is ever written to Parquet.
- **Z-Score Clamping**: Standardized values are clamped to $[-10.0, 10.0]$.

### 6.2 Three-Tier NaN Taxonomy & Row Validity

The feature engine formalizes three distinct categories of `NaN`:

1. **Warmup NaN**:
   - *Cause*: Insufficient historical bars prior to reaching the declared maximum registry-derived history requirement ($i < 311$).
   - *Flag*: `is_warmup = True`.
   - *Impact*: `is_valid = False` during warm-up.
2. **Data-Quality NaN**:
   - *Cause*: Corrupt market data, non-positive price, parsing failure, missing candle in lookback window, window crossing a registered gap, or missing/incomplete aligned HTF observation.
   - *Flag*: `has_data_gap = True` or `data_quality_nan_count > 0`.
   - *Impact*: Invalidates the row (`is_valid = False`).
3. **Domain-Defined NaN**:
   - *Cause*: Mathematically defined edge case where an indicator's domain is undefined on valid market data (e.g. zero-volume liquidity metrics like `liq_taker_buy_ratio` when $V[t] = 0$, or materially negative $GK$ variance).
   - *Flag*: `domain_nan_feature_count: SMALLINT`.
   - *Impact*: **Does NOT invalidate the row**. If a bar is complete and has zero data gaps, the market data is valid (`is_valid = True`), even if liquidity features evaluate to domain-defined NaNs.

**Row Validity Contract**:
$$\mathbf{is\_valid} = (\mathbf{is\_warmup} == \text{False}) \;\land\; (\mathbf{has\_data\_gap} == \text{False}) \;\land\; (\mathbf{data\_quality\_nan\_count} == 0)$$

> [!IMPORTANT]
> **Decoupling of History Requirement (`is_warmup`) and Row Validity (`is_valid`)**:
> - `is_warmup` tracks strictly whether the maximum registry-derived history requirement (311 primary 5m bars) has elapsed.
> - `is_valid` verifies that data is usable: post-warm-up, gap-free, zero data-quality NaNs, and all required observations (including aligned HTF bars) are present. A row at index $\ge 311$ has `is_warmup = False`, but may still have `is_valid = False` if an aligned HTF observation is missing or incomplete.

- **Downstream Query Standard**:
  Strategy discovery queries valid post-warm-up rows via:
  ```sql
  SELECT * FROM features WHERE is_warmup = FALSE AND is_valid = TRUE;
  ```
  If consumers specifically require non-null liquidity features:
  ```sql
  SELECT * FROM features WHERE is_warmup = FALSE AND is_valid = TRUE AND domain_nan_feature_count = 0;
  ```

---

## 7. Architecture and FeatureRegistry

### 7.1 Typed Multi-Column Registry Architecture

The `FeatureRegistry` is the sole authoritative source for feature definitions, column typing, warm-up derivation, and schema generation.

```python
@dataclass(frozen=True)
class ColumnSpec:
    """Explicitly typed column definition emitted by a feature."""
    name: str
    duckdb_type: str        # 'DOUBLE', 'BOOLEAN', 'TIMESTAMPTZ', 'SMALLINT', 'VARCHAR'
    nullable: bool = False  # True ONLY for event attributes (pivot timestamp & age)
    description: str = ""

@dataclass(frozen=True)
class FeatureDefinition:
    """Registry entry owning metadata and typed column specifications."""
    name: str
    family: str
    calculator: str
    parameters: dict
    required_history_bars: int      # Derived automatically by FeatureRegistry
    columns: tuple[ColumnSpec, ...] # One or more typed output columns
    temporal_semantics: str         # 'point_in_time', 'confirmation_lag_s'
    mtf_timeframe: str | None       # '1m', '15m', '1h', or None
    estimator_type: str             # 'exact', 'wilder_smoothed', 'rs_single_window_proxy'
    interpretation: str             # 'standard', 'research_feature_only'
    session_definition_version: str | None
    version: str = "2.0.0"
```

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
- `is_warmup`: `BOOLEAN` (True if row index $< 311$, indicating row is within the maximum registry-derived history requirement)
- `has_data_gap`: `BOOLEAN` (True if row window crosses a registered gap)
- `is_valid`: `BOOLEAN` (True if post-warm-up, gap-free, zero data-quality NaNs, and all required aligned HTF observations are complete and available)
- `nan_feature_count`: `SMALLINT` (Total count of NaNs across all non-nullable numeric features)
- `domain_nan_feature_count`: `SMALLINT` (Count of NaNs specifically caused by mathematical domain limits)
- `input_dataset_version`: `VARCHAR` (`"v1.1.0"`)
- `feature_set_version`: `VARCHAR` (`"v2.0.0"`)
- `session_definition_version`: `VARCHAR` (`"1.0.0"`)

**Feature Columns**:
- Typed dynamically by registry: `DOUBLE` for continuous metrics, `BOOLEAN` for pivot flags, `TIMESTAMPTZ` (nullable) for pivot timestamps, `SMALLINT` (nullable) for pivot age.

---

## 9. Comprehensive Testing Plan

### 9.1 Mathematical Correctness Tests (`tests/unit/features/`)
- `test_required_history_bars_convention`: programmatic check that every registered feature emits non-NaN at index `required_history_bars - 1` and NaN at prior indices.
- `test_macd_natural_composition`: verify EMA-12 continues recursively without re-seeding; verify MACD histogram first valid at bar index 33 (34 bars).
- `test_rsi_boundary_zero_loss_is_100`: monotonically increasing prices produce `RSI = 100.0` exactly.
- `test_rsi_boundary_zero_gain_is_0`: monotonically decreasing prices produce `RSI = 0.0` exactly.
- `test_rsi_boundary_flat_price_is_50`: zero price change across window produces `RSI = 50.0` exactly.
- `test_atr_exact_boundary`: verify ATR calculation produces exact values without epsilon skew; verify `vol_atr_pct` handles non-positive close with NaN.
- `test_garman_klass_roundoff_guard`: verify $|\text{raw\_variance}| \le 10^{-12}$ rounds cleanly to $0.0$.
- `test_garman_klass_materially_negative_domain`: verify $\text{raw\_variance} < -10^{-12}$ outputs `NaN` and increments `domain_nan_feature_count` without failing `is_valid`.
- `test_zero_volume_liquidity_domain_nans`: verify zero-volume candle produces `NaN` for `liq_taker_buy_ratio`, `liq_avg_trade_size`, `liq_delta_proxy`, etc., and increments `domain_nan_feature_count` while leaving `is_valid = True`.
- `test_zscore_zero_variance_is_zero`: constant close series yields Z-score = $0.0$.
- `test_hurst_proxy_known_answer`: verify frozen R/S proxy against the Section 3.6.3 reference test vector ($R/S \approx 1.7848266192003244 \implies H = \mathbf{0.278594645149448}$ / exact double `0.2785946451494484`) within $10^{-12}$ numerical tolerance.
- `test_hurst_proxy_constant_boundary`: verify flat return series ($S == 0.0$ or $R == 0.0$) strictly yields the defined $0.5$ boundary value.
- `test_pivot_typed_emission`: verify confirmation at $t = k + s$, verifying emitted `BOOLEAN`, `TIMESTAMPTZ`, and `SMALLINT` values.

### 9.2 Validity & Decoupling Tests
- `test_is_warmup_boundary`: verify rows $0 \dots 310$ have `is_warmup = True`, row $311$ has `is_warmup = False` based strictly on the 311-bar maximum registry history requirement.
- `test_mtf_missing_htf_availability`: verify that for row index $\ge 311$, if an aligned HTF candle is missing or incomplete, `is_warmup` evaluates to `False` while `is_valid` evaluates to `False` (with `data_quality_nan_count > 0`), verifying that the history requirement is not an unconditional guarantee of MTF validity.
- `test_nan_feature_count_excludes_nullable_pivots`: verify normal non-pivot row with `ms_pivot_high_timestamp = NULL` has `nan_feature_count = 0`.
- `test_domain_nan_does_not_invalidate_row`: verify complete bar with zero volume has `domain_nan_feature_count > 0` but `is_valid = True`.
- `test_is_valid_warmup_separation`: verify post-warm-up row with synthetic gap has `is_warmup = False`, `has_data_gap = True`, and `is_valid = False`.

### 9.3 Temporal Invariance & MTF Alignment Tests
- `test_no_lookahead_all_features`: verify truncating series does not alter prior bar feature values.
- `test_1m_constituent_availability`: verify all five 1m constituent bars are available when 5m bar completes at $t+300\text{s}$.
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

## 11. Acceptance Criteria (Refinements C2, C3)

| # | Criterion | Verification |
|---|---|---|
| AC-1 | All unit and registry consistency tests pass | `pytest tests/unit/features/ -v` (0 failures) |
| AC-2 | All integration tests pass | `pytest tests/integration/features/ -v` (0 failures) |
| AC-3 | Feature row count matches 5m candle count exactly | `SELECT COUNT(*)` = 315,648 |
| AC-4 | Zero `inf` or `-inf` across all columns | DuckDB scan across Parquet partitions |
| AC-5 | **Registry history vs. row validity decoupling**: Maximum registry-derived history requirement is 311 primary 5m bars. Rows $0 \dots 310$ have `is_warmup = True`; rows $\ge 311$ have `is_warmup = False`. Reaching row $\ge 311$ satisfies history but does not guarantee that every MTF feature becomes valid at that exact row; missing/incomplete aligned HTF observations independently make features unavailable and evaluate `is_valid = False`. | DuckDB verification query & test harness |
| AC-6 | **Zero unexplained invalid rows**: all post-warm-up rows are valid (`is_valid = True`) except rows explicitly affected by registered input gaps or incomplete source observations | Manifest coverage verification & DuckDB diagnostic audit query |
| AC-7a | **Same-runtime determinism**: identical serialized Parquet output (matching SHA-256) across repeated runs on same runtime and writer configuration | Byte-level SHA-256 comparison |
| AC-7b | **Cross-runtime determinism**: identical row ordering, column names, column order, and types; floating-point numerical equivalence within tolerance ($10^{-12}$ general scalar, $10^{-10}$ recursive accumulators) | Cross-platform test harness comparison |
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
> **GATE ENFORCEMENT**: This is a design-only document (Revision 5.1). Zero implementation has been executed. No feature code has been written. No data has been downloaded, modified, or processed. No commits or pushes have been made. The working tree is unchanged. Awaiting formal review and explicit approval from Nishant before Phase 2 implementation begins.
