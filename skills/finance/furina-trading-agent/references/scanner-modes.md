# Furina Scanner Modes — Complete Reference

All modes defined in `automatic_signal_scanner.py` `MODES` dict.

---

## ⚡ AGGRESSIVE (AGGR)
- **TF chain:** 15m → 30m → 1h | Context TF: 1h
- **Min/Max score:** 6/7 (most lenient)
- **Min RR:** 1.5
- **Risk:** 0.5% (star bucket → 0.75%)
- **Volume min:** $8M 24h quote volume
- **Vol ratio min:** 1.25x
- **RSI window:** LONG (45-78), SHORT (22-55)
- **Cooldown:** 8 hours
- **Max symbols:** 50
- **Filters:** NO BTC bias hard, NO ADX, NO MACD, NO BB width, NO MTF align, NO OHLC patterns
- **Weekend mode:** OFF (Sat-Mon WIB)
- **Win rate (audit):** 77.8% ← STAR BUCKET
- **Character:** Fast momentum capture, fewest confirmations needed. Best for trending markets with clear momentum.

## 🔹 MEDIUM (MED)
- **TF chain:** 1h → 4h | Context TF: 4h
- **Min/Max score:** 7/9
- **Min RR:** 2.0
- **Risk:** 0.5%
- **Volume min:** $20M 24h quote volume
- **Vol ratio min:** 1.4x
- **RSI window:** LONG (50-72), SHORT (28-50)
- **Cooldown:** 16 hours
- **Max symbols:** 80
- **Filters:** BTC bias hard=YES, ADX ≥ 20, MACD=YES, NO BB width, NO MTF align, NO OHLC
- **Win rate (audit):** ~50%
- **Character:** Balanced. Requires BTC trend alignment + ADX/MACD confirmation. Good for swing trades.

## 🛡️ SAFE (SAFE)
- **TF chain:** 4h → 1d | Context TF: 1d
- **Min/Max score:** 8/18 (strictest — many confirmations available)
- **Min RR:** 2.5
- **Risk:** 0.5%
- **Volume min:** $40M 24h quote volume
- **Vol ratio min:** 1.3x
- **RSI window:** LONG (50-65), SHORT (35-50)
- **Cooldown:** 24 hours
- **Max symbols:** 60
- **Filters:** ALL ON — BTC bias hard, ADX ≥ 25, MACD, BB width, MTF alignment, OHLC confluence, Weekly OHLC, Monthly OHLC
- **Win rate (audit):** ~49%
- **Character:** Most selective. Full multi-TF + OHLC confluence required. Signals rare but high conviction. Best for multi-day holds.

## 🔄 COUNTER-TREND (COU)
- **TF chain:** 1h → 4h | Context TF: 4h
- **Min/Max score:** 6/10
- **Min RR:** 1.5
- **Risk:** 0.5% (star bucket → 0.75%)
- **Volume min:** $15M 24h quote volume
- **Vol ratio min:** 1.5x
- **RSI window:** LONG ONLY (10-30), SHORT disabled (999,999)
- **Cooldown:** 6 hours (fastest)
- **Max symbols:** 60
- **Filters:** BTC bias=NO, ADX=NO, MACD=YES, NO BB width, NO MTF align, NO OHLC
- **counter_trend_mode:** True (special logic for oversold bounces)
- **Win rate (audit):** 75% ← STAR BUCKET
- **Character:** LONG-only, buys oversold dips (RSI < 30, BB%B < 0.15). Ignores BTC bias. Mean-reversion play.

---

## Disabled Buckets
- **AGGR_30M** — WR 31.8%, main leak in 61-trade audit. Disabled.
- **MED_4H** — poor performance. Disabled.

## Expanding Beyond These Modes

All four modes above are trend-following / oversold-bounce and share the same
7-layer engine. Candidate NEW setup types that use idle perp data (funding,
OI, basis) or cover the choppy-market gap — Funding Extreme, OI Divergence,
Range Mean-Reversion, Liquidation Cascade, Breakout-Retest — are scoped in
`references/new-setup-research.md`. Build each as a parallel scanner with its
own journal so trial metrics stay clean.

## Score Weights (Safe mode, all filters active)
- EMA alignment (50/200): +2
- RSI in zone: +1
- MACD crossover: +1
- BB squeeze: +1
- Volume spike: +1
- ADX trend: +1
- MTF alignment: +2
- OHLC confluence: +1
- Weekly OHLC: +2
- Monthly OHLC: +2
- Close above prev weekly high: +2
- BTC bias alignment: +1
