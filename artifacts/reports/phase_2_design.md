# Phase 2 Design Specification: Market Feature Engine

**Project**: XAU Quantitative Strategy Discovery and Decision Platform
**Phase**: 2 (Market Feature Engine)
**Status**: DESIGN DOCUMENT — Awaiting User Review and Approval — Zero Implementation Done
**Date**: 2026-09-19
**Primary Target Dataset**: `BTCUSDT` Binance Spot — Phase 1C canonical dataset (`v1.1.0`)
**Research Clock**: 5-minute bars (primary); 1m, 15m, 1h as context timeframes
**Execution Boundary**: Feature Engineering Only — Zero Strategies, Zero Signals, Zero ML, Zero Backtesting, Zero UI

---

## 1. Objective and Scope

### 1.1 Mission Statement

Phase 2 builds a **deterministic, temporally correct, research/live-parity market feature layer** on top of the validated Phase 1C BTCUSDT Spot dataset. Its sole output is a versioned, schema-validated feature dataset that downstream strategy discovery can consume without re-computing or re-validating features.

The feature engine must be:
- **Deterministic**: identical inputs produce identical outputs, always, on any machine
- **Temporally correct**: zero look-ahead leak; features at bar `t` use only data available at the close of bar `t`
- **Research/live-parity**: the exact same computation path runs on historical completed bars and on live completed bars without divergence
- **Instrument/provider-agnostic**: architecture accommodates XAUUSD and any future instrument by configuration, not by code modification

### 1.2 In-Scope

| Item | Detail |
|---|---|
| **Primary research clock** | 5m bars (granularity at which features are indexed) |
| **Context timeframes** | 1m (microstructure), 15m (intraday trend), 1h (session cycle) |
| **Input dataset** | Phase 1C BTCUSDT v1.1.0 canonical partitioned Parquet dataset |
| **Output** | Versioned feature Parquet dataset under `data/features/` |
| **Feature families** | Price/Returns, Momentum, Volatility, Volume/Liquidity, Market Structure, Mean-Reversion, Session/Time, Multi-Timeframe |
| **Quality controls** | NaN/inf handling, missing-data propagation, duplicate detection, history guards, numerical stability, validity metadata per row |

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
> - No 4h or 1d features in the initial feature set (may be added in Phase 2.x per OQ-5)

---

## 2. Feature Taxonomy

### 2.1 Distinction: Raw Observations vs. Derived Features

| Category | Definition |
|---|---|
| **Raw observation** | A field sourced directly from a `CanonicalCandle` without computation: `open`, `high`, `low`, `close`, `volume`, `quote_volume`, `trade_count`, `taker_buy_base_volume`, `taker_buy_quote_volume`, `is_complete` |
| **Derived feature** | Any computation applied to raw observations across one or more bars, e.g. log-returns, ATR, VWAP deviation |

Raw observations are **not** stored in the feature dataset. They remain in the canonical candle dataset. The feature dataset contains only derived features plus the composite primary key (`timestamp_utc`, `venue`, `instrument`, `timeframe`).

### 2.2 Feature Families

| # | Family | Prefix | Description |
|---|---|---|---|
| 1 | **Price and Returns** | `ret_` / `price_` | Log-returns, bar-body, wick metrics |
| 2 | **Momentum** | `mom_` | Rate-of-change, slope, signed momentum |
| 3 | **Volatility** | `vol_` | ATR, realized volatility, Garman-Klass |
| 4 | **Volume and Liquidity** | `liq_` | Taker aggression ratio, average trade size, normalized volume |
| 5 | **Market Structure** | `ms_` | Rolling high/low, price position, pivot detection |
| 6 | **Mean-Reversion** | `mr_` | Z-score of close, Hurst proxy, autocorrelation |
| 7 | **Session and Time** | `time_` | UTC hour, day-of-week, session encoding, bars-since-open |
| 8 | **Multi-Timeframe** | `mtf_` | 1m, 15m, 1h features aligned to the 5m bar timestamp |

---

## 3. Mathematical Definitions

All definitions below use **completed-bar semantics** (see Section 4). The 5m bar at timestamp `t` covers `[t, t + 300s)` and is the atomic unit of the feature dataset.

**Notation**:
- `C[t]`, `O[t]`, `H[t]`, `L[t]` — close, open, high, low of the 5m bar at timestamp `t`
- `V[t]` — base asset volume; `QV[t]` — quote volume; `N[t]` — trade count
- `TB[t]` — taker buy base volume; `TQ[t]` — taker buy quote volume
- `n` — lookback window in completed 5m bars (inclusive of bar `t` unless stated)
- All logarithms are natural log (`ln`)
- `eps = 1e-8` throughout (numerical stability guard for all divisions)

---

### 3.1 Price and Returns Family (`ret_`, `price_`)

**3.1.1 Log-Return (Close-to-Close)**
```
ret_log_cc_{n}  =  ln(C[t]) - ln(C[t-n])
```
- `n in {1, 3, 6, 12, 24, 48, 96}` (5m, 15m, 30m, 1h, 2h, 4h, 8h wall-clock)
- Expected range: approx (-0.10, +0.10); tail events may exceed +/-0.20
- Warm-up: `n` bars

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

### 3.2 Momentum Family (`mom_`)

**3.2.1 Rate of Change (ROC)**
```
mom_roc_{n}  =  (C[t] - C[t-n]) / C[t-n]
```
- `n in {6, 12, 24, 48}` (30m, 1h, 2h, 4h). Units: dimensionless. Warm-up: `n` bars.

