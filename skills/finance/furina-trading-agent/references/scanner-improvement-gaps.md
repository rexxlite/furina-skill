# Scanner Improvement Gaps (Identified 2026-05-29)

Analysis of `automatic_signal_scanner.py` (860 lines) against 10 fundamental trading mastery topics revealed 7 actionable gaps. These are features the scanner LACKS that would improve signal quality.

## Gap 1: Candlestick Pattern Recognition
**Status:** ✅ IMPLEMENTED (2026-05-29) in `scanner_enhancements.py`
**Impact:** HIGH — entry without candle confirmation
**What to add:** Detect engulfing, pin bar, hammer, shooting star, inside bar on the signal timeframe candle. Use as +1 score bonus, not standalone filter.
**Implementation notes:**
- Check last 1-3 candles on signal TF
- Engulfing: `prev_o > prev_c` AND `cur_c > cur_o` AND `cur_c > prev_o` AND `cur_o < prev_c` (bullish)
- Pin bar: `wick_ratio = abs(o-c) / (h-l)` < 0.35 AND `lower_wick / (h-l)` > 0.6 (bullish)
- Inside bar: `cur_h < prev_h` AND `cur_l > prev_l`
- Score bonus: +1 if pattern detected at key level (S/R zone)

## Gap 2: RSI Divergence Detection
**Status:** ✅ IMPLEMENTED (2026-05-29) in `scanner_enhancements.py`
**Impact:** HIGH — misses strongest reversal signals
**What to add:** Compare price swing highs/lows with RSI swing highs/lows over last 20-30 candles.
**Implementation notes:**
- Bullish divergence: price makes lower low, RSI makes higher low
- Bearish divergence: price makes higher high, RSI makes lower high
- Use `find_peaks`-style logic on close prices and RSI series
- Only flag divergence at significant S/R levels (not mid-range)
- Score bonus: +1 for regular divergence, +0.5 for hidden divergence

## Gap 3: Support/Resistance Detection
**Status:** ✅ IMPLEMENTED (2026-05-29) in `scanner_enhancements.py` — cluster-based S/R for SL placement
**Impact:** MEDIUM — SL/TP lack precision
**What to add:** Cluster-based S/R detection using swing highs/lows over larger lookback.
**Implementation notes:**
- Find all swing highs/lows in last 100 candles (pivot with 3-candle confirmation)
- Cluster levels within 0.5% of each other (more touches = stronger level)
- Use nearest S/R for SL placement instead of just recent_high/recent_low
- Weight by: number of touches, recency, timeframe (HTF levels > LTF)

## Gap 4: Market Regime Filter
**Status:** ✅ IMPLEMENTED (2026-05-29) in `scanner_enhancements.py` — ADX hard gate for aggressive
**Impact:** MEDIUM — entries during choppy/ranging market
**What to add:** Classify market as trending vs ranging before scoring.
**Implementation notes:**
- ADX already computed for medium/safe — use it for all modes
- BB width already computed for safe — use for regime detection
- Ranging filter: `ADX < 20` AND `BB_width < 5%` → skip or reduce score
- Trending: `ADX > 25` AND `BB_width expanding` → bonus score
- Add as hard gate: aggressive skips if ADX < 15, medium if ADX < 20

## Gap 5: Volume Profile / VWAP
**Status:** NOT IMPLEMENTED (low priority — requires intraday volume data)
**Impact:** MEDIUM — doesn't know accumulation/distribution zones
**What to add:** Compute VWAP from intraday data; use as dynamic S/R.
**Implementation notes:**
- VWAP = cumulative(typical_price × volume) / cumulative(volume)
- Typical price = (H+L+C)/3
- Use 1D VWAP for intraday modes (aggressive/medium)
- If price is below VWAP and setup is LONG → reduce confidence
- Score bonus: +0.5 if entry near VWAP (within 0.3% of VWAP)

## Gap 6: Smart Money / Liquidity Detection
**Status:** ✅ IMPLEMENTED (2026-05-29) in `scanner_enhancements.py`
**Impact:** MEDIUM — frequent stop hunt victims
**What to add:** Detect equal highs/lows (liquidity pools) and stop hunt patterns.
**Implementation notes:**
- Equal highs: 2+ swing highs within 0.2% of each other → stop cluster above
- Equal lows: 2+ swing lows within 0.2% → stop cluster below
- Liquidity sweep: price wicks beyond equal high/low then closes back inside
- Score bonus: +1 if entry is AFTER a liquidity sweep (smart money already taken liquidity)
- Score penalty: -1 if entry is DIRECTLY INTO a liquidity pool (SL likely hunted)

