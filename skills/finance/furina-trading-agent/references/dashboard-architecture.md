# Furina Dashboard Architecture

## Stack
- Single-file HTML (`/root/calendar_app/public/index.html`, ~1150 lines)
- No framework — vanilla JS, CSS variables, fetch API
- Data: `trades.json` + `last_updated.json` (rebuilt by `build_unified.py` every 5min cron)
- Server: Python HTTP server on port 8888 (0.0.0.0, accessible via VPS public IP)

## Page structure
- Sidebar with `data-page` nav items (Calendar, Trades)
- `switchPage(page)` toggles `#page-calendar` / `#page-trades` visibility
- Each page has its OWN filter pills and STATE vars (independent filtering)
- Calendar page: stats cards + calendar grid + modal detail
- Trades page: entries list with full card details (entry/SL/TP1-3/R/PnL%/Net)

## Key state variables
```js
STATE = {
  trades: [],           // full array from trades.json
  meta: null,           // last_updated.json
  view: new Date(),     // calendar month being viewed
  filterSource: 'all',  // calendar filter
  filterStatus: 'all',  // calendar filter
  tradesFilterSource: 'all',  // trades page filter (independent)
  tradesFilterStatus: 'all',  // trades page filter (independent)
  query: '',            // search input
  statsScope: 'month',  // 'month' or 'all'
}
```

## Rendering chain
All re-renders must call ALL render functions:
`renderCalendar(); renderStats(); renderEntries();`

Call sites that need all three:
- Filter pill clicks (source × 2 pages, status × 2 pages)
- Nav buttons (prev/next/today)
- Search input (debounced)
- `load()` function
- `switchPage()` calls renderEntries when switching to trades

## Scanner badge system
- `_scanner_label()` in `build_unified.py` returns `{key, name, emoji}` from risk_model/bucket
- CSS classes `.scn-<key>` with pastel bg + dark text
- Rendered as `.scn-badge` spans in both calendar detail modal and trades page entries
- Current scanners: aggressive, medium, safe, counter_trend, alpha, oi_divergence,
  range_mr, funding, liq_cascade, breakout_retest, manual, other

## All Entries section (added 2026-06-13)
- "All Entries" list below calendar: every trade as a card (symbol/side/status/
  scanner badge/entry/SL/TP1-3/R/PnL%/Net USDT). Click → detail modal (data-idx
  into STATE.trades). Filtered by same source+status pills as calendar.
- CSS: `.entries-section` / `.entry-item` / `.entry-grid` (4-col → 2-col mobile).
- `renderEntries()` called alongside renderCalendar+renderStats at every
  filter/nav/refresh site. build_unified.py rebuilds trades.json (feeds both).

## Mobile responsive
- ≤600px: sidebar collapses to hamburger, stat cards stack, calendar cells compact,
  trade grid → 2 columns, entry grid → 2 columns
- User accesses from HP — ALL UI changes must work on phone

## Trade-card columns — MUST be uniform across all sources (2026-06-22)
User rejects per-source column variation. Every trade card (day-detail modal AND
trades page) shows the SAME 4 columns regardless of source:
`Entry · Exit · PnL % · Net USDT`. Do NOT branch on `t.source==='manual'` to swap
labels (old bug: manual→Exit/PnL%, auto→SL/R — looked inconsistent, user complained
"kenapa tampilan tiap posisi beda beda?").
- Exit value fallback chain: `t.manual_exit_vwap ?? t.close_price ?? t.exit_vwap ?? null`
  → render '—' while position still ACTIVE (no exit yet).
- PnL %: `t.pnl_pct` (signed, 2dp + '%'), '—' if null.
- Net USDT: `tradeNetUsd(t)`, colored `.pnl-pos`/`.pnl-neg`.
- The "R" column (result_r) was DROPPED from the day modal — if R is ever needed
  again it goes back as a 5th cell, not by reviving the isManual branch.

## Two distinct card-render surfaces (don't confuse them)
- `showDetail(dateStr, trades)` ≈ line ~940 — DAY modal opened from a calendar cell
  ("25 trades" header). Uses `.trade-grid` / `.trade-cell-label` / `.trade-cell-value`.
  THIS is the one shown in the screenshot; it now uses the uniform 4-col layout.
- `renderEntries()` ≈ line ~1128 — full Trades page list. Uses `.entry-grid` /
  `.entry-cell-label`. Still carries Entry/SL/TP1/TP2/TP3/R/PnL%/Net (richer plan view).
  If user asks to "samakan semua", confirm WHICH surface — they're separate code blocks.

## index.html is LIVE, not generated
`/root/calendar_app/public/index.html` is hand-edited directly — `build_unified.py`
only rewrites `trades.json`/`last_updated.json`, NOT the HTML. Patches to the HTML
survive rebuilds. (Don't go hunting for a template that regenerates it — there isn't one.)

## Trade Explainer (pipeline.html) — interactive Sankey pipeline (2026-06-23)
Standalone page `/root/calendar_app/public/pipeline.html` (~410 lines) visualizing the
6-stage trade decision flow in Transformer-Explainer style. Linked from the dashboard
sidebar as a plain `<a href="pipeline.html">` nav-item (icon ⊹), NOT a switchPage SPA
route — opening a standalone page is more robust and doesn't touch index.html routing.
- Content is full ENGLISH (user request) even though chat stays Indonesian.
- 5 pipeline columns (grid `212px 248px 206px 206px 212px`, natural width 1204px,
  auto-scale via `.scaler` + `fit()`): Signal → 8 Gates → Submit → Management → Outcome.
