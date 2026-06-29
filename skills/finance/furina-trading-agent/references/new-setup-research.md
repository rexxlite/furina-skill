# Furina — Candidate New Setup Types (Beyond Trend-Following)

The existing scanners (Aggressive / Medium / Safe) are all trend-following,
plus one Counter-Trend (oversold-bounce). They share the same 7-layer
confirmation engine. That leaves whole classes of edge ungenerated —
especially **perp-specific data** (funding, open interest, basis) which is
NOT used to generate any signal today.

User wants to expand setups during the demo/testnet trial phase
("selagi masih trial and error", 2026-06-12). The agreed approach: build
each candidate as a **parallel scanner with its own journal** so its
performance is measured cleanly, not as a score-layer bolted onto existing
scanners (which contaminates their metrics).

## Candidate ranking (most distinct from existing logic first)

1. **Funding Rate Extreme (mean-reversion, contrarian).**
   Funding very positive → longs crowded → long-squeeze risk → SHORT bias.
   Funding very negative → shorts crowded → LONG bias. Pure perp data, zero
   overlap with trend scanners. Trigger: funding > +0.05% or < -0.05% per 8h
   PLUS a reversal confirmation candle. **Never enter on funding alone** —
   funding can stay extreme for days in a strong trend. Detail in section
   "Funding Extreme — full logic" below.

2. **Open Interest Divergence (context/quality filter).**
   OI rising + price flat = energy building, breakout imminent. OI falling +
   price rising = weak rally (short-covering, not new demand). Use as a
   stand-alone scanner OR as a quality gate on other signals.

3. **Range / Mean-Reversion for choppy markets.**
   Biggest gap: all current scanners bleed in sideways markets (whipsaw).
   Detect ADX < 20 (no trend) + price at lower BB → LONG to mid; upper BB →
   SHORT to mid. Active precisely when the others should stay quiet.

4. **Liquidation Cascade Reversal (aggressive scalp).**
   After a large liquidation wipeout (sharp spike + extreme volume + long
   wick), a fast bounce often follows. More aggressive than existing
   Counter-Trend. Data from liquidation feed / volume spike + wick length.

5. **Breakout-Retest (dedicated).**
   BB squeeze is only 1 score layer today. Promote to its own mode: detect
   squeeze → wait for expansion candle → enter on the RETEST of the breakout
   level (not chasing the first candle). Better RR than raw breakout chasing.

**Recommended starting pair for trial:** #1 (Funding Extreme) and #3 (Range
MR) — one uses idle perp data, one closes the choppy-market weakness; both
have low overlap with existing scanners so results stay clean.

## Funding Extreme — full logic (the lead candidate)

**Concept:** Funding rate = 8h long/short payment (00:00, 08:00, 16:00 UTC).
Positive = longs pay shorts = longs crowded; negative = shorts crowded.
Extreme funding = one-sided positioning = squeeze risk. This is contrarian,
NOT trend-following.

**Why it's a distinct edge:** trend scanners follow the crowd (price up +
momentum = LONG). Funding extreme fades the crowd at exhaustion. The two
capture different moments → they don't eat each other's signals.

**Trigger logic (draft):**
- Step 1 — funding extreme filter: SHORT bias if funding > +0.05%/8h,
  LONG bias if < -0.05%/8h. Normal funding ≈ 0.01%; true extreme often 0.1%+.
- Step 2 — confirmation (MANDATORY, don't fade blind): reversal candle on
  exec TF (15m/1h: rejection wick / close back the other way), OR RSI
  divergence, OR funding starting to roll off its peak (crowd unwinding).
- Step 3 — anti-trap gates: skip if OI still rising hard (crowd still
  adding — too early); skip if structural trend strong (price far above
  EMA200 + ADX > 30 → high funding is justified, not exhaustion).

**Entry/SL/TP:**
- Entry: at the confirmation candle.
- SL: beyond the last swing extreme (for a short, above the freshly-made
  high) — if price keeps running, the "crowded" thesis is wrong, cut fast.
- TP: conservative. Mean-reversion → target the mean (EMA20/VWAP) or
  RR 1.5-2R. Don't get greedy; MR winrate can be high but per-trade profit
  is small.

**Risks to acknowledge:** funding extreme ≠ instant reversal; counter-trend
losers hurt more per trade, so tight SL is mandatory.

**Integration options:** (1) stand-alone scanner with `funding_extreme`
journal, TF 1h/4h — preferred for clean trial metrics; (2) +2 score layer on
the existing Counter-Trend scanner. Go with (1) during trial.

**Data source:** Binance USDⓈ-M Futures `fapi.binance.com`:
- Funding rate: `/fapi/v1/premiumIndex` (lastFundingRate) or
  `/fapi/v1/fundingRate` (history)
- Open interest: `/fapi/v1/openInterest` + `/futures/data/openInterestHist`
- These match the data sources already noted in memory for Furina perp analysis.

## Build discipline when implementing any of these
- Parallel scanner + dedicated journal (don't pollute existing scanner metrics).
- Run in current mode (paper/demo) first; evaluate over 2-4 weeks before
  promoting a pattern into the main scanners.
- Connect conclusions back to signal generation — the user expects actionable
  scanner improvements, not generic write-ups.
