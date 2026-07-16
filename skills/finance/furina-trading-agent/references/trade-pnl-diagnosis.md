# Trade PnL Diagnosis — "Why did this trade lose more than 1R?"

Playbook for the recurring user question: **"kenapa posisi X minus sampai Nr?"**
when the realized loss exceeds the planned 1R. This is a per-trade forensic,
DISTINCT from:
- §5g of operational-systems.md — multi-leg PnL *summing* (TP1+TP2+TP3 totals)
- §9 of operational-systems.md — aggregate audit (bucket/session/symbol leaks)
- §5f of operational-systems.md — stale-order cleanup cancelling SL (a *cause*
  this diagnosis must distinguish from genuine slippage)

The goal is to tell the user, with exchange ground-truth, WHICH of three
root-cause classes fired — not to guess from the journal alone.

---

## 1. Three root-cause classes (decide which one before answering)

| Class | Signature | Who's at fault |
|---|---|---|
| **A. SL cancelled / never placed** | No close order on Binance for the trade window, OR position still open with no algo SL | System bug (cleanup_stale, watcher gap, manual-placement race) |
| **B. SL triggered + slippage** | Close order EXISTS, status FILLED, fill price beyond SL (worse) | Market structure — STOP_MARKET on thin book during cascade |
| **C. TP/SL mislabel (cosmetic)** | Net PnL correct, only the *status label* wrong (e.g. shows TP1_HIT but TP2 was banked) | Reconciler label derivation — see §5e + the milestone-floor fix |

**Class B is NOT a bug.** Telling the user "SL-nya kena cancel" when it was
actually class B is the worst outcome — it sends them hunting for a system
fault that doesn't exist. Always pull the close order + fill price FIRST.

---

## 2. Diagnostic sequence (run in order)

### Step 1 — Read the journal record by trade ID
```python
import json
recs = json.load(open('/root/.hermes/trading_journals/automatic_signal_real_journal.json'))
r = next(x for x in recs if x['id'] == JID)
ex = r['executor']
entry  = float(ex['entry_price'])
sl     = float(ex['sl_price'])
qty    = float(ex['qty'])
risk_$ = float(ex['risk_dollar'])          # planned 1R in dollars
exit_p = float(ex.get('real_last_exit_price') or 0)
net    = float(ex.get('real_net_pnl_usdt') or 0)
```
`risk_dollar` is the planned 1R. `real_net_pnl_usdt` is the wallet truth.
`result_r` in the journal can lag/be null — **don't use it**, compute R yourself.

### Step 2 — Pull Binance ground-truth (3 calls)
Load keys from `/root/.hermes/secrets/binance_real.env` (3 lines: key, secret, base).
Sign with HMAC-SHA256. Then:

1. **`/fapi/v1/allOrders?symbol=X&limit=50`** — find the close order. A
   STOP_MARKET trigger produces a child MARKET order (type=MARKET, side=SELL
   for a LONG, reduceOnly=true, status=FILLED). Its `avgPrice` is the actual
   fill. If no such order exists in the trade window → **class A**.
2. **`/fapi/v1/income?symbol=X&limit=20`** — sum `REALIZED_PNL` + `COMMISSION`
   + `FUNDING_FEE` rows in the window. This is the wallet delta (matches
   `real_net_pnl_usdt`). If the close leg's REALIZED_PNL alone is more
   negative than `risk_dollar` → **class B** (slippage).
3. **`/fapi/v1/userTrades?symbol=X&startTime=<entry_ms>`** — the exit fill
   row(s): `price`, `qty`, `realizedPnl`, `maker=false`. VWAP of these =
   true exit price.

### Step 3 — Pull klines around the close to find the trigger event
```python
start = close_ms - 30*60*1000   # 30 min before close
url = f'https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=5m&startTime={start}&endTime={close_ms+300000}&limit=20'
```
Scan for the candle where price crossed SL. A **liquidation cascade** shows
up as: one 5m candle with volume 10–40× the prior candles and a long wick
through SL. That's the smoking gun for class B slippage.

### Step 4 — Isolate the slippage dollars (class B)
```python
planned_loss = risk_$                                  # = |entry - sl| * qty
actual_loss  = -net                                    # wallet delta (positive = lost)
slippage_$   = actual_loss - planned_loss              # extra lost beyond 1R
slippage_R   = slippage_$ / risk_$
slip_price   = sl - (slippage_$ / qty)                 # for LONG; invert for SHORT
# slip_price should match the userTrades exit VWAP
```
Report as: "1R planned = -$X, slippage = -$Y (≈Zr), total = -$T = -Nr",
and name the cascade candle (time + volume multiple).

---

