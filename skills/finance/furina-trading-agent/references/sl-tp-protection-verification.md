# Verifying SL/TP Protection on Binance Futures Positions

When checking whether open positions are protected (have a working stop-loss),
you MUST query **two separate endpoints**. SL/TP in the Furina system are placed
as **algo / conditional orders**, NOT plain limit orders.

## The two endpoints — check BOTH

- `/fapi/v1/openOrders`  → plain LIMIT orders only (entries). **SL/TP are NOT here.**
- `/fapi/v1/openAlgoOrders` → STOP_MARKET / TAKE_PROFIT_MARKET conditional orders (the actual SL & TP).

Client methods: `BinanceRealClient.open_orders()` and `BinanceRealClient.open_algo_orders()`
(see `binance_real_client.py`). The reconciler distinguishes them everywhere.

### PITFALL (hit 2026-06-18 — DO NOT REPEAT)
A diagnostic that queries only `openOrders` will show `orders=0` for every
position and falsely conclude "ALL positions are naked / no SL". This is a
**false alarm** — the SL/TP are sitting in `openAlgoOrders`. Always pull
`open_algo_orders()` before asserting a position has no stop. In the incident,
the first pass reported 12/12 naked; the correct algo-endpoint check showed
42 algo orders live and only **3** positions actually missing their SL.

## Correct verification recipe

Run from `/root/.hermes/scripts` (so `from binance_real_client import BinanceRealClient` resolves —
the module is NOT importable from `/tmp`, copy the probe into the scripts dir or run there):

```python
from binance_real_client import BinanceRealClient
from collections import defaultdict
c = BinanceRealClient()

pos   = {p["symbol"]: p for p in c.position_risk() if abs(float(p.get("positionAmt",0))) > 0}
algo  = c.open_algo_orders()      # SL + TP live here
limit = c.open_orders()           # entries only

abys = defaultdict(list)
for o in algo:
    abys[o["symbol"]].append(o)

for s, p in pos.items():
    amt  = float(p["positionAmt"])
    a    = abys.get(s, [])
    # A real SL sits on the CLOSING side, on the losing side of entry:
    #   LONG  (amt>0): SL = SELL trigger BELOW entry
    #   SHORT (amt<0): SL = BUY  trigger ABOVE entry
    # TP sits on the closing side too but on the PROFIT side of entry,
    # so "has any closing-side algo" is NOT enough — check trigger placement.
    entry = float(p["entryPrice"])
    closing = "SELL" if amt > 0 else "BUY"
    has_sl = any(
        o.get("side") == closing and (
            (amt > 0 and float(o.get("stopPrice") or o.get("triggerPrice") or 0) < entry) or
            (amt < 0 and float(o.get("stopPrice") or o.get("triggerPrice") or 0) > entry)
        )
        for o in a
    )
    print(f"{s:12} amt={amt:>11.4f} uPnL={float(p['unRealizedProfit']):>7.2f} "
          f"algo={len(a)} {'OK' if has_sl else '*** NO SL ***'}")
```

NOTE on the naive `has_sl` check: testing only `algoType=='STOP_MARKET'` can
still mislead because TPs are also conditional. The reliable test is
**closing-side trigger on the loss side of entry** (logic above). A position with
several TP algos but zero loss-side trigger = genuinely unprotected.

## Diagnostic signature of a genuinely-lost SL

In the incident the 3 unprotected positions (HUSDT, BNBUSDT, TRUMPUSDT — also the
3 deepest floating losses) each had **TPs intact but exactly the SL missing**.
That precise pattern (TP present, only SL gone) points at the
**move-SL-to-BE path**, not at `cleanup_stale_open_orders`:

- `_move_sl_to_be()` / `_move_full_sl_to_be()` in `binance_real_reconciler.py`
  follow "cancel old SL → place new SL @ BE".
- If the **cancel succeeds but the re-place raises `BinanceRealError`**, the
  function logs an event and `return`s — leaving the position with **no SL** while
  all TPs remain untouched. Positions that briefly moved favorable (triggering the
  BE logic) then reversed are the ones left naked.
- By contrast `cleanup_stale_open_orders` cancels by symbol and would typically
  remove TP+SL together, not SL alone — so "only SL gone" is the tell that
  distinguishes the BE-replace failure from the cleanup bug.

When you see only-SL-missing: pull the executor `events` log for those symbols and
look for a `cancel SL` immediately followed by a place-SL `FAIL`/`WARN` event to
confirm before re-arming. Fix direction: make the BE move atomic / re-arming —
never leave a cancelled SL without a successfully placed replacement (e.g. place
new SL first, then cancel old; or on place-failure, restore the original SL).

## binance_real.env location
Secrets live at `/root/.hermes/secrets/binance_real.env` (NOT in `scripts/`).
Env var names: `BINANCE_REAL_API_KEY`, `BINANCE_REAL_API_SECRET`,
`BINANCE_REAL_BASE_URL` (testnet: `https://testnet.binancefuture.com`).