## Gap 7: Multi-Candle Momentum Context
**Status:** ✅ IMPLEMENTED (2026-05-29) in `scanner_enhancements.py`
**Impact:** LOW-MEDIUM — loses context from 2-3 candles before entry
**What to add:** Analyze the last 3-5 candles for momentum direction and quality.
**Implementation notes:**
- Count bullish vs bearish candles in last 5
- Check if body sizes are increasing (momentum building) or decreasing (fading)
- Strong momentum: 3+ consecutive same-direction candles with increasing bodies
- Fading momentum: last candle body < 50% of average body (potential reversal)
- Score bonus: +1 for strong momentum alignment with side

## Gap 8: Previous Candle OHLC Break Confirmation
**Status:** ✅ IMPLEMENTED (2026-06-02) in `automatic_signal_scanner.py`
- Config flag: `use_close_above_ph: True` on all 3 modes (aggressive/medium/safe)
- LONG: `cs[-2]["c"] > cs[-3]["h"]` → +1 score ("Close above prev high (TF)")
- SHORT: `cs[-2]["c"] < cs[-3]["l"]` → +1 score ("Close below prev low (TF)")
- Uses last COMPLETED candle (`cs[-2]`), not the forming one — avoids false intra-candle signals
- Tested 2026-06-02: fires correctly on WLDUSDT 1D (close $0.4378 > prev high $0.3564), LABUSDT 1D, BTCUSDT 1D (bearish), SOLUSDT 4h (bearish)
- Pattern alone doesn't unblock signals during BTC-bearish regime (longs still gated by bias), but lowers threshold for future setups
- Max score: Aggressive 7→8 (this gap alone); combined with Gap 9: Medium 9→11, Safe 12→14
**Impact:** MEDIUM — misses strong trend continuation signals
**Source:** Little Things channel (@yourlittlething) trading methodology, validated 2026-06-02

**Core concept (from source):**
> "Daily skrg ditutup diatas prev high = ada strong2nya kawan. makin gede tf makin strong"

When a candle **closes above the previous candle's HIGH**, it signals strong bullish continuation. Conversely, close below prev LOW = bearish continuation. The signal strengthens with timeframe size (monthly > weekly > daily > 4h).

**Real example cited:** WLD weekly broke previous high → buy signal confirmed → profitable.

**Implementation notes:**
- For LONG: check if current candle closes above previous candle's HIGH → +1 score bonus
- For SHORT: check if current candle closes below previous candle's LOW → +1 score bonus
- Use as confirmation, not standalone filter — must still pass structure/trend gates
- Can also use as a "strengthener" for breakout-retest setups: if the breakout candle itself closed above prev high, the breakout is higher quality

**Pattern variants:**
1. **Direct break:** Candle N close > Candle N-1 high (most common)
2. **Multi-candle break:** Candle N close > Candle N-2 or N-3 high (stronger, rarer)
3. **HTF confirm:** Daily close above weekly prev high = very strong signal
4. **Failed break:** Candle closes above prev high but next candle closes back below → false breakout, reject

**Pitfall:** A candle that wicks above prev high but closes back below is a FALSE break (deviation), not a valid signal. Require CLOSE above, not wick.

## Gap 9: OHLC S/R Confluence Zone
**Status:** ✅ IMPLEMENTED (2026-06-02) in `automatic_signal_scanner.py`
- Config flag: `use_ohlc_confluence: True` on Medium and Safe modes (NOT aggressive — too many API calls for 50 symbols every 15 min)
- Helper functions: `ohlc_nearby(price, candles, pct_thresh)` and `ohlc_confluence(price, tf_candles, pct_thresh)`
- Logic: collect OHLC levels (Open/High/Low/Close) from last completed candle across signal TF + context TF, count how many are within ±0.5% of current price
- Gate: ≥3 levels from ≥2 different TFs → +1 score ("OHLC confluence zone (tf:Nlvls, tf:Nlvls)")
- Max score updated: Medium 10→11, Safe 13→14
**Impact:** MEDIUM — identifies high-probability bounce/rejection zones
**Source:** Little Things channel (@yourlittlething) — "buat candle2 gede gini ada 4 titik bisa jadi S/R: Open, High, Low, Close"

**Core concept:**
Every candle has 4 OHLC levels that act as S/R. Big candles (especially monthly/weekly) have stronger levels because more orders cluster there. When price approaches a zone where MULTIPLE OHLC levels from DIFFERENT timeframes converge, it's a high-probability decision zone.

