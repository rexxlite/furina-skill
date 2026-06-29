# Manual Trade Execution & Dashboard Sync

## Chart Image Analysis Workflow

When user sends a TradingView/Binance chart screenshot:

1. **Vision fallback chain**: Primary model (mimo-v2.5-pro) has NO vision. Use bluesminds provider (api.bluesminds.com) with gpt-4o model. Check `/v1/models` endpoint first for available vision models.
2. **Charts use ZONES not lines**: Colored rectangles/bands — yellow=entry zone, green=TP zone, red=SL zone. Prompt vision AI with "zones/rectangles" not "lines".
3. **Confirm ALL levels** before executing — always ask user to verify. Vision AI misses lines/zones sometimes.
4. **Execute inline** via terminal script using `binance_real_client` methods (`place_limit`, `place_algo`), NOT via `manual_entry_executor.py` CLI (different arg format).

## Multi-Entry TP/SL Qty Management (CRITICAL)

**Rule (Updated 2026-06-12):** SL covers TOTAL expected entry qty from the start. TP deferred until entries fill.

**New SOP — Limit entries + SL first, TP on fill:**
1. Place 2 LIMIT entries (50/50 or custom split)
2. Place SL immediately with `reduce_only=False` (covers full expected qty, safe without position)
3. Do NOT place TPs yet — Binance rejects when trigger price is on wrong side of market (`-2021 Order would immediately trigger`)
4. `entry_fill_watcher.py` detects fills → places TPs with `reduce_only=True` (position exists now)
5. SL uses `reduce_only=False` + `working_type="CONTRACT_PRICE"` via `/fapi/v1/algoOrder`

**Why this flow:**
- `reduce_only=False` on SL: safe pre-fill because SL is on loss side of entry (won't trigger unless entries already filled and price reversed)
- TPs: only placeable after position exists because trigger price may be on "wrong" side of current market for orders placed before fill
- Even if market moves past TP levels before fill, once position exists Binance accepts any trigger price

**Never:** use market orders for manual entries. Never auto-cancel limit orders still waiting.

## PnL Breakdown (Always Show)

Every manual entry confirmation must include:
```
📊 PnL Breakdown:
SL loss:  -$X.XX
TP1 profit: +$X.XX (X.XR)
TP2 profit: +$X.XX (X.XR)
TP max:   +$X.XX (X.XR)
```

## Dashboard Sync Pipeline

Manual chat trades must sync to web dashboard via `dashboard_sync.py`:
1. **New entry** → `sync_and_rebuild()` writes to `public/manual_trades.json` + rebuilds
2. **Entry2 fill** → `entry_fill_watcher.py` adjusts TP/SL + syncs
3. **Position close** → `entry_fill_watcher.py` detects (position gone from Binance) + syncs
4. **Live uPnL** for ACTIVE trades → updated every 2min from Binance `position_risk()`

### Files
- `/root/.hermes/scripts/dashboard_sync.py` — shared utility (sync_and_rebuild, rebuild_dashboard)
- `/root/.hermes/scripts/entry_fill_watcher.py` — cron watcher (entry fills, closes, live uPnL)
- `/root/.hermes/scripts/manual_entry_executor.py` — CLI entry executor (calls dashboard_sync)
- `/root/calendar_app/public/manual_trades.json` — dashboard data source for manual trades
- `/root/calendar_app/build_unified.py` — merges auto + alpha + manual → trades.json

## Close Reason Verification

When reporting trade outcomes:
- ALWAYS check Binance `income_history` for `REALIZED_PNL` entries
- Check `user_trades` for last fill price vs SL/TP levels
- Don't assume close reason from context — verify against actual Binance data
- Update journal with correct status: `SL_HIT`, `TP_HIT`, `TP1_HIT`, etc. (not just `CLOSED`)

## Risk Model for Manual Entries

- **User-initiated manual entries**: 1% of total equity
- **Scanner signals**: 0.5% of total equity
- **Star buckets** (AGGR_15M, COU_4H): 0.75% (scanner only)
