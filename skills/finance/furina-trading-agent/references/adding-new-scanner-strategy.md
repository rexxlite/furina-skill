# Adding a New Scanner Strategy to the Furina Pipeline

How to build and wire a brand-new automatic signal scanner (e.g. OI Divergence,
Range Mean-Reversion) so it fires → executes to Binance (demo/real) → shows on the
dashboard, WITHOUT breaking the existing 5 scanners. Proven on the 2026-06-13
OI Divergence + Range MR deployment.

## Architecture decision that keeps it clean

Write the new scanner as a **standalone module** that `import automatic_signal_scanner as base`
to reuse helpers (`klines`, `ema`, `rsi`, `atr`, `adx`, `bb_width`, `bb_pct_b`,
`get_json`, `EXCLUDE_SYMBOLS`, `COMMODITY_KEYWORDS`, `ALLOWED_CONTRACT_TYPES`,
`ALLOWED_UNDERLYING_TYPES`, `EXCLUDE_SUBTYPES`). Do NOT fork the scanner.

The new scanner appends to the **SAME** `automatic_signal_real_journal.json` but
with its own `risk_model` value. This is the key choice: reconciler, monitor,
risk-manager, dashboard, and entry-fill-watcher all pick it up automatically — no
new monitoring pipeline needed — yet per-strategy performance stays separable by
filtering on `risk_model`.

Data source note: scanner reads klines/OI from **mainnet** `fapi.binance.com`
(testnet data is thin/inaccurate) even when execution goes to testnet. This is
correct and intentional.

## Binance API data sources for scanner signals (mainnet fapi)

Verified endpoints used by the trial scanners (all GET, no auth, mainnet):
- **Open Interest history**: `/futures/data/openInterestHist?symbol=X&period=15m&limit=N`
  — drives OI Divergence. Needs human ticker (BTCUSDT), not internal symbol.
- **Funding rate (current, ALL symbols in one call)**: `/fapi/v1/premiumIndex`
  with NO symbol param returns a list of every perp's `lastFundingRate` +
  `markPrice` + `nextFundingTime`. Far cheaper than per-symbol calls — fetch
  once, build a funding map, filter to extremes. Drives Funding Extreme.
- **Funding history**: `/fapi/v1/fundingRate?symbol=X&limit=N`.
- **24h tickers (ALL symbols)**: `/fapi/v1/ticker/24hr` — one call gives
  `quoteVolume` for the whole universe; use for the liquidity floor.

⚠️ **Liquidation feed is BLOCKED.** `/fapi/v1/allForceOrders` returns HTTP 400.
There is no usable public liquidation stream. Build liquidation-based strategies
(e.g. Liquidation Cascade) from a **klines PROXY** instead: volume spike
(current bar vol ≥ 3× the trailing average), large range bar (≥ 2× ATR), and a
long rejection wick in the cascade direction. Klines carry `v` (base vol) and
`qv` (quote vol) per candle, which is enough. Don't waste time trying to unblock
the force-orders endpoint.

## The 5 trial scanners (deployed 2026-06-13, demo testnet)

All write to `automatic_signal_real_journal.json`, own `risk_model`, exempt from
Asia bump, deliver to Auto Signal topic 570, execute via `process_record_for_scanner`.

- **📡 OI Divergence** — `oi_divergence_scanner.py`, risk_model `oi_divergence`,
  bucket OI_DIV, lev 5, TF 15m, score ≥3/5, cron :12/:42 (job 1df8d845ec25).
  OI vs price: continuation (both up/down) + exhaustion (price moves, OI fades).
  Gates: OI Δ≥3%, price Δ≥1.5% (anti-flush cap 20%), candle confirm, RSI sane.
- **📐 Range Mean-Reversion** — `range_mr_scanner.py`, risk_model `range_mr`,
  bucket RANGE_MR, lev 4, TF 1h, score ≥4/6, cron :27/:57 (job 787a2130c7e1).
  Fires ONLY when ADX<20 (ranging). Fades BB %B extremes back to mid-band.
- **📈 Funding Extreme** — `funding_extreme_scanner.py`, risk_model `funding`,
  bucket FUNDING, lev 4, TF 1h, score ≥4/6, cron :03/:33 (job 07e7de4edac6).
  Contrarian fade when |funding|≥0.04%/8h. Anti-trend gate: skip if ADX≥30 or
  price >10% from EMA200 (extreme funding is justified in strong trends).
  Uses `/fapi/v1/premiumIndex` (all symbols, one call).
