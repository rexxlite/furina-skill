# Range Mean-Reversion Scanner — `range_mr_scanner.py`

**Status:** REMOVED FROM CRON (2026-06-26) — script kept for reference
**Risk model tag:** `range_mr` — emoji 📐
**Source:** `scripts/range_mr_scanner.py` (354 lines)

## Why removed

Eval 2-week testnet (2026-06-12 to 2026-06-26): net **-$136.69**, win rate 30%.
Worst performer of all scanners. Shorts were 2W/7L (22% WR, -$23.92) even with
a 4h EMA50 gate — the macro uptrend killed every fade-short. LONG-only switch
did not rescue the edge. Removed from cron on the real-mainnet switch; script
kept in repo as a learning artifact.

## Thesis

Closes the BIGGEST gap in the system: every existing scanner is trend-following,
so they bleed (whipsaw) in sideways/choppy markets. This scanner is the
opposite — it ONLY fires when the market is ranging, and fades extremes back
to the mean.

- REGIME GATE: ADX < ADX_MAX (no trend) — if trending, stay out entirely
- LONG setup: price at/below lower Bollinger Band (%B <= LOW_PCTB) + RSI
  oversold → fade UP toward the mid-band
- SHORT setup: price at/above upper Bollinger Band (%B >= HIGH_PCTB) + RSI
  overbought → fade DOWN toward the mid-band

Confirmation: rejection wick at the extreme (price poked the band and got
rejected), RSI extreme aligned with the fade, range must be "clean" (price has
respected the bands recently, not breaking out).

## Parameters

- Signal timeframe: `1h`
- ADX max: 20.0 (regime gate — only fire when ranging)
- Bollinger: N=20, K=2
- Low %B: 0.05 (at/below lower band → LONG)
- High %B: 0.95 (at/above upper band → SHORT)
- RSI oversold: 35 (LONG)
- RSI overbought: 65 (SHORT)
- Universe: top 60 USDT perp by 24h quote volume
- Cooldown: 8 hours per symbol
- SL band buffer: 0.5 (SL = band +/- band_width x buffer fraction of ATR)
- ATR SL multiplier: 1.0 (range stops are tight)
- Min score: 4 of 5 (raised 2026-06-23: cut coin-flip marginals)
- Min band width: 2.0% (range must have enough width to be tradeable)
- Max band width: 12.0% (too wide = volatile, not a clean range)
- SHORT_MTF_TF: 4h, EMA50 (price must be <= this EMA on 4h to allow SHORT)
- SHORT_ENABLED: False (LONG-only since 2026-06-23)

## Scoring (5 points, need 4)

1. Base — at-band extreme + regime gate passed
2. RSI oversold / overbought — aligned with the fade
3. Rejection wick — buyers/sellers stepping in at the extreme
4. Candle turning toward mean — close moving back to mid-band
5. Range intact — no breakout (bands respected recently)

## Exit philosophy

Mean-reversion. TP = mid-band (VWAP-like mean) primarily — conservative, high
win-rate target. SL = just beyond the band (if the band breaks, the range is
dead → bail fast). This is NOT a trend trade; profit per trade is modest,
win-rate is the edge.

## Lessons learned (documented in scanner-remediation-methodology.md)

- Range MR was the biggest loser despite a sound thesis — mean-reversion in
  crypto perps is hard because "ranges" often break into continuation
- SHORT side was especially bad (22% WR) — fading strength in a macro uptrend
  is a structural losing trade
- MIN_SCORE raised 3 → 4 on 2026-06-23 but the edge did not recover
- Removed rather than fixed: the regime gate (ADX < 20) is correct in theory
  but crypto rarely ranges cleanly enough for 1h band-fades to pay

## Bucket / leverage (historical)

- Executor bucket: RANGE_MR (now disabled)
- Leverage: 4x (CROSSED)
- Risk: flat 1% per trade
