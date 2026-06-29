# EPICUSDT Incident — 2026-06-12

## Summary
EPICUSDT LONG entries filled at 11:50 WIB, price crashed 16% in 18 minutes.
Position closed at 12:08 WIB with NO SL protection. Loss: **-$13.78 (4.9% equity)**.

## Timeline
- 11:50 WIB — Limit entries filled (70.9 @ 0.6263 + 71 @ 0.6130)
- 11:50-12:08 — Price dropped from ~0.62 to 0.52 (no SL to cut loss)
- 12:08 WIB — Position closed at 0.5229 (likely manual or liquidation)
- Total realized PnL: -$13.78 (REALIZED_PNL + COMMISSION)

## Root Cause Chain
1. SL algo placement failed at order time (`reduce_only=True` without position → -2021)
2. The `check_pending_sltp()` function in entry_fill_watcher.py did NOT exist yet
3. The watcher ran every 2 min but had no logic to auto-place SL/TP on fill
4. By the time SL placement code was added, the position was already closed at a loss

## What Changed After This Incident
1. **SOP v2 established** — SL placed immediately with entries (`reduce_only=False`), TP deferred
2. **`check_pending_sltp()` added to watcher** — auto-places SL/TP when entries fill
3. **User explicitly stated:** "jangan diaktifkan auto cleanup jika ada ticker limit"
4. **Memory updated** — permanent SOP rules encoded

## Lessons
- SL MUST be placed with entries, NEVER deferred
- `reduce_only=False` is safe for SL (trigger far from market, won't fire without position)
- `reduce_only=True` is ONLY for when position already exists
- Watcher is the safety net for TP, not for SL
- User trust is lost when SL protection is missing — this is the #1 priority

## Recovery Trade
DUSKUSDT LONG was identified as recovery setup:
- RSI 4H 57.68 rising, MACD bullish crossover, ADX 28 (+DI > -DI)
- Entry 1: $0.0915, Entry 2: $0.0880
- TP1: $0.1000 (0.98R), TP2: $0.1141 (2.33R)
- SL: $0.0793
- Executed with SOP v2 (limit + SL immediate, TP via algo with reduce_only=False)
- All SL + TP placed successfully in single execution
