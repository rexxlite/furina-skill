# Breakout-Retest Scanner — `breakout_retest_scanner.py`

**Status:** REMOVED FROM CRON (2026-06-26) — script kept for reference
**Risk model tag:** `breakout_retest` — emoji 🚀
**Source:** `scripts/breakout_retest_scanner.py` (383 lines)

## Why removed

Eval 2-week testnet (2026-06-12 to 2026-06-26): net **-$85.69**, win rate 43%.
Worst performer after range_mr. A prior 2026-06-21 "score-inversion fix" made
things worse (moved WR from 46% to 38.5% on shorts). Removed from cron on the
real-mainnet switch; script kept in repo as a learning artifact.

## Thesis

Upgrades the BB-squeeze idea from a single score-point into a full setup with
better entry timing. Three phases:

1. SQUEEZE — Bollinger Band Width compressed (low volatility coil)
2. BREAKOUT — an expansion candle closes beyond the range + volume rises
3. RETEST — price pulls back to the broken level → ENTER there
   (not chasing the first breakout candle)

Why retest > chase: the retest filters fakeouts (if it doesn't hold, skip) and
gives a much tighter stop → better RR. Trade-off: strong breakouts sometimes
never retest (we miss those). That's acceptable — quality over quantity.

Direction: bullish breakout (close above recent high after squeeze) → LONG on
retest of that high. Bearish breakout → SHORT on retest of that low.

## Parameters

- Signal timeframe: `1h`
- Lookback: 120 bars
- BBW squeeze percentile: 0.30 (squeeze = BBW in lowest 30% of recent range)
- Squeeze window: 40 bars (measure BBW percentile)
- Breakout window: 20 bars (range whose high/low defines the breakout level)
- Breakout max bars ago: 8 (breakout must have happened within last N bars)
- Retest tolerance: 1.2% (price within this of broken level = retest zone)
- Volume confirm multiplier: 1.3x (breakout candle vol >= 1.3x average)
- Universe: top 60 USDT perp by 24h quote volume
- Cooldown: 8 hours per symbol
- ATR SL multiplier: 1.2
- RR TP: [1.0, 2.0, 3.0] (momentum trade — let winners run)
- Min score: 3 of 4
- SHORT_ENABLED: False (LONG-only)
- Long MTF: 4h, EMA50 (price must be >= this EMA on 4h to allow LONG)

## Scoring (4 points, need 3)

1. Base — squeeze + breakout + retest pattern present
2. Preceded by BB squeeze — BBW in lowest percentile band
3. Breakout volume confirmed — vol >= 1.3x average
4. RSI healthy — room to run (not already overbought/oversold)

## Confirmation gates (hard skips)

- Prior squeeze: BBW in the lowest band of its recent range
- Breakout candle had above-average volume
- Retest holds: price came back to the level (within tolerance) and is rejecting
- LONG-only: shorts fight the macro uptrend (4h EMA50 gate)

## Lessons learned (documented in scanner-remediation-methodology.md)

- Breakout-retest had no macro filter initially → shorts bled in uptrend
- Score-inversion fix (06-21) backfired — blind parameter tuning can make
  things worse; always backtest before deploying
- MIN_SCORE stayed at 3 because max_score is only 4 (no headroom to raise)
- Removed rather than fixed because the edge did not survive a real 2-week eval

## Bucket / leverage (historical)

- Executor bucket: BR_RT (now disabled)
- Leverage: 4x (CROSSED)
- Risk: flat 1% per trade
