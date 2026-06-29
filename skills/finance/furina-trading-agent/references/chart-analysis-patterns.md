# Chart Analysis Patterns — Manual Trade Learning Log

Track patterns from user-submitted chart images that were manually executed.
Used to identify which setups are consistently profitable and worth integrating
into the automatic signal scanner.

## Chart Image Analysis Protocol

1. User sends chart screenshot → route through **bluesminds gpt-4o** for vision (current primary model mimo-v2.5-pro does NOT support vision)
2. Ask vision AI to identify **zones** (rectangles/bands), not just lines
3. Always confirm ALL levels with user before executing — vision AI misses lines/zones
4. User provides exact levels in format: `Entry: X, Y / TP: Z / SL: W`

### Vision Model Routing
- **bluesminds gpt-4o** = primary for chart image analysis (via api.bluesminds.com)
- mimo-v2.5-pro = NO vision capability
- claude-opus-4.8 via omniroute = NO vision capability
- If bluesminds fails, ask user to type out levels manually

### Zone-Based Chart Reading
TradingView charts often use colored **zones** (horizontal bands/rectangles), not single lines:
- **Yellow zone** = ENTRY area (top & bottom prices = 2 limit entries)
- **Green zone** = TP area (top = TP1, bottom = TP2)
- **Red zone** = SL area (bottom = tight SL, top = wide SL)
When prompting vision AI, explicitly ask for "zones/rectangles" not "lines".

**Re-prompt when initial analysis only returns single lines:**
If the first vision call returns single prices (e.g. "Entry: $0.18576") but the user
says there are zones/areas, re-run with this prompt:
```
Look at this trading chart VERY carefully. I see colored HORIZONTAL ZONES
(rectangles/areas), not just single lines. Describe EXACTLY what you see:
1. YELLOW zones: How many? What are their TOP and BOTTOM prices? (ENTRY zones)
2. GREEN zones: How many? TOP and BOTTOM prices? (TP zones)
3. RED zones: How many? TOP and BOTTOM prices? (SL zones)
```
This forces GPT-4o to describe bands instead of lines. The AIOUSDT chart had 1 yellow
zone ($0.18000-$0.18576), 1 green zone ($0.14010-$0.16150), 1 red zone ($0.19529-$0.20392)
but the first call only returned single-line prices.

---

## Multi-Entry Order Management SOP (v2 — 2026-06-12)

### Setup Phase (when executing from chart)
1. Submit entry 1 & entry 2 as separate LIMIT orders
2. **SL covers TOTAL qty (both entries) IMMEDIATELY** with `reduce_only=False`
   — works without existing position, won't trigger unless price reaches SL
3. **TP is DEFERRED** — watcher auto-places TP once entries fill (position exists)
   — TP with `reduce_only=True` REQUIRES a position
   — TP where trigger < market ALSO immediately triggers — cannot pre-place
4. Entry fill watcher (`entry_fill_watcher.py`, cron every 2min) monitors entries
5. When both entries fill → watcher places TPs with `reduce_only=True`
6. Notification sent when TPs are placed

### ⚠️ EPICUSDT Incident (2026-06-12) — -$13.78 loss (4.9% equity)
SL was DEFERRED along with TP. Entries filled at 11:50 WIB, price crashed
16% in 18 minutes, position closed at 12:08 WIB with NO SL protection.
**Lesson: SL MUST be placed IMMEDIATELY. Only TP is deferred.**

### ⚠️ OPNUSDT Half-Close Incident
SL/TP was placed for entry 1 qty only (236), not total (472). When entry 2
filled, watcher failed to adjust. Result: only half position protected.
**Lesson: SL qty = total of ALL entries from the start.**

### TP Hit SOP (Manual Trades)
When TP1 hits:
1. 50% position closes → profit locked
2. SL moves to breakeven (or entry price to cover fees)
3. TP2 continues running → risk-free remainder

---

## Trade Log

