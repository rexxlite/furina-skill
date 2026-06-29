# Furina Operational Systems — Recurring Patterns

Durable patterns for the Furina production trading agent (Binance Perps — paper or real mode, controlled by PAPER_MODE flag).
Distilled from sessions where these decisions had to be re-derived.

---

## 1. Real-Money Journal Filter (Dashboard / Reports / Stats)

Furina journals carry BOTH signals that hit Binance and signals that were
skipped/errored before reaching the matching engine. When building any
real-money view (dashboard, daily report, stats, win-rate), filter by
`executor.status`:

```python
EXEC_DROP_STATUSES = {"SKIPPED", "ERROR", "ERROR_PERMANENT"}

def is_real_executed(t):
    """True if record represents an order that actually hit Binance."""
    ex = t.get("executor")
    if not isinstance(ex, dict) or not ex:
        return False
    status = ex.get("status")
    if status in EXEC_DROP_STATUSES:
        return False
    # Limit orders submitted but never filled — don't show on dashboard
    if status == "WAITING_ENTRY":
        return False
    # Some ERROR rows have an entry_order_id but were rolled back —
    # require either a real order id OR final CLOSED state.
    if not ex.get("entry_order_id") and status != "CLOSED":
        return False
    return True
```

Apply this to:
- `automatic_signal_real_journal.json`
- `binance_alpha_real_journal.json`
- `automatic_signal_monitor.py` (cross-ref by `record.id` — see `monitor-cross-reference-bug.md`)

Typical filter ratios (so you can sanity-check counts):
- Auto-signal: ~55% kept (signals beat all the executor gates)
- Alpha: ~6% kept (Alpha tokens often fail perp_volume_too_low or
  symbol_not_on_futures gates — by design)

If your "kept" ratio is dramatically off from this, the filter is wrong.

---

## 2. OHLC Patterns: Match the Pattern Timeframe to the Trade Timeframe

The "Close Above/Below Prev High/Low" + "Multi-TF OHLC Confluence" patterns
(from Little Things channel @yourlittlething) work on Weekly and Monthly
OHLC as S/R, but ONLY for trades held over multi-day horizons.

**Hard rule:** Weekly/Monthly OHLC scoring belongs on Safe mode (4h/1D
signal) only. Aggressive (15m/30m/1h) and Medium (1h/4h) get noise from
W/M S/R because the price reacts faster than the level can stay relevant.

| Mode | TF | Weekly OHLC | Monthly OHLC | Reason |
|---|---|---|---|---|
| Aggressive | 15m/30m/1h | ❌ | ❌ | Scalp; W/M S/R irrelevant in 1-3h hold |
| Medium | 1h/4h | ❌ | ❌ | Intraday-to-swing; W/M misleading |
| Safe | 4h/1D | ✅ | ✅ | Multi-day hold; W/M directly relevant |
| Counter-Trend | 1h | ❌ | ❌ | Mean-reversion ignores higher-TF trend |

Full mode reference: `references/scanner-modes.md`

Implementation lives in `automatic_signal_scanner.py`:
- Per-mode flags `use_weekly_ohlc`, `use_monthly_ohlc`
- Klines for 1w/1M only fetched when flag is true (saves Binance rate limit)
- Wrap fetch in try/except — fail gracefully if symbol lacks long history

**Score weights when enabled:**
- Close above prev weekly high (LONG) / below prev weekly low (SHORT): +2
- Price near 2+ weekly OHLC levels (1% tolerance): +1
- Close above prev monthly high (LONG) / below prev monthly low (SHORT): +2

---

## 3. Dashboard Auto-Rebuild Hook Architecture

Web dashboard at `/root/calendar_app/` reads `trades.json` produced by
`/root/calendar_app/build_unified.py`. Two complementary triggers keep
it fresh:

**Inline trigger (real-time)** — `binance_real_reconciler.py` calls
`build_unified.py` as fire-and-forget subprocess WHEN it detects a status
transition into a CLOSE state:

```python
CLOSE_STATES = {"TP1_HIT", "TP2_HIT", "TP3_HIT", "SL_HIT", "MANUAL_CLOSED", "INVALID"}

# At end of reconciler main(), after journal save:
if close_event_detected:
    subprocess.Popen(
        ["python3", "/root/calendar_app/build_unified.py"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
```

Detect transitions by comparing `prior_status → new_status`, not just
"status is now CLOSED" — otherwise re-runs of stable rows trigger
useless rebuilds.

**Cron safety net** — `*/5 min` cron (`a700b6110d65`) runs builder
unconditionally. Catches edge cases where reconciler hook didn't fire
(crash mid-run, Telegram-only journal updates from manual close, etc.).

The two triggers are intentionally redundant. Inline is the
fast-path (~5 sec lag), cron is the recovery-path (max 5 min lag).

---

## 4. Cron Stagger Discipline

User cares about Binance IP rate limits. **Never schedule two API-hitting
cron jobs at the same minute mark.** Use random offsets like `:13/:23/:42`
not neat `:00/:05/:10`.

For non-critical monitors (Risk Manager, Reconciler, Funding Alert),
prefer 5-30 min frequency over per-minute when business logic allows.
The Risk Manager and Reconciler cluster at offsets like `1,6,11...` and
`2,7,12...` to interleave their REST calls across consecutive minutes.

---

## 5. Dashboard UI/UX Preferences

The trading calendar dashboard at `/root/calendar_app/public/index.html` has
been redesigned multiple times. User preferences that have stuck:

**Color palette — "Winter" (cool/calm/premium):**

```
--moonlight: #F0ECDD   /* main background, cream */
--frost:     #8BA3C5   /* secondary accent */
--steel:     #495B7D   /* secondary dark */
--storm:     #23354D   /* sidebar background, primary dark */
--oxford:    #02122F   /* text/contrast */
```

Layout reference: Pinterest pin 192458584071662394 (sidebar-left + cream
main + stat cards row + calendar grid). Keep the sidebar dark (`--storm`)
and main area cream (`--moonlight`).

**Typography — sans-serif only.** User explicitly rejected serif display
fonts (Cormorant Garamond) as "susah dibaca" (hard to read). For trading
data — numbers, P&L, ratios — readability beats elegance every time.

Use:
- **Plus Jakarta Sans** for headers, stat values, card titles (weight 600-800)
- **Inter** for body, labels, table cells (weight 400-600)

Both are loaded from Google Fonts. Apply tighter `letter-spacing: -0.3px to
-0.5px` on large display numbers so digits group readably without looking
like a marketing headline.

Do NOT propose serif display fonts again for this dashboard, even when
the requested vibe is "elegant/premium". Premium feel comes from spacing,
hierarchy, and the cool palette — not from a serif typeface.

**Centralize typography in CSS variables.** Don't hardcode
`font-family: 'Plus Jakarta Sans', ...` in 8 separate rules. Define
once and reuse so a future palette/style swap doesn't require finding
every occurrence:

```css
:root {
  --font-display: 'Plus Jakarta Sans', Inter, system-ui, sans-serif;
  --font-body:    'Inter', system-ui, sans-serif;
}
.page-title, .stat-value, .cal-month, .modal-title, .trade-sym,
.brand-text, .sf-value { font-family: var(--font-display); }
body { font-family: var(--font-body); }
```

This matters specifically because of section 5d below — without
variables, a rollback to an older `.bak.<timestamp>` file silently
resurrects the rejected serif font in every rule, and the user has
to flag it again.

**P&L color contrast on cream background:** default red/green on
`#F0ECDD` can lack contrast. Use slightly darker tokens (e.g. loss
`#8B3030` over default `#E04444`, win `#2E5F2E` over default `#22C55E`)
so the win/loss text reads cleanly without losing the muted palette.

**Event color tokens for trade dots/cells** (pastel, not saturated):
- TP Hit → `#E1ECDB / #3F5A33` (sage)
- SL Hit → `#F2DFDF / #6B3838` (rose)
- Active → `#DCE5F0 / #2E4664` (frost blue)
- Pending → `#ECE7D5 / #5D5238` (cream)
- BE / break-even → `#FAEFD6 / #715A2C` (amber)
- Manual Closed → `#E8E3F0 / #4B3E5F` (mauve)

**Sidebar menu labels for trading dashboards** — drop generic SaaS items
(Inbox, Notifications, Contacts, Upgrade-to-PRO). Use trading-relevant
items only: Dashboard, Calendar, Trades, Stats, Settings, Support. Footer
slot below the menu shows live Net P&L + closed-trade count, not an
upgrade card.

**Stats-scope toggle (per-month vs all-time):** the four stat cards above
the calendar should support a small toggle (`All Time` | `This Month`)
with `This Month` as default. When toggled to `month`, stats follow
`STATE.view` (the month currently rendered in the calendar) so the user
sees only that month's totals. Implementation pattern:

```js
STATE.statsScope = 'month'; // default

function inViewedMonth(t) {
  const closedAt = (t.executor||{}).closed_at || t.closed_at;
  const d = closedAt ? closedAt.slice(0,10) : t.bucket_date;
  if (!d) return false;
  const td = new Date(d + 'T00:00:00');
  return td.getFullYear() === STATE.view.getFullYear()
      && td.getMonth() === STATE.view.getMonth();
}

// Use executor.closed_at as the canonical bucket date for stats —
// a trade closed in June counts in June even if opened in May.
```

Two non-obvious rules that have stuck:

1. **Calendar nav (prev/next/today) must call `renderStats()` too**, not
   just `renderCalendar()`. Otherwise stats freeze on the originally
   loaded month while the calendar visibly moves — a confusing bug.
2. **Sidebar Net-P&L footer always shows all-time**, regardless of the
   stats-scope toggle. It's a stable mental anchor — "where am I overall"
   — that should not flicker when the user is just browsing months. If
   the user later asks for the sidebar to follow the toggle, it's a
   one-line change, but don't do it preemptively.

The stats-card heading text should reflect the scope: e.g. "Juni 2026
Performance" when `month`, "All-Time Performance" when `all`.

---

## 5b. Output Formatting in Trading-Ops Chat

