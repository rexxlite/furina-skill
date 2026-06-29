# Binance USDⓈ-M Futures Auto-Execution Reference

Reference for building an executor module that takes Furina signal-scanner output
(Automatic Signal Aggressive/Medium/Safe, Binance Alpha) and submits real orders
to Binance Futures (testnet `https://testnet.binancefuture.com` or live
`https://fapi.binance.com`).

---

## CRITICAL: Conditional Order Endpoint Migration (Dec 2025)

Binance moved all conditional / TP / SL / trailing orders OFF the standard order
endpoint. Discovered the hard way during testnet pre-flight; the error message
is clear once you know what to look for.

**Before (rejected after Dec 2025):**

```
POST /fapi/v1/order
  type=STOP_MARKET | TAKE_PROFIT_MARKET | STOP | TAKE_PROFIT | TRAILING_STOP_MARKET
  stopPrice=...
→ HTTP 400  -4120  "Order type not supported for this endpoint.
                    Please use the Algo Order API endpoints instead."
```

**After (correct):**

```
POST /fapi/v1/algoOrder
  algoType=CONDITIONAL
  type=STOP_MARKET | TAKE_PROFIT_MARKET | STOP | TAKE_PROFIT | TRAILING_STOP_MARKET
  triggerPrice=...   (NOT stopPrice)
  workingType=MARK_PRICE
  priceProtect=true
  reduceOnly=true    (preferred over closePosition for our flow)
  quantity=0.001
→ HTTP 200
  { "algoId": 1000000077795130, "clientAlgoId": "...", "algoStatus": "NEW", ... }
```

Field rename map vs old endpoint:

| Old (`/fapi/v1/order`)    | New (`/fapi/v1/algoOrder`)            |
|---------------------------|---------------------------------------|
| `stopPrice`               | `triggerPrice`                        |
| response `orderId`        | response `algoId`                     |
| response `clientOrderId`  | response `clientAlgoId`               |
| `clientOrderId` (request) | `newClientOrderId` still works        |

Endpoints that exist and that DON'T exist on testnet (verified 2026-05-17):

- ✅ `POST /fapi/v1/algoOrder` — submit conditional
- ✅ `DELETE /fapi/v1/algoOrder?symbol=&algoId=` — cancel by `algoId`
- ✅ `GET /fapi/v1/openAlgoOrders?symbol=` — list open conditionals
- ❌ `GET /fapi/v1/algoOpenOrders` — wrong path, returns -5000 invalid

> ⚠️ **AUDITING SL PROTECTION:** SL & TP are algo orders here, NOT in
> `/fapi/v1/openOrders` (entries only). A diagnostic that queries only
> `openOrders` falsely reports every position as naked (`orders=0`). To check
> whether live positions actually have a stop, you MUST pull `open_algo_orders()`
> and test for a **closing-side trigger on the loss side of entry**. Full
> recipe + the "only-SL-missing → BE-replace-failure" diagnostic signature in
> `references/sl-tp-protection-verification.md`.
- ❌ `GET /fapi/v1/algoOrders` — wrong path, returns -5000 invalid
- ❌ `POST /fapi/v1/algo/order` — wrong path, returns -5000 invalid

`closePosition=true` requires an existing open position, otherwise returns
`-4509 "Time in Force (TIF) GTE can only be used with open positions."` Use
`reduceOnly=true` + explicit `quantity` for the TP/SL pattern; it works even
before the entry has filled and partials cleanly across TP1/TP2/TP3.

`-4164 "Order's notional must be no smaller than 50 (unless you choose reduce only)."`
fires on entry orders below $50 notional. Reduce-only TP/SL are exempt — but
the entry is what gets rejected, so the entry-side notional check must be done
before submitting anything.

Standard order endpoints unchanged and still used for entries:

- ✅ `POST /fapi/v1/order` `type=LIMIT` — entry orders
- ✅ `DELETE /fapi/v1/order?symbol=&orderId=` — cancel entry
- ✅ `GET /fapi/v1/openOrders?symbol=` — list open non-conditional
- ✅ `POST /fapi/v1/leverage` — per-symbol leverage
- ✅ `POST /fapi/v1/marginType` `marginType=ISOLATED` — per-symbol margin mode
- ✅ `GET /fapi/v2/account` — balance, positions, asset breakdown

---

## Position Sizing Rule

Risk-per-trade is FIXED. SL price is structural (from the signal). Position size
adapts. Never the other way around — never tighten SL to fit risk budget.

User's standing rule: **risk = 1% of equity** (testnet uses dynamic balance from
`availableBalance`).

```
sl_distance = abs(entry - sl)
risk_dollar_gross = equity * risk_pct           # e.g. 5116 * 0.01 = 51.16
fee_pct = 0.0008                                # taker entry + taker exit
risk_dollar = risk_dollar_gross * 0.95          # 5% slippage cushion
qty = risk_dollar / (sl_distance + entry * fee_pct)
notional = qty * entry
```

Why the 5% cushion: STOP_MARKET fills at mark price after trigger, often a few
ticks past `triggerPrice`. Worst-case real loss including slippage + 0.08% taker
fee should still land near 1% of equity.

Skip rules (refuse to submit, log reason):

| Reason key             | Trigger                                             |
|------------------------|-----------------------------------------------------|
| `symbol_not_on_futures`| Symbol absent from `exchangeInfo` perp list (Alpha) |
| `qty_below_min`        | Rounded qty < `LOT_SIZE.minQty`                     |
| `notional_too_small`   | `qty * entry < 50` USDT                             |
| `notional_above_cap`   | `notional > equity * leverage_cap`                  |
| `sl_too_wide`          | qty hits min after distance correction              |
| `sl_too_tight`         | notional > equity × max leverage                    |

Round qty DOWN to `stepSize`; round price to `tickSize`. Use `Decimal` not
float for the rounding to avoid printing junk like `0.001000000004`.

Per-source leverage (cap 20x per user, choose by TF noise):

- Aggressive 15m/30m/1h → `15x`
- Medium 1h/4h → `10x`
- Safe 4h/1D → `5x`
- Binance Alpha (early-stage, thin liquidity) → `5x`

Margin mode: ISOLATED on every symbol before first order. Set leverage and
margin mode are idempotent — calling them on every submit is fine.

---

## TP/SL Order Pattern

For LONG (mirror for SHORT — flip side, swap stop direction):

**Automated executor (entries fill immediately or near-immediately):**

1. **Entry**: `POST /fapi/v1/order` `type=LIMIT` `side=BUY` `price=entry_mid`
   `timeInForce=GTC` `newClientOrderId=TT-<journal_id>`. Idempotency through
   `newClientOrderId` — Binance dedupes if the id was used in the last ~24h.
2. **SL**: `POST /fapi/v1/algoOrder` `algoType=CONDITIONAL` `type=STOP_MARKET`
   `side=SELL` `quantity=full_qty` `triggerPrice=sl` `reduceOnly=true`
   `workingType=MARK_PRICE` `priceProtect=true`.
3. **TP1**: same algoOrder shape, `type=TAKE_PROFIT_MARKET`,
   `quantity=full_qty * 0.50`, `triggerPrice=tp1`.
4. **TP2**: 25% of qty, `triggerPrice=tp2`.
5. **TP3**: 25% of qty, `triggerPrice=tp3`.

**Manual chat entries (limit orders, may not fill immediately) — SOP v2 (2026-06-12):**