### 2026-06-11: SAHARAUSDT LONG
- Chart: Binance, 15m
- Pattern: `higher_low_formation` — after decline + sideways consolidation, price formed higher low
- Entry: 2 limits ($0.01613 / $0.01572), avg $0.01593
- SL: $0.01529
- TP1: $0.01704 (40%), TP2: $0.01784 (30%), TP3: $0.01872 (30%)
- Risk: 1% ($2.86), RR max: 2.93R
- Key insight: User marked 2 entry zones (vision AI only caught 1 — always confirm ALL levels)
- Result: **TP HIT** — exit $0.01663, profit +$3.14, +4.43%, +1.11R
- Status: CLOSED (TP_HIT)
- Source: TradingView chart, user "KingViktor"

### 2026-06-11: AIOUSDT SHORT
- Chart: Binance, 5m
- Pattern: `resistance_rejection` — steep downtrend, entry at bounce/resistance before continuation
- Entry: 2 limits ($0.18576 / $0.19529), avg $0.19053
- SL: $0.20392
- TP1: $0.16150 (50%), TP2: $0.14010 (50%)
- Risk: 1% ($2.86), RR max: 2.97R
- Result: **SL HIT** — loss -$2.89. Price bounced above entry zone.
- Key insight: Zone-based chart (yellow/green/red bands). Entry 2 filled via watcher.
- Status: CLOSED (SL_HIT)
- Source: TradingView chart, user "KingViktor"

### 2026-06-11: ZECUSDT LONG
- Entry: 2 limits ($419.71 / $410.69), avg $415.20
- TP: $420.12 | SL: $400.81
- Result: **TP HIT** — profit +$0.85
- Status: CLOSED (TP_HIT)

### 2026-06-11: VELVETUSDT LONG
- Entry: 2 limits ($0.79818 / $0.75114)
- TP: $0.90698 / $1.02844 | SL: $0.70687
- Result: **TP HIT** — profit +$2.35
- Key insight: TP/SL was set for total qty (36) but only entry 1 (18) filled. TP triggered full close instead of partial. Led to multi-entry SOP creation.
- Status: CLOSED (TP_HIT)

### 2026-06-12: EPICUSDT LONG ❌ INCIDENT
- Entry: 2 limits ($0.6263 / $0.6130), avg $0.61965
- TP: $0.6577 / $0.6935 | SL: $0.6002
- Risk: 1% ($2.86)
- Result: **SL NOT PLACED** — -$13.78 loss (4.9% equity)
- Entry filled 11:50 WIB, price crashed to $0.5229 in 18 min, closed 12:08 WIB
- Root cause: SL was deferred (reduce_only=True failed without position), watcher code not yet ready
- Lesson: SL MUST use `reduce_only=False` and be placed IMMEDIATELY with entries
- Status: CLOSED (SL_HIT) — manual close at $0.5229

### 2026-06-12: DUSKUSDT LONG (Recovery trade)
- Context: MACD bullish crossover + ADX 28 (+DI > -DI) + RSI 57.68 rising
- Entry: 2 limits ($0.0915 / $0.0880), avg $0.0897
- SL: $0.0793 (placed immediately, reduce_only=False)
- TP1: $0.1000 (50%, 0.98R) | TP2: $0.1141 (50%, 2.33R) — placed immediately (above market)
- Risk: 1% ($2.42)
- SOP: All SL + TP placed with entries (TPs above market = no rejection)
- Status: WAITING_ENTRY

### 2026-06-12: ZECUSDT LONG
- Entry: 2 limits ($404.88 / $396.18), avg $400.53
- SL: $385.98 (placed immediately)
- TP1: $423.67 (40%, 1.59R) | TP2: $441.62 (30%, 2.82R) | TP3: $462.31 (30%, 4.25R)
- Risk: 1% ($2.40)
- SOP: All SL + TP placed with entries
- Status: WAITING_ENTRY

---

## Pattern Performance Summary

- higher_low_formation: 1 trade, 1W 0L → **WR: 100%** (SAHARAUSDT TP +$3.14)
- resistance_rejection: 1 trade, 0W 1L → **WR: 0%** (AIOUSDT SL -$2.89)

*Minimum 5 trades per pattern before scanner integration consideration.*

---

## Scanner Integration Candidates

None yet. Need 5+ closed trades per pattern with WR ≥ 60% and avg R ≥ 1.5 to consider.
Current: 2 patterns tested, 1 loss, 1 pending. Too early.