The Furina chat lives on Telegram (operator's group, real-money topic).
The Hermes gateway's markdown→Telegram converter has known sharp edges,
and the user has flagged ugly output multiple times with screenshots
("teks balasan berantakan", "kenapa memanjang kebawah gini",
"kenapa ada kosong 1 enter dari tiap kalimat"). Use this format for ALL
trading-ops replies in this chat:

**Hard rules — these break Telegram rendering:**

- **No pipe tables.** Gateway rewrites `| col | col |` into row-group
  bullets and inserts `\n\n` between rows, producing ugly extra blank
  lines. Even a clean 4-row table looks like double-spaced spam.
  Use plain dash bullets with `:` or `—` separators.
- **No nested bold inside any structure.** `**bold**` inside `|...|`
  cells, inside list items that already start with `**Word**`, or
  inside another `**...**` produces stray `**` or `****` literals
  (Telegram parses `****foo****` as no-op).
- **No `##` / `###` headers in replies.** They render fine on most
  clients but add visual weight that fights the chat density. Prefer
  one-line bold labels.
- **No double newlines between bullets.** Single `\n` per bullet line
  is enough — gateway already inserts vertical breathing room.

**Preferred shape for status / market / scanner replies:**

```
Activity 6 jam terakhir:
- AUTO Real (5 scanner): 0 signal
- Alpha Real: 1 skipped
- Total real fired: 0

Market: BTC $61,768 (+1.4% 24h), 4h bullish, 1D bearish, mixed
Scanner: stuck (mixed bias blocks Aggressive/Medium/Safe)

Next runs:
- Counter-Trend 07:54
- Aggressive 08:00
- Safe 10:10
```

That structure scans fast, has no double-newlines, no tables, no
nested bold. The user's working tone is concise and operational —
match it.

**When you DO need denser data** (e.g. audit results across many
buckets), prefer aligned key-value bullets over a table:

```
Per-bucket audit (real money):
- AGGR_15M — N=10, WR 77.8%, totR +2.71, net +$5.89  STAR
- COU_4H   — N=4,  WR 75.0%, totR +1.34, net +$3.55
- AGGR_30M — N=26, WR 31.8%, totR -6.76, net -$14.59  LEAK
```

Pad the symbol column manually if it improves scanability — Telegram
respects the spacing inside a bullet.

---

## 5c. Don't Flip-Flop on Ambiguous UI Instructions

When the user issues a UI / styling instruction that contains an
internal contradiction — most commonly a color *name* that doesn't
match the *hex value* — STOP and ask one short clarification question
before executing. Examples that have actually fired:

- "ganti sidebar **navy** dengan kode warna `#F8F0E5`" — `#F8F0E5`
  is cream, not navy. Don't pick one and run with it.
- "main area **dark mode** pakai `#F0ECDD`" — `#F0ECDD` is cream.
- "**bg merah** pakai `#0E2A6A`" — `#0E2A6A` is navy.

The cost of one clarifying message is small. The cost of executing
the wrong interpretation is rebuilding the whole layout twice and
the user typing "jelek. kembali ke awal aja" (which actually
happened in this skill's source session).

Format the question so the user can answer with a single token:

> Yang mulia, `#F8F0E5` itu cream, bukan navy. Mau:
> 1. Sidebar cream `#F8F0E5` (sesuai hex)
> 2. Sidebar navy `#082052` (sesuai kata)
> 3. Hex lain
> Pilih nomor.

**Before any non-trivial layout flip** (swapping sidebar/main color
roles, switching light↔dark, redoing typography wholesale), confirm
the destination state explicitly even when the instruction looks
clear. Layout swaps cascade through 20+ CSS rules and are expensive
to undo. Always `cp index.html index.html.bak.<timestamp>` before
the first patch, and tell the user "backup tersimpan di `<path>`"
in your response so the rollback path is obvious.

---

## 5d. Rollback Hygiene — Don't Resurrect Rejected Decisions

When the user says "kembali ke awal" / "rollback" / "balik ke versi
yang bagus", you're tempted to `cp index.html.bak.<old-timestamp>
index.html` and call it done. **Don't.** Backups predate every
preference correction the user has issued *since* that backup, and
restoring blindly resurrects rejected decisions.

Concrete failure mode that happened in this skill's source session:
user wanted the layout reverted to "the version that was bagus" but
the most recent `.bak` predated the font swap from Cormorant Garamond
(rejected as "susah dibaca") to Plus Jakarta Sans. A blind copy
resurrected Cormorant in 8 hardcoded CSS rules. The user noticed and
had to ask again — costing trust in the rollback workflow.

**Mandatory checks before declaring a rollback "done":**

1. **Diff the rollback target against the rejected-decisions list.**
   For this dashboard the list lives in section 5 above:
   - sans-serif typography only (no Cormorant / Garamond / Playfair / serif)
   - Pinterest-reference layout (sidebar-left dark, main cream)
   - trading-relevant menu items (no Inbox/Notifications/Upgrade)
   - Plus Jakarta Sans + Inter as the only two font families
   - cool/winter palette (Moonlight/Frost/Steel/Storm/Oxford)

   Run a quick grep BEFORE saying "done":

   ```bash
   grep -E "Cormorant|Garamond|Playfair|serif" /root/calendar_app/public/index.html
   grep -E "Inbox|Notifications|Upgrade" /root/calendar_app/public/index.html
   ```

   If any of those return hits, the rollback is incomplete — patch
   them in the same response, don't ship a half-rolled-back state.

2. **Diff against features-added-since-backup, not just rejected
   decisions.** A backup taken at time T predates EVERY feature added
   between T and now, not only style corrections. Concrete bug from
   this skill's source session: rolling back to the pre-Étoile-palette
   `.bak` silently dropped the stats-scope toggle (section 5's
   "All Time | This Month" buttons) — user noticed only because the
   PnL toggle disappeared from the UI. Run a feature-presence grep
   that matches whatever was added recently:

   ```bash
   # Stats-scope toggle — must be present after section-5 work
   grep -E "stats-heading|scope-btn|statsScope|inViewedMonth" \
     /root/calendar_app/public/index.html | wc -l   # expect ≥10

   # Auto-rebuild hook signature (in reconciler) — section 3
   grep -n "trigger_dashboard_rebuild\|build_unified" \
     /root/.hermes/scripts/binance_real_reconciler.py
   ```

   If a feature grep returns 0, the rollback dropped that feature.
   Re-apply it in the same response. Maintain a short
   "features-added-since-last-bak" list in your working notes during
   any session that adds non-style functionality, so the rollback diff
   is mechanical instead of memory-dependent.

3. **Show the user what you actually restored.** State the timestamp
   of the backup you copied AND the corrections + features you
   re-applied on top. Format:

   > Rolled back to `index.html.bak.20260607_172148` (state when you
   > said "sudah bagus"), and re-applied: Plus Jakarta Sans typography,
   > stats-scope toggle (All Time | This Month), [other corrections
   > that happened after that backup].

4. **Prefer surgical revert over blind copy.** If only one aspect went
   wrong (e.g. just the colors), revert only the CSS variables, not
   the whole file. Preserves all the other corrections + features the
   user added since the last backup. Surgical revert dodges both the
   rejected-decision class (item 1) and the dropped-feature class
   (item 2) simultaneously.

5. **Backups are checkpoints, not ground truth.** Every `.bak.<ts>`
   file is a snapshot of "the state at that moment" — it does not
   automatically mean "the state the user wants now". The user's
   *most recent* preferences AND most recent feature additions
   override what's in any backup.

---

## 5e. Journal `status` vs Executor `close_kind` — Lifecycle Discipline

The Furina real journal carries TWO status fields that drift apart if not
maintained:

- `record["status"]` — **journal-level**, displayed on dashboard, used
  by daily reports + post-mortem
- `record["executor"]["close_kind"]` — **execution-level**, set by
  reconciler when the position is fully flat at Binance

**`TP1_HIT` is NOT a terminal status — it's an intermediate marker.**
After TP1 fills, the reconciler enters BE-trail mode (`TP1_HIT_BE`) and
the journal status sits at `TP1_HIT` while the runner is still open.
The position later exits via TP2 / TP3 / SL_BE / SL_T1, and at that
moment three things must happen atomically in the close handler:

1. `executor.status = "CLOSED"`
2. `executor.close_kind = "TP2_HIT"` (or whichever final exit fired)
3. `record.status = close_kind` (with SL_BE→MANUAL_CLOSED, SL_T1→TP2_HIT mapping)

**Failure mode that has actually happened:** the close handler had a
guard `if journal_status not in {"SL_HIT", "TP1_HIT", "TP2_HIT", ...}`
that included `TP1_HIT` in the skip set. So when a trade reached TP1
(BE-trail engaged, status=TP1_HIT) and then fully exited at TP2, the
guard skipped the status bump. Dashboard kept showing `TP1_HIT` for a
trade that was actually a `+1.84R / TP2_HIT` win. Telegram notif was
correct (it reads `close_kind` directly), so the divergence only
surfaces on dashboard / daily report.

**Correct guard logic** (in `binance_real_reconciler.py` close handler):

```python
journal_status = rec.get("status", "")
skip_update = False
# Truly terminal — these are user/manual-set, don't overwrite
if journal_status in ("MANUAL_CLOSED", "INVALID"):
    skip_update = True
# Anti-downgrade: don't let the no-match fallback overwrite a specific status
elif final_kind == "MANUAL_CLOSED" and journal_status in (
    "SL_HIT", "TP1_HIT", "TP2_HIT", "TP3_HIT"
):
    skip_update = True

if not skip_update:
    if final_kind == "SL_BE_HIT":   rec["status"] = "MANUAL_CLOSED"
    elif final_kind == "SL_T1_HIT": rec["status"] = "TP2_HIT"
    else:                            rec["status"] = final_kind
    rec[f"{final_kind.lower()}_at"] = now_iso()
    rec["closed_at"] = now_iso()
    rec["close_reason"] = f"binance_real:{final_kind}"
```

**Defensive normalizer in dashboard builder** (`build_unified.py`,
both `normalize_auto` AND `normalize_alpha`):

```python
ex = t.get("executor") or {}
exec_close_kind = ex.get("close_kind") if ex.get("status") == "CLOSED" else None
if exec_close_kind in ("TP1_HIT", "TP2_HIT", "TP3_HIT", "SL_HIT", "MANUAL_CLOSED"):
    status = exec_close_kind  # override stale journal status
```

This is belt-and-suspenders — the reconciler fix prevents the bug, the
normalizer recovers gracefully if any historical row already has
divergent fields. Apply BOTH; don't rely on just one.

**Backfill historical rows when fixing this class of bug:**

```python
# Walk both real journals, fix any record where:
#   executor.close_kind is TP2/TP3 but record.status is TP1_HIT (or ACTIVE)
# Always backup first:  cp <journal>.json <journal>.json.bak.<reason>.<date>
for r in data:
    ex = r.get("executor") or {}
    ck = ex.get("close_kind") if ex.get("status") == "CLOSED" else None
    js = r.get("status")
    if ck in ("TP2_HIT", "TP3_HIT") and js == "TP1_HIT":
        r["status"] = ck
        r.setdefault(f"{ck.lower()}_at", ex.get("closed_at"))
        r.setdefault("closed_at", ex.get("closed_at"))
        r.setdefault("close_reason", f"binance_real:{ck}")
    elif ck == "SL_T1_HIT" and js in ("ACTIVE", "TP1_HIT"):
        r["status"] = "TP2_HIT"
        r.setdefault("tp2_hit_at", ex.get("closed_at"))
        r.setdefault("closed_at", ex.get("closed_at"))
        r.setdefault("close_reason", "binance_real:SL_T1_HIT")
```

**Sanity check after any reconciler edit that touches close handling:**

```bash
# No record should be CLOSED in executor but stuck at TP1_HIT in journal
python3 -c "
import json
for path in [
  '/root/.hermes/trading_journals/automatic_signal_real_journal.json',
  '/root/.hermes/trading_journals/binance_alpha_real_journal.json',
]:
    for r in json.load(open(path)):
        ex = r.get('executor') or {}
        ck = ex.get('close_kind') if ex.get('status')=='CLOSED' else None
        if ck and ck != r.get('status') and r.get('status') not in ('MANUAL_CLOSED','INVALID'):
            print(f\"DRIFT  {r['id']}  journal={r.get('status')}  exec={ck}\")
"
```

If that script prints anything other than nothing, the close handler
or the backfill missed something.

---

## 5f. Reconciler Stale-Order Cleanup — Protection Gap (FIXED 2026-06-12)

The `cleanup_stale_open_orders()` function in `binance_real_reconciler.py`
cancels TP/SL orders on Binance for symbols that have no active position
AND are not in the `protected_symbols` set. This **was** a bug that caused
unprotected positions. **Now fixed with 3-layer protection.**

**Root cause chain (historical):**

1. `protected_symbols` was built ONLY from journal records whose
   `executor.status in ACTIVE_STATES` — `WAITING_ENTRY` was missing.
2. Manual entries set `executor.status = "WAITING_ENTRY"` → not protected.
3. Entries placed directly on Binance had no journal record → not protected.
4. Race condition in `manual_entry_executor.py`: orders submitted BEFORE
   journal logged.

**Concrete incident (2026-06-12):** STGUSDT and XPLUSDT entered via manual
chat. 6 TP/SL algo orders cancelled before entries filled. STGUSDT entry
filled → position with NO TP/SL protection.

**Deployed fix — `cleanup_stale_open_orders()` now has 3-layer protection:**

```python
# Layer 1: ACTIVE_STATES includes WAITING_ENTRY
ACTIVE_STATES = {"SUBMITTED", "ACTIVE", "TP1_HIT_BE", "TP2_HIT_T1",
                 "PENDING_API", "WAITING_ENTRY", "PENDING"}

# Layer 2: Symbols with pending (non-reduceOnly) LIMIT entries are auto-protected
pending_entry_symbols: set[str] = set()
for order in client.open_orders():
    symbol = order.get("symbol")
    order_id = order.get("orderId")
    reduce_only = str(order.get("reduceOnly", "false")).lower() == "true"
    if not symbol or not order_id:
        continue
    if not reduce_only:
        pending_entry_symbols.add(symbol)  # protect this symbol
        continue
    # ... cancel reduceOnly orders only if not in any protection set ...

# Layer 3: Full protection set = active_positions | journal_protected | pending_entries
full_protected = active_symbols | protected_symbols | pending_entry_symbols
for order in client.open_algo_orders():
    if not symbol or symbol in full_protected or not algo_id:
        continue
    # ... cancel stale algo orders ...
```

**Key insight:** The cleanup scan order matters — open_orders() must be
scanned FIRST to build `pending_entry_symbols` BEFORE algo orders are
checked. This ensures a symbol with a pending LIMIT entry never has its
pre-placed TP/SL cleaned up, regardless of journal state.

**Verification after any reconciler edit:**
```python
python3 -c "
import sys; sys.path.insert(0, '/root/.hermes/scripts')
from binance_real_reconciler import main
result = main()
for n in result.get('notifications', []):
    if 'cleanup' in n.lower():
        print(n)
"
```

If cleanup reports cancelling orders for a symbol that has pending LIMIT
entries, the fix is incomplete.

---

## 5g. Net PnL Across Multi-Leg Closes — Sum ALL Legs + Funding

When a position closes via multiple partial TPs (TP1→TP2→TP3, each a
separate Binance fill), the dashboard/journal "net usdt" must be the
**total across all legs**, not any single leg. Three numbers exist and
they are all correct — they just measure different things:

- **Binance app "Realized PnL" column** shows only the **LAST closing
  leg's** realized PnL (e.g. the TP3/runner close), NOT the whole trade.
  This is the #1 source of "dashboard vs Binance mismatch" questions.
- **`executor.real_pnl_usdt`** = sum of `realizedPnl` over ALL `user_trades`
  fills since entry (gross, all legs).
- **`executor.real_net_pnl_usdt`** = gross − commission **+ funding_fee**.
  This equals the actual Binance wallet delta for the whole trade.

**Concrete case (TAOUSDT, 2026-06-25):** closed in 3 legs —
TP1 +$7.98, TP2 +$10.88, TP3 +$13.16 → gross +$32.02. User saw "$13.15"
in the Binance demo app and asked which was right; that was just the
final leg. Total net = 32.02 − fee 0.37 − funding 0.06 = **+$31.59**.

**Ground-truth check — always pull `income_history` (per incomeType), not
`user_trades` alone.** `user_trades` carries realizedPnl + commission but
NOT funding. To reconcile against the wallet, aggregate income by type:

```python
inc = client.income_history(symbol=sym, start_time_ms=entry_ms-60_000, limit=1000)
from collections import defaultdict
agg = defaultdict(float)
for r in inc:
    agg[r["incomeType"]] += float(r["income"])
# agg["REALIZED_PNL"] + agg["COMMISSION"] + agg["FUNDING_FEE"] == wallet delta
```

**`_finalize_closed()` in `binance_real_reconciler.py` now includes funding
(fixed 2026-06-25):**

```python
pnl_total = sum(float(t.get("realizedPnl", 0)) for t in trades)   # all legs
fee_total = sum(float(t.get("commission", 0)) for t in trades
                if t.get("commissionAsset") == "USDT")
funding_total = 0.0
try:
    inc = client.income_history(symbol=symbol, income_type="FUNDING_FEE",
                                start_time_ms=start_ms, limit=200)
    funding_total = sum(float(r.get("income", 0)) for r in inc)
except BinanceRealError as e:
    ex["events"].append({"ts": now_iso(), "type": "RECONCILE_WARN",
                         "msg": f"funding income: {e.msg}"})

ex["real_pnl_usdt"]      = round(pnl_total, 4)
ex["real_fee_usdt"]      = round(fee_total, 4)
ex["real_funding_usdt"]  = round(funding_total, 4)        # new field
ex["real_net_pnl_usdt"]  = round(pnl_total - fee_total + funding_total, 4)
```

The CLOSED event msg + the close notif now both carry the breakdown:
`realized · fee · funding · net`.

**Pitfall: funding only matters on positions held over a funding stamp
(00:00 / 08:00 / 16:00 UTC).** Scalps that open+close between stamps have
funding_total = 0 and net == gross − fee. Long holds accrue multiple
stamps, so the gap between "sum of TP legs minus fee" and "wallet delta"
widens — that's the funding, not a bug.

**Backfill note:** older CLOSED rows predate the funding field. When a
user flags a specific old trade, patch its `real_net_pnl_usdt` directly
(gross − fee + funding from `income_history`) and rebuild the dashboard;
new closes self-populate. The `real_funding_usdt` field stays `None` on
backfilled rows unless you set it explicitly.

---

## 5h. Notification Dedup — one event, one source (Reconciler is canonical)

Two cron jobs can both detect and notify the same TP/SL event, producing
DUPLICATE Telegram messages (user dislikes this — "kenapa notif TRUMP 2x?").
The two sources:

- **Reconciler** (`binance_real_reconciler.py`, `067d187b9235`) — reads ACTUAL
  Binance fills (user_trades / income_history) → accurate prices + PnL.
- **Entry TP SL Monitor** (`automatic_signal_monitor.py`, `f4e7c0f7c8e2`) —
  polls PUBLIC mark-price and infers hits → approximate, no fill data.

**Decision (user-approved 2026-06-25): pause the Monitor, keep the Reconciler
as the single notif source.** Once all trades are executor-backed, the Monitor
is pure redundancy and its mark-price inference is strictly less accurate than
the Reconciler's actual-fill data. `cronjob action=pause` the Monitor
(`f4e7c0f7c8e2`); check whether the Alpha equivalent (`6762c84d2af3`) needs the
same treatment for the same reason.

**General rule:** when two systems can fire a notif for the same lifecycle event,
keep the one reading exchange ground-truth and silence the one inferring from
public data. Never "dedup" by hashing message text — kill the redundant SOURCE.

### Scanner-name label in notifications — 3-layer decode

The Monitor only showed the raw Journal ID, so the user couldn't tell which
scanner fired a signal ("signal SUSDT dari scanner mana?"). When a notif must
show the scanner name + emoji, decode in priority order (most reliable first):

1. **Journal-ID prefix** (most reliable): `AS-COU-…`→Counter-Trend, `AS-RMR-…`→
   Range MR, `AS-AGG-…`→Aggressive, `AS-OID-…`→OI Divergence, `AS-BRT-…`→
   Breakout-Retest, etc.
2. **`risk_model`** field (e.g. `counter_trend`, `range_mr`).
3. **`executor.bucket`** (e.g. `COU_4H`).
4. Fallback → 📊 Signal.

Use the prefix first because the regular journal sometimes lacks
`executor.bucket`. Emoji map: ⚡Aggressive 🎯Medium 🛡️Safe 🔄Counter-Trend
📡OIDiv 📐RangeMR 📈Funding 💥LiqCascade 🚀Breakout-RT 🅰️Alpha 📊fallback.

---

## 6. Killswitch Files

Three separate kill files — don't confuse them:

| File | Effect |
|---|---|
| `/root/.hermes/EXEC_KILL` | Spot paper executor halt (paper-only) |
| `/root/.hermes/EXEC_KILL_REAL` | Real Binance executor halt (real money) |
| `/root/.hermes/EXEC_PAUSE_REAL` | Auto-set by Risk Manager on drawdown breach |

Presence of `EXEC_KILL` does NOT block real money. Presence of
`EXEC_KILL_REAL` does NOT block paper trading. Verify the right one
when the user asks "is real money trading paused?"

**How the kill switch works:** The executor's `process_record_for_scanner()`
checks `KILL_FILE.exists()` as its FIRST gate. When present, it returns
`{"status": "killed"}` immediately — no order reaches Binance. The scanner
still runs, still generates signals, still logs to journal (with killed
status). This is the correct behavior for "pause execution but keep
scanning."

**To pause:** `touch /root/.hermes/EXEC_KILL_REAL`
**To resume:** `rm /root/.hermes/EXEC_KILL_REAL`

**Risk model (current as of 2026-06-10):**
- Manual chat entries: `RISK_PCT = 0.01` (1% of equity — user conviction)
- Automatic scanner signals: `RISK_PCT = 0.005` (0.5% — system-generated)
- Star buckets (AGGR_15M, COU_4H): `0.0075` (0.75%, proportional boost, scanner only)
- Cushion: `RISK_CUSHION = 0.93` (7% slippage+fee buffer)
- Leverage: varies by bucket (see binance-futures-execution skill)

---

## 6b. Manual Chat Entry Workflow (SOP v2 — 2026-06-12)

User can request trades directly from chat. Furina executes with **1% risk**
(higher than scanner's 0.5% because user conviction).

### ⚡ CRITICAL SOP — Entries + SL First, TP Deferred

**Finalized 2026-06-12 after ZECUSDT incident.** The sequence is:

1. **User provides:** entry area (2 limit prices), TP levels, SL price
2. **System immediately places:** LIMIT entries + SL (reduce_only=False, safe without position)
3. **TP is DEFERRED** until entries fill — watcher auto-places TP with `reduce_only=True`
4. **NEVER place TP with `reduce_only=False` before entries fill** — Binance opens opposite position

**Why TP is deferred:**
- `reduce_only=False` on a TP order = regular SELL/BUY order
- If TP trigger hits BEFORE entry fills → Binance opens OPPOSITE position
- ZECUSDT incident: TP2 ($441.62) triggered before entry fill → opened SHORT instead of closing LONG
- `reduce_only=True` REQUIRES existing position — placing before entries fill → HTTP 400 -2021
- Therefore: TP can only be placed AFTER entries fill (position exists)

**Why SL with `reduce_only=False` is safe:**
- For LONG: SL at $63000, entry at $64000, market at $65000
- Price must pass through $64000 (entry fills) before reaching $63000 (SL triggers)
- Entry ALWAYS fills before SL can trigger — no opposite-position risk

**NEVER use market orders for manual entries. Default: entries + SL first, TP on fill.**

### Execution Steps (inline script pattern)

```python
# STEP 1: Limit entries
r1 = client._signed('POST', '/fapi/v1/order', {
    'symbol': sym, 'side': 'BUY', 'type': 'LIMIT', 'timeInForce': 'GTC',
    'quantity': str(q1), 'price': str(e1), 'newClientOrderId': f'FM-E1-{ts}-{sym[:8]}'
})
r2 = client._signed('POST', '/fapi/v1/order', {
    'symbol': sym, 'side': 'BUY', 'type': 'LIMIT', 'timeInForce': 'GTC',
    'quantity': str(q2), 'price': str(e2), 'newClientOrderId': f'FM-E2-{ts}-{sym[:8]}'
})

# STEP 2: SL IMMEDIATELY (reduce_only=False — works without position)
sl_r = client.place_algo(sym, 'SELL', 'STOP_MARKET', total_qty, sl_price,
    f'FM-SL-{ts}-{sym[:8]}', reduce_only=False, working_type='CONTRACT_PRICE')

# STEP 3: TP IMMEDIATELY (reduce_only=False — works without position, safe because entry must fill first)
tp_ids = []
for i, (tp_price, tp_qty) in enumerate(tp_configs):
    try:
        tp_r = client.place_algo(sym, 'SELL', 'TAKE_PROFIT_MARKET', tp_qty, tp_price,
            f'FM-TP{i+1}-{ts}-{sym[:8]}', reduce_only=False, working_type='CONTRACT_PRICE')
        tp_ids.append(tp_r.get('algoId'))
    except BinanceRealError as e:
        if 'would immediately trigger' in str(e):
            # Market already past this TP level — rare edge case
            print(f'TP{i+1}: market above TP, deferred to watcher')
            tp_ids.append(None)
        else:
            raise

# STEP 4: Save to watcher state (for deferred TPs)
watcher_state[sym] = {
    'symbol': sym, 'side': 'LONG',
    'entry1_order_id': r1['orderId'], 'entry2_order_id': r2['orderId'],
    'sl_algo_id': sl_r.get('algoId'),
    'total_qty': total_qty, 'avg_entry': avg_entry,
    'entry1_filled': False, 'entry2_filled': False,
    'sl_price': sl_price, 'pending_sltp': True,
    'tp_configs': [{'price': p, 'qty': q, 'pct': pct} for (p, pct), q in zip(tp_configs, tp_qtys)]
}

# STEP 5: Dashboard sync
trade = {
    'symbol': sym, 'side': 'LONG', 'source': 'manual', 'status': 'WAITING_ENTRY',
    'created_at': now_iso, 'bucket_date': today_wib,
    'entry_price': avg_entry,
    'entry_orders': [
        {'entry_id': 'ENTRY_1', 'price': e1, 'qty': q1, 'status': 'NEW', 'order_id': r1['orderId']},
        {'entry_id': 'ENTRY_2', 'price': e2, 'qty': q2, 'status': 'NEW', 'order_id': r2['orderId']}
    ],
    'take_profits': [{'tp_id': f'TP{i+1}', 'price': p, 'qty': q, 'qty_pct': pct} for i, ((p, pct), q) in enumerate(zip(tp_configs, tp_qtys))],
    'stop_loss': sl_price, 'sl_algo_id': sl_r.get('algoId'),
    'risk_model': 'manual_chat', 'risk_pct': 1.0,
    'notes': 'SOP v2: limit + SL first, TP on fill'
}
```

### Risk Calculation

```python
equity = available_balance_usdt()
risk = equity * 0.01 * 0.99  # 1% risk, 1% fee cushion
avg_entry = (e1 + e2) / 2
sl_distance = abs(avg_entry - sl_price)
total_qty = risk / (sl_distance + avg_entry * 0.0004)
# Round to exchange step_size (from exchange_info)
```

### TP Split Patterns

- **2 TP:** 50% / 50% — standard swing
- **3 TP:** 40% / 30% / 30% — trend runner
- SL always covers 100% of total qty

### Multi-TP qty math

```python
tp1_qty = floor(total_qty * 0.40, step)  # or 0.50 for 2-TP
tp2_qty = floor(total_qty * 0.30, step)
tp3_qty = total_qty - tp1_qty - tp2_qty  # remainder (avoids rounding drift)
```

### Scripts

- `/root/.hermes/scripts/manual_entry_executor.py` — CLI for single/2-entry + 1 TP
- `/root/.hermes/scripts/entry_fill_watcher.py` — cron every 2min, handles:
  - Entry 2 fill detection → auto-adjust TP/SL qty
  - Deferred TP placement via `check_pending_sltp()`
  - Close detection → exit price + PnL → dashboard update
  - Live uPnL for active positions
- `/root/.hermes/scripts/dashboard_sync.py` — instant dashboard sync utility

### Risk Model (as of 2026-06-10)

- Manual chat entries: **1% equity** (user conviction)
- Automatic scanner signals: **0.5% equity** (system-generated)
- Star buckets (AGGR_15M, COU_4H): 0.75% (scanner only)

---

### Pitfalls (ALL from real incidents)

**⚠️ ZECUSDT Incident (2026-06-12) — TP created SHORT position**
Root cause: TP2 ($441.62) placed with `reduce_only=False` BEFORE entry fill.
Entry was at $404.88/$396.18 (below market $435). Market hit TP2 trigger price
before entry filled. Since `reduce_only=False` = regular SELL order, Binance
opened a NEW SHORT position instead of closing a (non-existent) LONG.
Closed by luck for +$0.26, but could have been a significant loss.
**Lesson:** NEVER place TP with `reduce_only=False` before entries fill.
TP MUST be deferred until position exists, then placed with `reduce_only=True`.
This incident finalized the SOP: entries + SL first, TP deferred.

**Pitfall: `reduce_only=False` on TP → opens opposite position.**
When placing TP (TAKE_PROFIT_MARKET) with `reduce_only=False` BEFORE entry fills:
- If price hits TP trigger → Binance opens OPPOSITE position
- For LONG TP (SELL): opens SHORT
- For SHORT TP (BUY): opens LONG
- `reduce_only=True` would prevent this but requires existing position
- Solution: defer TP until entries fill, then place with `reduce_only=True`
Root cause: SL was deferred along with TP. Entries filled at 11:50 WIB,
price crashed 16% in 18 minutes, position closed at 12:08 WIB with NO SL
protection. The `check_pending_sltp()` function was added to the watcher
AFTER this incident — too late for EPICUSDT.
**Lesson:** SL MUST be placed IMMEDIATELY with entries. Only TP is deferred.

**Pitfall: `reduce_only=True` without position → -2021 error.**
`place_algo(reduce_only=True)` fails when no position exists because
"reduce from zero" = immediately triggered. Use `reduce_only=False` for
SL when placing before entries fill. Safe because SL trigger is far from
market price.
```python
# WRONG (fails without position)
client.place_algo(sym, 'SELL', 'STOP_MARKET', qty, sl, cid, reduce_only=True)
# → HTTP 400 code=-2021 msg=Order would immediately trigger

# CORRECT (works without position)
client.place_algo(sym, 'SELL', 'STOP_MARKET', qty, sl, cid, reduce_only=False)
```

**Pitfall: TP price already below market → -2021 error.**
Even with `reduce_only=False`, TAKE_PROFIT_MARKET SELL fails if trigger
price is below current mark (condition already met). This happens when
market moves past TP levels between signal and execution.
Handling: catch error, mark TP as deferred, notify user.

**Pitfall: Some symbols require Algo Order API for conditional orders.**
`/fapi/v1/order` returns `-4120 "Order type not supported for this endpoint"`
for STOP_MARKET/TAKE_PROFIT_MARKET on some symbols (XPLUSDT, STGUSDT).
Always use `place_algo()` → `/fapi/v1/algoOrder` for SL/TP.

**Pitfall: Never use market orders for manual entries.**
User explicitly corrected this (2026-06-12): "Kenapa xpl market order?
Kan bisa limit?" Market entries at unfavorable prices when limit orders
at user-specified levels are the correct approach.

**Pitfall: Do NOT auto-cleanup/cancel limit orders still waiting.**
User explicitly stated (2026-06-12): "jangan diaktifkan auto cleanup
jika ada ticker limit." The reconciler's `cleanup_stale_open_orders()``
must protect pending LIMIT entries.

**Pitfall: SL/TP qty must match TOTAL entry qty, not just one entry.**
OPNUSDT incident: SL/TP was set for entry 1 qty (236) only. Entry 2
added another 236, total position 472. When price hit SL, only 236
was protected — half the position ran unprotected.
**Verification after placing orders:**
```python
# Run this after every manual entry to verify coverage
for sym in ['XPLUSDT', 'STGUSDT', ...]:
    orders = client.open_orders(sym)
    algos = client.open_algo_orders(sym)
    entry_qty = sum(float(o['origQty']) for o in orders if o['side'] == 'BUY')
    sl_qty = sum(float(a.get('quantity', 0)) for a in algos if 'STOP' in str(a.get('type', '')))
    tp_qty = sum(float(a.get('quantity', 0)) for a in algos if 'TAKE' in str(a.get('type', '')))
    expected = entry_qty  # or total_qty from watcher state
    assert abs(sl_qty - expected) < 0.01, f'{sym} SL MISMATCH: sl={sl_qty} expected={expected}'
```
Always verify SL qty = total of ALL entries immediately after placing orders.

**Pitfall: manual_binance_sync.py creates FALSE trades from TP hits.**
The sync script reconstructs trades from Binance `user_trades` history.
When a TP1 triggers (SELL partial qty from a LONG), the script interprets
the SELL as opening a SHORT position, and a subsequent buyback as closing
that SHORT. Result: phantom SHORT trades that never existed.
Incident (2026-06-12): ZECUSDT TP1 SELL at $423.81 was misinterpreted as
"ZECUSDT SHORT opened", buyback at $425.44 as "SHORT closed at -$0.13".
111 false trades were generated across multiple symbols.
**Mitigation:** After running manual_binance_sync, audit for false SHORT
trades that match LONG TP quantities. Better: disable sync script's
trade reconstruction and only use it for open position detection.
The user explicitly said "balik ke sistem seperti awal" (go back to original
system) — meaning only explicitly-executed trades should appear on dashboard.

**Pitfall: Dashboard JavaScript timezone — `toISOString()` shifts dates for UTC+N.**
The calendar's `fmt.date()` used `d.toISOString().slice(0,10)` which converts
to UTC. For WIB (UTC+7) browsers, `new Date(2026, 5, 12)` (June 12 local) →
`"2026-06-11T17:00Z"` → sliced to `"2026-06-11"`. This broke calendar dates.
**Fix:** Use local timezone components:
```javascript
date: d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`,
```

---

## 6c. Dashboard Manual Trade Sync

The dashboard now shows ALL trades from the Binance account — including trades
the user opened manually on Binance, not just Furina-executed signals.

**Script:** `/root/.hermes/scripts/manual_binance_sync.py`

**Architecture:**
1. Sync script reads `/fapi/v1/income` (REALIZED_PNL) + `/fapi/v1/userTrades`
   windowed in 7-day chunks (Binance API cap — naive single-call backfill returns only ~7 days)
2. Reconstructs closed position episodes from fills (walk chronologically,
   track signed qty, emit when pos→0)
3. Attributes: if fill's orderId matches a Furina `entry_order_id` → skip
   (already on dashboard via journals). Otherwise → manual trade.
4. **Open position sync** — after merge, calls `position_risk()` to find
   currently OPEN positions not tracked by Furina journals; emits
   `status: "ACTIVE"` records; removes stale ACTIVE records when position closes
5. Writes to `/root/calendar_app/public/manual_trades.json`
6. `build_unified.py` merges: automatic + alpha + manual = total

**Cron:** every 30 min at :18/:48 (staggered from scanner/reconciler ticks)

**Pitfall: bucket_date timezone — must use WIB (UTC+7) in BOTH backend AND frontend.** The dashboard
calendar shows dates in the user's timezone (WIB, UTC+7). Two independent timezone bugs have hit:

1. **Backend (Python):** `build_unified.py` derived `bucket_date` from UTC datetimes, so trades
   created after 17:00 UTC appeared on the WRONG calendar day (next day in WIB).
2. **Frontend (JavaScript):** The calendar's `fmt.date()` used `d.toISOString().slice(0,10)` which
   converts to UTC. For UTC+7 browsers, `new Date(2026, 5, 12)` (June 12 local) →
   `"2026-06-11T17:00Z"` → sliced to `"2026-06-11"`. This broke BOTH the "today" highlight AND
   the date-key lookup for trade dots. User reported: "klik tanggal 12 tapi yang masuk tanggal 11".

**Backend fix (already applied):**
```python
from datetime import datetime, timezone, timedelta
_WIB = timezone(timedelta(hours=7))

# In all 3 normalizer functions:
"bucket_date": bucket.astimezone(_WIB).date().isoformat() if bucket else None,
```

Same fix applies to `dashboard_sync.py`'s `_bucket_date_from_ts()` helper.

**Frontend fix (already applied in index.html):**
```javascript
// WRONG — converts to UTC, shifts date back for UTC+7
date: d => d.toISOString().slice(0,10),

// CORRECT — uses browser's local timezone (matches WIB for user)
date: d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`,
```

When adding new code that derives calendar dates from timestamps, ALWAYS
convert to WIB (backend) or use local timezone (frontend) — never use raw UTC dates.
The `toISOString()` trap applies to ANY JavaScript that formats dates for display
in non-UTC timezones.

**Pitfall: status must be specific, not "CLOSED".** When syncing closed trades
to the dashboard, pass the specific status (SL_HIT, TP_HIT) NOT generic "CLOSED".

**Dashboard UI markers (source attribution):**
- Filter pill "Manual" — isolates manual trades
- Calendar events: 🤖 Auto Signal, ⚡ Binance Alpha, ✋ Manual (icon before symbol)
- Modal: colored badge pill (`src-automatic` blue, `src-alpha` amber, `src-manual` mauve)
- Manual trades show "Exit VWAP" instead of "SL", "PnL %" instead of "R-multiple"
- Meta text: "opened on Binance" for manual, bucket+leverage for Furina
- Win/loss colors: green for profit, red for loss (by realized outcome via `tradeWinLoss()`)
- Stats (win-rate, net USD, lifetime P&L) include manual trades via
  `tradeNetUsd(t)` and `tradeWinLoss(t)` unified helpers
- Mobile: source icons hidden (dots only), modal badges still visible

**Dashboard filter: only real executed trades.** `build_unified.py._is_real_executed()`
drops WAITING_ENTRY (limit orders never filled), SKIPPED, ERROR, ERROR_PERMANENT.
Only ACTIVE, CLOSED, TP*_HIT, SL_HIT, MANUAL_CLOSED records reach the dashboard.

**Pitfall: Binance API 7-day cap.** `/fapi/v1/income` and `/userTrades`
silently return only ~7 days per call. Multi-month backfill MUST window
forward in 7-day chunks with both startTime+endTime. Run backfill as
background process (nohup), not inline — takes 3-5 min for 90 days.
See `binance-futures-execution/references/account-history-reconstruction.md`.

**Pitfall: incremental sync is fast, full backfill is slow.** Once state file
exists (`.manual_sync_state.json`), subsequent runs only query new income (~10s).
Don't `rm .manual_sync_state.json` unless you need complete re-sync.

**Pitfall: manual trades merged AS-IS — `normalize_manual()` is NEVER called.**
In `build_unified.py` lines 562-573, manual trades from `manual_trades.json` are
loaded and appended directly to the trades list WITHOUT going through any normalizer:
```python
# build_unified.py — manual section
manual_recs = load_json(MANUAL_PATH)
if isinstance(manual_recs, list):
    for r in manual_recs:
        if r.get("bucket_date"):
            trades.append(r)  # ← AS-IS, no normalize_manual() call
```
This means:
1. All fields the dashboard needs (`close_price`, `pnl_pct`, `manual_net_usdt`,
   `manual_close_pnl_pct`, `close_info`, `entry_orders`) MUST exist in the
   source `manual_trades.json` — the build won't derive them.
2. The `normalize_manual()` function at line 247 is DEAD CODE for new-style
   manual trades (from `manual_entry_executor.py` / `dashboard_sync.py`).
   It only applies to old-format trades with `events[]` and `entry_zone[]`.
3. After the build merges, `compute_pnl_pct(t)` runs on ALL trades. It checks
   `pnl_pct` first, then falls back to `manual_close_pnl_pct` and
   `close_info.pnl_pct`. If none are set, `pnl_pct` stays `None`.

**SAHARAUSDT incident (2026-06-12):** During a dedup cleanup of `manual_trades.json`
(reducing from 261 to 115 records), SAHARAUSDT was accidentally removed. It was
reconstructed from Binance `user_trades` + `income_history` API and re-added.
The dedup key was insufficient — it compared symbol+status but SAHARA had been
manually added alongside sync-reconstructed entries, causing a false duplicate match.

**Pitfall: `manual_binance_sync.py` dedup KeyError on missing `id` field.**
New-style manual trades (from inline execution) don't have an `id` field.
The dedup at line 390 used `r["id"]` → KeyError. Fix:
```python
# OLD (crashes on trades without 'id')
if r["id"] in seen: continue

# CORRECT (fallback to composite key)
rid = r.get("id") or f"{r.get('symbol','')}_{r.get('bucket_date','')}_{r.get('created_at','')}"
if rid in seen: continue
```

**Pitfall: STGUSDT lost during manual_binance_sync.**
The sync script overwrites `manual_trades.json` with synced data from Binance.
If a trade was added inline (not yet on Binance as a filled position), it gets
lost in the next sync cycle. The sync merges from `.manual_sync_state.json`
tracked trades + open positions. Inline-added trades with `pending_sltp: true`
that haven't filled yet are NOT in either source → dropped.
**Fix:** After adding inline trades, verify they survive a sync cycle. If lost,
re-add manually. Better fix: sync script should MERGE with existing trades
(not replace), preserving records with `status=WAITING_ENTRY`.

**When adding new fields to manual trades**, ensure:
1. The field is set in `manual_trades.json` source (by executor, watcher, or sync)
2. `compute_pnl_pct()` in `build_unified.py` knows to read it (add fallback if needed)
3. The dashboard JS (`index.html`) reads and renders it

**Pitfall: `compute_pnl_pct()` must check `manual_close_pnl_pct` and `close_info.pnl_pct`.**
The function at line 485 of `build_unified.py` checks `pnl_pct` first, then falls through to
price-level derivation. New-style manual trades carry PnL in `manual_close_pnl_pct` (from
`manual_entry_executor.py` / `dashboard_sync.py`), NOT in `pnl_pct`. Without fallbacks,
ALL new-style manual trades show `pnl_pct: null` on the dashboard. Fix:
```python
def compute_pnl_pct(rec):
    if rec.get("pnl_pct") is not None:
        return rec["pnl_pct"]
    # New-style manual trades carry pnl in alternate fields
    mcp = rec.get("manual_close_pnl_pct")
    if mcp is not None:
        return safe_float(mcp)
    ci = rec.get("close_info") or {}
    if ci.get("pnl_pct") is not None:
        return safe_float(ci["pnl_pct"])
    # Then fall through to TP/SL price-level derivation...
```

**Pitfall: integer-qty symbols (stepSize=1).** Some Binance symbols (e.g. XPLUSDT) have
`LOT_SIZE.stepSize = 1` and `quantityPrecision = 0`. Passing float qty like `568.038`
causes `HTTP 400 code=-4120 msg=Precision is over the maximum defined for this asset`.
Always check `step_size` after `exchange_info()` and convert to int when step_size >= 1:
```python
if step_size >= 1:
    qty = int(qty)  # integer-only symbol
```
Common culprits: newly listed tokens, low-price tokens with large circulating supply.

---

## 6cc. Dashboard Sync Utility (Real-Time from Chat Entries)

The `manual_binance_sync.py` handles periodic bulk sync, but chat-initiated trades
need INSTANT dashboard visibility. The `dashboard_sync.py` utility fills this gap.

**Script:** `/root/.hermes/scripts/dashboard_sync.py`

**What it provides:**
- `sync_trade_to_dashboard()` — adds/updates a trade in `public/manual_trades.json`
  in the exact schema `build_unified.py` expects (bucket_date, source, all fields)
- `rebuild_dashboard()` — triggers `build_unified.py` as subprocess
- `sync_and_rebuild()` — combined call (sync + rebuild in one)

**Who calls it:**
- `manual_entry_executor.py` — after submitting entries, syncs ACTIVE trade
- `entry_fill_watcher.py` — on entry2 fill (syncs ACTIVE with total qty) AND
  on position close detection (syncs CLOSED with realized PnL + close reason)

**Dedup logic:** matches on `symbol + entry_order_id + status in (ACTIVE, WAITING_ENTRY)`.
If a matching record exists, it UPDATES status/closed_at/pnl rather than creating
a duplicate. This prevents the same trade from appearing multiple times on the calendar.

**Pitfall: manual_trades.json path.** The file lives at
`/root/calendar_app/public/manual_trades.json` (inside `public/`), NOT at
`/root/calendar_app/manual_trades.json`. The build script reads from `public/`.

**Pitfall: bucket_date is required.** `build_unified.py` drops any record without
`bucket_date`. The sync utility auto-derives it from `closed_at` (for closed trades)
or `created_at` (for active trades), but if both are null, the trade won't appear
on the dashboard.

**Pitfall: close status must be specific.** When syncing a closed trade, pass the
specific status (SL_HIT, TP_HIT) NOT generic "CLOSED". The dashboard renders different
emojis/colors based on status. Use `status=close_reason` where close_reason is
determined by comparing exit price against SL/TP levels.

**Pitfall: dedup by symbol + entry_order_id.** When adding a trade that might already
exist (e.g. a sync-reconstructed entry vs a chat-initiated entry for the same symbol),
check for existing records before inserting. The dedup key is
`symbol + status in (ACTIVE, WAITING_ENTRY) + entry_order_id`.

---

## 6d. Chart-Based Manual Entry Workflow (Image → Execute → Learn)

User sends TradingView chart screenshots with entry/TP/SL pre-marked (yellow/green/red lines).
Furina analyzes the image, confirms details, executes on Binance, and logs the pattern for
scanner learning.

**Vision provider chain:**
- Primary model (mimo-v2.5-pro via xiaomi-tokenplan) does NOT support vision
- Current session model (kr/claude-opus-4.8 via omniroute) does NOT support vision
- **Fallback: bluesminds provider + gpt-4o** — call via direct HTTP to `https://api.bluesminds.com/v1/chat/completions` with base64 image in `image_url` content block
- API key: stored in `config.yaml` under `custom_providers` with `bluesminds` in the base_url
- Alternative models on bluesminds that support vision: `gemini-3.1-pro-preview`, `gpt-4o-mini`
- The image file path is provided by the system: `/root/.hermes/image_cache/<hash>.jpg`

**Vision analysis prompt template** (ask for ALL details):
```
Describe this trading chart in FULL detail.
1) Symbol/pair and exchange. 2) Timeframe. 3) Current price.
4) ALL entry points (yellow lines) — give exact prices for EACH yellow line.
5) ALL take profit levels (green lines) — exact prices.
6) ALL stop loss levels (red lines) — exact prices.
7) Any indicators visible. 8) Chart pattern or setup type.
9) Key support/resistance levels. 10) Any text/annotations.
Be very precise with prices — count ALL horizontal lines of each color.
```

**Charts use ZONES (rectangles/bands), not single lines.** The user marks
entry/TP/SL as colored HORIZONTAL ZONES on TradingView, where each zone
has a top and bottom price. When prompting the vision AI, ask for
"zones/rectangles/bands" not "lines". Example output format:
- Yellow zone (Entry): $0.18000 — $0.18576
- Green zone (TP): $0.14010 — $0.16150
- Red zone (SL): $0.19529 — $0.20392

For multi-entry from zones: use the zone edges as entry prices
(e.g. entry1 = bottom of yellow zone, entry2 = top of yellow zone).
For TP/SL: use the edge closest to entry (TP = top of green zone for LONG,
SL = bottom of red zone for LONG) for tighter risk, or the far edge for
more room. Confirm with user.

**Mandatory confirmation BEFORE executing chart entries:**
1. List ALL levels detected (entries, TPs, SLs) with exact prices
2. Confirm side (LONG/SHORT) based on entry vs SL positioning
3. Confirm risk % (default 1% for manual)
4. Ask user to confirm any ambiguous levels (especially when multiple SL lines exist)
5. **Ask user to confirm entry count** — vision AI sometimes misses lines. If user says
   there are more entries than detected, ask for the missing price(s)

**Pitfall: vision AI misses entries.** In the SAHARAUSDT session, GPT-4o detected only 1
yellow entry line but the chart had 2. User corrected: "Kenapa sahara hanya 1 entryan?
Kan ada 2 garis kuning di gambar." Always present detected levels and explicitly ask
"Ada entry lain yang terlewat?" before executing.

**Log chart analysis for learning pipeline:**
When executing from a chart image, log additional fields to the journal entry:
```python
{
    # ... standard journal fields ...
    "source": "manual_chat",
    "chart_analysis": {
        "timeframe": "15m",
        "pattern": "consolidation_breakout",
        "setup_type": "long_bounce",
        "key_levels": {"support": [0.01572, 0.01529], "resistance": [0.01704, 0.01784]},
        "indicators": ["RSI_oversold", "BB_squeeze"],
        "notes": "Higher low forming after decline, entry at support retest"
    }
}
```

**Learning pipeline (future):**
- Track which chart patterns produce profitable manual trades
- When pattern X accumulates 5+ wins → consider integrating as scanner confirmation
- Example: if "consolidation breakout on 15m" has 80% WR across manual trades,
  add a `use_consolidation_breakout` flag to Aggressive mode
- This is a MANUAL review process — Furina doesn't auto-add patterns to scanner
- Pattern log: `references/chart-analysis-patterns.md` — update after each chart entry
- **User explicitly requested this learning loop (2026-06-11):** "kalau kamu bilang
  entry manual dari gambar chart kamu pelajarin gimana dia analisanya, kalau profit
  tradenya kamu aplikasikan ke automatic trade." This is the primary feedback loop
  for improving scanner quality — manual chart trades ARE training data for Furina.

---

## 6e. Entry Fill Watcher — Multi-Entry TP/SL Auto-Adjustment + Close Detection

When a manual trade has 2 limit entries, TP/SL must cover the FILLED qty only,
not the total expected qty. If entry 2 hasn't filled yet and TP triggers, it
closes 100% of the partial position instead of the intended partial %.

**Root cause (VELVETUSDT incident, 2026-06-11):**
- Setup: 2 entries × 18 qty, TP1 = 50%, TP2 = 50%
- Entry 1 filled (18), entry 2 pending ($0.75114)
- TP/SL set for total qty 36
- TP1 triggered → closed ALL 18 units (100%) instead of 9 (50%)
- User lost the TP2 runner opportunity

**SOP (Standard Operating Procedure):**

Phase 1 — Initial setup:
1. Submit entry 1 & entry 2 as limit orders
2. Set TP/SL for **qty of entry 1 ONLY** (the one most likely to fill first)
3. Log to journal with both entry order IDs
4. Sync to dashboard via `dashboard_sync.sync_and_rebuild()` (ACTIVE status)

Phase 2 — Entry fill watcher (`entry_fill_watcher.py`, cron every 2min):
1. Scans `manual_chat_journal.json` for records with pending `entry2.order_id`
2. Checks order status via `cli.get_order(sym, order_id=e2_oid)`
3. If `FILLED`:
   a. Cancel all existing algo orders for that symbol
   b. Re-submit SL for **total filled qty** (entry1 + entry2)
   c. Re-submit TPs with correct split (40/30/30 or 50/50)
   d. Update journal: `status: "ACTIVE"`, `entry2_filled: true`
   e. Sync to dashboard via `dashboard_sync.sync_and_rebuild()`
   f. Output notification for cron delivery
4. State file at `~/.hermes/state/entry_watcher_state.json` tracks which
   entries have already been adjusted (prevents re-processing)

**Script:** `/root/.hermes/scripts/entry_fill_watcher.py`
**Cron:** `af8d381a9581`, every 2 minutes, `deliver: local`, `no_agent: true`

### Close Detection + Exit Price + PnL

The watcher monitors active manual positions for closes. It compares
`manual_chat_journal.json` ACTIVE records against `position_risk()` — if a
symbol disappears from open positions, it:
1. Fetches `income_history` for realized PnL (sum of REALIZED_PNL entries)
2. Fetches `user_trades` for exit price (calculate VWAP from closing trades)
3. Determines close reason by comparing exit price against SL/TP levels
   (within 0.2% tolerance: `last_price <= sl * 1.002` → SL_HIT)
4. Updates journal: status, closed_at, realized_pnl, close_price
5. Syncs to dashboard via `dashboard_sync.sync_and_rebuild()` with correct
   status (SL_HIT / TP_HIT, NOT generic "CLOSED")
6. Updates `manual_trades.json` with `close_price`, `manual_exit_vwap`, `pnl_pct`
7. State tracked in `entry_watcher_state.closed_synced[]`

**Dashboard fields required for closed trades to show PnL:**
- `close_price` — exit VWAP from Binance user_trades
- `manual_exit_vwap` — same value (dashboard HTML reads this field)
- `pnl_pct` — calculated: `(exit - entry) / entry * 100` for LONG, inverse for SHORT
- `manual_net_usdt` — realized PnL from Binance income_history
- `result_r` — `(exit - entry) / abs(entry - sl)` for LONG
- `status` — must be SL_HIT or TP_HIT, NOT generic "CLOSED" (dashboard uses status for emoji)

**Pitfall: status must be specific, not "CLOSED".** The dashboard renders:
- `TP_HIT` / `TP1_HIT` / `TP2_HIT` / `TP3_HIT` → ✅ green
- `SL_HIT` → ❌ red
- `CLOSED` / `MANUAL_CLOSED` → 🔵 blue (neutral)
Using generic "CLOSED" for a stop-loss hit shows the wrong color and confuses the user.

### Deferred TP Placement via `check_pending_sltp()`

Added 2026-06-12 after EPICUSDT incident. The watcher now handles deferred
TP placement for trades where SL was placed immediately but TP could not be
(e.g. market price above TP levels).

**Watcher state flag:** `pending_sltp: true` in `entry_watcher_state.json`

**Flow:**
1. Entry execution saves `pending_sltp: true` + `tp_configs[]` to watcher state
2. `check_pending_sltp()` runs every 2 min (on watcher cron)
3. For each `pending_sltp: true` entry:
   a. Check `get_order()` for entry1 + entry2 fill status
   b. If both filled → check `position_risk()` for actual position
   c. If position exists → place SL + TPs with `reduce_only=True` (now safe)
   d. Clear `pending_sltp: false`, update `manual_trades.json` to ACTIVE
4. If TPs would immediately trigger (market above TP), skip and notify

**Critical:** This function handles the case where entries fill but TP needs
to be placed AFTER fill. It does NOT replace the SL that was already placed
at execution time — it only adds the missing TPs.

### Live uPnL for Active Positions

Active positions show real-time unrealized PnL on the dashboard. The watcher
fetches `position_risk()` at the start of each run and updates `manual_net_usdt`
in `manual_trades.json` for all ACTIVE records. Dashboard is rebuilt at the end
of each watcher run to reflect the latest uPnL.

**Frequency:** Every 2 minutes (cron schedule). Acceptable lag for non-HFT manual trades.

**Pitfall: `check_closes()` only reads journal, not manual_trades.json state.**
The watcher's close detection (`check_closes`) iterates over `manual_chat_journal.json`
records. New-style trades placed via inline execution (not `manual_entry_executor.py`)
may only exist in `manual_trades.json` and `entry_watcher_state.json`, NOT in the
journal file. The `check_pending_sltp()` function handles the new-style path — it
reads from `entry_watcher_state.json` and updates `manual_trades.json` directly.
But close detection for these trades still relies on `check_closes()` reading the
journal. If a trade was placed inline without journal logging, it won't be detected
as closed by the watcher. **Always ensure manual trades are logged to BOTH
`manual_trades.json` AND `entry_watcher_state.json`.**

**Pitfall: SL/TP side depends on position direction.**
- LONG → SL is SELL (stop-market below), TP is SELL (take-profit above)
- SHORT → SL is BUY (stop-market above), TP is BUY (take-profit below)
Getting this wrong means the algo order is rejected or creates a hedged position.

**Pitfall: `get_order()` needs order_id, not client_order_id.**
The watcher uses `cli.get_order(sym, order_id=int(entry2_order_id))` because
journal stores the Binance orderId. If the journal has a clientOrderId instead,
the lookup will fail silently.

**Pitfall: order_id can be non-numeric placeholder.** Journal entries created
from inline execution (not via manual_entry_executor.py) may have placeholder
values like "opn_e1" or "pending" as order_id. The watcher guards against this
with `int(oid) if oid and str(oid).isdigit() else 0`.

**Pitfall: inline execution must also sync to dashboard.** When executing trades
inline in chat (not via `manual_entry_executor.py`), the trade won't auto-sync
to the dashboard. Always call `dashboard_sync.sync_and_rebuild()` after inline
execution, OR ensure the entry_fill_watcher picks it up from
`manual_chat_journal.json`.

### TP1 Hit SOP (Manual Trades)

When TP1 triggers on a manual chat entry:
1. 50% of position is closed at TP1 (via Binance algo order)
2. SL is NOT automatically moved to breakeven by the algo — this requires
   a manual cancel+re-submit of the SL algo order
3. TP2 runs risk-free for the remaining 50%

The entry_fill_watcher does NOT currently handle SL→BE after TP1. If the user
wants automated BE-trailing, the reconciler's TP1_HIT_BE logic (already in
`binance_real_reconciler.py`) would need to be extended to cover manual chat
entries. For now, Furina should notify the user when TP1 hits and offer to
move SL to breakeven.

---

## 7. Trading Mode Context Discipline

The system operates in ONE mode at a time: **paper**, **demo/testnet**, or **real**.
The current mode is determined by `PAPER_MODE` flag in `binance_real_executor.py`
PLUS the endpoint + keys in `/root/.hermes/secrets/binance_real.env`.

### 7.0 Demo / Testnet Mode (Binance Futures Testnet)

There are actually THREE operating modes, not two. Demo/testnet uses the
REAL execution code path (`PAPER_MODE=False`, real order submission) but
points at Binance's testnet matching engine — fake money, real order logic.
This is the best fidelity test of executor + reconciler + watcher behavior
without risking funds.

**Setup (only the env file changes — code path is identical to real):**

```
# /root/.hermes/secrets/binance_real.env
BINANCE_REAL_API_KEY=<testnet key>
BINANCE_REAL_API_SECRET=<testnet secret>
BINANCE_REAL_BASE_URL=https://testnet.binancefuture.com   # ← the only difference vs mainnet
```

- Mainnet (real money): `https://fapi.binance.com`
- Testnet (demo):        `https://testnet.binancefuture.com`
- Testnet keys are minted at testnet.binancefuture.com and are NOT
  interchangeable with mainnet keys — a mainnet key returns -2015
  (invalid API-key) against testnet and vice versa.

**Both key AND secret are mandatory.** Binance signs every private request
with HMAC-SHA256(secret). A key alone fails all signed calls (account,
order, balance). If the user pastes only one value, ask for the other
before doing anything.

**Verify connectivity before flipping any crons** — one Python probe
catches a wrong endpoint / wrong-network key immediately:

```python
from binance_real_client import BinanceRealClient
c = BinanceRealClient()
print('BASE:', c.base)          # confirm testnet vs mainnet
print(c.account().get('totalWalletBalance'))   # confirm key valid + balance
```

**Equity-cap pattern (EQUITY_CAP).** Testnet accounts are often funded with
a round number the user didn't choose (e.g. $5000) while the user wants to
simulate a different size (e.g. $1000). Risk sizing reads
`available_balance_usdt()` directly, so an uncapped $5000 makes 1% risk =
$50/trade instead of the intended $10. Cap it:

```python
EQUITY_CAP = 1000.0   # simulate $1000 regardless of actual testnet balance
# at BOTH fetch sites (process_record_for_scanner AND main):
equity = min(client.available_balance_usdt(), EQUITY_CAP)
```

After changing risk, also clear any per-bucket override
(`RISK_PCT_BY_BUCKET = {}`) if the user asked for a flat risk % across all
buckets — otherwise star buckets silently keep their boosted rate.

**Real Executor Audit Optimization (2026-06-07, 61-trade audit, 5 changes):**
1. `AGGR_30M` + `MED_4H` removed from `ALLOWED_BUCKETS`. `DISABLED_BUCKETS_AUDIT`
   set tracks audit-disabled vs phase-1-disabled buckets.
2. `RISK_PCT_BY_BUCKET` dict: `AGGR_15M` & `COU_4H` → 1.5% (star buckets, WR
   77.8% & 75%); `calc_qty(bucket=)` param added. (Cleared to {} in demo flat-risk mode.)
3. `get_blacklisted_symbols()` scans both real journals → dict[symbol→cooldown_iso]
   for symbols with 2+ losses in last 14 days, 48h cooldown after last loss.
4. Asia-session filter `is_asia_session_now()` (00-08 UTC = 07-15 WIB) bumps
   min_score +1 (`ASIA_SCORE_BUMP=1`). `get_scanner_min_score()` recovers from
   record.scanner_min_score / record.min_score / risk_model fallback (aggr=6,
   medium=7, safe=8, counter_trend=6). Trial scanners EXEMPT via ASIA_EXEMPT_RISK_MODELS.
5. `skip_reason` distinguishes `bucket_disabled_audit_X` vs `bucket_disallowed_X`.

**Pre-flight checklist when enabling demo/real execution** (learned the hard
way — each of these has blocked a trade silently):
1. `PAPER_MODE = False`
2. env has key + secret + correct base URL; connectivity probe passes
3. `EQUITY_CAP` set if simulating a smaller balance than the account holds
4. `RISK_PCT` set to the requested value; `RISK_PCT_BY_BUCKET` cleared if flat
5. **Remove `/root/.hermes/EXEC_PAUSE_REAL`** — the risk manager sets this on
   drawdown breach and it blocks the executor; it survives a paper→real flip
   and will silently kill every trade until removed. Also check `EXEC_KILL_REAL`.
6. Resume real crons (reconciler, risk manager, entry-fill watcher, monitors),
   pause the paper watcher (`paper_trade_watcher.py`) so the two don't fight.
7. Verify the signal→execution wiring: scanners are thin wrappers
   (`automatic_signal_scanner_<mode>.py` → `os.execvp` → `automatic_signal_scanner.py --mode X`).
   The real hook lives at the end of `automatic_signal_scanner.py` main():
   it appends the row to `automatic_signal_real_journal.json` and calls
   `binance_real_executor.process_record_for_scanner(real_row)`, which honors
   PAPER_MODE / KILL / PAUSE gates internally.

Note: demo mode still writes to the REAL journals
(`automatic_signal_real_journal.json` / `binance_alpha_real_journal.json`)
and the real dashboard (`build_unified.py`), NOT the paper journal. So the
dashboard "real money" view actually shows testnet trades while in demo mode.

**Dashboard cron-wrapper repoint (paper↔demo/real).** The dashboard build
cron (`a700b6110d65`) runs the wrapper
`/root/.hermes/scripts/calendar_build_paper_dashboard.py`, which `subprocess`-
calls ONE builder. The wrapper body must be rewritten when switching modes —
resuming/pausing crons alone is NOT enough:
- Paper mode  → wrapper calls `/root/calendar_app/build_paper_dashboard.py` (reads `paper_trades.json`)
- Demo/real   → wrapper calls `/root/calendar_app/build_unified.py` (reads the two REAL journals)

`build_unified.py` labels trades with normal `source` values
(`automatic`/`alpha`/`manual`) — there is no "demo"/"testnet" label anywhere,
so demo trades render exactly like real ones (this is what the user wants:
"track ke dashboard tapi jangan tulis demo, buat seperti biasa"). After
repointing, run the builder once by hand to confirm 0 errors and
`mode: real_only` in `last_updated.json`.

---

### Mode flag reference

### Current mode: PAPER (since 2026-06-12)

When PAPER_MODE is True:
- Scanner-generated signals → written to `paper_trades.json` (virtual entry, no Binance orders)
- Manual chat entries → use `paper_manual_entry.py` (not `manual_entry_executor.py`)
- TP/SL monitoring → `paper_trade_watcher.py` (fetches live prices, auto-closes on hit)
- Dashboard source → `paper_trades.json` only (via `build_paper_dashboard.py`)
- Virtual equity: $100 starting

When PAPER_MODE is False (real money):
- Scanner-generated signals → placed on Binance via `binance_real_executor.py`
- Manual chat entries → use `manual_entry_executor.py`
- TP/SL monitoring → `entry_fill_watcher.py` + `binance_real_reconciler.py`
- Dashboard sources → `automatic_signal_real_journal.json` + `binance_alpha_real_journal.json`

### Switching modes

**Paper → Real:**
1. Set `PAPER_MODE = False` in `binance_real_executor.py`
2. Resume real-money cron jobs (reconciler, risk manager, entry fill watcher, monitors)
3. Unpause the AS Monitor, Alpha Monitor crons
4. Dashboard build cron switches back to `build_unified.py`

**Real → Paper:**
1. Set `PAPER_MODE = True` in `binance_real_executor.py`
2. Pause real-money cron jobs (reconciler, risk manager, entry fill watcher, monitors)
3. Create/reset `paper_trades.json` to `[]`
4. Dashboard build cron points to `build_paper_dashboard.py`

### Concrete consequences
- Don't surface spot paper stats when asked about Furina performance.
- When the user says "fokus trading" without further qualification, check the current PAPER_MODE flag.
- In paper mode, audit/stats/dashboard source is `paper_trades.json`.
- In real mode, sources are the two real journals (see section 1).

---

## 8. Paper Trading System Architecture (since 2026-06-12)

The paper trading system mirrors the real-money architecture but writes to
`paper_trades.json` instead of placing Binance orders. All signals from
scanners are still generated — only the execution step changes.

### Data flow

```
Scanners (unchanged)
  ├── automatic_signal_scanner_aggressive.py  → automatic_signal_real_journal.json
  ├── automatic_signal_scanner_medium.py      → automatic_signal_real_journal.json
  ├── automatic_signal_scanner_safe.py        → automatic_signal_real_journal.json
  ├── automatic_signal_scanner_counter_trend.py → automatic_signal_real_journal.json
  └── binance_alpha_signal_scanner.py         → binance_alpha_real_journal.json

Executor (PAPER_MODE=True)
  └── binance_real_executor.py reads journals
      ├── PAPER mode: write to paper_trades.json (virtual entry, immediate fill)
      └── REAL mode: place Binance orders (when PAPER_MODE=False)

Watcher (paper mode)
  └── paper_trade_watcher.py (cron every 2m)
      ├── Fetches live prices from Binance public API
      ├── Checks SL/TP hits for OPEN paper trades
      ├── Closes trades with PnL calculation
      └── Updates unrealized PnL for open trades

Dashboard
  ├── build_paper_dashboard.py reads paper_trades.json
  └── Writes trades.json → served at localhost:8888
```

### Key files

| File | Role |
|---|---|
| `/root/calendar_app/public/paper_trades.json` | Paper trade journal (source of truth) |
| `/root/.hermes/scripts/binance_real_executor.py` | Executor with `PAPER_MODE=True` flag |
| `/root/.hermes/scripts/paper_trade_watcher.py` | Price monitor, auto-close on TP/SL |
| `/root/.hermes/scripts/paper_manual_entry.py` | Manual chat entries in paper mode |
| `/root/calendar_app/build_paper_dashboard.py` | Dashboard builder from paper journal |
| `/root/.hermes/scripts/calendar_build_paper_dashboard.py` | Cron wrapper for dashboard build |

### Cron jobs (paper mode active)

| Job | Schedule | Script | Deliver |
|---|---|---|---|
| Paper Trade Watcher | every 2m | paper_trade_watcher.py | telegram:129 |
| Paper Trading Dashboard Build | */5min | calendar_build_paper_dashboard.py | local |
| Aggressive Scanner | */15min | automatic_signal_scanner_aggressive.py | telegram:570 |
| Medium Scanner | 5,35 * * * * | automatic_signal_scanner_medium.py | telegram:570 |
| Safe Scanner | 10 */2 * * * | automatic_signal_scanner_safe.py | telegram:570 |
| Counter-Trend Scanner | 9,24,39,54 * * * * | automatic_signal_scanner_counter_trend.py | telegram:570 |
| Alpha Scanner | */15min | binance_alpha_signal_scanner.py | telegram:829 |

### Paused real-money crons (resume when switching to real)

- Binance REAL — Reconciler (067d187b9235)
- Binance REAL — Risk Manager (cd3a04b52889)
- Entry Fill Watcher (af8d381a9581)
- Binance WS Monitor — Watchdog (d6634a912a1b)
- Manual Binance Sync (9f287b40e73e)
- AS Entry TP SL Monitor (f4e7c0f7c8e2)
- Alpha Entry TP SL Monitor (6762c84d2af3)
- AS Trailing Stop Risk Manager (31871b9a302f)

### Manual entry in paper mode

```bash
python3 /root/.hermes/scripts/paper_manual_entry.py BTCUSDT LONG 64000 63000 66000
```

This writes directly to `paper_trades.json` with `source: "manual_chat"` and
triggers a dashboard rebuild. The paper watcher monitors TP/SL automatically.

### Paper trade PnL calculation

```python
# LONG
pnl_pct = ((close_price - entry_price) / entry_price) * 100 * leverage
pnl_usdt = (close_price - entry_price) * qty

# SHORT
pnl_pct = ((entry_price - close_price) / entry_price) * 100 * leverage
pnl_usdt = (entry_price - close_price) * qty
```

### Pitfalls

- **Paper watcher uses Binance public API** — no auth needed, no rate limit
  issues for price checks. But if Binance is down, watcher will skip and
  retry next cycle (2 min lag).
- **Paper trades fill instantly** — no limit order waiting. The entry price
  is the signal's mid-price, not a real fill price. This means paper results
  will be slightly optimistic vs real fills (no slippage).
- **Virtual equity is fixed at $100** — does not compound. Each trade risks
  the same dollar amount regardless of prior wins/losses. Real equity would
  fluctuate.
- **No position limit enforcement** — paper mode doesn't check MAX_CONCURRENT_POSITIONS.
  If 10 signals fire simultaneously, all 10 become paper trades. Real mode caps at 5.

## 9. Audit-Driven Executor Optimization Workflow

When the user asks to audit Furina real trading (or you offer it after a
chunk of closed trades has accumulated), follow this workflow. It works
on top of the journal filter from section 1.

### 9.1 Audit aggregations to compute

Run all four against the filtered real-executed trades. The dataset is
small (60-200 trades typical), so plain Python + collections.Counter is
sufficient, no pandas needed.

| Aggregation | Group key | Metrics | Purpose |
|---|---|---|---|
| **Per-bucket** | `executor.bucket` (AGGR_15M, MED_1H, …) | N, WR, sum(R), sum(net_usd) | Find leak/star buckets |
| **Per-session** | UTC hour → Asia/Europe/US (07-15 / 15-22 / 22-07 WIB) | N, WR, sum(R) | Find best/worst trading hours |
| **Per-symbol losses** | `executor.futures_symbol`, filter to losses | count, sum(net_usd) | Find systemic-bias symbols |
| **Per-side** | `side` (LONG/SHORT) within bucket | WR | Spot one-sided edges |

R is `executor.real_net_pnl_usdt / executor.risk_dollar`. Use that, not
journal `result_r`, because the journal field can lag or be null on
manually closed rows.

### 9.2 Decision rules (what is a leak vs noise)

- **Leak bucket** = N ≥ 8 AND (WR < 40% OR sum(R) < -2.0 OR sum(net_usd) < -$5).
  Disable. Sample size matters — 3 trades at 0% WR is noise, not a leak.
- **Star bucket** = N ≥ 8 AND WR ≥ 60% AND sum(R) > +1.0. Boost RISK_PCT
  by 50% (1.0% → 1.5%), don't go higher without more data.
- **Repeat-loss symbol** = 2+ losses in trailing 14 days. Blacklist with
  48h cooldown after last loss. Threshold tuned to ~60 trades/month
  dataset; if the dataset doubles, raise threshold to 3.
- **Bad session** = WR < 50% AND sum(R) < -1.0 across 15+ trades. Don't
  disable the session entirely — bump min_score by +1 to filter chop.

### 9.3 Where the optimization belongs: EXECUTOR, not scanner

Implement audit-derived risk controls in `binance_real_executor.py`,
not in `automatic_signal_scanner.py`. Reasons:

1. **Single point of control.** Scanner stays focused on signal generation;
   one place to read/audit all risk gates.
2. **No cross-contamination of paper journal.** Scanner edits would also
   change paper-journal behavior (which the user doesn't want filtered
   the same way).
3. **Reversibility.** Re-enabling a bucket = adding one string to a set.
   Re-tuning scanner logic is days of work and bug-prone.

### 9.4 Concrete code patterns (already in executor)

```python
# Bucket allowlist with audit-disabled tracking
ALLOWED_BUCKETS = {"AGGR_15M", "AGGR_1H", "MED_1H", "SAFE_4H", "SAFE_1D",
                   "COU_1H", "COU_4H", "ALPHA"}
DISABLED_BUCKETS_AUDIT = {"AGGR_30M", "MED_4H"}  # for clearer skip_reason

# Per-bucket RISK_PCT — only star buckets get a key, default 1.0%
RISK_PCT_BY_BUCKET = {"AGGR_15M": 0.015, "COU_4H": 0.015}

def calc_qty(equity, entry, sl, step_size, bucket=None):
    risk_pct = RISK_PCT_BY_BUCKET.get(bucket, RISK_PCT) if bucket else RISK_PCT
    # ...

# Symbol blacklist — recompute on every signal (cheap, ~140 records)
BLACKLIST_LOOKBACK_DAYS = 14
BLACKLIST_LOSS_THRESHOLD = 2
BLACKLIST_COOLDOWN_HOURS = 48

# Asia session score bump
ASIA_SESSION_UTC_START = 0   # 07 WIB
ASIA_SESSION_UTC_END = 8     # 15 WIB
ASIA_SCORE_BUMP = 1
```

### 9.5 Skip-reason labeling for audit traceability

Distinguish reason classes in `executor.skip_reason` so the next audit
can tell which control prevented a trade:

- `bucket_disabled_audit_<NAME>` — disabled by an audit finding
- `bucket_disallowed_<NAME>` — disabled by phase-1 / not yet enabled
- `symbol_blacklisted_<SYMBOL>` — repeat-loss filter triggered
- `asia_session_score_too_low_<got>_lt_<required>` — session filter
- `max_concurrent_<N>` — concurrency cap
- `risk_paused` — `EXEC_PAUSE_REAL` set by risk manager

Future audits should count skip events per reason to validate the
filters are catching what they should and not over-blocking.

### 9.6 Pitfalls

- **Don't rebuild the scanner** when the audit points to a risk-allocation
  problem. The 31% WR on AGGR_30M wasn't a "scanner bug" — it was a
  size + leverage + TF-noise mismatch fixed at executor level.
- **Don't confuse signal count with executed count.** Auto-signal real
  journal is ~55% kept; Alpha is ~6%. Audits must read from the
  filtered set (section 1), otherwise `executor.real_net_pnl_usdt` is
  null on most rows and Net$/R sums are misleading.
- **Don't forget timedelta import.** When adding the blacklist function
  to executor, the existing `from datetime import datetime, timezone`
  needs `, timedelta` — easy to miss because `datetime.now()` works
  without it.
- **Forecasted impact is asumsi pola berulang.** State the forecast as
  a hypothesis to validate over 2-4 weeks of fresh trades, not as a
  promise. Re-audit after that window before making more changes.