**3.2.2 Smoothed Close Slope (OLS)**
```
y[k] = ln(C[t-n+1+k])  for k = 0..n-1
x[k] = k
mom_slope_{n}  =  OLS_slope(x, y) * n / (|ln(C[t])| + eps)
```
- `n in {12, 24, 48}` (1h, 2h, 4h). Warm-up: `n` bars.

**3.2.3 SMA Deviation**
```
SMA_n  =  mean(C[t-n+1], ..., C[t])
mom_sma_dev_{n}  =  (C[t] - SMA_n) / SMA_n
```
- `n in {12, 24, 48, 96}`. Warm-up: `n` bars.

**3.2.4 EMA Deviation**
```
alpha  =  2 / (n + 1)
EMA[t] =  alpha * C[t] + (1 - alpha) * EMA[t-1];  EMA[t0] = C[t0]
mom_ema_dev_{n}  =  (C[t] - EMA[t]) / EMA[t]
```
- `n in {12, 26, 50}`. Warm-up: `3*n` bars (EMA convergence guard; see Section 4.4).

**3.2.5 MACD Histogram (Normalized)**
```
MACD_line    =  EMA(C, 26) - EMA(C, 12)
MACD_signal  =  EMA(MACD_line, 9)
mom_macd_hist  =  (MACD_line - MACD_signal) / (C[t] + eps)
```
- Warm-up: `3*26 + 9 = 87` bars.

**3.2.6 RSI (Wilder Smoothed)**
```
delta[i] = C[i] - C[i-1]
U[i] = max(delta[i], 0);  D[i] = max(-delta[i], 0)
AvgU[n] = mean(U[1..n]);  AvgD[n] = mean(D[1..n])   (seed)
AvgU[t] = ((n-1)*AvgU[t-1] + U[t]) / n               (update)
AvgD[t] = ((n-1)*AvgD[t-1] + D[t]) / n
RS[t] = AvgU[t] / (AvgD[t] + eps)
mom_rsi_{n}  =  100 - 100 / (1 + RS[t])
```
- `n in {14, 28}`. Range: [0, 100]. Warm-up: `n + 1` bars.

---

### 3.3 Volatility Family (`vol_`)

**3.3.1 Average True Range (ATR)**
```
TR[t] = max(H[t]-L[t], |H[t]-C[t-1]|, |L[t]-C[t-1]|)
ATR[n] = mean(TR[1..n])   (seed)
ATR[t] = ((n-1)*ATR[t-1] + TR[t]) / n   (update)
vol_atr_{n}      =  ATR[t]          (USD)
vol_atr_pct_{n}  =  ATR[t] / C[t]   (dimensionless)
```
- `n in {14, 28}`. Warm-up: `n + 1` bars.

**3.3.2 Realized Volatility (CC Log-Returns)**
```
r[i] = ln(C[i]) - ln(C[i-1])
vol_realized_{n}  =  std(r[t-n+1..t], ddof=1)
```
- `n in {12, 24, 48, 96}`. Warm-up: `n + 1` bars.

**3.3.3 Garman-Klass Volatility**
```
GK[t] = 0.5*(ln(H[t]/L[t]))^2 - (2*ln(2)-1)*(ln(C[t]/O[t]))^2
vol_gk_realized_{n}  =  sqrt(mean(GK[t-n+1..t]))
```
- `n in {12, 24}`. Units: dimensionless. Warm-up: `n` bars.

**3.3.4 Volatility Z-Score**
```
vol_zscore_12_96  =  (vol_realized_12 - mean(vol_realized_12, last 96 bars))
                     / (std(vol_realized_12, last 96 bars) + eps)
```
- Warm-up: `12 + 1 + 96 = 109` bars.

---

### 3.4 Volume and Liquidity Family (`liq_`)

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
VWAP_n  =  sum(QV[t-n+1..t]) / (sum(V[t-n+1..t]) + eps)
liq_vwap_dev_{n}  =  (C[t] - VWAP_n) / VWAP_n
```
- `n in {12, 48}`. Warm-up: `n` bars.

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
liq_delta_proxy      =  CD[t] / (V[t] + eps)
liq_cum_delta_{n}    =  sum(CD[t-n+1..t]) / (sum(V[t-n+1..t]) + eps)
```
- `n in {12, 48}` for rolling. Range: [-1, 1]. Warm-up: `n` / 0 respectively.

---

### 3.5 Market Structure Family (`ms_`)

> [!NOTE]
> All swing and pivot computations use **completed bars only**.

**3.5.1 Rolling N-Bar High and Low**
```
ms_high_{n}  =  max(H[t-n+1..t])
ms_low_{n}   =  min(L[t-n+1..t])
```
- `n in {12, 24, 48, 96}`. Units: USD. Warm-up: `n` bars.

**3.5.2 Price Position within N-Bar Range**
```
ms_price_position_{n}  =  (C[t] - ms_low_{n}) / (ms_high_{n} - ms_low_{n} + eps)
```
- Range: [0, 1]. Warm-up: `n` bars.

**3.5.3 Bars Since N-Bar High/Low**
```
ms_bars_since_high_{n}  =  t - argmax_{i in [t-n+1,t]} H[i]   (ties: most recent)
ms_bars_since_low_{n}   =  t - argmin_{i in [t-n+1,t]} L[i]
```
- `n in {24, 96}`. Range: [0, n-1]. Warm-up: `n` bars.

**3.5.4 Pivot High/Low Detection (Strict, with Lag)**

