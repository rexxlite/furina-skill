# Demo/Testnet Mode + Per-Scanner Markers

Two reusable Furina configurations, captured 2026-06-12.

## A. Running the executor against Binance Demo (testnet) instead of paper

The executor (`binance_real_executor.py`) has three modes that share the same
code path: paper, demo/testnet, and real-money. Switching between them:

1. **Credentials/endpoint** live in `/root/.hermes/secrets/binance_real.env`:
   - `BINANCE_REAL_API_KEY`, `BINANCE_REAL_API_SECRET`
   - `BINANCE_REAL_BASE_URL` — **this is the mode switch**:
     - Real (mainnet): `https://fapi.binance.com`
     - Demo (testnet): `https://testnet.binancefuture.com`
   - Testnet keys are generated at testnet.binancefuture.com and ONLY work on
     the testnet endpoint (and vice-versa). A key/secret pair always comes
     together — Binance needs both to sign requests; key alone is useless.

2. **`PAPER_MODE` flag** (top of `binance_real_executor.py`):
   - `True`  → signals written to `paper_trades.json`, no API calls
   - `False` → real API calls to whatever `BINANCE_REAL_BASE_URL` points at
     (so demo and real both run with `PAPER_MODE=False`; the env URL decides
     which venue).

3. **Equity cap pattern** — testnet accounts are often pre-funded with an
   arbitrary balance (e.g. $5000) that doesn't match the simulation target.
   To simulate a specific equity (e.g. $1000) while the account holds more:
   ```python
   EQUITY_CAP = 1000.0
   # at every balance fetch:
   equity = min(client.available_balance_usdt(), EQUITY_CAP)
   ```
   There are TWO fetch sites (`process_record_for_scanner` path ~L747 and
   `main()` path ~L811) — cap BOTH. Verify with a one-liner that prints
   raw vs capped and `risk_dollar = capped * RISK_PCT`.

4. **Risk %**: `RISK_PCT` is the flat per-trade risk. `RISK_PCT_BY_BUCKET`
   overrides per bucket (audit boosted AGGR_15M/COU_4H to 0.75% on real money).
   For a clean flat-1% demo run, clear `RISK_PCT_BY_BUCKET = {}` so every
   bucket uses the same `RISK_PCT`.