- **💥 Liquidation Cascade** — `liq_cascade_scanner.py`, risk_model `liq_cascade`,
  bucket LIQ_CASCADE, lev 4, TF 5m, score ≥4/6, cron :08/:23/:38/:53 (job 089ef884efba).
  Klines PROXY (force-orders blocked): vol spike ≥3× + range ≥2×ATR + rejection
  wick ≥40%. Scalp bounce after panic. Rare by design.
- **🚀 Breakout-Retest** — `breakout_retest_scanner.py`, risk_model `breakout_retest`,
  bucket BREAKOUT_RT, lev 6, TF 1h, score ≥4/6, cron :21/:51 (job 96b10463c57f).
  Squeeze (low BBW) → breakout + volume → entry on RETEST of broken level (not
  chasing). Tighter SL, better RR; misses breakouts that never retest.

## The journal record MUST include these fields

Minimum viable record the executor + Asia filter + dashboard need:

- `id`, `created_at` (ISO), `symbol`, `side` (LONG/SHORT)
- `entry_low`, `entry_high`, `entry_mid`, `sl`, `tp1`, `tp2`, `tp3`
- `status` = "WAITING_ENTRY"
- `risk_model` = your new key (e.g. "oi_divergence")
- **`score`** (int) — ⚠️ CRITICAL, see pitfall #1
- `scanner_min_score` (int) — fallback for Asia gate
- `source`, `timeframe_context`, `technique`, `reason`, `invalidation`

Execute with: `import binance_real_executor as bre; bre.process_record_for_scanner(row)`
then re-save the journal (executor mutates `row["executor"]` in place). The
notification string comes back in the result dict's `notification` key.

## Executor wiring (binance_real_executor.py) — 6 edits

1. `detect_bucket()`: add `if risk_model in ("your_key", ...): return "YOUR_BUCKET"`
   (place BEFORE the TF-text fallback block).
2. `ALLOWED_BUCKETS`: add `"YOUR_BUCKET"`.
3. `LEVERAGE_BY_BUCKET`: add `"YOUR_BUCKET": N`.
4. `get_scanner_min_score()` fallback dict: add your key → min score.
5. (notification) `bucket_short` map + `scanner_emoji` ternary: add your bucket +
   emoji so Hasil Trade messages are visually distinct.