## 3. Worked example — ARPAUSDT OID-20260705041241 (2026-07-05)

- LONG @ 0.00977, SL 0.00947, qty 8046, risk_dollar $2.68 (1R)
- Close order 4841009621: MARKET SELL, FILLED, avgPrice **0.00910**, qty 8046
- income REALIZED_PNL = -$5.39 (single leg) → class B, not class A
- klines: 06:05 UTC candle open 0.00969 → low 0.00896, vol 223M vs ~5M
  baseline = **~40× volume cascade**, wick straight through SL
- Math: planned -$2.68, slippage (0.00947→0.00910)×8046 = -$2.71 (≈1.01R),
  total -$5.39 = **-2.23R** (notif's number, verified)
- Conclusion: SL live + triggered correctly; STOP_MARKET slipped on a
  40×-volume cascade through a thin ARPA order book. **Not a system bug.**

The user's first instinct (reasonable, given the known cleanup_stale bug
in memory) was to suspect SL cancellation. The close order existing +
FILLED at a worse price ruled that out in one API call.

---

## 4. STOP_MARKET slippage on low-cap alts — execution-risk knowledge

**Mechanism.** Furina places SL as `STOP_MARKET` via `/fapi/v1/algoOrder`.
When trigger fires, it becomes a **market order** — no price guarantee. On a
thin-book alt during a liquidation cascade (volume 10–40× normal), the
market sell walks down the book. Slippage of 1+ extra R is realistic and
was observed (ARPA case above: +1.23R slippage on top of the planned 1R).

**Where this bites hardest.** The anomaly-hunting scanners (OI_DIV,
LIQ_CASCADE, FUNDING) deliberately fire on volatile low-cap names — exactly
the names with thin perp order books. So the slippage risk is concentrated
in the scanner family that's already the noisiest.

**Mitigation options (present to user, don't silently pick):**

1. **Keep STOP_MARKET** (status quo). Safe when price doesn't gap; slips on
   cascades. Acceptable on majors (BTC/ETH/SOL — deep books, slippage tiny).
2. **Switch to STOP_LIMIT at SL price.** Guarantees fill price BUT if price
   *gaps* through the limit (the exact cascade case), the order never fills
   → position stays open **naked**, which can be worse than slippage. Net
   risk: trades a known small slippage for an unknown large naked loss.
3. **STOP_LIMIT with a buffer** (limit a few ticks beyond SL). Best of both
   only if the buffer is wider than typical cascade gap — hard to tune per
   symbol, and still fails on a 40× cascade.
4. **Liquidity filter at scanner/executor level.** Require min 24h
   quote-volume or min order-book depth for OI_DIV/LIQ_CASCADE/FUNDING
   buckets; size-down or skip sub-threshold names. This attacks the *cause*
   (thin book) rather than the *symptom* (slippage). Pairs naturally with
   the existing majors-score-bonus (anomaly scanners already tilt toward
   majors; a liquidity floor extends that protection).

**Recommendation framing for the user:** option 4 is the only one that
reduces expected slippage without introducing naked-position risk. Options
2/3 trade slippage for a fatter tail. Don't implement any without explicit
user sign-off — this is real-money risk-model territory.

---

## 5. Pitfalls

- **Don't answer from the journal alone.** The journal has `real_net_pnl_usdt`
  and `real_last_exit_price` but NOT the cascade context. A user asking "why
  2R?" deserves the klines + close-order evidence, not "SL hit, that's the
  number."
- **Don't conflate class A and class B.** The known `cleanup_stale_open_orders`
  bug (§5f) is class A — it CANCELS the SL, leaving a naked position that
  closes later at whatever price. Class B is the SL *working* but slipping.
  The fix and the user message are completely different. Check the close
  order's existence + reduceOnly flag first.
- **`real_last_exit_price` can equal a TP price on trailed-SL exits** (§5e
  milestone-floor). If exit price == TP1 but net PnL says TP2 was banked,
  that's a label bug (class C), not slippage — trust the events trail.
- **`/fapi/v1/historicalAlgoOrders` does not exist** on USDⓈ-M futures
  (404). To inspect a triggered algo SL, query `allOrders` — the trigger
  produces a regular MARKET child order whose `orderId` differs from the
  `sl_algo_id` stored in the journal. The journal's algo id is only valid
  for `openAlgoOrders` while the order is still pending; once triggered it
  returns -2013 "Order does not exist" on the algo endpoint.
- **Single-leg vs multi-leg.** If the trade had TP1/TP2 fills before the SL,
  the SL close is just the *runner* leg. Compare the SL leg's realizedPnl
  against the *runner's* planned R (risk_dollar × runner_qty_fraction), not
  the full trade's risk_dollar. The ARPA case was single-leg (full close),
  so the comparison was direct.

---

## 6. SL-cluster forensic — "kenapa entryan SL semua?" (a streak, not one trade)

Different question from §1–5. Here the user reports MULTIPLE trades stopping
out in a row. The §2 per-trade sequence is the wrong first move — a streak is
almost never N independent per-trade bugs. It's usually **one systemic cause**.
Diagnose the CLUSTER before drilling any single trade.

### Step 1 — Pull ALL closed records, look at the SIDE distribution first
```python
import json
d = json.load(open('/root/.hermes/trading_journals/automatic_signal_real_journal.json'))
sl = [r for r in d if r.get('status') == 'SL_HIT']
sides = [r.get('side') for r in sl]
buckets = [r.get('bucket') or r.get('executor',{}).get('bucket') for r in sl]
```
**The tell:** if every SL is the SAME side (e.g. all LONG), the cause is
directional, not per-trade. Group by `bucket`/`scanner` too — a streak often
concentrates in ONE scanner family.

### Step 2 — Pull the BTC trend over the streak window (the systemic cause)
```python
# BTC 1h + 48h % move via /fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=48
```
All-LONG SLs during a BTC downtrend (or all-SHORT during an uptrend) = the
scanners were fighting the market. That is the answer; report it with the
numbers (side count, BTC % move, total −$ ≈ N×1R) rather than N separate
per-trade autopsies. Worked case 2026-07-08: 6/6 SL all LONG, BTC −2.55% (12h),
total ~−$15.8. 4/6 were COUNTER-TREND, 2/6 OI_DIV.

### Step 3 — Attribute to scanner CHARACTER, then check the direction gate
- **Counter-trend (`counter_trend_mode`) is the usual culprit in a downtrend.**
  It is LONG-only and buys oversold dips. A dip inside an uptrend/range is the
  ideal mean-reversion setup; a "dip" inside a DAILY DOWNTREND is a falling
  knife. Historically it IGNORED BTC direction by design → caught knives.
  **Fix (deployed 2026-07-08, automatic_signal_scanner.py):** in the
  `counter_trend_mode` branch of `setup_for` (~line 701),
  `allowed_long = btc_bias_long != "bearish"` (was unconditional `True`); and
  `btc_bias_long` must now be fetched when `counter_trend_mode` too (~line 1087:
  `if cfg["use_multi_tf_align"] or cfg.get("counter_trend_mode")`). Still
  LONG-only, still buys dips — but stands aside when BTC 1D is bearish.
- Trend scanners (aggressive/medium/safe) ALREADY have `btc_bias_hard` gates —
  don't "add a BTC gate" to them (I wrongly proposed that first; verify the
  config before proposing a fix). OI_DIV has its own 2-layer 1h+1D gate; it can
  still slip a signal through when 1h is momentarily neutral.