A bar at position `k` is a **pivot high of strength s** if:
```
H[k] > H[k-j]  for all j in {1..s}   (left side confirmed)
H[k] > H[k+j]  for all j in {1..s}   (right side confirmed, all bars complete)
```

```
ms_is_pivot_high_{s}  =  1 if the pivot condition holds, else 0
ms_is_pivot_low_{s}   =  analogous
```

- `s in {3, 5}`.
- **Critical temporal constraint**: pivot at bar `k` is only deterministic at current bar `t >= k + s`. The feature is stored at the pivot bar's timestamp with confirmed lag of `s` bars (see OQ-4 for storage convention decision).
- Warm-up: `2*s` bars.

**3.5.5 Consecutive Bar Direction**
```
ms_consec_up_{n}    =  length of longest consecutive run of C[i] > C[i-1] ending at bar t, within n bars
ms_consec_down_{n}  =  analogous
```
- `n = 5` (25m). Range: [0, 5]. Warm-up: `n + 1` bars.

---

### 3.6 Mean-Reversion Family (`mr_`)

**3.6.1 Z-Score of Close**
```
mu_n  =  mean(C[t-n+1..t])
sg_n  =  std(C[t-n+1..t], ddof=1)
mr_zscore_{n}  =  (C[t] - mu_n) / (sg_n + eps)
```
- `n in {24, 48, 96}`. Warm-up: `n` bars.

**3.6.2 Distance from Rolling Mean**
```
mr_mean_dev_{n}  =  (C[t] - mu_n) / mu_n
```
- `n in {12, 48}`. Warm-up: `n` bars.

**3.6.3 Hurst Exponent Proxy (RS Method)**
```
X[i]    =  ln(C[t-n+1+i]) - ln(C[t-n])   for i = 0..n-1
mean_X  =  mean(X)
Y[i]    =  X[i] - i * mean_X / (n-1)     (demeaned cumulative sum)
R       =  max(Y) - min(Y)
S       =  std(ln-returns over n bars, ddof=1)
RS      =  R / (S + eps)
mr_hurst_proxy_{n}  =  ln(RS) / ln(n),  clamped to [0, 1]
```
- `n in {48, 96}`. Interpretation: <0.5 = mean-reverting, ~0.5 = random walk, >0.5 = trending.
- This is a single-window RS proxy, not a full DFA estimate. The feature registry must reflect this.
- Warm-up: `n + 1` bars.

**3.6.4 Lag-1 Autocorrelation of Log-Returns**
```
r[i]  =  ln(C[i]) - ln(C[i-1])
mr_autocorr_lag1_{n}  =  Pearson(r[t-n+1..t], r[t-n..t-1])
```
- `n in {24, 96}`. Range: [-1, 1]. Warm-up: `n + 1` bars.

---

### 3.7 Session and Time Features (`time_`)

All time features are derived purely from the bar's UTC timestamp. **Warm-up: 0 for all.**

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

**3.7.5 Trading Session Flag (Bitfield)**:

| Session | UTC Hours | Bit |
|---|---|---|
| Asian | 00:00-08:00 | 1 |
| London | 07:00-16:00 | 2 |
| New York | 13:00-22:00 | 4 |

`time_session_flags = asian_bit OR london_bit OR ny_bit`. Range: {1..7}. Fixed UTC convention.

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

### 3.8 Multi-Timeframe Features (`mtf_`)

Features from 1m, 15m, and 1h timeframes are aligned to the 5m bar's timestamp using the **last-completed-bar-at-or-before-t** rule (see Section 4.3).

**3.8.1 15m Features** (aligned 15m bar: `t_15 = floor(t, 15m)`)

| Feature | Definition | 15m Lookback |
|---|---|---|
| `mtf_15m_ret_log_cc_4` | `ln(C_15[t_15]) - ln(C_15[t_15 - 4*15m])` | 4 bars = 1h |
| `mtf_15m_ret_log_cc_16` | 16-bar 15m log-return | 16 bars = 4h |
| `mtf_15m_mom_rsi_14` | Wilder RSI-14 on 15m closes | 15 bars |
| `mtf_15m_vol_atr_pct_14` | Wilder ATR-14 % on 15m OHLC | 15 bars |
| `mtf_15m_price_position_16` | Close position in 16-bar 15m range | 16 bars |
| `mtf_15m_liq_taker_buy_ratio` | Single 15m bar taker ratio | 0 |
| `mtf_15m_liq_vol_ratio_16` | Volume ratio over 16 15m bars | 16 bars |

**3.8.2 1h Features** (aligned 1h bar: `t_1h = floor(t, 1h)`)

| Feature | Definition | 1h Lookback |
|---|---|---|
| `mtf_1h_ret_log_cc_4` | 4-bar 1h log-return (4h) | 4 bars |
| `mtf_1h_ret_log_cc_24` | 24-bar 1h log-return (24h) | 24 bars |
| `mtf_1h_mom_rsi_14` | Wilder RSI-14 on 1h closes | 15 bars |
| `mtf_1h_vol_realized_24` | 24-bar realized vol on 1h | 25 bars |
| `mtf_1h_price_position_24` | Close position in 24-bar 1h range | 24 bars |
| `mtf_1h_mr_zscore_24` | Z-score of 1h close over 24 bars | 24 bars |
| `mtf_1h_liq_taker_buy_ratio` | Single 1h bar taker ratio | 0 |

**3.8.3 1m Microstructure Context** (5 constituent 1m bars of the 5m bar; warm-up: 0)

