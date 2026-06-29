# Decision Pipeline — signal to managed position

End-to-end map of how a scanner signal becomes a managed position with trailing
risk. This reflects the **real mainnet** deployment (Binance USDT-M perpetual,
one-way CROSSED, flat 1% risk per trade, max 6 concurrent positions). Verified
against `binance_real_executor.py` and `binance_real_reconciler.py`.

The gates in Stage 2 run **sequentially and short-circuit** on the first failure.

## Full pipeline

```mermaid
flowchart TD
    S1[Stage 1 — Scanner fire<br/>10 scanners, multi-TF<br/>need at least 4/7 confirmations] --> WJ[Write record to journal<br/>symbol, side, entry, SL, TP1/2/3, score]
    WJ --> G{Stage 2 — Executor gates}

    G --> Ga[a. valid side/symbol/levels]
    Ga --> Gb[b. symbol on Binance perp]
    Gb --> Gc[c. bucket allowed + alpha volume]
    Gc --> Gd[d. not blacklisted<br/>cooldown after 2+ losses / 14d]
    Gd --> Ge[e. same-symbol guard<br/>1 pair = 1 active position]
    Ge --> Gf[f. Asia-session score filter<br/>00-08 UTC]
    Gf --> Gg[g. max concurrent<br/>active below 6]
    Gg --> Gh[h. sizing — risk 1% flat<br/>qty from SL distance]

    Gh --> SUB[Stage 3 — Submit order<br/>set margin + leverage<br/>LIMIT entry placed]
    SUB --> SUBSTATE[Status: SUBMITTED]

    SUBSTATE --> RC[Stage 4 — Reconciler every 5 min<br/>only acts on SUBMITTED / ACTIVE / TP1_BE / TP2_T1]

    RC --> FILLCHECK{Entry filled?}
    FILLCHECK -- No, stale --> FB[Fallback to MARKET<br/>one-shot if age past threshold]
    FILLCHECK -- Yes --> ACTIVE[Place SL + TP algos<br/>Status: ACTIVE]

    ACTIVE --> SLGUARD[SL-guard every tick<br/>naked position -> re-place STOP + alert]
    ACTIVE --> TPSTATE{Stage 5 — TP/SL state machine}

    TPSTATE -- SL hit --> SLLOSS[SL_HIT<br/>full stop, approx -1R]
    TPSTATE -- TP1 reached --> TP1[Close 30%<br/>SL moves to breakeven<br/>Status: TP1_HIT_BE]
    TP1 --> TPSTATE2{Next event?}
    TPSTATE2 -- SL at BE --> BEEXIT[SL@BE<br/>capital safe, TP1 profit kept]
    TPSTATE2 -- TP2 reached --> TP2[Close next leg<br/>SL trails to TP1<br/>Status: TP2_HIT_T1]
    TP2 --> TPSTATE3{Next event?}
    TPSTATE3 -- Trailing stop --> TRAIL[Closed by trailing stop]
    TPSTATE3 -- TP3 reached --> TP3[TP3_HIT<br/>runner closes at TP3]

    SLLOSS --> DASH[Dashboard sync<br/>near real-time]
    BEEXIT --> DASH
    TRAIL --> DASH
    TP3 --> DASH

    FB --> ACTIVE
```

## Stage notes

**Stage 1 — Scanner fire.** Ten scanners cover different timeframes and edges:
aggressive / medium / safe / counter-trend / alpha (trend-following) plus
oi_divergence, funding, liq_cascade, breakout_retest (statistical-edge). Each
requires at least 4 of 7 confirmations: multi-TF alignment, volume, Bollinger
squeeze, RSI + MACD, price action, smart volume, TA + sentiment. A passed
signal writes a journal record with a top-level `score` and `scanner_min_score`
(the score field is mandatory — without it the Asia-session filter reads 0 and
silently skips the signal).

**Stage 2 — Executor gates.** All eight gates must pass, in order. Any failure
sets status SKIPPED or ERROR with a granular `skip_reason`, sends a single-line
notification to the Auto Signal topic, and places no order. The same-symbol
guard and the manual-position guard (skip symbols the operator holds manually)
keep Furina from fighting itself or the operator.

**Stage 3 — Submit order.** Margin mode and leverage are set idempotently
(tolerating the "open position exists" error). A LIMIT entry is placed. The
STOP_MARKET and TAKE_PROFIT_MARKET algos are placed **after** the entry fills,
because reduce-only orders require an existing position — placing them before
fill triggers error -2021 "would immediately trigger".

**Stage 4 — Reconciler.** Runs every 5 minutes and only acts on live states.
On LIMIT fill it records the average fill price and slippage, places the SL and
TP algos, and flips status to ACTIVE. If the limit order is stale but price
already swept the entry zone, a one-shot market fallback may fire. The SL-guard
runs every tick: every open position must have a live STOP on Binance; a naked
position gets its STOP re-placed at the tightest earned level and an alert fires.

**Stage 5 — TP/SL state machine.** Transitions are detected by comparing closed
quantity against stored TP1/TP2 thresholds. TP1 closes a partial leg and moves
SL to breakeven — the remainder runs risk-free. TP2 trails SL up to TP1. Exits
are SL_HIT, SL@BE, trailing stop, or TP3. TP3 rarely tags directly because the
trailing stop usually stops the runner first; "TP3 = 0 across scanners" is
expected, not a bug. Every transition syncs to the dashboard in near real-time.

## Risk envelope

- Flat 1% risk per trade (RISK_PCT = 0.01) across all scanners.
- Max 6 concurrent positions — limits aggregate risk, not margin. Worst case
  6 simultaneous SL hits = -6% drawdown.
- Leverage 4-5x by bucket (OI divergence / confirmation-of-understanding 5x,
  funding / liq-cascade / alpha 4x). Leverage does not set risk — position size
  comes from the SL distance. Leverage only affects margin lockup and how far
  the liquidation price sits behind the stop.
- Risk manager runs every 5 minutes: auto-PAUSE on 5% daily drawdown,
  auto-KILL on 10% catastrophic drawdown.
- Manual killswitch: `touch /root/.hermes/EXEC_KILL_REAL` freezes the executor
  instantly for maintenance or emergency.