### Step 4 — Distinguish real ERRORs from harmless timeouts (don't over-report)
`executor.status == "ERROR_PERMANENT"` is NOT necessarily a bug. Read the
events trail:
- **`FALLBACK_TIMEOUT`** ("LIMIT NEW for 61 min, scanner not ACTIVE — give up")
  = the LIMIT entry sat unfilled ~61 min because price never returned to the
  entry level, then the reconciler cancelled it cleanly (`_cancel_residual_orders`,
  binance_real_reconciler.py ~line 306). **No orphan, no loss, not a bug.** The
  signal just missed its entry. (A strong-score SHORT that missed while the
  market fell that way is a shame, not a fault — its limit was simply skipped.)
- **`status == "ERROR"` with a real message** (e.g.
  `margin_setup: Timeout waiting for response from backend server`) = a genuine
  transient backend failure with no retry. THIS is worth fixing.
  **Fix (deployed 2026-07-08, binance_real_executor.py ~line 546):**
  `_setup_with_retry(fn, label, tolerate_fn)` wraps both `set_margin_mode` and
  `set_leverage` — 3 attempts, `time.sleep(1.5 * (attempt+1))` backoff, retries
  only on transient signatures (`"timeout"` / `"status unknown"` in msg, or code
  −1007/−1001); tolerable codes return immediately, non-transient raises at once.

### Pitfall — don't front-run the diagnosis with a guess
In this session the first hypothesis ("trend scanners lack a BTC gate") and the
first read of the errors ("3 entries errored") were BOTH wrong — trend gates
already existed, and the "errors" were mostly harmless FALLBACK_TIMEOUTs. State
a hypothesis, then VERIFY against the config + events trail before patching. When
the investigation contradicts an earlier claim to the user, correct it openly
("koreksi diagnosis awalku") rather than quietly patching around it — the user
values the honest correction.