| Feature | Definition |
|---|---|
| `mtf_1m_vol_dispersion` | `std(V_1m[0:5]) / (mean(V_1m[0:5]) + eps)` — intra-5m volume CV |
| `mtf_1m_taker_trend` | OLS slope of `TB_1m[i]/(V_1m[i]+eps)` over 5 bars, normalized |
| `mtf_1m_return_skew` | `(r_last - r_first) / (sum(|r_i|) + eps)` — momentum concentration |

---

## 4. Temporal Correctness

### 4.1 No Look-Ahead Principle

A feature is **look-ahead-free** if and only if its computation at bar `t` uses exclusively:
```
I(t) = { C[s], O[s], H[s], L[s], V[s], QV[s], N[s], TB[s], TQ[s]
         : s <= t  AND  is_complete(s) = True }
```
No feature may reference bars `s > t` or any bar where `is_complete = False`.

### 4.2 Completed-Bar Semantics

A 5m bar at timestamp `t` is **complete** when:
1. Wall-clock time has passed `t + 300s`, AND
2. All 5 constituent 1m bars `{t, t+60s, t+120s, t+180s, t+240s}` have `is_complete = True`

**Historical (batch)**: all Phase 1C bars are `is_complete = True` by construction.
**Live (future phase)**: the engine must never emit a feature row before condition 1 and 2 hold.

### 4.3 Multi-Timeframe Alignment Rule

For a 5m bar at `t`, the aligned bar for timeframe TF is:
```
t_TF  =  max { s : s is a valid TF boundary, s <= t, is_complete(s, TF) = True }
```
In the batch case (all bars complete), this simplifies to `floor(t, TF)`. Since `floor(t, TF) <= t` always, no look-ahead is possible.

### 4.4 EMA Initialization and Warm-Up Inventory

The implementation returns `NaN` for EMA-based features until `3*n` completed bars have been processed. The factor-of-3 ensures the EMA seed contributes less than `(1-alpha)^(3n) < 0.05` of its initial weight.

**Warm-up inventory** (5m bars required before first valid value):

| Feature | Warm-up |
|---|---|
| `ret_log_cc_1` | 1 |
| `ret_log_cc_96` | 96 |
| `mom_roc_48` | 48 |
| `mom_slope_48` | 48 |
| `mom_sma_dev_96` | 96 |
| `mom_ema_dev_50` | 150 (3*50) |
| `mom_macd_hist` | 87 (3*26 + 9) |
| `mom_rsi_28` | 29 |
| `vol_atr_pct_28` | 29 |
| `vol_realized_96` | 97 |
| `vol_gk_realized_24` | 24 |
| `vol_zscore_12_96` | 109 |
| `liq_vwap_dev_48` | 48 |
| `ms_high_96` | 96 |
| `ms_is_pivot_high_5` | 10 |
| `mr_zscore_96` | 96 |
| `mr_hurst_proxy_96` | 97 |
| `mr_autocorr_lag1_96` | 97 |
| `mtf_15m_*` (max 16 bars) | 16*3 = 48 5m bars |
| `mtf_1h_*` (max 24 bars) | 24*12 = **288** 5m bars |

**Maximum warm-up: 288 5m bars = 24 hours.** The first 288 feature rows will have NaN for at least one column.

### 4.5 Missing Candle Behavior

When a gap exists in the Phase 1C dataset (recorded in the Gap Registry):

1. **Zero fabrication**: do not forward-fill or interpolate
2. **NaN propagate**: features whose window crosses a gap produce NaN
3. **Shrinking-authentic-window**: rolling accumulators count only present bars; a gap extends the window further back to find `n` real bars
4. **Row validity**: `is_valid = False` for any row where a window includes a gap bar
5. **No row for absent bar**: if a 5m timestamp is entirely missing from the Parquet, no feature row is emitted

### 4.6 Duplicate Timestamp Handling

Input validation raises `FeatureInputError` on duplicate timestamps before any computation. No feature row is produced; the event is logged as a critical data quality anomaly.

---

## 5. Research/Live Parity

### 5.1 Parity Requirement

The same `FeatureEngine` class and identical formulas must operate in:
- **Batch mode** (historical): sorted arrays of completed `CanonicalCandle` objects
- **Incremental mode** (future live): one newly-completed bar at a time, updating rolling state, emitting one feature row

No separate "research-only formula" that differs from the live formula is permitted.

### 5.2 Input Contract

```python
@dataclass
class FeatureEngineInput:
    candles_primary: list[CanonicalCandle]         # 5m bars, sorted ASC, all is_complete=True
    context_candles: dict[str, list[CanonicalCandle]]  # {"1m": [...], "15m": [...], "1h": [...]}
    venue: str
    instrument: str
    primary_timeframe: str                          # "5m"
    input_dataset_version: str                      # "v1.1.0"
```

Preconditions enforced by `FeatureInputValidator` before any computation:
- All candles have `is_complete = True`
- Strict chronological sort (no ties)
- Zero duplicate timestamps
- Consistent `(venue, instrument, timeframe)` across the list

### 5.3 State Model for Incremental Operation

The engine maintains serializable per-instrument state:
- Bounded deque of recent `max_warm_up` completed 5m bars
- Current EMA values keyed by `(feature_name, n)`
- Current Wilder ATR values keyed by `n`
- Current Wilder RSI AvgU/AvgD keyed by `n`

State is serializable to disk so a live engine can resume after restart without reprocessing history.

---

## 6. Feature Quality Controls