- Background cream `#F7F6F2`, white cards. `Run Signal` button animates 8 gates lighting
  up + status flow SUBMITTED→ACTIVE. Hover dims non-path ribbons (fill-based highlight).

### Sankey ribbon rendering — what actually worked
Goal: translucent flowing BANDS that widen/narrow (Sankey), not thin SVG strokes.
- DON'T use stroke-paths or a fan of many thin ribbons per row — at low opacity they
  read as "background bleed / AI-slop". First attempt was 25 thin ribbons → rejected.
- DO use a few BOLD full-height TRUNK ribbons: 5 trunks (card-edge to card-edge, height
  ≈ 0.86× card) + 4 lane-separated outcome bands = 9 ribbons total. Crisp, reads clean.
- `ribbon(p,x1,y1,x2,y2,t1,t2)` draws a filled band (thickness t1 at source, t2 at target).
  `edge(el,side)` returns `{x, y(center), h}` for full-height trunk anchoring.
  `addWire(a,b,group,color,t,tEnd,op)` is 7-arg; `highlight()` toggles fill/opacity
  (NOT stroke/strokeWidth — ribbons are filled paths now).
- OPACITY TUNING on cream bg is the make-or-break: 0.30 is far too faint (salmon/red
  worst). Final working alphas: teal `.52`, green `.72`, red `.66`, amber `.66`, plus a
  white edge stroke `.ribbon{stroke:rgba(255,255,255,.5);stroke-width:.6}` to define edges.
- Color = design language: teal = signal/validation phase, green = live/executed position,
  amber/red = BE/SL outcome. (User may ask to unify to one flowing color — single patch.)
- Emoji 📤 (outbox) misrenders as "cake" in the system font → use 📩 instead.

### Visual QA pitfall — browser_vision drifts badly, cross-check with vision_analyze
The `browser_vision` helper model is highly unreliable for fine visual-quality judgments:
across identical-direction improvements it swung 6→4→3→7.5 (random drift, not signal).
NEVER trust a single browser_vision rating for accept/reject decisions. Take an independent
`vision_analyze` read of the same screenshot and cross-check before concluding. In this
session vision_analyze correctly diagnosed the real issue (opacity too low on cream, shape
was already correct) while browser_vision kept falsely claiming "bare/missing ribbons".

## Scanner selector — multi-select winrate filter (2026-06-23)
Calendar page has a `.scn-selector` chip row (below the source/status filter pills,
above `.cal-grid`) letting the user pick ANY subset of scanners; stats cards (winrate,
net P&L, R, total) + calendar + Trades page then count ONLY selected scanners. Empty
selection = all scanners.

### Where scanner identity lives in trades.json (IMPORTANT)
- There is NO usable top-level `scanner` field — it is `None` for every record.
- The real key is `t.scanner_label.key` (e.g. `oi_divergence`, `breakout_retest`),
  with `t.risk_model` as the fallback and `'other'` as last resort:
  `(t.scanner_label && t.scanner_label.key) || t.risk_model || 'other'`.
- `scanner_label` = `{key, name, emoji}`, emitted by `_scanner_label()` in build_unified.
- Canonical 11 keys (+ emoji): aggressive ⚡, medium 🎯, safe 🛡️, counter_trend 🔄,
  alpha 🅰️, oi_divergence 📡, range_mr 📐, funding 📈, liq_cascade 💥,
  breakout_retest 🚀, manual ✋.

### Implementation pattern (vanilla JS, no framework)
1. `STATE.scannerFilter = new Set()` — empty means "all" (don't default to a list).
2. Add the scanner-key gate to BOTH filter funcs: `passes()` (calendar+stats) AND
   the inner `tradesPasses()` (Trades page) so the two surfaces stay consistent.
3. `buildScannerSelector()` injects chips fresh each toggle (removes old `.scn-chip`/
   `.scn-chip-clear`, keeps the label). Because it rebuilds the DOM, old chip element
   references go stale — re-query `#scn-selector .scn-chip` after a toggle, don't hold refs.
4. Toggle handler: add/delete key in the Set → `buildScannerSelector()` →
   `renderCalendar(); renderStats(); renderEntries();` (the full re-render trio).
5. Call `buildScannerSelector()` once in `load()` after the first render trio.
6. CSS: chips at `opacity:.45`, hover `.8`, selected `.on` = `opacity:1` +
   `box-shadow:0 0 0 2px var(--storm) inset` (ring). Reuse the existing `.scn-<key>`
   pastel bg classes so chip colors match the badges already on trade cards.

### Pitfall — inserting a line just before `} catch (e) {`
When patching the end of `load()` to add a call after the render trio, it's easy to
clobber the `} catch (e) {` line (replace tool matched the trio + catch together and
dropped the catch). Always re-read the few lines after the insert point and verify the
try/catch is intact, then `node --check` the extracted `<script>` block before browser test.

### Verification recipe (no manual clicking needed)
Drive `STATE.scannerFilter` directly via `browser_console` expression and read back
`#s-wr` / `#s-total` / `#s-wr-foot` for each subset — confirms the math, then one
`.click()` sim + screenshot confirms the UI. Live baseline this session: all=46.7%
(262), oi_divergence only=50.5% (94, 47W/46L), oi+breakout=46.7% (202).

## User preferences (CRITICAL)
- Font: Plus Jakarta Sans headings, Inter body. NEVER Cormorant Garamond (serif rejected)
- Additive-only: "tambahkan" = ADD, never delete/replace existing sections
- Prefer sidebar pages over cramming below calendar
- Independent filter state per page (don't share filters between Calendar and Trades)
- Compact output — user dislikes verbose responses
