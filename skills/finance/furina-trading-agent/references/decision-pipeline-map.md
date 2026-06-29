# Furina Decision Pipeline — signal → TP/SL (verified 2026-06-22)

End-to-end map of how a signal becomes a managed position. Verified against
`binance_real_executor.py` and `binance_real_reconciler.py`. Use this when the
user asks "how do you decide before entering" or for any executor/reconciler audit.
Quote the gate ORDER accurately — these run sequentially and short-circuit on the
first failure.

## Stage 1 — Scanner fire
10 scanners (aggressive / medium / safe / counter_trend / alpha + 5 trial:
oi_divergence, range_mr, funding, liq_cascade, breakout_retest) scan multi-TF.
Need ≥4/7 confirmations (MTF align, volume, BB squeeze, RSI+MACD, price action,
smart volume, TA+sentiment). Pass → write record to `automatic_signal_real_journal.json`
with symbol, side, entry, sl, tp1/2/3, and top-level `score` + `scanner_min_score`.

## Stage 2 — Executor validation gates (ALL must pass, in this order)
`process_record_for_scanner()` (~line 674) + `execute_signal()` (~line 451):
a. valid side/symbol + entry_mid>0 & sl>0 & tp1>0 → else SKIP `missing_*`
b. symbol resolves on Binance Futures perp (alpha tries `+USDT`) → else `symbol_not_on_futures`
c. bucket in ALLOWED_BUCKETS (AGGR_30M & MED_4H disabled) + alpha perp-volume validate
d. symbol blacklist — 2+ losses in last 14d → cooldown SKIP `symbol_blacklisted_X`
e. same-symbol guard — 1 pair = 1 active position max across ALL scanners (`symbol_already_active_X`)
f. Asia-session filter (00–08 UTC) — min_score +1 unless risk_model in ASIA_EXEMPT.
   MISSING top-level `score` → reads 0 → silent SKIP `asia_session_score_too_low_0_lt_N`
g. max concurrent — reject if active_count ≥ MAX_CONCURRENT_POSITIONS (10)
h. sizing — qty ≥ min_qty, notional ≥ min_notional & ≤ equity×leverage. Risk 1% flat
   (RISK_PCT=0.01; SL hit ≈ $10 on $1000 capped equity)
Any failure → status SKIPPED/ERROR, `skip_reason` logged, notif to Auto Signal, NO order.

## Stage 3 — Submit order
Set margin mode + leverage (idempotent; -4048 "open position" is tolerated).
Place LIMIT entry. SL STOP_MARKET follows AFTER fill (reduce_only needs a position;
placing before fill → -2021 "would immediately trigger"). Status → SUBMITTED.

## Stage 4 — Reconciler (every 5 min) — entry fill → ACTIVE
`reconcile_record()` only acts on status in {SUBMITTED, ACTIVE, TP1_HIT_BE, TP2_HIT_T1}.
- LIMIT FILLED → record avg fill + slippage, place SL & TP algos, status ACTIVE.
- LIMIT stale but price already swept the zone → `_maybe_fallback_to_market()`:
  one-shot MARKET entry if journal says ACTIVE and age ≥ LIMIT_FALLBACK_SECONDS;
  if signal already closed scanner-side → ERROR_PERMANENT, cancel residuals.
- SL-guard runs every tick: each open position must have a live STOP on Binance;
  naked → re-place (tightest earned SL, see testnet-eval-and-sl-guard.md) + alert.

## Stage 5 — TP/SL state machine (the trailing logic user cares about)
Transitions detected from `closed_qty = qty_total - live positionAmt` vs stored
`tp1_qty`/`tp2_qty` (works for old 50/25/25 and new 30/30/40 splits):
- status ACTIVE: closed_qty ≥ tp1_qty×0.8 → `_move_sl_to_be()` → status TP1_HIT_BE.
  Partial closes at TP1; SL moves to entry (breakeven); remaining runs RISK-FREE.
  (Soft-BE at +0.6R was REMOVED per user 2026-05-26 — do NOT touch SL before TP1.)
- status TP1_HIT_BE: closed_qty ≥ (tp1_qty+tp2_qty)×0.85 → `_move_sl_to_tp1()`
  → status TP2_HIT_T1. SL trails up to TP1.
- Exit: SL_HIT (full stop ≈ 1R loss), SL@BE (profit = TP1 only, capital safe),
  or TP3_HIT (runner closes at TP3/trail). TP3 rarely tags — trail usually stops
  the runner first; "TP3=0 across scanners" is expected, not a bug.

Every transition syncs to the dashboard near-real-time (entry, fill, TP, SL, BE, close).

## Rendering this as a shareable diagram (HTML → PNG, no Excalidraw)
Excalidraw needs drag-drop to web — impractical for Telegram delivery. Instead:
1. write a dark-theme single-file HTML flowchart to `/tmp/*.html` (palette: bg
   #0E1626, nodes #16223A, blue #7FB3FF process, green TP, red SL, gold BE;
   fonts Plus Jakarta Sans headings / Inter body to match dashboard).
2. `browser_navigate` to `file:///tmp/...html`, then `browser_vision` — its
   `screenshot_path` is a FULL-PAGE PNG (matches body.scrollHeight, not just viewport).
3. copy that PNG to /tmp and deliver via `MEDIA:/tmp/....png`.
Pitfall: don't write CSS hex values with placeholder words (e.g. `#3A4straight`) —
browser silently ignores them and borders vanish. Use real 6-digit hex and grep
for stray letters before rendering.