1. **Entries**: 2× `POST /fapi/v1/order` `type=LIMIT` — wait for fill.
2. **SL**: `POST /fapi/v1/algoOrder` `type=STOP_MARKET` `reduceOnly=false`
   `workingType=CONTRACT_PRICE` — placed IMMEDIATELY. Safe without position
   because SL is on loss side of entry (won't trigger unless price reverses through entries).
3. **TPs**: NOT placed yet. Binance rejects TAKE_PROFIT_MARKET with `-2021`
   when trigger price is on wrong side of current market.
4. **Watcher** detects entries filled → places TPs with `reduceOnly=true`.
   Once position exists, any trigger price works.

After TP1 fills:

- Cancel original SL `algoId`.
- Submit new SL `STOP_MARKET reduceOnly` with `triggerPrice=entry_fill_price`
  (BE) and `quantity` = remaining open qty.

After TP2 fills:

- Cancel BE SL.
- Submit new SL with `triggerPrice=tp1` and remaining qty.

This matches the existing `automatic_signal_risk_manager.py` BE/trailing logic
that journals already implement — executor just needs to reflect it onto
Binance instead of just updating the journal file.

---

## Reconciliation Loop (5-min cron, lazy + smart-skip)

State drift between Binance and the local journal is the main failure mode.
But polling the API every minute "just in case" is wasteful — the user
explicitly rejected per-minute reconciliation as "boros credit". The
correct shape:

**Schedule**: `*/5 * * * *` (`no_agent=true`, deliver to the Hasil Trade topic).

**Smart-skip preamble** before instantiating the API client:

```python
ACTIVE_STATES = {"SUBMITTED", "ACTIVE", "TP1_HIT_BE", "PENDING_API"}

def main() -> dict:
    candidates_per_file = []
    total_active = 0
    for path in [AUTO_PATH, ALPHA_PATH]:
        records = load_json(path)
        active = [r for r in records
                  if (r.get("executor") or {}).get("status") in ACTIVE_STATES]
        candidates_per_file.append((path, records, active))
        total_active += len(active)

    if total_active == 0:
        # Zero API calls, zero credits, zero rate-limit pressure.
        return {"status": "skipped_no_active",
                "counts": {"scanned": 0, "mutated": 0},
                "notifications": []}

    client = BinanceTestnetClient()  # only instantiate when there's work
    # ...iterate active records only, not every record in the file
```

When there ARE active orders, pull authoritative truth:

- `GET /fapi/v2/account` → `availableBalance`, list of `positions` with non-zero
  `positionAmt`. This is ground truth for what's actually open.
- `GET /fapi/v1/userTrades?symbol=&startTime=` → fill history for entries,
  partials, TPs, SL fills. Compute real fill price, real PnL, real fee per leg.
- `GET /fapi/v1/openOrders?symbol=` + `GET /fapi/v1/openAlgoOrders?symbol=` →
  what's still pending.

Per active record:

1. If entry orderId not seen filled and not in openOrders → it was canceled
   externally. Flip to `executor.status=CANCELED`, no further action.
2. If entry filled (userTrades match by `clientOrderId=TT-<journal_id>`) but
   journal still says `WAITING_ENTRY` → set `entry_hit_at`, capture
   `real_entry_fill_price`, compute `real_entry_slippage_pct`, flip status to
   `ACTIVE`, send Telegram notif.
3. If positionRisk shows `positionAmt=0` but journal still `ACTIVE` → position
   closed. Determine which leg closed it by matching userTrades to TP/SL
   `clientAlgoId`s. Cancel all remaining algo orders, update journal final
   status (`TP1_HIT`/`TP2_HIT`/`TP3_HIT`/`SL_HIT`/`MANUAL_CLOSED`), record
   `real_pnl_usdt` and `real_fee_usdt` from userTrades.
4. If TP1 filled → cancel old SL, submit new BE SL (above). Update journal
   `tp1_hit_at`, `sl_current=entry_fill_price`.

Idempotency: every algo submission uses `newClientOrderId=TT-<journal_id>-<leg>`
(e.g. `TT-AS-20260517000123-BTCUSDT-SL`, `-TP1`, `-TP2`, `-TP3`). When a
restart happens mid-flow, re-submit with the same id; Binance returns the
existing record instead of creating a duplicate.

---

## Submission Trigger: Synchronous Scanner Hook (NOT a poller cron)

The original executor design was a `* * * * *` cron that scanned the journal
for new `WAITING_ENTRY` rows and submitted them. The user rejected this
("Boros credit"). The fix is structural, not a tweak: there should be no
poller cron at all.

Design:

1. **Expose a function** in `binance_testnet_executor.py` that accepts a
   single journal record dict, validates it, submits to Binance, and mutates
   `record["executor"]` in place. Never raises:

   ```python
   def process_record_for_scanner(record: dict) -> dict:
       """Returns {status, msg, notification?}. Mutates record in place.
       Caller re-saves the journal after this returns."""
       if KILL_FILE.exists():
           return {"status": "killed", ...}
       if record.get("status") not in ("WAITING_ENTRY", "PENDING"):
           return {"status": "ignored", ...}
       if record.get("executor", {}).get("status"):
           return {"status": "ignored", "msg": "already processed"}
       # ... fetch equity, execute_signal(), build notification ...
       # On -1003 IP ban: write executor.status=PENDING_API so the reconciler
       # can pick it up later when the ban clears (PENDING_API is in
       # ACTIVE_STATES so smart-skip won't ignore it).
   ```

2. **Hook the scanners.** In `automatic_signal_scanner.py`, immediately
   after `journal.append(row); save_journal(journal)`:

   ```python
   try:
       import binance_testnet_executor as _bte
       _bte.process_record_for_scanner(row)
       save_journal(journal)   # re-save with executor sub-doc populated
   except Exception as _bte_err:
       print(f"[testnet-hook] {_bte_err}", file=sys.stderr)
   ```

   Same shape in `binance_alpha_signal_scanner.py` after `rows.append(row); save(rows)`.

3. **Critical**: the try/except wrapper must NEVER re-raise. A testnet
   failure (network, rate limit, bad credentials, exchange info miss) MUST
   NOT block the signal from being printed to the topic. Signals continue to
   publish; execution is best-effort.

4. **Notification channel**: scanner already prints to stdout, which Hermes
   cron forwards to the configured Telegram topic. The hook just appends a
   `[TESTNET][AS-Aggr15m] BTCUSDT LONG SUBMITTED ...` line to that stdout
   when needed; no separate delivery wiring required.

End-to-end smoke test recipe:

```python
# 1. Backup journal
shutil.copy(AUTO_PATH, AUTO_PATH + '.before_chain_test')

# 2. Build a scanner-shape row using a real symbol with realistic levels
row = {"id": f"AS-CHAIN-{int(time.time())}-ETHUSDT",
       "symbol": "ETHUSDT", "side": "LONG", "status": "WAITING_ENTRY",
       "risk_model": "aggressive", "timeframe_context": "30m signal + 1h context",
       "entry_low": ..., "entry_high": ..., "entry_mid": ...,
       "sl": ..., "tp1": ..., "tp2": ..., "tp3": ..., ...}

# 3. Append to journal, call hook, re-save
journal.append(row); save_journal(journal)
result = bte.process_record_for_scanner(row)
save_journal(journal)
assert result['status'] == 'submitted'

# 4. Verify orders live on testnet
client.open_orders('ETHUSDT')        # 1 LIMIT
client.open_algo_orders('ETHUSDT')   # 4 algo (SL, TP1, TP2, TP3)

# 5. Cleanup: cancel all + restore journal from backup
```

If `result['status'] == 'submitted'` but `open_orders` is empty, the hook
silently failed somewhere — read `row['executor']['events']`. If
`result['status'] == 'rate_limited'`, that's expected during ban; the
reconciler will pick up `PENDING_API` records once the ban clears.

---

## Anti-Pattern: Producer Cron + Consumer Cron

Generalize this lesson beyond the executor. When a long-running scanner
already runs on its own cron and produces a trigger event in a local file
(journal, queue, signal), the temptation is to add a separate cron that
polls that file and acts on it. Resist.

- The producer cron already knows when there's a new event — it just wrote
  it. Calling the consumer inline takes 0ms more than printing a Telegram
  message.
- A poller cron with `*/1 * * * *` (or worse, the default cron behavior with
  `no_agent=true`) costs API quota and rate-limit budget every single
  minute, 1440x/day, even when there's nothing to do. The user feels this.
- Two crons = two race-condition surfaces. If the consumer reads the file
  while the producer is writing, you can corrupt state.
- Inline = same process, same lock domain, same error surface.

The only legitimate "polling" cron in this architecture is the **reconciler**
— and even that one is lazy (smart-skip on no-active-records, every 5
minutes, not every minute).

---

## Reconciliation Loop (legacy doc, see "5-min cron" section above)

The earlier 1-min reconciler design is deprecated. The 5-min lazy
smart-skip design above replaces it.

---

## Executor State Schema (per journal record)

Add an `executor` object to each Automatic Signal / Binance Alpha journal
record. Manual Crypto journals can adopt the same shape if user later wants
auto-execution there.

```json
"executor": {
  "venue": "binance_testnet",
  "status": "PENDING|SUBMITTED|ACTIVE|TP1_HIT_BE|CLOSED|SKIPPED|ERROR|CANCELED",
  "skip_reason": null,
  "leverage": 10,
  "margin_type": "ISOLATED",
  "qty": 0.0065,
  "notional_usdt": 510.50,
  "entry_order_id": 13152181083,
  "entry_client_id": "TT-AS-20260517000123-BTCUSDT",
  "sl_algo_id": 1000000077795130,
  "tp1_algo_id": 1000000077795131,
  "tp2_algo_id": 1000000077795132,
  "tp3_algo_id": 1000000077795133,
  "real_entry_fill_price": 100012.30,
  "real_entry_slippage_pct": 0.012,
  "real_pnl_usdt": null,
  "real_fee_usdt": null,
  "events": [
    {"ts": "2026-05-17T07:01:00Z", "type": "SUBMITTED", "msg": "lev=15x qty=0.0065"},
    {"ts": "2026-05-17T07:14:32Z", "type": "ENTRY_FILLED", "fill": 100012.3}
  ]
}
```

Calendar build script (`/root/calendar_app/build_unified.py`) should prefer
`executor.real_pnl_usdt` over derived `pnl_pct` when present, so the dashboard
shows real Binance PnL once executions are flowing.

---

## Binance Alpha + Futures Mismatch

Most Binance Alpha tokens are spot-only listings; only a small subset have
USDⓈ-M perpetual contracts. User's standing rule: **execute Alpha signals only
when the symbol is listed on perp futures, otherwise skip execution but still
publish the signal to the Binance Alpha topic and journal.**

Implementation: at executor entry, do `set(s['symbol'] for s in
exchangeInfo['symbols'] if s['contractType']=='PERPETUAL' and
s['status']=='TRADING')`. Cache for 1 hour. If signal symbol not in set, set
`executor.status=SKIPPED`, `executor.skip_reason="symbol_not_on_futures"`,
notif `[TESTNET] <SYMBOL> alpha-only — signal published, execution skipped`.

Do NOT silently swallow these — the journal entry still exists and the daily
report still counts it as a signal, just without an executor PnL.

---

## Testnet vs Live Differences

- Testnet base URL: `https://testnet.binancefuture.com`. Account starts with
  ~10k–100k virtual USDT (varies). API key generated separately at
  `https://testnet.binancefuture.com/en/futures/BTCUSDT`. Login is via Github
  or a temp email — completely independent from main Binance account.
- Live: `https://fapi.binance.com`. API key at
  `https://www.binance.com/my/security/api-management`. Permissions: enable
  `Reading` + `Futures`, **never** enable `Withdrawals`. IP whitelist mandatory.
- Both signing identical: HMAC-SHA256 over the urlencoded querystring,
  `X-MBX-APIKEY` header, `recvWindow=10000`, `timestamp=<ms>`.
- Some testnet symbols don't match live exactly. Verify against
  `GET /fapi/v1/exchangeInfo` of the target environment, not assumed.
- Fee tier on testnet is 0; on live, default tier 0 = 0.02% maker / 0.04% taker.
  Position-sizing fee constant `0.0008` (0.08% round trip) is for live taker
  estimation; for testnet it overestimates real cost by 0.08% which is harmless.

---

## Pre-Flight Verification Script

Before wiring an executor cron, run this once against the target environment.
If any check fails, do not proceed.

```python
"""Binance Futures executor pre-flight. Reads creds from
/root/.hermes/secrets/binance_testnet.env (or _live.env). Confirms:
  1. Server time + signed account read
  2. exchangeInfo parses with tickSize/stepSize/minNotional for BTCUSDT
  3. set leverage + ISOLATED margin
  4. LIMIT order submit + cancel cycle (far OTM, no fill risk)
  5. algoOrder STOP_MARKET reduceOnly + algoOrder TAKE_PROFIT_MARKET
     submit + cancel via openAlgoOrders + DELETE algoId
"""
import hmac, hashlib, time, urllib.parse, urllib.request, json

env = {}
for line in open('/root/.hermes/secrets/binance_testnet.env'):
    if '=' in line:
        k, v = line.strip().split('=', 1); env[k] = v
API_KEY = env['BINANCE_TESTNET_API_KEY']
SECRET  = env['BINANCE_TESTNET_API_SECRET']
BASE    = env['BINANCE_TESTNET_BASE_URL']

def signed(method, path, params=None):
    p = dict(params or {})
    p['timestamp'] = int(time.time()*1000); p['recvWindow'] = 10000
    qs = urllib.parse.urlencode(p, doseq=True)
    sig = hmac.new(SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
    full = f"{qs}&signature={sig}"
    if method == 'GET':
        req = urllib.request.Request(f"{BASE}{path}?{full}",
            headers={'X-MBX-APIKEY': API_KEY}, method='GET')
    else:
        req = urllib.request.Request(f"{BASE}{path}", data=full.encode(),
            headers={'X-MBX-APIKEY': API_KEY}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

# 1. Account
code, acc = signed('GET', '/fapi/v2/account')
assert code == 200 and 'totalWalletBalance' in acc, acc
print(f"OK account balance={acc['totalWalletBalance']}")

# 2. exchangeInfo BTCUSDT
with urllib.request.urlopen(f"{BASE}/fapi/v1/exchangeInfo", timeout=15) as r:
    info = json.loads(r.read())
sym = next(s for s in info['symbols'] if s['symbol'] == 'BTCUSDT')
filt = {f['filterType']: f for f in sym['filters']}
print(f"OK BTCUSDT tickSize={filt['PRICE_FILTER']['tickSize']} "
      f"stepSize={filt['LOT_SIZE']['stepSize']} "
      f"minNotional={filt.get('MIN_NOTIONAL') or filt.get('NOTIONAL')}")

# 3. Leverage + ISOLATED
code, _ = signed('POST', '/fapi/v1/leverage', {'symbol':'BTCUSDT','leverage':5})
assert code == 200
code, _ = signed('POST', '/fapi/v1/marginType',
    {'symbol':'BTCUSDT','marginType':'ISOLATED'})
assert code == 200
print("OK leverage 5x + ISOLATED set")

# 4. LIMIT round-trip
with urllib.request.urlopen(f"{BASE}/fapi/v1/ticker/price?symbol=BTCUSDT") as r:
    px = float(json.loads(r.read())['price'])
ts = int(time.time())
code, o = signed('POST', '/fapi/v1/order', {
    'symbol':'BTCUSDT','side':'BUY','type':'LIMIT','quantity':0.002,
    'price': round(px*0.5, 1), 'timeInForce':'GTC',
    'newClientOrderId': f"TT-PRE-LIM-{ts}"})
assert code == 200, o
code, _ = signed('DELETE', '/fapi/v1/order',
    {'symbol':'BTCUSDT','orderId':o['orderId']})
assert code == 200
print(f"OK LIMIT submit + cancel (orderId={o['orderId']})")

# 5. algoOrder round-trip (TP_MARKET reduceOnly, won't trigger)
code, a = signed('POST', '/fapi/v1/algoOrder', {
    'symbol':'BTCUSDT','side':'SELL','type':'TAKE_PROFIT_MARKET',
    'algoType':'CONDITIONAL','quantity':0.001,
    'triggerPrice': round(px*1.5, 1),
    'reduceOnly':'true','workingType':'MARK_PRICE','priceProtect':'true',
    'newClientOrderId': f"TT-PRE-ATP-{ts}"})
assert code == 200, a
code, opens = signed('GET', '/fapi/v1/openAlgoOrders', {'symbol':'BTCUSDT'})
assert code == 200 and len(opens) >= 1
code, _ = signed('DELETE', '/fapi/v1/algoOrder',
    {'symbol':'BTCUSDT','algoId':a['algoId']})
assert code == 200
print(f"OK algoOrder TAKE_PROFIT_MARKET submit + cancel (algoId={a['algoId']})")

print("\nALL PRE-FLIGHT CHECKS PASSED")
```

If `LIMIT` returns 200 but `algoOrder STOP_MARKET` returns -4120 with the
"Algo Order API endpoints" message, **someone is still pointing at
`/fapi/v1/order` for the conditional**. The whole point of this reference is
that this no longer works.

---

## Bucket Detection From Journal Records

The journal records produced by `automatic_signal_scanner.py` and
`binance_alpha_signal_scanner.py` do NOT carry a `scanner_tag` or
`source_tag` field. They carry:

- `risk_model`: `"aggressive" | "medium" | "safe"` — set from the scanner mode
  config (`automatic_signal_scanner.py --mode <mode>`). This is the
  authoritative bucket source.
- `timeframe_context`: free-text like `"15m signal + 1h context"`,
  `"30m signal + 1h context"`, `"1h signal + 4h context"`,
  `"5m/15m scalping + 1h intraday"`. Use this only as a sub-classifier for
  the leverage tier inside `aggressive` / `medium` / `safe`.
- `source`: `"automatic_signal"` for all Automatic Signal entries; Binance
  Alpha entries are stored in a separate file (`binance_alpha_signal_journal.json`)
  and may carry `alpha_id` or `source` containing `"alpha"`.

Detection precedence the executor MUST use:

```python
def detect_bucket(rec: dict) -> str:
    src = (rec.get("source") or "").lower()
    if rec.get("alpha_id") or "alpha" in src:
        return "ALPHA"
    risk_model = (rec.get("risk_model") or "").lower()
    tf = (rec.get("timeframe_context") or "").lower()
    if risk_model == "aggressive":
        if "5m" in tf or "15m" in tf: return "AGGR_15M"
        if "30m" in tf:               return "AGGR_30M"
        return "AGGR_1H"
    if risk_model == "medium":
        if tf.split("signal")[0].strip().endswith("4h"): return "MED_4H"
        return "MED_1H"
    if risk_model in ("safe", "conservative"):
        if "1d" in tf: return "SAFE_1D"
        return "SAFE_4H"
    # fallback: parse TF string only
    ...
```

Pitfall: a previous draft of the executor checked `scanner_tag`/`source_tag`,
which are always empty, and fell through to a `MED_1H` default for every
trade. The leverage was wrong (10x instead of 15x) and the Telegram label
read `Med1h` for Aggressive scalps. Always validate the bucket distribution
on real journal data before enabling the cron:

```python
from collections import Counter
import json
auto = json.load(open('/root/.hermes/trading_journals/automatic_signal_journal.json'))
print(Counter(detect_bucket(r) for r in auto).most_common())
# Expected for current scanner config:
# AGGR_15M >> AGGR_30M >> AGGR_1H >> MED_1H, no MED_1H-flooded results.
```

If you see every record bucketed as the same tier, the field name is wrong.

---

## Common Errors (and what they really mean)

| Code  | Message                                                                        | Fix                                             |
|-------|--------------------------------------------------------------------------------|-------------------------------------------------|
| -4120 | "Order type not supported for this endpoint. Please use the Algo Order API…"   | STOP/TP types must use `/fapi/v1/algoOrder`      |
| -1102 | "Mandatory parameter 'triggerprice' was not sent"                              | algoOrder uses `triggerPrice` not `stopPrice`    |
| -4164 | "Order's notional must be no smaller than 50 (unless you choose reduce only)"  | Bump qty so `qty*price ≥ 50`, OR mark reduceOnly |
| -4509 | "TIF GTE can only be used with open positions"                                 | `closePosition=true` needs an open position     |
| -1100 | "Illegal characters found in parameter 'newclientorderid'"                     | Restrict to `^[.A-Z:/a-z0-9_-]{1,36}$`          |
| -5000 | "Path /fapi/v1/algoOrders, Method GET is invalid"                              | Wrong path; correct: `/fapi/v1/openAlgoOrders`  |
| -1003 | "Way too many requests; IP(...) banned until <ms_ts>"                          | IP rate-limit. Wait until `ms_ts`. Cron jobs MUST silent-return on this code, not surface errors. |

---

## Rate-Limit Pitfall: Burst Pre-Flight Bans the Cron IP

The pre-flight script above does ~5 signed requests in <2s. On Binance testnet
this can trip the unauthenticated weight cap and earn a 10–15 minute IP ban
returning HTTP 418 → `-1003`. Live has more headroom but the same rule applies.

If the executor / reconciler cron fires while the IP is still banned, every
minute they will throw and (if `deliver=telegram:...`) spam the user channel.

Two mitigations that are mandatory before enabling the cron:

1. **Silent-return on -1003** in the executor and reconciler `main()`:

   ```python
   try:
       equity = client.available_balance_usdt()
   except BinanceTestnetError as e:
       if e.code == -1003:
           return {"status": "rate_limited", "msg": e.msg}
       return {"status": "error", "msg": f"account fetch failed: {e.msg}"}
   ```

   For the reconciler, also handle -1003 inside the per-record loop and bail
   out early (after persisting any in-progress mutations) rather than retrying
   per record:

   ```python
   except BinanceTestnetError as e:
       if e.code == -1003:
           if dirty_file:
               save_json(path, records)
           return {"status": "rate_limited", "msg": e.msg, ...}
   ```

2. **Pause the cron jobs while running pre-flight bursts.** Re-enable them
   only after at least one manual `python3 binance_testnet_client.py` smoke
   test succeeds (proves IP is unbanned).

When verifying that mitigation works, an easy test is to run the executor
script while still banned — it should print `'status': 'rate_limited'` and
exit 0, no traceback. Cron delivery to Telegram remains silent.

---

## When Live Cutover Eventually Happens

Don't move from testnet to live until at least 2 weeks of testnet runs show:

- All entries fill within tolerable slippage (target < 0.15% on Aggressive, < 0.05% on Safe).
- Reconciliation never marks a position as drift-detected without cause.
- BE/trailing flow lands new SL successfully after every TP1.
- No orphaned algo orders left after position close (verify openAlgoOrders
  empty when no open positions).

Live cutover changes only:

- Base URL → `https://fapi.binance.com`.
- Secrets file → `/root/.hermes/secrets/binance_live.env` (never reuse testnet creds).
- IP whitelist on the API key, locked to the host running the executor.
- Add a max-daily-loss circuit breaker that touches `/root/.hermes/EXEC_KILL`
  when realized PnL for the day < -X% equity.
- Tighter risk: drop default to 0.5% per trade for the first 2 weeks live.

Everything else (signing logic, endpoint paths, position sizing, reconciler)
is identical to testnet.
