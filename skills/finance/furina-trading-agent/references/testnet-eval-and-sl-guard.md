# Testnet PnL noise, direction-based evaluation, and SL-guard trailing

Two durable lessons from the EIGENUSDT "TP2 hit but closed minus" investigation
(2026-06-22). Both apply whenever Furina runs on **Binance testnet**
(`testnet.binancefuture.com`) and whenever you touch the SL-guard / trailing logic.

## 1. Testnet dollar PnL is unreliable — judge signals by DIRECTION

Symptom that triggered the investigation: a journal record showed
`TP2_HIT` events, yet the realized PnL was **negative** and the user asked why a
"TP2 win" closed at a loss.

Root cause — **thin testnet orderbook**. When a `STOP_MARKET` order triggers, the
market order sweeps the (near-empty) testnet book and fills far below the trigger
price. Real Binance trade history confirmed it: on EIGENUSDT the same exit
timestamp produced BOTH good fills (e.g. 170.9 @ $0.2925) AND garbage fills
(294.8 @ $0.2688) — $0.2688 was *below the SL of $0.2767* while market was
$0.29–0.30. On mainnet the deep book would fill near the trigger; on testnet it
does not.

Conclusion: **do not evaluate strategy quality by testnet dollar PnL.** Evaluate
by direction — did price reach a take-profit before stopping out. A trade that
tags TP1+ is a directional WIN even if the eventual testnet exit fill produced
negative dollars.

### How to pull REAL fill history (verify before asserting)

The journal records the *intended* close kind; the exchange records the *actual*
fills. When PnL looks wrong, pull `userTrades` directly:

- Endpoint: `GET /fapi/v1/userTrades?symbol=...&startTime=...` (signed).
- Env file `/root/.hermes/secrets/binance_real.env` uses prefixed keys:
  `BINANCE_REAL_API_KEY`, `BINANCE_REAL_API_SECRET`, `BINANCE_REAL_BASE_URL`
  (NOT bare `BINANCE_API_KEY` / `BASE_URL`). Sum `realizedPnl` across fills to
  reconcile against the journal's `real_net_pnl_usdt`.
- Tell-tale of a book-sweep: multiple fills at the SAME timestamp, some at
  sensible prices and some far worse, with one chunk dumped below the SL trigger.

### Direction-based win-rate tracker

`scripts/signal_winrate_direction.py` (lives in `/root/.hermes/scripts/`)
classifies every closed auto-signal trade by the highest TP it ever tagged
(events `TPx_HIT` / `tpx_hit_at` are the source of truth), ignoring dollar PnL:
- WIN_TP3 / WIN_TP2 / WIN_TP1 = price tagged that TP (signal correct)
- LOSS = SL hit with zero TP tagged (signal wrong)
- Groups by `source` (scanner) and prints per-scanner + overall WR.

Use it for scanner tuning: low-WR scanners (e.g. Funding, RangeMR in the
2026-06-22 run) are candidates to tighten thresholds; high-WR with big sample
(OIDiv) to keep. Note "TP3 = 0 across all scanners" is expected, not a bug — the
trailing locks SL at TP1 after TP2, so the runner almost always stops before TP3.

## 2. SL-guard must use the TIGHTEST earned SL — never downgrade to breakeven

Bug found + fixed 2026-06-22 in `scripts/_sl_guard_block.py`
(`_sl_price_for_position`). The SL-guard re-places a vanished STOP_MARKET each
tick. But for status `TP2_HIT_T1` (SL should be locked at TP1 +1R), the resolver
only checked `sl_be_price` → it **downgraded a profit-locked stop back to
breakeven** on every guard re-place, because it never read `sl_t1_price`.

Fix (priority order, tightest first):
- status `TP2_HIT_T1` → return `ex["sl_t1_price"]` (fallback `tp1_price`)
- status in (`TP1_HIT_BE`, `TP2_HIT_T1`) → `sl_be_price` / entry fill
- else recorded `sl_price`, then journal `sl`.

Rule: the guard must never move the SL to a level LOOSER than what the trade has
already earned through its trailing stages.

### NOT a bug (don't "fix" this)

The SL_GUARD_REPAIR firing with **full position size** (e.g. 1552.5 when remaining
"should" be the TP3 portion) is correct. The guard reads live `positionAmt` from
`position_risk()`, so qty is always the true remaining size. Full-size repairs
just mean no TP had filled yet at that moment.

## 3. Close-label milestone-floor: never derive the exit tier from price-match alone

Bug found + fixed 2026-06-25 in `binance_real_reconciler.py` `_finalize_closed()`
(~line 908). Backup tag `.bak.tplabel.<ts>`.

**Symptom (user-facing):** a trade that actually banked TP2 (or TP3) showed up on
the dashboard / in chat labeled `TP1_HIT`. The user noticed positions that "closed
even though only TP1 hit" and asked why. IDUSDT example: full close +$13.54 (TP1
+3.24 / TP2 +5.08 / runner +5.23) yet the title said TP1.