5. **Notification format** — D2 label rule (user-approved 2026-06-14): NO
   `[DEMO]`/`[PAPER]` prefix in any notification; mode is obvious from channel
   context. Cron job names also clean ("Reconciler */5min", NOT "Binance REAL
   — Reconciler").

   **Rich multi-line template (user-approved 2026-06-25, supersedes the old
   single-line `fmt_label` format).** All trade-lifecycle notifs use a shared
   formatter module `furina_notif_format.py` (single source of truth, imported
   as `fnf` by BOTH `binance_real_executor.py` and `binance_real_reconciler.py`).
   Header keeps the scanner marker (option 2): `<emoji> [<SRC>-<bucket>] <SYM>
   Perp — <EVENT>`, then a Status line, Journal ID, a **Setup** block
   (Side / Entry / SL+risk% / TP1-3) and an **Update** block (Hit price /
   PnL from entry % / Result ±R / Action). Example TP1 HIT:
   ```
   🔄 [AS-Cou4h] XLMUSDT Perp — TP1 HIT

   Status: Running profit
   Journal ID: AS-COU-...-XLMUSDT

   Setup
   - Side: LONG
   - Entry: 0.181770
   - SL: 0.181770 (risk 0.81%)
   - TP1: 0.182952
   - TP2: 0.183986
   - TP3: 0.185020

   Update
   - Hit price: 0.182952
   - PnL from entry: +0.65%
   - Result: +0.80R
   - Action: Take profit 30% dan pindahkan SL sisa posisi ke entry / BE
   ```
   Formatter rules baked into `fnf`:
   - `fmt_submitted / fmt_entry_filled / fmt_tp1_hit / fmt_tp2_hit /
     fmt_soft_be / fmt_closed` — one helper per event; reconciler/executor
     just call them with the live SL price (BE/TP1) so Setup shows the
     trailed stop while risk% always reflects the ORIGINAL plan.
   - **R-multiple** = signed move ÷ |entry − original sl_price| (LONG vs SHORT
     handled). **risk%** = |entry − sl| / entry. Verify these on a real record
     before deploy: SL exit must read −1.00R, TP1 ≈ +0.8R, TP2 ≈ +1.5R.
   - Price precision scales with magnitude (`_fmt_px`): ≥100 → 2dp, ≥1 → 4dp,
     ≥0.01 → 6dp, else 8dp — so sub-cent coins keep meaningful digits.
   - Multi-line notifs are SAFE: both scripts emit notifs via stdout one
     element per `print`, and Telegram delivery handles embedded newlines.
   - **Deliberately single-line (NOT templated):** SKIPPED / ERROR executor
     lines, and reconciler *failure* alerts ("TP1 HIT but SL→BE failed",
     cleanup, exceptions). These are operational noise, not trade results —
     keep them terse. Only successful lifecycle events get the rich block.
   - Backups before this refactor: `*.bak.notiftpl.<ts>`.

6. **Blockers to clear before demo trades fire**:
   - `EXEC_PAUSE_REAL` flag file (set by risk_manager on drawdown breach) —
     `rm -f /root/.hermes/EXEC_PAUSE_REAL`. Silently blocks all execution.
   - `EXEC_KILL_REAL` — hard killswitch, also blocks.
   - Resume the real-money crons that were paused for paper mode: Reconciler,
     Risk Manager, Signal Monitor, Alpha Monitor, Entry Fill Watcher,
     Manual Sync. Pause the Paper Trade Watcher so it doesn't conflict.

### Leverage setup must be FAULT-TOLERANT, not fatal (fixed 2026-06-26)

`enter_position()` in `binance_real_executor.py` sets margin mode + leverage
before submitting the entry. The OLD code wrapped BOTH calls in one try and only
tolerated `-4048`, so any other "can't change while open orders/position exist"
rejection aborted the whole entry with `set_error("leverage_setup: ...")`. In the
2-week testnet eval this silently DISCARDED 26 valid signals (all ERROR records
had `bucket/lev/margin = None`, proving they died here before the order was sent —
they never created naked positions, but the signals were wasted).

**Key insight: leverage does NOT control our risk.** Position size is
`qty = (equity × risk%) ÷ |entry − SL|` — derived from SL distance, independent of
leverage. Leverage only controls (a) margin locked per position and (b) liquidation
distance. With CROSSED margin + an always-present SL at −1% to −3%, liquidation
(~−20% at 5x before other positions) is never reached while the SL lives. So a
margin/leverage no-op change is harmless — the existing setting stays and the trade
is still correctly sized. Aborting over it is pure signal loss.

**Fix pattern (apply when touching leverage setup):**
- Split margin and leverage into SEPARATE try blocks (a margin no-op must not skip
  the leverage call).
- Tolerate the whole family of "can't change with open orders/position" codes:
  `{-4046, -4048, -4061, -4067, -4068}` PLUS message-match on
  `"cannot be changed"` / `"no need to change"` (codes vary across endpoints).
  These are non-fatal — continue to order submission.
- Handle `"Leverage X is not valid"` / `-4028` by STEPPING DOWN
  (20→10→8→5→3→2→1, only values < requested) until one is accepted, instead of
  dropping the signal. Update the `leverage` local so the accepted value is what
  lands in the journal (`ex["leverage"]`). This also cleared the 5 "Leverage 6 not
  valid" ERRORs. Combined, 31 of 43 eval-window ERRORs are now executed instead of
  wasted.

### Leverage table (LEVERAGE_BY_BUCKET) — current, conservative by design
- OI_DIV 5x · COU_1H/COU_4H 5x · FUNDING 4x · LIQ_CASCADE 4x · ALPHA 4x
- trend legacy: AGGR 10x · MED 8x · SAFE 4x (rarely fire) · DEFAULT 8x
- Active real-money scanners sit at 4–5x — keep it there; do NOT raise. The
  `notional_exceeds_leverage_cap` gate (`max_notional = equity × leverage`) at
  $300 gives $1200–1500/position headroom, far above risk-sized notional, so it
  won't block valid signals. The knob that actually matters for small equity is
  MAX_CONCURRENT_POSITIONS (margin contention), not leverage.

### Signal → execution wiring (how a scanner reaches the venue)
- `automatic_signal_scanner_{aggressive,medium,safe,counter_trend}.py` are thin
  `os.execvp` wrappers that call `automatic_signal_scanner.py --mode X`.
- The main scanner, on a fired signal, appends a `WAITING_ENTRY` row to the
  regular journal, then calls `binance_real_executor.process_record_for_scanner(real_row)`
  on a copy appended to the REAL journal
  (`automatic_signal_real_journal.json`), then re-saves that journal.
- So `PAPER_MODE`/`BASE_URL` inside the executor fully decide the venue; the
  scanner's analysis logic is untouched by mode changes.

> To build a brand-new scanner STRATEGY (not just a marker for an existing one),
> see `references/adding-new-scanner-strategy.md` — full integration checklist
> plus the score-field / Asia-exemption / manual-sync-duplicate pitfalls.

## B. Per-scanner markers (Hasil Trade notifications + dashboard badges)

Goal: make each trade visually identifiable by which scanner produced it.

Identity source field: `risk_model` on auto records
(`aggressive`/`medium`/`safe`/`counter_trend`), or executor `bucket`
(`AGGR_*`/`MED_*`/`SAFE_*`/`COU_*`/`ALPHA`). Alpha uses its own journal.

Agreed emoji set (keep consistent across notification + dashboard):
- ⚡ Aggressive · 🎯 Medium · 🛡️ Safe · 🔄 Counter-Trend · 🅰️ Alpha · ✋ Manual
- 📡 OI Divergence · 📐 Range MR · 📈 Funding Extreme · 💥 Liq Cascade · 🚀 Breakout-Retest (5 trial scanners added 2026-06-13)

Three touch points (executor + reconciler + dashboard — all three must agree).
**As of 2026-06-25 the notification emoji/bucket/header logic lives in ONE
shared module `furina_notif_format.py`** (`scanner_emoji`, `bucket_short`,
`src_label`, `header`, plus the `fmt_*` event builders). Both the executor and
reconciler import it as `fnf` — so adding a new scanner means updating the
`_BUCKET_SHORT` dict + emoji map in `furina_notif_format.py` ONCE, not in two
files. (The executor/reconciler still keep their own legacy `bucket_short`/
`scanner_emoji` copies for the single-line SKIPPED/ERROR/failure lines; keep
those in sync too, or migrate them to `fnf` when you touch them.)
1. **Executor `emit_notification`** — SUBMITTED now delegates to
   `fnf.fmt_submitted(rec, sym)` (rich block). SKIPPED/ERROR stay inline
   single-line with `scanner_emoji` prefix.
2. **Reconciler `binance_real_reconciler.py`** — fire-and-forget life-cycle
   notifications route through `fnf.fmt_entry_filled / fmt_tp1_hit /
   fmt_tp2_hit / fmt_soft_be / fmt_closed`. Pass the live SL (BE or TP1 lock)
   so Setup shows the trailed stop. Failure/cleanup/exception lines stay plain
   single-line. The reconciler MUST share `fnf` with the executor or the two
   look inconsistent (raw bucket vs `Aggr15m`, missing emoji).
   When adding a new scanner strategy, register the bucket in
   `furina_notif_format._BUCKET_SHORT` + emoji map — forgetting it is the
   common miss.
3. **Dashboard `build_unified.py`** — add a `_scanner_label(t)` helper returning
   `{"key","name","emoji"}`, attach as `scanner_label` field in `normalize_auto`,
   `normalize_alpha`, and `normalize_manual` (give manual/alpha hardcoded labels).
   Frontend `index.html` renders `<span class="scn-badge scn-${key}">` with
   per-key pastel CSS classes, placed in the trade-row head before the src-badge.

Verify end-to-end by temporarily injecting one dummy record into the real
journal, running `build_unified.py`, checking `trades.json[0].scanner_label`,
then restoring the journal to its original content and rebuilding.

## C. Dashboard builder selection
- `calendar_build_paper_dashboard.py` (cron `a700b6110d65`) is a thin wrapper.
  Point it at `/root/calendar_app/build_paper_dashboard.py` for paper mode
  (reads `paper_trades.json`) or `/root/calendar_app/build_unified.py` for
  demo/real mode (reads the REAL journals, renders normal source labels with
  no "demo" wording). Switching modes = swap which builder the wrapper calls.
- `build_unified.py` `_is_real_executed()` filter drops WAITING_ENTRY,
  SKIPPED/ERROR/ERROR_PERMANENT, and records with no entry_order_id unless
  CLOSED — so trades only appear on the dashboard after the entry actually fills.
