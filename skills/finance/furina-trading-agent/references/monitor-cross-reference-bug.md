# Monitor Cross-Reference Bug (2026-06-11)

## Problem
`automatic_signal_monitor.py` reads the **regular** journal (`automatic_signal_journal.json`)
which has NO `executor` field. The executor status lives only on the **real** journal copy
(`automatic_signal_real_journal.json`).

When the real executor fails (e.g. "Margin type cannot be changed if there exists open orders"),
it sets `executor.status = "ERROR"` on the real journal entry. But the monitor doesn't know —
it tracks price against the entry/TP/SL levels and sends false notifications like "TP2 HIT"
for positions that were never opened on Binance.

## Root Cause
The scanner writes to two journals:
1. Regular journal (`automatic_signal_journal.json`) — signal + TP/SL levels, NO executor field
2. Real journal (`automatic_signal_real_journal.json`) — same signal + executor sub-document

The monitor reads only the regular journal. It has no way to know if execution succeeded or failed.

## Fix Pattern
Cross-reference the real journal by matching `record.id`:

```python
REAL_JOURNAL = Path.home() / ".hermes" / "trading_journals" / "automatic_signal_real_journal.json"
EXEC_DROP_STATUSES = {"SKIPPED", "ERROR", "ERROR_PERMANENT"}

def load_real_exec_statuses():
    if not REAL_JOURNAL.exists():
        return {}
    try:
        rows = json.loads(REAL_JOURNAL.read_text())
        return {r["id"]: (r.get("executor") or {}).get("status", "") for r in rows}
    except Exception:
        return {}

# In per-record loop, BEFORE evaluating TP/SL:
real_statuses = load_real_exec_statuses()
for rec in records:
    real_status = real_statuses.get(rec.get("id"), "")
    if real_status in EXEC_DROP_STATUSES or real_status == "":
        continue
```

## Key Insight
This is the SAME bug class as the dashboard builder filter (operational-systems.md §1),
but applied to the notification pipeline. Every consumer of journal data that assumes
"record exists → real position exists" must independently verify executor status.
The monitor, dashboard, and daily reports each read from slightly different paths,
so the guard must exist in each consumer.

## Real Journal Filter (canonical — same as operational-systems.md §1)
```python
EXEC_DROP_STATUSES = {"SKIPPED", "ERROR", "ERROR_PERMANENT"}
# Also drop: empty executor dict, WAITING_ENTRY (limit never filled)
# Keep: SUBMITTED, ACTIVE, TP1_HIT_BE, CLOSED
```