**Root cause — the SAME trailing mechanism from §2 causes a labeling artifact.**
After TP2 hits, the trailing logic moves the SL up to the TP1 price (+1R lock).
So when the runner finally stops out, its exit price equals the TP1 price. The old
`_finalize_closed` derived `final_kind` by **price-matching the last exit against
the TP levels** → runner exit ≈ TP1 price → mislabeled `TP1_HIT`, even though TP2
was already banked. This is purely a COSMETIC label bug — `real_net_pnl_usdt` was
ALWAYS correct (it sums all legs), only the title/tier label was wrong.

**Fix — milestone-floor correction.** Derive the tier from the `events` trail
(which never regresses) as a FLOOR, and use price-match only to distinguish the
top leg (TP3 vs TP2-lock):
- events contain `TP2_HIT_T1` → floor = TP2_HIT (can only be upgraded to TP3, never down to TP1)
- events contain `TP1_HIT_BE` → floor = TP1_HIT
- price-match is then allowed to distinguish TP3 vs TP2 ONLY (never to demote below the floor)

The events trail is monotonic by construction (`TP1_HIT_BE → TP2_HIT_T1 → CLOSED`),
so using it as the floor is safe. Apply the IDENTICAL logic in three places that
each derive a label: (1) `_finalize_closed` in the reconciler, (2) the journal
status-update path, (3) the dashboard label derivation in `build_unified.py`.

## 4. Closed-trade NET = sum of ALL legs — see operational-systems §5g

The multi-leg net+funding reconciliation (Binance per-row "Realized PnL" = LAST
leg only; pull `income_history` and sum REALIZED_PNL − COMMISSION + FUNDING_FEE;
`_finalize_closed` funding patch) is documented in full in
`references/operational-systems.md` §5g. Don't duplicate the procedure here.

**One extra diagnostic from the TAOUSDT 2026-06-25 case worth flagging:** when a
user reports "dashboard net ≠ Binance realized", there are TWO independent causes,
not one — check BOTH:
1. The Binance number is just the last leg (the §5g case), OR
2. A **ghost record** — `manual_binance_sync.py` tagged the TP3/runner leg of a
   Furina trade as a separate "manual" trade (e.g. `manual-open-TAOUSDT-<ts>`,
   manual_qty 0.971), so the dashboard had the real record AND a phantom partial.
   Fix: confirm the real executor-backed record exists, then rebuild
   (`cd /root/calendar_app && python3 build_unified.py`) — the ghost drops.
   Durable guard (pending): `manual_binance_sync.py` must not tag a position whose
   qty matches an active executor-backed runner as manual (check FURINA_LIVE_STATES).

Incident 2026-06-25: `[SL-GUARD 1000BONKUSDT NAKED re-place FAILED]`. The position
(130,618 units LONG) lost its SL and the guard could not re-place it.

**Root cause — per-order maxQty cap.** For 1000BONKUSDT the `MARKET_LOT_SIZE`
filter caps a single market/stop-market order at **maxQty 100,000** (min 1, step 1).
A single STOP_MARKET for 130,618 is rejected. Two other traps found:
- `closePosition:true` via `POST /fapi/v1/order` is **rejected on demo** with
  `HTTP 400 -4120 "Order type not supported for this endpoint. Please use the Algo
  Order API endpoints instead."` → on testnet you MUST use the algo API with an
  EXPLICIT qty (no closePosition shortcut).
- `BinanceRealClient.exchange_info(sym)` cache does NOT store maxQty (only
  price/qty precision, tick, step, min_qty, min_notional). Pull maxQty from raw
  `GET /fapi/v1/exchangeInfo` (MARKET_LOT_SIZE filter) when you need it.

**Manual fix applied:** placed 2× STOP_MARKET (65,309 + 65,309) @ trigger via
`place_algo(...)` — both NEW, position fully covered.

**Durable pattern for `ensure_stop_loss_guard()` auto-split:** when the live
`positionAmt` (always the true remaining size, see §2) exceeds MARKET_LOT_SIZE
maxQty for the symbol, split the SL into ceil(qty/maxQty) STOP_MARKET orders, each
≤ maxQty, rounded to step; put the remainder on the last order so the sum equals
the full position. All legs share the same trigger price. Verify the qty sum
equals positionAmt before declaring the position protected.

**Backfilling historical mislabels:** write a one-shot that re-applies the same
floor rule to already-CLOSED records whose `status`/label says `TP1_HIT` but whose
events trail reached `TP2_HIT_T1`/`TP3`. The 2026-06-25 backfill corrected 34
records TP1→TP2. **Net PnL must NOT change** — only the label. Verify after:
re-run the reconciler smoke-test (`mutated=0`, no regression) and rebuild the
dashboard. ALWAYS back up the journal (`.bak.tplabel.<ts>`) before backfilling.

**General lesson:** whenever a trailing stop locks profit at a prior TP level, the
final exit fill will price-match that prior level. Any close-label logic that
trusts price-match alone WILL mislabel trailed winners. Derive the tier from the
monotonic events trail as a floor; let price-match only break ties on the top leg.