### 6.1 NaN and Infinity Handling

| Condition | Action |
|---|---|
| Fewer bars available than warm-up requires | Return `float('nan')` |
| Denominator evaluates to 0 | Add `eps = 1e-8`; never return `inf` |
| Rolling std evaluates to 0 | Return 0.0 for Z-score; do not return NaN |
| Any input price is NaN or non-finite | Propagate NaN; do not crash |
| Result is `inf` or `-inf` | Replace with NaN; log as data anomaly |

**Invariant**: zero `inf` or `-inf` in any output Parquet column.

### 6.2 Missing-Data Propagation Rules

```
RULE 1: Any candle in a rolling window has is_complete=False or is a gap:
    All features whose window spans that bar -> NaN

RULE 2: MTF features inherit from their aligned bar:
    Aligned 15m bar has is_complete=False -> all mtf_15m_* = NaN

RULE 3: EMA state at a gap bar:
    EMA state NOT updated for the gap bar
    Feature for gap bar = NaN
    EMA resumes on next present bar, carrying forward last valid state
```

### 6.3 Feature Validity Metadata Columns

| Column | Type | Description |
|---|---|---|
| `is_valid` | BOOLEAN | True if all features are non-NaN and no anomaly |
| `nan_feature_count` | SMALLINT | Count of NaN-valued feature columns in this row |
| `input_dataset_version` | VARCHAR | e.g. `"v1.1.0"` |
| `feature_set_version` | VARCHAR | e.g. `"v2.0.0"` |

### 6.4 Numerical Stability

- Rolling variance/std use **Welford's online algorithm** throughout (avoids catastrophic cancellation)
- Log-price differences preferred over arithmetic differences for returns
- Z-scores clamped to `[-10, +10]`; clamping logged as a data anomaly but not stored in Parquet

### 6.5 Deterministic Reproducibility

1. Identical inputs -> bit-identical float64 outputs across runs and machines
2. No random seeds, process-dependent state, or wall-clock-dependent values
3. `float` (IEEE 754 double) is the exclusive numeric type for all computations
4. DuckDB `DOUBLE` is the exclusive storage type for all feature columns

---

## 7. Architecture

### 7.1 Module Structure

```
src/xau_quant/
├── data/                            # Phase 1C — unchanged
│   ├── models.py                    # CanonicalCandle (consumed by features layer)
│   ├── storage.py                   # DuckDB Parquet I/O (pattern reused)
│   └── ...
└── features/                        # NEW — Phase 2
    ├── __init__.py
    ├── models.py                    # FeatureRow, FeatureDatasetManifest (Pydantic)
    ├── registry.py                  # FeatureRegistry: declarative feature catalog
    ├── engine.py                    # FeatureEngine: orchestration entry point
    ├── storage.py                   # FeatureParquetStorage: read/write
    ├── validators.py                # FeatureInputValidator, FeatureOutputValidator
    └── calculators/
        ├── __init__.py
        ├── returns.py               # Price and Returns family
        ├── momentum.py              # Momentum family
        ├── volatility.py            # Volatility family
        ├── liquidity.py             # Volume and Liquidity family
        ├── structure.py             # Market Structure family
        ├── meanreversion.py         # Mean-Reversion family
        ├── time_features.py         # Session and Time family
        └── multitimeframe.py        # MTF alignment and computation

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
│   ├── test_feature_engine.py
│   └── test_feature_storage.py
└── integration/features/
    └── test_feature_pipeline_integration.py
```

### 7.2 Component Responsibilities

| Component | Responsibility | Does NOT |
|---|---|---|
| `calculators/*.py` | Pure-function formula implementations | Access disk, manage state, validate inputs |
| `registry.py` | Declares every feature: name, family, formula ref, warm-up, units, range | Compute |
| `engine.py` | Orchestrates: validate -> compute -> assemble rows -> validate output | Write disk, manage manifests |
| `storage.py` | Read/write feature Parquet; manage partitioning | Compute |
| `validators.py` | Validate input contracts and output rows | Compute |
| `models.py` | Pydantic schemas for `FeatureRow`, `FeatureDatasetManifest` | Business logic |

### 7.3 Calculator Interface Contract

```python
def compute_ret_log_cc(
    closes: list[float],
    *,
    n: int,
    epsilon: float = 1e-8,
) -> list[float | None]:
    """
    Returns list of same length as closes.
    Leading indices [0..n-1] are None (insufficient history).
    None is converted to float('nan') in the engine assembly step.
    Pure function: no side effects, no I/O, no global state.
    """
```

All calculator functions follow this pattern: pure, same-length output, `None` for warm-up positions.

### 7.4 Infrastructure Reuse Decision

**DuckDB reused** for feature storage. The vectorized TSV bulk-write pipeline from Phase 1C (`ParquetCandleStorage`) is the direct template for `FeatureParquetStorage`.

**No new Python dependencies.** Feature engine uses exclusively:
- Python stdlib: `math`, `statistics`, `collections.deque`, `datetime`
- `pydantic >= 2.7.0` (already installed)
- `duckdb >= 1.0.0` (already installed)

For rolling windows with `n > 50`, hand-rolled Welford online algorithms replace `statistics.stdev` (which requires full window materialization). See Section 10 and OQ-1 for escalation path.

> [!IMPORTANT]
> **Dependency Decision**: NumPy and pandas are explicitly excluded from Phase 2 — same principle as the Phase 1C PyArrow exclusion. If profiling shows pure Python cannot meet the 140s benchmark, the escalation path is DuckDB SQL window functions (no new dependencies). See OQ-1.

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
                        ├── year=2024/month=01/
                        │   └── btcusdt_5m_features_v2.0.0_202401.parquet
                        └── ...

