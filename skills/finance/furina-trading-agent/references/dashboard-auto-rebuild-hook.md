# Auto-Rebuild Web Dashboard on Close Events

Pattern for triggering downstream artifact regeneration (web dashboard,
report file, derived journal, etc.) **only when** trading state transitions
into a terminal/close state. Avoids noisy rebuilds on every reconciler tick.

## Trigger architecture (chosen approach)

**Inline subprocess fire-and-forget** at the end of the reconciler's `main()`,
gated by a `close_event_detected` flag set during the per-record loop.

Why this over alternatives:

| Approach | Latency | Decoupling | Pick? |
|---|---|---|---|
| Inline call (this) | ~5s after detect | low | ✅ simple, reliable |
| File-watch daemon | ~real-time | high | overkill, extra process |
| Hybrid flag-file + cron | up to 2min | high | ✅ if reconciler latency-sensitive |

Reconciler runs every 5 min (real) / 10 min (spot), so worst-case lag from
trade-close to dashboard-shown is one tick + ~5s rebuild → still feels
"live" to the user.

## Implementation pattern (reconciler)

### 1. Helper at module scope

```python
def trigger_dashboard_rebuild():
    """Fire-and-forget rebuild of web dashboard data after close events.

    Calls /root/calendar_app/build_unified.py via subprocess (background, no wait).
    Failures are silent — dashboard rebuild must never block the reconciler.
    """
    try:
        import subprocess
        subprocess.Popen(
            ["python3", "/root/calendar_app/build_unified.py"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        print(f"[dashboard-rebuild] {e}", file=sys.stderr)
```

Key flags:
- `Popen` not `run` — no `.wait()`, parent returns immediately.
- `start_new_session=True` — child detaches; reconciler can exit while
  rebuild is still running.
- `stdout/stderr DEVNULL` — never deadlock on pipe buffer fill.
- Bare-except logged but never propagated.

### 2. Define close states up front

```python
CLOSE_STATES = {"TP1_HIT", "TP2_HIT", "TP3_HIT", "SL_HIT", "MANUAL_CLOSED", "INVALID"}
```

Spot paper variant has different vocabulary (`SL_HIT_AFTER_TP`, no
`TP1_HIT/TP2_HIT` because TPs are partial fills, not state transitions —
spot only fully closes on TP3 or trailing stop):

```python
spot_close_states = {"TP3_HIT", "SL_HIT", "SL_HIT_AFTER_TP", "MANUAL_CLOSED", "INVALID"}
```

### 3. Snapshot prior status, compare after reconcile

```python
close_event_detected = False  # one flag per main() invocation

for rec in active:
    prior_status = rec.get("status")  # snapshot BEFORE reconcile_record mutates
    try:
        if reconcile_record(client, rec, notifs):
            new_status = rec.get("status")
            if new_status in CLOSE_STATES and prior_status != new_status:
                close_event_detected = True
    except ...:
        ...

# At very end of main(), AFTER all journals saved:
if close_event_detected:
    trigger_dashboard_rebuild()
    notifs.append("[dashboard] auto-rebuild triggered (close event detected)")
```

**Order matters:** rebuild fires AFTER `save_json()` writes the journal — the
build script reads from disk, not memory.

## Recency filter (spot variant)

Spot risk manager doesn't snapshot `prior_status` because it does multi-stage
state walks (`WAITING_ENTRY → ACTIVE → TP1_HIT → TRAILING → TP3_HIT/SL`).
Instead, scan all rows after the loop and trigger only if a close-state row
has a `closed_at` within the last 15 min:

```python
cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
had_close = False
for r in rows:
    if not is_spot_paper(r):
        continue
    if r.get("status") not in spot_close_states:
        continue
    close_ts = (r.get("executor") or {}).get("closed_at") or r.get("closed_at")
    if close_ts:
        try:
            close_dt = datetime.fromisoformat(close_ts.replace("Z", "+00:00"))
            if close_dt >= cutoff:
                had_close = True
                break
        except Exception:
            pass
if had_close:
    subprocess.Popen([...], start_new_session=True)
```

Cutoff prevents **rebuild loops** from old closed trades — without it, every
risk-manager tick would re-fire the rebuild on the same historic SL hit.

## Pitfalls

1. **Don't call `build_unified.py` synchronously.** Even on a healthy box it
   takes 3–10s; reconciler hard-interrupt is 3 minutes total, and a slow
   rebuild can starve the per-record loop.
2. **Don't rebuild on every dirty file.** Position fills (`SUBMITTED → ACTIVE`),
   TP1 partial moves, BE shifts, trailing-stop moves — none of these need a
   dashboard refresh. Only true close events do.
3. **Don't batch up the flag across runs.** `close_event_detected` is per
   `main()` call; if you persist it across ticks and a rebuild fails silently,
   the next tick re-fires unnecessarily. Re-detect each run from journal state.
4. **Cron tick budget.** Both reconcilers already use `no_agent=True` and
   stagger minute offsets to avoid Binance rate-limit collisions. Subprocess
   spawn is cheap but the rebuild itself reads many JSON files — if you ever
   move to a DB-backed journal, reconsider whether rebuild needs to scan the
   whole corpus or can incrementally update.

## Where the dashboard lives

- Build script: `/root/calendar_app/build_unified.py`
- Output JSON (web reads this): `/root/calendar_app/public/trades.json`
- Output meta: `/root/calendar_app/public/last_updated.json`
- Static index: `/root/calendar_app/public/index.html`
- Local server (no Cloudflare tunnel): `python3 -m http.server 8888 --bind 0.0.0.0`
  in `/root/calendar_app/public/` — user prefers localhost-only, **no public
  tunnel**, so don't reintroduce cloudflared. Earlier deploys used a quick
  tunnel; that was retired by user request.

## Verification recipe

After installing the hook in a new reconciler:

1. `python3 -c "import ast; ast.parse(open('binance_real_reconciler.py').read())"` — syntax check.
2. Run `python3 build_unified.py` manually once to refresh stale data.
3. Confirm `stat /root/calendar_app/public/trades.json` shows fresh `Modify` time.
4. Wait for next natural close event (or force one in a paper journal) and
   confirm `last_updated.json` mtime advances within ~1 cron tick.