6. `ASIA_EXEMPT_RISK_MODELS` set (in `process_record_for_scanner`, near the Asia
   gate): add your risk_model + all its aliases so trial scanners run 24h. Skip
   this and the scanner goes dead every Asia session (see pitfall #2). This is a
   REQUIRED edit for any trial scanner, not optional.

Tip: add ALL aliases of your key consistently across edits 1/4/6 (e.g.
`("breakout_retest", "breakout_rt", "breakout")`) so detect_bucket, min_score,
and Asia-exemption agree regardless of which alias a row uses.

## Dashboard wiring (2 files)

- `build_unified.py` → `_scanner_label()`: add a branch returning
  `{"key": ..., "name": ..., "emoji": ...}`. This sets `scanner_label` on each record.
- `public/index.html`: add `.scn-<key>` CSS class (pastel bg + dark text) so the
  badge renders with its own color.

### User preference: additive-only dashboard changes

When user says "tambahkan" or "update" to dashboard, they mean **strictly ADD** —
never delete, replace, or modify existing sections. User explicitly corrected:
"ingat tambahan berarti tidak ada yang dihapus". Always scope changes narrowly:
add new HTML sections + CSS + JS, don't refactor existing layout. If adding a new
render function, append `renderX()` calls to existing call sites (filter pills,
nav buttons, load function) — don't restructure the call pattern.

Pattern for adding a new section below the calendar:
1. Add CSS block (new classes, mobile responsive)
2. Add HTML section after `</div>` closing cal-shell, before `</div></main>`
3. Add JS `renderX()` function before the `load()` function
4. Add `renderX();` to ALL places where `renderCalendar(); renderStats();` is called
   (filter pills ×2, prev/next/today buttons, search input, load function)
5. For clickable items: use `data-idx` into `STATE.trades` + event delegation
   (NOT inline onclick with template literal bugs — the `indexOf` in template
   literals references a variable that may not be available in the click handler)

Pattern for adding a new PAGE in sidebar (e.g. Trades page, separate from Calendar):
User prefers sidebar pages over cramming sections below the calendar. Steps:
1. Add `data-page="pagename"` to the sidebar nav-item div
2. Wrap existing content in `<div id="page-calendar">...</div>`
3. Add new page as `<div id="page-pagename" style="display:none;">...</div>`
4. Add independent filter pills inside the new page (use `data-filter-p` / `data-status-p`
   attributes to avoid colliding with calendar filter pills)
5. Add separate STATE vars (e.g. `tradesFilterSource`, `tradesFilterStatus`) and a
   dedicated `tradesPasses(t)` filter function inside `renderEntries()` — don't
   reuse the calendar's `passes()` function
6. Add `switchPage(page)` function that toggles display of page-calendar/page-pagename,
   updates nav-item active state, changes .page-title and .page-sub text
7. Wire nav-items: `document.querySelectorAll('.nav-item[data-page]').forEach(n => {
   n.addEventListener('click', () => switchPage(n.dataset.page)); })`

## Cron deployment

Stagger minutes away from the existing scanners (which occupy
:00/:05/:09/:15/:24/:35/:39/:45/:54). User cares about Binance IP rate limits —
never schedule two API-hitting scripts on the same minute. Use `no_agent=true`,
deliver to the Auto Signal topic (telegram:-100XXXXXXXXXX:570).

## Same-symbol guard (executor, 2b2)

Added 2026-06-13 after TONUSDT funding scanner hit a leverage ERROR because
the same pair already had an active breakout-retest position with open orders.

**The guard** (in `process_record_for_scanner`, after blacklist check 2b, before
Asia session 2c): scans BOTH journals (AUTO_PATH + ALPHA_PATH) for any record
with `executor.status` in `{ACTIVE, WAITING_ENTRY, PENDING, SUBMITTED, PARTIAL}`
matching the signal's symbol. If found → skip with `symbol_already_active_X`.

**Effect**: one pair = one active position max, across ALL scanners. Prevents:
- duplicate entries from different scanners on the same pair
- leverage setup failures ("Position side cannot be changed if there exists open orders")
- unintended double-exposure on the same symbol

Note: this also means a scanner won't re-enter a pair it just exited until the
CLOSED record is the only one remaining. The reconciler must flip the old record
to CLOSED before the guard allows re-entry.

## MAX_CONCURRENT_POSITIONS = 10

Raised from 5 → 10 on 2026-06-13 (trial phase, 10 scanners active). With
RISK_PCT=0.01 (1% per trade), max exposure = 10% equity. Revisit if adding
more scanners or switching to real money.

## PITFALLS (all hit on 2026-06-13, all real)

1. **Missing `score` field → silent Asia-session skip.** The Asia filter
   (`is_asia_session_now()` true during 00-08 UTC = 07-15 WIB) reads
   `record["score"]` and defaults to **0** if absent, so it skips with
   `asia_session_score_too_low_0_lt_N`. New scanners that compute score only
   internally MUST also write it to the journal row. Symptom: scanner fires fine
   outside Asia hours (trades even reach TP2) but goes dead every morning.

   ⚠️ **This is NOT only a trial-scanner trap.** Confirmed 2026-06-25 that the
   ORIGINAL trend scanners (aggressive / medium / safe) — which all funnel through
   `automatic_signal_scanner.py` (the wrappers `os.execvp` into it with `--mode X`)
   — were ALSO missing the field. Their `row` dict (~line 1036) only carried
   `symbol` + `side`, so every signal that reached `process_record_for_scanner`
   during Asia hours was silently skipped with `asia_session_score_too_low_0_lt_8`,
   and they NEVER appeared on the dashboard or in demo execution. The fix is to add
   `"score": best["score"], "scanner_min_score": cfg["min_score"], "max_score":
   cfg["max_score"]` to the row in `automatic_signal_scanner.py` — same fix as for
   trial scanners. If a whole class of scanners shows zero records / never executes,
   check the row dict for `score` FIRST before suspecting bucket gating.

   **Diagnostic distinction:** "never executes" has two independent causes that
   look similar — (a) missing `score` → Asia gate reads 0 → skip, and (b) the
   bucket sitting in `DISABLED_BUCKETS_AUDIT` / absent from `ALLOWED_BUCKETS`.
   AGGR_30M + MED_4H were disabled by the 2026-06-07 audit AND their rows lacked
   `score` — BOTH had to be fixed to get them executing again. Check both:
   `grep ALLOWED_BUCKETS binance_real_executor.py` and inspect a journal row's
   keys. Re-enabling a bucket: add it to `ALLOWED_BUCKETS`, set
   `DISABLED_BUCKETS_AUDIT=set()` (or remove the name), then unit-test
   `detect_bucket` returns `allowed=True` for the bucket. Backup
   `.bak.reenable.<ts>` before editing.

2. **Asia score-bump is calibrated on OLD scanners.** It requires score ≥
   min_score+1 during Asia hours. For trial scanners with no Asia audit history,
   that's unfair and starves them of data. Fix used: `ASIA_EXEMPT_RISK_MODELS`
   set near the gate in `process_record_for_scanner` — exempt trial risk_models so
   they run 24h on their own min_score. Revisit once they accrue Asia trades.

3. **manual_binance_sync duplicate-tagging.** A freshly-FILLED Furina entry sits
   at `status="WAITING_ENTRY"` until the reconciler flips it to ACTIVE. The open-
   position emitter in `manual_binance_sync.py` only skipped symbols with a Furina
   record at `status=="ACTIVE"`, so it mis-tagged the just-filled position as a
   "manual" trade → dashboard showed the same symbol twice. Fix: check a
   `FURINA_LIVE_STATES` set `{ACTIVE, WAITING_ENTRY, PENDING, SUBMITTED, PARTIAL}`
   AND `executor.status in {SUBMITTED, ACTIVE, WAITING_ENTRY}`, not just ACTIVE.

4. **Anti-flush guard.** Mean-reversion / OI-fade logic will try to fade a -41%
   crash/delisting candle. Cap the qualifying move (e.g. `PRICE_MAX_CHANGE_PCT=20`)
   so abnormal moves are skipped.

5. **Per-symbol cooldown.** Add a `recently_signaled()` check (filter journal by
   symbol + your risk_model + a cooldown window) so the same symbol doesn't get
   spammed every cron tick.

6. **Phantom WAITING_ENTRY records → fake "active positions" count.** ROOT CAUSE
   bug found 2026-06-16: every guard/error path in `process_record_for_scanner`
   sets `record["executor"]["status"]` (SKIPPED/ERROR/ERROR_PERMANENT) but the
   OLD code never updated the **top-level** `record["status"]`, which stayed
   `WAITING_ENTRY` forever. Result: 243 phantom records counted as "active"
   (248 reported vs 7 real positions on Binance), polluting the dashboard and
   every "active positions" tally.

   **Fix (permanent, in executor):** wrapped `process_record_for_scanner` so it
   calls the inner pipeline then `_sync_journal_status(record)`, which mirrors the
   terminal executor outcome onto the top-level status — at ONE point, covering
   all 20+ early-return guard paths at once. Logic:
   - if `record["status"]` not in `{WAITING_ENTRY, PENDING}` → return (never clobber)
   - if `executor.status` in `{SKIPPED, ERROR, ERROR_PERMANENT}` → mirror it onto `record["status"]`
   - SUBMITTED / ACTIVE / TP*_HIT / CLOSED → deliberately LEFT as WAITING_ENTRY so
     the reconciler + entry-fill-watcher can still detect the fill.
   - PENDING_API (rate-limited) → left untouched so it stays retryable.

   **Why a wrapper, not 20 inline edits:** the function has 20+ early returns,
   each setting executor.status separately. Patching each one is error-prone;
   syncing once at the single public entry point is bulletproof and future-proof
   (new guard paths inherit the fix automatically).

   **One-time cleanup of legacy phantom records** (run after deploying the fix;
   ALWAYS back up both journals first):
   ```python
   FINAL={'SKIPPED','ERROR','ERROR_PERMANENT'}
   for p in ['automatic_signal_real_journal.json','binance_alpha_real_journal.json']:
       rows=json.load(open(p))
       for r in rows:
           if (r.get('status') or '').upper() in ('WAITING_ENTRY','PENDING'):
               est=(r.get('executor') or {}).get('status')
               if est in FINAL: r['status']=est
       json.dump(rows, open(p,'w'), indent=2)
   ```
   Verify after: journal "active" count should match `positionRisk` live positions
   on Binance (allow +N for genuinely-pending limit entries not yet filled — those
   correctly stay WAITING_ENTRY until the entry-fill-watcher flips them to ACTIVE).

## Performance tuning from trade audits (data-driven, not theory)

When a scanner underperforms, NEVER guess from theory. Bedah the closed trades
first: split wins/losses by SIDE and compute the RR (avg win / avg loss). Two
distinct failure modes surface this way, each with a different fix. Both were
found + fixed 2026-06-17 on the trial scanners.

### Failure mode A — one SIDE bleeds in a trending macro (Range MR)

**Symptom:** scanner net-negative overall, but splitting by side reveals the rot
is asymmetric. Range MR audit (15 closed): LONG = 6W/4L +$13.56 (healthy),
SHORT = 0W/5L −$37.24 (every short hit SL). The whole −$23 was the short side.

**Root cause:** mean-reversion fades the band — it shorts when price pokes the
UPPER band, betting on a snap back to the mean. But in a macro UPTREND, price
tagging the upper band is BREAKOUT continuation, not exhaustion. The 1h ADX<20
"ranging" gate is blind to the higher-TF bullish bias, so every counter-trend
short gets run over.

**Fix — higher-TF directional gate on the counter-trend side only:**
```python
SHORT_MTF_TF = "4h"; SHORT_MTF_EMA = 50; SHORT_ENABLED = True
# after side is decided:
if side == "SHORT":
    if not SHORT_ENABLED: return None
    htf = base.klines(symbol, SHORT_MTF_TF, SHORT_MTF_EMA + 30)
    if len(htf) < SHORT_MTF_EMA + 5: return None
    hc = [c["c"] for c in htf]; he = base.ema(hc, SHORT_MTF_EMA)
    if he is None or hc[-1] > he: return None  # 4h bullish → don't short the trend
```
LONG left unrestricted (it aligns with the macro uptrend and already prints).
**Validation that proves the gate works:** re-run the gate logic on the symbols
that actually lost (SUI, ENA, ETH, LAB) — they should now be BLOCKED (4h close >
EMA50), while a genuinely-bearish symbol (BCH, 4h < EMA50) still passes. 4 of 5
historical losing shorts were blocked → ~−$30 of the −$37 avoided.
**General lesson:** any mean-reversion / counter-trend scanner needs a higher-TF
trend filter on the side that fights the prevailing trend. ADX-ranging on the
signal TF is NOT enough.

### Failure mode B — good win-rate but inverted RR (Funding Extreme)

**Symptom:** WR looks fine (~50%) yet still net-negative. Funding audit (4
closed): WR 50%, but avg win +$5.85 vs avg loss −$8.74 → **RR 0.67**. Losing by
structure — you can have a coin-flip win-rate and still bleed if losses are
bigger than wins.

**Root cause:** SL was ATR×1.5 (wide) while TP1 sat at RR 1.0 (near). On a TP1
hit only ~40% closes + remainder to BE → tiny locked profit; on SL → full wide
loss. Asymmetric payoff.

**Fix — tighten the stop and push the TP ladder out so the first partial ≥ risk:**
```python
ATR_SL_MULT = 1.0          # was 1.5 — tighter stop
RR_TP = [1.5, 2.5, 4.0]    # was [1.0, 1.5, 2.5] — TP1 now RR 1.5
```
With WR 50% and TP1 at RR 1.5, the system flips from negative to positive EV.
**Validation:** simulate entry=100, atr=2 → SL dist = risk = 2.0, TP1 = 103
(RR 1.5) ✓. Don't just trust the constant change — print the resulting SL/TP
ladder and confirm TP1 RR ≥ 1.5.

**General lesson:** WR alone is a vanity metric. Always check RR = avg_win /
avg_loss. RR < 1.0 with WR ≤ 55% = structurally losing. Fix by tightening SL,
widening TP1, or both — but verify the resulting ladder, don't assume.

### Audit method (reusable)
```python
# per scanner: split by side, compute WR + net + RR
for r in closed_records_for(risk_model):
    pnl = float((r.get("executor") or {}).get("real_net_pnl_usdt") or 0)
    # bucket by r["side"]; tally W/L/net; collect wins[] and losses[]
# RR = (sum(wins)/len(wins)) / abs(sum(losses)/len(losses))
```
Scanners auto-reload from cron after editing — no restart needed. Always back up
(`cp scanner.py scanner.py.bak.$(date +%Y%m%d_%H%M%S)`) before tuning.

## Verification sequence (do all before declaring done)

1. `python3 -c "import ast; ast.parse(open(f).read())"` on every edited file.
2. Unit-test detect_bucket: confirm new risk_model → expected bucket, in
   ALLOWED_BUCKETS, leverage set.
3. Live dry-scan top ~12-20 symbols printing detected setups (no journal write).
4. Full live run; then verify on testnet via `client._signed('GET','/fapi/v1/openOrders',{symbol})`
   AND `/fapi/v1/openAlgoOrders` that the limit entry + STOP_MARKET SL + 3
   TAKE_PROFIT_MARKET (reduceOnly) all landed.
5. Rebuild dashboard, confirm record appears once with the correct badge (watch
   for the duplicate-tag trap in pitfall #3).