**Real-world test (2026-06-02):**
- MUUSDT: 4 levels from 2 TFs (1h:2, 4h:2) → confluence zone confirmed
- NEARUSDT: 3 levels from 2 TFs (1h:1, 4h:2) → confluence zone confirmed
- BTCUSDT ($67,883): 2 levels from 1 TF (1h Low $67,574, 1h Close $67,990) — close but not enough (needs ≥3 from ≥2 TFs)

**Implementation notes:**
- Uses already-fetched candles (signal TF + context TF) — zero extra API calls for medium/safe
- `ohlc_nearby()` extracts O/H/L/C from `candles[-2]` (last completed) and counts levels within ±threshold
- `ohlc_confluence()` aggregates across multiple TFs
- Threshold 0.5% works well for crypto — tight enough to be meaningful, loose enough to catch real zones
- NOT a standalone filter — only adds +1 when a side is already determined
- Can be used for SL placement refinement: if confluence zone is near the structural SL, consider adjusting SL to the confluence boundary

**Connection to Gap 3 (S/R Detection):** Gap 3 was cluster-based S/R from swing highs/lows. Gap 9 is OHLC-based S/R from candle data. They complement each other — swing S/R for structural levels, OHLC S/R for immediate decision zones.

## Gap 10: Weekly/Monthly OHLC S/R (HTF Integration)
**Status:** ❌ NOT IMPLEMENTED — partial coverage (only Signal TF + Context TF, max 4h/1D)
**Impact:** HIGH — Gap 8 and Gap 9 are partially honoring the source methodology
**Source:** Little Things channel (@yourlittlething) — channel methodology explicitly teaches **Monthly OHLC** and **Weekly OHLC** as the PRIMARY S/R levels, with the rule "makin gede tf makin strong". Current implementation only uses Signal TF + Context TF, which is the LOWER-TF version of the same pattern.

**The gap (audit, 2026-06-07):**

| Pattern teaching | Current scanner | Status |
|------------------|----------------|--------|
| Close Above Prev High (intra-TF, 15m–1D) | ✅ Gap 8 implemented | Partial |
| OHLC Confluence (Signal TF + Context TF, ≤1D) | ✅ Gap 9 implemented | Partial |
| **Monthly OHLC** as S/R | ❌ Missing | **Gap 10** |
| **Weekly OHLC** as S/R | ❌ Missing | **Gap 10** |
| Close Above Prev Weekly High | ❌ Missing | **Gap 10** |
| Close Above Prev Monthly High | ❌ Missing | **Gap 10** |
| Multi-TF confluence (15m + 1h + 4h + 1D + 1W + 1M) | ❌ Missing | **Gap 10** |

The channel example ("WLD weekly broke previous high → buy") cannot be detected by current scanner because it never fetches Weekly klines for OHLC analysis. Same for monthly breakouts which the channel calls "very strong signal".

**Implementation plan:**

Phase 1 — fetch HTF candles:
- Aggressive: add `1w` to fetch chain (for close-above-weekly-high check only, no full confluence to keep API budget tight)
- Medium: add `1w` + `1M` (full pattern)
- Safe: already has `1d`; add `1w` + `1M`
- Counter-Trend: skip — counter-trend is mean-reversion, HTF break confirmation doesn't fit thesis

Phase 2 — new scoring rules:
- `+2 score` if last completed weekly candle close > prev weekly high (LONG) or < prev weekly low (SHORT)
- `+3 score` if last completed monthly candle close > prev monthly high (rare, very strong)
- `+1 score` extension to Gap 9 confluence: count weekly + monthly OHLC levels in `ohlc_confluence()` when available
- New no-trade-zone gate: if price is within 0.5% BELOW prev weekly high AND weekly candle hasn't closed yet → mark as `wait_weekly_close`, defer signal

Phase 3 — config + max_score updates:
- `use_close_above_ph_weekly: True` for Aggressive/Medium/Safe
- `use_close_above_ph_monthly: True` for Medium/Safe only
- Aggressive max_score: 8 → 10 (+2 weekly)
- Medium max_score: 11 → 14 (+2 weekly, +3 monthly — but rare so realistic ceiling lower)
- Safe max_score: 14 → 18 (+2 weekly, +3 monthly, +1 confluence extension)

Phase 4 — API budget consideration:
- Weekly klines: `interval=1w&limit=10` per symbol = 1 extra call. For 50 symbols on Aggressive = +50 calls per scan.
- Monthly klines: `interval=1M&limit=6` per symbol = 1 extra call. Medium/Safe only, lower symbol counts (60-80) = +60-80 calls per scan.
- Combined with existing Binance rate limit guards (`time.sleep(0.1)` between calls, `max_symbols` caps), this is feasible but pushes Aggressive close to the 120s cron timeout. Recommend implementing Medium/Safe FIRST, then Aggressive only after timing benchmark.