data/metadata/manifests/
└── btcusdt_5m_features_v2.0.0_manifest.json
```

Identical `year=YYYY/month=MM` convention as Phase 1C. The `feature_set=v2.0.0` partition dimension allows multiple versions to coexist without collision.

### 8.2 Feature Row Parquet Schema

**Key + metadata columns (8)**:

| Column | DuckDB Type | Description |
|---|---|---|
| `timestamp_utc` | TIMESTAMPTZ | 5m bar open timestamp (primary key) |
| `venue` | VARCHAR | e.g. `"binance"` |
| `instrument` | VARCHAR | e.g. `"BTCUSDT"` |
| `timeframe` | VARCHAR | `"5m"` |
| `is_valid` | BOOLEAN | True if all features non-NaN and no anomaly |
| `nan_feature_count` | SMALLINT | Count of NaN feature values |
| `input_dataset_version` | VARCHAR | `"v1.1.0"` |
| `feature_set_version` | VARCHAR | `"v2.0.0"` |

**Feature columns (~82, all DOUBLE)**:
- `ret_log_cc_1/3/6/12/24/48/96`, `ret_log_oc`, `price_body_ratio`, `price_upper_wick_ratio`, `price_lower_wick_ratio`, `price_midpoint`
- `mom_roc_6/12/24/48`, `mom_slope_12/24/48`, `mom_sma_dev_12/24/48/96`, `mom_ema_dev_12/26/50`, `mom_macd_hist`, `mom_rsi_14/28`
- `vol_atr_14/28`, `vol_atr_pct_14/28`, `vol_realized_12/24/48/96`, `vol_gk_realized_12/24`, `vol_zscore_12_96`
- `liq_taker_buy_ratio`, `liq_avg_trade_size`, `liq_dollar_volume`, `liq_vwap_dev_12/48`, `liq_vol_ratio_12/24/48`, `liq_delta_proxy`, `liq_cum_delta_12/48`
- `ms_high_12/24/48/96`, `ms_low_12/24/48/96`, `ms_price_position_12/24/48/96`, `ms_bars_since_high_24/96`, `ms_bars_since_low_24/96`, `ms_is_pivot_high_3/5`, `ms_is_pivot_low_3/5`, `ms_consec_up_5`, `ms_consec_down_5`
- `mr_zscore_24/48/96`, `mr_mean_dev_12/48`, `mr_hurst_proxy_48/96`, `mr_autocorr_lag1_24/96`
- `time_hour_utc`, `time_dow`, `time_hour_sin`, `time_hour_cos`, `time_dow_sin`, `time_dow_cos`, `time_session_flags`, `time_bars_since_midnight`, `time_bars_since_week_open`
- `mtf_15m_ret_log_cc_4/16`, `mtf_15m_mom_rsi_14`, `mtf_15m_vol_atr_pct_14`, `mtf_15m_price_position_16`, `mtf_15m_liq_taker_buy_ratio`, `mtf_15m_liq_vol_ratio_16`
- `mtf_1h_ret_log_cc_4/24`, `mtf_1h_mom_rsi_14`, `mtf_1h_vol_realized_24`, `mtf_1h_price_position_24`, `mtf_1h_mr_zscore_24`, `mtf_1h_liq_taker_buy_ratio`
- `mtf_1m_vol_dispersion`, `mtf_1m_taker_trend`, `mtf_1m_return_skew`

**Total**: approximately **90 columns** (8 key/metadata + ~82 feature).

### 8.3 Feature Dataset Manifest Schema

```json
{
  "schema_version": "2.0.0",
  "feature_set_version": "v2.0.0",
  "dataset_id": "btcusdt_5m_features_v2.0.0",
  "created_at_utc": "2026-09-XX T00:00:00.000000Z",
  "input_dataset": {
    "dataset_id": "binance_spot_btcusdt_canonical_v1.1.0",
    "dataset_version": "v1.1.0",
    "root_manifest_sha256": "<sha256_of_phase_1c_root_manifest>"
  },
  "engine": {
    "module": "xau_quant.features.engine",
    "commit_hash": "<git_sha_at_computation_time>",
    "python_version": "3.12.x"
  },
  "feature_clock": {
    "primary_timeframe": "5m",
    "context_timeframes": ["1m", "15m", "1h"]
  },
  "coverage": {
    "start_utc": "2023-09-18T00:00:00Z",
    "end_utc": "2026-09-18T00:00:00Z",
    "total_5m_bars": 315648,
    "warm_up_rows": 288,
    "valid_rows": 315360,
    "invalid_rows": 0
  },
  "feature_catalog": {
    "total_features": 82,
    "families": {
      "ret": 12, "mom": 15, "vol": 11, "liq": 9,
      "ms": 16, "mr": 8, "time": 9, "mtf": 17
    }
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
                 -> Feature Parquet Partitions  (SHA-256 per partition file)
```

---

## 9. Testing

### 9.1 Unit Tests: Mathematical Correctness

Each calculator function receives tests verifying known-answer cases:

- `test_ret_log_cc_known_values`: `ln(110) - ln(100) = 0.09531` to 5 decimal places
- `test_rsi_all_up_approaches_100`: monotonically increasing -> RSI approaches 100
- `test_rsi_all_down_approaches_0`: monotonically decreasing -> RSI approaches 0
- `test_atr_constant_hl_range`: fixed H-L bars -> ATR converges to that range
- `test_garman_klass_doji`: O=H=L=C -> GK = 0.0
- `test_zscore_constant_series`: constant close -> numerator = 0
- `test_hurst_proxy_brownian_motion`: 1000-bar Brownian motion -> proxy in (0.35, 0.65)
- `test_taker_buy_ratio_bounded`: `liq_taker_buy_ratio in [0, 1]` for all valid inputs
- `test_session_flags_overlap_hours`: 14:00 UTC -> flags = 6 (London + NY)
- `test_vwap_dev_zero_when_price_equals_vwap`: synthetic case -> deviation = 0

### 9.2 Boundary and Warm-Up Tests

For every feature with warm-up `w` (parametrized over the full feature registry):
- `test_insufficient_history_is_nan`: `w-1` bars -> all outputs are NaN
- `test_exact_warmup_first_valid`: exactly `w` bars -> last output non-NaN, all preceding NaN

### 9.3 Missing-Candle Tests

Using synthetic 100-bar series with deliberate 10-bar gap at positions 40-49:
- No feature row exists for timestamps 40-49
- Features at positions 50-59 are NaN where the lookback window crosses the gap
- Features at position 70+ recover to valid (NaN-free) for features with lookback <= 20
- `is_valid = False` for all rows whose computation window crosses the gap

### 9.4 No-Lookahead Tests (Critical, Parametrized over All Features)

```python
def test_no_lookahead(feature_fn, n_param, candles_100):
    result_full  = feature_fn(candles_100, n=n_param)
    result_trunc = feature_fn(candles_100[:-1], n=n_param)
    # Second-to-last of full == last of truncated (or both NaN)
    assert result_trunc[-1] == result_full[-2]
```

**Pivot detection specific**: `ms_is_pivot_high_5` at bar `t-5` is NaN when input terminates at bar `t-4`; becomes deterministic only after bar `t-4+5` is present.

### 9.5 Multi-Timeframe Alignment Tests

- `test_mtf_15m_uses_floor_boundary`: 5m bar at `14:03 UTC` uses aligned 15m bar at `14:00 UTC`, not `14:15 UTC`
- `test_mtf_1h_uses_floor_boundary`: 5m bar at `14:55 UTC` uses 1h bar at `14:00 UTC`, not `15:00 UTC`
- `test_mtf_nan_when_htf_incomplete`: aligned bar with `is_complete=False` -> all MTF features = NaN
- `test_mtf_1m_dispersion_constant_volume`: equal 1m volumes -> `mtf_1m_vol_dispersion = 0.0`

### 9.6 Determinism Tests

```python
def test_determinism(candles_1000):
    r1 = FeatureEngine().compute(candles_1000)
    r2 = FeatureEngine().compute(candles_1000)
    assert r1 == r2   # bit-identical
```

Also run in a fresh subprocess to confirm no process-level state pollution.

### 9.7 Integration Tests Against Phase 1C Dataset

Tagged `@pytest.mark.integration`:

- `test_row_count_matches_candle_count`: 315,648 5m input bars -> 315,648 feature rows
- `test_no_inf_in_output`: DuckDB scan -> zero `inf` values across all columns
- `test_valid_row_ratio`: `valid_rows / (total - warm_up_rows) >= 0.999`
- `test_manifest_sha256_stable`: two runs -> identical `combined_parquet_sha256`
- `test_rsi_range_sanity`: all `mom_rsi_*` -> [0, 100] where non-NaN
- `test_body_ratio_range_sanity`: `price_body_ratio` -> [0, 1] where non-NaN
- `test_taker_ratio_range_sanity`: `liq_taker_buy_ratio` -> [0, 1] where non-NaN
- `test_mtf_changes_only_at_boundaries`: `mtf_15m_*` values change only at 15m boundaries

---

## 10. Performance

### 10.1 Benchmark Expectations (315,648 5m bars, developer workstation)

| Stage | Target | Risk |
|---|---|---|
| Load 5m candles from Parquet (DuckDB) | < 5s | Low |
| Load 15m context candles | < 2s | Low |
| Load 1h context candles | < 1s | Low |
| Feature computation (all 82 features, pure Python) | < 120s | Moderate |
| Feature Parquet write (vectorized TSV bulk) | < 10s | Low |
| Manifest generation | < 2s | Low |
| **End-to-end total** | **< 140s** | |

### 10.2 Computationally Expensive Features and Mitigations

| Feature | Why Expensive | Mitigation |
|---|---|---|
| `mr_hurst_proxy_96` | RS range over 96 elements per bar | Incremental deque for max/min; incremental cumulative sum |
| `mom_slope_48` | OLS solve per bar | Precompute `(X'X)^{-1}X'` once for fixed `n`; reduce to dot product per bar |
| `mr_autocorr_lag1_96` | Pearson corr of two 96-element arrays per bar | Welford-style incremental covariance update: O(1) per bar |
| Pivot detection | Symmetric neighborhood scan per bar | O(n) monotone deque sliding maximum |
| MTF alignment joins | Cross-index matching 5m to 15m/1h | Sort-merge join O(n); never O(n^2) |

### 10.3 Design for Scale

- All rolling computations maintain O(1) incremental state (bounded deques, Welford accumulators, Wilder EMA values)
- Memory footprint: `288 * ~500 bytes ~ 144 KB` maximum
- Month-by-month streaming possible: carry state across partition boundaries
- Adding XAUUSD requires zero architectural changes: run the same engine per instrument

### 10.4 Escalation Path (No New Dependencies)

If profiling shows pure Python cannot meet 140s: use **DuckDB SQL window functions** to compute rolling features inside DuckDB's vectorized C++ engine.

```sql
SELECT
  timestamp_utc,
  LN(close) - LN(LAG(close, 1) OVER w) AS ret_log_cc_1,
  AVG(close) OVER (w ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS sma_12,
  ...
FROM feature_input
WINDOW w AS (ORDER BY timestamp_utc)
```

This escalation requires explicit approval and is out of scope for the initial Phase 2 implementation.

---

## 11. Dependency Decision

**Zero new Python packages added in Phase 2.**

Existing: `pydantic >= 2.7.0`, `duckdb >= 1.0.0`, `pyyaml >= 6.0.1`, `rich >= 13.7.0`, `websockets >= 13.0.0`, `pytz >= 2024.1`, Python 3.12 stdlib.

See OQ-1 in Section 14 for the NumPy exception policy.

---

## 12. Deliverables

| Deliverable | Description | Location |
|---|---|---|
| `xau_quant.features` package | All 8 feature families, engine, storage, validators, registry | `src/xau_quant/features/` |
| Feature dataset v2.0.0 | Versioned, partitioned, validated Parquet files | `data/features/binance/spot/BTCUSDT/5m/feature_set=v2.0.0/` |
| Feature dataset manifest | JSON provenance with full SHA-256 chain | `data/metadata/manifests/btcusdt_5m_features_v2.0.0_manifest.json` |
| `compute_features.py` | Reproducible CLI pipeline: Phase 1C -> feature Parquet | `scripts/compute_features.py` |
| Unit test suite | 60+ parametrized tests: all features, all edge cases | `tests/unit/features/` |
| Integration test | End-to-end pipeline test against Phase 1C dataset | `tests/integration/features/` |
| Phase 2 completion report | Validation summary, feature statistics, timing | `artifacts/reports/phase_2_completion_report.md` |

---

## 13. Acceptance Criteria

Phase 2 is complete when **all** of the following hold simultaneously:

| # | Criterion | Verification |
|---|---|---|
| AC-1 | All unit tests pass | `pytest tests/unit/features/ -v` -> 0 failures |
| AC-2 | All integration tests pass | `pytest tests/integration/features/ -v` -> 0 failures |
| AC-3 | Feature dataset row count = 315,648 | `SELECT COUNT(*) FROM feature_parquet` |
| AC-4 | Zero `inf` or `-inf` in any feature column | DuckDB `IS INFINITE` scan |
| AC-5 | >= 99.9% post-warm-up rows have `is_valid = True` | Manifest `valid_rows` field |
| AC-6 | Feature manifest SHA-256 stable across two independent runs | Compare `combined_parquet_sha256` |
| AC-7 | All no-lookahead tests pass for every feature | Parametrized pytest |
| AC-8 | All warm-up boundary tests pass for every feature | Parametrized pytest |
| AC-9 | End-to-end computation < 140 seconds | `time python scripts/compute_features.py` |
| AC-10 | Zero mypy errors in features package | `mypy src/xau_quant/features/ --strict` |
| AC-11 | Zero ruff violations | `ruff check src/xau_quant/features/` |
| AC-12 | Zero new entries in `pyproject.toml` dependencies | `git diff pyproject.toml` |
| AC-13 | Feature manifest `input_dataset.root_manifest_sha256` matches Phase 1C root | Manual inspection |

---

## 14. Open Questions Requiring Nishant's Decision Before Implementation

> [!IMPORTANT]
> **OQ-1: NumPy/pandas dependency exception policy**
> The design mandates zero new dependencies and nominates DuckDB SQL window functions as the performance escalation path if pure Python proves too slow. Is this policy confirmed? Or is NumPy permitted as a dependency from the start to simplify calculator implementation?

> [!IMPORTANT]
> **OQ-2: Feature set scope**
> The specification defines approximately 82 features across all 8 families. Should the initial v2.0.0 deliver the full set, or should Phase 2.0 deliver a trimmed core (e.g., `ret_`, `mom_`, `vol_`, `liq_`, `time_` families only — approximately 40 features) with `ms_`, `mr_`, and `mtf_` deferred to Phase 2.1?

> [!NOTE]
> **OQ-3: Hurst exponent proxy — include in v2.0.0 or defer**
> `mr_hurst_proxy_96` is computationally heavier and statistically noisier (single-window RS estimator) than all other features. Include in Phase 2.0 or defer to Phase 2.1?

> [!NOTE]
> **OQ-4: Pivot detection storage convention**
> Pivot features are stored at the pivot bar's timestamp (not the detection bar). This creates a mandatory `s`-bar lag that all downstream consumers must understand. Is this convention acceptable, or should pivot features be stored at the detection bar `t` with an explicit `pivot_age_bars` column?

> [!NOTE]
> **OQ-5: 4h and 1d multi-timeframe context**
> The current design excludes 4h and 1d MTF features. These timeframes provide valuable macro regime context. Should they be included in v2.0.0 alongside the 1h and 15m context, or deferred?

---

> [!CAUTION]
> **GATE ENFORCEMENT**: This is a design-only document. Zero implementation has been executed. No feature code has been written. No data has been downloaded, modified, or processed. No commits or pushes have been made. The working tree is unchanged except for this design document. Awaiting formal review and explicit approval from Nishant before Phase 2 implementation begins.
