# Order-Book Depth Liquidity Gate (thin-book slippage defense)

Deployed 2026-07-06 on OI_DIV, then extended same day to LIQ_CASCADE + FUNDING.

## Problem it solves

Furina places SL as `/fapi/v1/algoOrder` STOP_MARKET. On trigger it becomes a
market order — **no price guarantee**. On a thin order book during a liquidation
cascade (volume 10–40× normal), the SL fills far past the trigger. Worked case:
ARPAUSDT OID-20260705041241 — SL 0.00947 triggered, filled 0.00910, **−2.23R**
(1R planned + 1.23R pure slippage). This is a market-structure risk, NOT a bug.

The existing `MIN_QUOTE_VOLUME_24H = $50M` floor filters *daily turnover* but not
*instantaneous resting depth* — ARPA passed the 24h floor yet had only ~$43K
resting within ±1% of mid.

## The gate (single source of truth in base module)

Added to `automatic_signal_scanner.py` (imported as `base` by the anomaly
scanners), so the threshold lives in ONE place:

```python
DEPTH_BAND_PCT = 1.0                 # measure resting notional within ±1% of mid
MIN_EXIT_DEPTH_USD = 250_000         # exit-side notional floor; below → no trade

def orderbook_depth(symbol, band_pct=DEPTH_BAND_PCT):
    # GET /fapi/v1/depth?symbol&limit=500 (uses base.get_json → retry+backoff)
    # returns (bid_notional, ask_notional) summed within ±band_pct of mid,
    # or (None, None) on error
    ...

def exit_side_depth(symbol, side, band_pct=DEPTH_BAND_PCT):
    # LONG exits by SELLING into bids; SHORT exits by BUYING from asks.
    # returns the notional on the side the STOP_MARKET SL will sweep, or None.
    bid_dep, ask_dep = orderbook_depth(symbol, band_pct)
    if bid_dep is None: return None
    return bid_dep if side == "LONG" else ask_dep
```

## Wiring in each scanner (identical pattern)

Placed in `setup_for()` **right after the `if score < MIN_SCORE: return None`
check** — so depth is only fetched for signals that already passed scoring
(0–3 API calls per scan, not per-symbol). `side` is fully determined by then.

```python
    # ── Liquidity gate: refuse thin books (SL is STOP_MARKET → slips on thin
    #    books during cascades). Check the EXIT side where the SL fills.
    exit_dep = base.exit_side_depth(symbol, side)
    if exit_dep is None:
        return None  # can't verify liquidity → stand aside (fail-SAFE)
    if exit_dep < base.MIN_EXIT_DEPTH_USD:
        return None  # book too thin → SL would slip; no trade
```

And add to the returned signal dict for journal audit:
```python
        "exit_depth_usd": round(exit_dep), "depth_band_pct": base.DEPTH_BAND_PCT,
```

- OI_DIV originally had a local `orderbook_depth()` copy; refactored to call
  `base.exit_side_depth` so all three share the base implementation.
- FUNDING has no `build_universe` (uses `build_volume_map` + `premium_index_all`
  + `setup_for(symbol, funding_rate)`); the gate wiring is still identical inside
  `setup_for`.

## Calibration (live books, 2026-07-06)

- Blue-chips (BTC/ETH/SOL): $9M–25M exit depth → PASS
- DOGE / 1000PEPE: $1.5M–5M → PASS
- ARPA-class micro-caps: ~$43K → BLOCK (the exact class that caused −2.23R)

$250K floor blocks ARPA-class with wide margin while passing all legit
mid/large-caps.

## Fail-SAFE semantics

If the depth call errors or returns None → the scanner **stands aside** (returns
None), it does NOT open blind. This is the opposite polarity from the LLM gate
(which is fail-OPEN). Rationale: an unverifiable book is exactly the condition
where slippage risk is highest, so default to no-trade.

## Backups

- `oi_divergence_scanner.py.bak.20260706_213315`
- `liq_cascade_scanner.py.bak.<ts>` + `funding_extreme_scanner.py.bak.<ts>`

## Tuning note (do NOT lower blindly)

When the desk goes quiet and the user asks to lower the threshold to "get more
signals" — first PROVE whether the gate is actually the blocker. Set
`base.MIN_EXIT_DEPTH_USD = 0` in a throwaway run and re-scan: if scanners still
return 0 signals, the block is at the SCORE stage (or market simply isn't giving
setups), NOT liquidity, and lowering the depth floor only invites slippage with
zero benefit. Verified 2026-07-06: with the gate fully off, OI_DIV/LIQ/FUNDING
still produced 0 signals — the 6 funding-extreme candidates all failed
`MIN_SCORE`, and their books were $50K–213K (i.e. the gate was correctly primed
to reject them anyway). The real signal-count lever in quiet markets is
`MIN_SCORE`, not the depth floor.