Phase 5 — pitfalls to anticipate:
- **Weekly close timing:** Binance weekly candles close Sunday 24:00 UTC = Monday 07:00 WIB. The "last completed weekly candle" is the one whose close happened ≥ 1 minute ago. Use `cs[-2]` not `cs[-1]` to avoid the forming weekly.
- **Monthly close timing:** Calendar-month boundary in UTC. Last completed monthly candle changes only once per month — cache it across scanner runs to save API calls.
- **Wick-vs-close trap:** Same as Gap 8 — require CLOSE above weekly/monthly high, not wick. A weekly candle that wicks above prev high but closes back below is a deviation, REJECT.
- **Multi-week consolidation:** if price is below prev weekly high for 4+ weeks in a row, the level is "matured" and break is more significant. Bonus score consideration.
- **API interval case sensitivity:** weekly = `1w` (lowercase), monthly = `1M` (uppercase M). Reminder from main SKILL.md pitfall section.

**Connection to Gap 8 + Gap 9:** Gap 10 is the HTF extension of both. Gap 8 + Gap 9 fire on the timeframes the scanner already fetches; Gap 10 brings in the timeframes the channel actually teaches as primary. After Gap 10 is in, the scanner will be honoring the source methodology fully — not just partially.

## Priority Implementation Order
1. Gap 1 (Candlestick) — easiest, highest impact per effort ✅
2. Gap 4 (Market Regime) — ADX/BB data already exists, just needs gating ✅
3. Gap 2 (RSI Divergence) — powerful signal, moderate complexity ✅
4. Gap 6 (Smart Money) — requires swing detection, moderate complexity ✅
5. Gap 3 (S/R Detection) — larger refactor, but improves SL precision ✅
6. Gap 7 (Multi-Candle) — simple addition once others are done ✅
7. Gap 8 (OHLC Break) — simple prev-candle comparison ✅
8. Gap 9 (OHLC Confluence) — multi-TF OHLC zone detection ✅
9. Gap 10 (Weekly/Monthly OHLC) — HTF extension of Gap 8 + Gap 9, brings scanner in line with source methodology (PENDING)
10. Gap 5 (VWAP) — requires intraday volume data, lowest priority (pending)

## Integration Plan
All gaps should be integrated as **optional score bonuses** (not hard gates) so they don't break existing signal flow. Add a `features_enabled` config per mode:
- Aggressive: Gap 1, 4, 7, 8
- Medium: Gap 1, 2, 4, 7, 8, 9
- Safe: Gap 1, 2, 3, 4, 5, 6, 7, 8, 9

## Connection to 10 Trading Mastery Topics
These gaps map directly to the foundational trading topics:
- Gap 1 → Topic 3 (Candlestick Patterns) ✅
- Gap 2 → Topic 4 (Technical Indicators — RSI) ✅
- Gap 3 → Topic 2 (Support & Resistance) ✅
- Gap 4 → Topic 6 (Chart Patterns — regime detection) ✅
- Gap 5 → Topic 5 (Volume Analysis — VWAP) — pending
- Gap 6 → Topic 9 (Order Flow & Market Microstructure) ✅
- Gap 7 → Topic 1 (Market Structure & Price Action — momentum) ✅
- Gap 8 → Topic 2 (Support & Resistance — OHLC break as continuation) ✅
- Gap 9 → Topic 2 (Support & Resistance — OHLC confluence zones) ✅

Plus: **Late-Entry Tighten** filter added as hard gate in `scanner_enhancements.py`.
Plus: **EMA Reclaim** filter already existed in scanner (2026-05-14 BIOUSDT lesson).

## Current Max Score Summary (after all gaps integrated)
| Mode | Before | After (Gap 8+9) | Target (Gap 10) | Gains |
|------|--------|-----------------|-----------------|-------|
| Aggressive | 7 | 8 | 10 | +1 (Gap 8) +2 (Gap 10 weekly) |
| Medium | 9 | 11 | 14+ | +1 (Gap 8) +1 (Gap 9) +2 weekly +3 monthly |
| Safe | 12 | 14 | 18+ | +1 (Gap 8) +1 (Gap 9) +2 weekly +3 monthly +1 confluence-htf |

Note: Gap 8 + Gap 9 are LTF-only implementations. Gap 10 is the HTF extension that brings the scanner in line with the source methodology (channel @yourlittlething explicitly teaches Weekly/Monthly OHLC as primary S/R, not 4h/1D). Until Gap 10 ships, the scanner is honoring the source methodology PARTIALLY — patterns fire on lower timeframes the scanner already fetches, but miss the strongest HTF breaks the channel actually trades.
