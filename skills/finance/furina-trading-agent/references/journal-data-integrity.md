# Journal Data Integrity — status lifecycle & performance reads

How the Furina real journals (`automatic_signal_real_journal.json`,
`binance_alpha_real_journal.json`) track state, the invariants that must hold,
and how to read them correctly. Both learnings below were root-caused on
2026-06-16 from a "249 active positions but only 7 real on Binance" investigation.

## Two status fields, and they must agree

Every record has TWO status fields:
- **`record["status"]`** (top-level) — the journal's lifecycle marker. Set to
  `"WAITING_ENTRY"` when the scanner first appends the row.
- **`record["executor"]["status"]`** — the executor's outcome:
  `SUBMITTED / ACTIVE / SKIPPED / ERROR / ERROR_PERMANENT / PENDING_API / TP*_HIT / CLOSED`.

What counts as an "active position" everywhere (dashboard, same-symbol guard,
concurrent-position cap) is `status` ∈ `{ACTIVE, WAITING_ENTRY, PENDING, SUBMITTED, PARTIAL}`.

## BUG CLASS: phantom WAITING_ENTRY (status desync)

**Symptom:** journal reports hundreds of "active" positions
(e.g. 248) while Binance has only a handful (7). Performance/position counts are
wildly inflated; dashboard risks showing ghost entries.

**Root cause:** every guard/error early-return in `process_record_for_scanner` /
`execute_signal` set `executor.status = SKIPPED/ERROR/ERROR_PERMANENT` but
**never updated the top-level `record["status"]`**, which stayed `WAITING_ENTRY`
forever. A signal that was guarded out (Asia filter, concurrent cap, blacklist,
same-symbol, leverage error, etc.) and never reached Binance still looked
"active". On 2026-06-16: 216 SKIPPED + 19 ERROR + 8 ERROR_PERMANENT = 243
phantom records vs 5 genuinely ACTIVE + 2 TP1_HIT runners = 7 real on Binance.

**Root-cause FIX (one place, covers all 20+ early returns):** wrap the public
entry point instead of patching every return site. Rename the body to
`_process_record_for_scanner_inner`, and make the public function:

```python
def _sync_journal_status(record: dict) -> None:
    cur = (record.get("status") or "").upper()
    if cur not in ("WAITING_ENTRY", "PENDING"):
        return  # already finalized elsewhere — never clobber
    est = (record.get("executor") or {}).get("status")
    if est in ("SKIPPED", "ERROR", "ERROR_PERMANENT"):
        record["status"] = est

def process_record_for_scanner(record: dict) -> dict:
    res = _process_record_for_scanner_inner(record)
    _sync_journal_status(record)
    return res
```

**Critical: only finalize NON-executed terminal outcomes.** Mirror
SKIPPED/ERROR/ERROR_PERMANENT onto the top-level status. Deliberately leave
ALONE:
- `SUBMITTED / ACTIVE / TP*_HIT / CLOSED` — fill-detection (reconciler,
  entry-fill watcher) relies on the record sitting at WAITING_ENTRY until a fill
  flips it. Clobbering these breaks fill detection.
- `PENDING_API` (rate-limited) — must stay retryable.

Verify the sync helper with a status matrix (WAITING_ENTRY×each executor status →
expected top-level status) before declaring done. No network needed — stub
`binance_real_client` and exec the source in an isolated namespace.

**Before fixing, confirm no `executor.main()` cron retries the ERROR records.**
Scanners call `process_record_for_scanner` inline once per signal; if no cron
runs the executor's `main()` loop, ERROR is effectively final and safe to mirror.
Leverage errors ("Position side cannot be changed if there exists open orders")
are permanent for that signal — the pair is already occupied (see same-symbol
guard).

**Cleanup of pre-existing phantom records** is a SEPARATE one-shot step: backup
the journal, then for each `WAITING_ENTRY` record whose `executor.status` is
SKIPPED/ERROR/ERROR_PERMANENT, set top-level `status` to match; rebuild dashboard.

## Reading performance correctly (win rate / net PnL)

When computing per-scanner stats from the journals:

- **Net PnL per closed trade lives at `record["executor"]["real_net_pnl_usdt"]`**,
  NOT at top-level `result_r` (which is almost always `None` on these records).
  Reading `result_r` makes every scanner show 0% WR / $0 net — a false "all losses"
  signal. Always pull from `executor.real_net_pnl_usdt` and coerce to float.
- **Closed statuses:** `{TP1_HIT, TP2_HIT, TP3_HIT, SL_HIT, MANUAL_CLOSED, CLOSED}`.
- **Active statuses:** `{ACTIVE, WAITING_ENTRY, PENDING, SUBMITTED, PARTIAL}` —
  but post-fix, WAITING_ENTRY with a terminal executor status is NOT active.
- Group by `record["risk_model"]` for per-strategy WR/net/avg. Win = net > +$0.01,
  loss = net < -$0.01, else breakeven.
- A `TP1_HIT` record can still be a live partial runner on Binance (50% closed,
  rest at breakeven) — that is correct, not a desync. Reconcile journal vs
  `client._signed('GET','/fapi/v2/positionRisk',{})` (positionAmt≠0) before
  declaring anything lost or orphaned.

## Statistical guard for scanner go/no-go decisions

Don't shut down a low-WR trial scanner on a tiny sample. Rule of thumb used with
the user: wait until **≥30 closed trades per scanner OR a hard 7-day deadline**,
whichever comes first, before verdict. Exceptions:
- A scanner with **0 closes** (e.g. Liquidation Cascade in calm markets) is a
  FREQUENCY issue, not a WR issue — leave it running, different category.
- **Early-pension trigger** for a clearly-failing scanner: a worsening net trend
  (e.g. Range MR -$22 → -$30 while WR < 40%) signals broken entry logic, not
  variance — retire before the deadline. The real danger is failing to DECIDE,
  not deciding wrong.
