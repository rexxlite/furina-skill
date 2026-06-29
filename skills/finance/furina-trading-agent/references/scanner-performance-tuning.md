# Diagnosing & Tuning a Losing Scanner

How to figure out WHY a deployed scanner bleeds and fix it from DATA, not theory.
Proven on the 2026-06-17 Funding + Range MR tune-up. Pairs with
`references/adding-new-scanner-strategy.md` (that one is about BUILDING a scanner;
this one is about EVALUATING and REPAIRING one that's already live).

## The golden rule: bedah the losses before touching the logic

User explicitly values this — never propose a fix from theory. Pull the closed
trades first, find the pattern in the actual losses, THEN read the scanner code to
explain the pattern, THEN fix. Present the smoking gun with numbers before asking
to apply anything. Sequence that wins user trust:
1. Per-trade dump of every closed trade for the scanner (win/loss, side, symbol,
   PnL, status, score, timestamp).
2. Split the stats by **SIDE** (LONG vs SHORT) — this is the single highest-yield
   cut and routinely exposes the whole problem.
3. Compute **avg win vs avg loss → RR ratio**. WR alone lies.
4. Read the scanner's gate/SL/TP logic to explain the pattern mechanically.
5. Present findings with numbers; propose fix; get approval; apply with backup +
   syntax check + dry-test that PROVES the gate works on real symbols.

## Diagnostic probe (run against the real journal)

Split closed trades by side and compute RR. This one script surfaces both classic
failure modes at once:

```python
import json
from collections import defaultdict
rows=json.load(open('/root/.hermes/trading_journals/automatic_signal_real_journal.json'))
CLOSED={'TP1_HIT','TP2_HIT','TP3_HIT','SL_HIT','MANUAL_CLOSED','CLOSED'}
for RM in ['funding','range_mr']:            # ← scanner risk_model(s) under review
    recs=[r for r in rows if r.get('risk_model')==RM and (r.get('status') or '').upper() in CLOSED]
    byside=defaultdict(lambda:{'w':0,'l':0,'net':0.0})
    for r in recs:
        pnl=float((r.get('executor') or {}).get('real_net_pnl_usdt') or 0)
        s=byside[r.get('side','?')]; s['net']+=pnl
        s['w' if pnl>0 else 'l']+= 1 if pnl else 0
    wins=[float((r.get('executor') or {}).get('real_net_pnl_usdt') or 0) for r in recs if float((r.get('executor') or {}).get('real_net_pnl_usdt') or 0)>0]
    loss=[float((r.get('executor') or {}).get('real_net_pnl_usdt') or 0) for r in recs if float((r.get('executor') or {}).get('real_net_pnl_usdt') or 0)<0]
    aw=sum(wins)/len(wins) if wins else 0; al=sum(loss)/len(loss) if loss else 0
    print(RM, dict(byside), f'avg win {aw:+.2f} avg loss {al:+.2f} RR {abs(aw/al) if al else 0:.2f}')
```

PnL lives at `executor.real_net_pnl_usdt` (NOT top-level `result_r`, which is often
None — if you read result_r you'll see a fake "all 0% WR" and chase a ghost).

## Two failure modes this exposes (both real, both fixed 2026-06-17)

### Mode 1 — one SIDE is structurally broken (Range MR)
Symptom: LONG 6W/4L +$13.56 (healthy) but SHORT 0W/5L -$37.24 (every short hit
SL). The whole scanner looked like a -$23 loser; really it was a profitable LONG
engine dragged down by a broken SHORT side.

Root cause: **mean-reversion has no higher-TF trend filter.** In a macro uptrend,
price poking the upper Bollinger band is breakout CONTINUATION, not a reversion
signal. The 1h `ADX<20` ranging gate can't see the 4h bullish bias, so every
counter-trend short gets run over.

Fix: gate the counter-trend side on a higher timeframe. Only allow SHORT when
4h close ≤ 4h EMA50 (no bullish HTF bias). Leave the trend-aligned side (LONG)
unrestricted. Generalizable rule: **any mean-reversion / fade scanner needs a
higher-TF trend filter on the side that fights the macro trend.** A single-TF
ADX/regime gate is not enough.

Proof-of-fix that convinced the user: re-ran the gate logic on the exact symbols
that lost (SUI, ENA, ETH, LAB) — 4 of 5 are now BLOCKED because 4h is still
bullish. The losing shorts would never have fired. That's the verification bar:
show the fix would have prevented the historical losses on named symbols.

### Mode 2 — RR is inverted, WR is a red herring (Funding)
Symptom: WR 50% but still losing. avg win +$5.85 vs avg loss -$8.74 → **RR 0.67**.
A coin-flip win-rate loses money when each loss is bigger than each win.

Root cause: **wide SL + near TP1.** SL was ATR×1.5 (wide) while TP1 sat at RR 1.0
(near). On a TP1 hit only ~40% closes + rest goes to BE → tiny locked profit; on
SL → the full wide loss. Asymmetric by construction.

Fix: tighten SL (ATR×1.5 → ATR×1.0) AND push the TP ladder out
(RR [1.0,1.5,2.5] → [1.5,2.5,4.0]) so the first partial is at least worth the risk
taken. Generalizable rule: **a good win-rate is worthless if RR is inverted.**
TP1 should sit at RR ≥ 1.5 when the exit plan banks a partial at TP1 and trails
the rest; otherwise the locked-in profit can't cover the full-size stop-outs.

## Apply-fix checklist (user's trusted staged workflow)
1. `cp scanner.py scanner.py.bak.$(date +%Y%m%d_%H%M%S)` — backup first, always.
2. Edit config constants at the top (keep the old values in an inline comment +
   a dated rationale comment block — user likes the audit trail in-code).
3. `python3 -c "import ast; ast.parse(open('scanner.py').read())"` syntax check.
4. Dry-test that PROVES the new gate/RR on REAL data — don't just say "0 fired, ok".
   For a gate: run the gate logic against the symbols that historically lost and
   show they'd now be blocked. For an RR change: print the resulting SL/TP ladder
   with computed RR per TP.
5. No restart needed — cron scanners auto-reload the module each tick.

## When to tune vs shut down vs wait (decision frame the user endorsed)
- Sample < ~30 closed trades per scanner → too small to vonis; WR is mostly
  variance. Demo phase costs nothing, so prefer WAIT over shutdown.
- Set a hard finish line: 7 days OR 30 closed trades, whichever first. The real
  danger is neither shutdown nor wait — it's forgetting to decide and letting a
  loser bleed "to collect data" forever.
- Zero-fire scanners (e.g. Liq Cascade with 0 closed) are a FREQUENCY issue, not a
  WR issue — different category, don't judge them on WR. Let them run.
- A scanner with a deteriorating trend (WR down AND net down week over week) can be
  retired early without waiting the full window — that pattern signals broken entry
  logic, not variance.
- If losses concentrate on one side or one regime, TUNE (gate the bad side/regime)
  before you SHUT DOWN — you usually have a profitable sub-strategy hiding inside a
  net-losing scanner.
