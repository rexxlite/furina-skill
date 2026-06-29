# Trailing Stop Patterns

Reference for trailing stop logic across spot and perp. Use when the user asks
about trailing, partial close, runner management, or "TP gimana untuk spot".

## Five Common Trailing Patterns

### A. Activate-and-Trail (Simple Peak-Offset)
- SL awal struktural (support/swing low for long).
- Saat profit ≥ activation threshold (default `+3%` to `+5%`), trailing ON.
- Trail SL = `peak × (1 − offset%)` where offset is `2–3%`.
- Pros: simple, no indicator dependency.
- Cons: rigid — same offset on volatile and stable coins.

### B. ATR Trailing (Chandelier Exit) — Adaptive Volatility
- SL = `peak − ATR(14) × multiplier`.
- Multiplier `2.5–3.0` for swing 4h/1D.
- Auto-loosens on volatile coins, tightens on stable.
- Pros: respects each symbol's noise level.
- Cons: needs ATR calc per tick; trail recalc on every new candle.

### C. Step Trailing per Milestone
- `+3%` → SL → BE.
- `+6%` → SL → `+3%`.
- `+10%` → SL → `+6%`.
- Pros: discrete, predictable, easy to journal.
- Cons: between milestones the SL doesn't move; gives back more on reversal.

### D. EMA Trailing (Trend-Following)
- Exit when candle closes below EMA20 (4h) or EMA50 (1D).
- Pros: rides full trend, captures big moves.
- Cons: late exit; gives back recent peak; misses scalping ranges.

### E. Hybrid (RECOMMENDED for spot paper trading)
- TP1 partial close `40%` of qty at `+5%` (lock realized profit).
- Move SL on remaining `60%` to break-even.
- Remaining qty: trail with ATR `×2.5` or peak `−3%` (whichever wider).
- Optional fallback: exit if 1D candle closes below EMA20.
- Pros: locks early profit, lets winner run, protected vs reversal.
- Cons: more state to track per position.

## Hybrid Mechanics Example (the user's clarification)

The user asked: "kalau entry ETH $100 dan TP1 ambil 40% di +5%, jadi sisa $42?"

Common confusion: **partial close = 40% of QTY, not 40% of PROFIT.**

```text
Buy        : 1 ETH @ $100        → modal $100
+5% hit    : harga $105
TP1 jual   : 40% × 1 ETH = 0.4 ETH @ $105 → cash $42
Sisa       : 0.6 ETH masih hold (worth $63 di harga $105)
SL move    : break-even = $100 untuk sisa 0.6 ETH
```

After TP1:
- Realized cash: `$42`
- Open position: `0.6 ETH`
- Total equity at $105: `$42 + $63 = $105` (≈ +5% on full)

### Scenario A — price keeps running

```text
peak $115  → trailing peak −3% = SL sisa di $111.55
peak $120  → trailing $116.40
harga turun close di $116 → exit 0.6 ETH @ ~$116
Cash final : $42 + (0.6 × $116) = $42 + $69.6 = $111.6
Profit     : +$11.6 (+11.6%)
```

### Scenario B — price reverses after TP1

```text
harga turun ke BE $100 → SL sisa kena
exit 0.6 ETH @ $100 → cash $60
Cash final : $42 + $60 = $102
Profit     : +$2 (+2%) — TP1 already locked
```

### Scenario C — no hybrid (full hold)

```text
entry $100, peak $115, balik ke BE $100, SL kena
exit 1 ETH @ $100 → cash $100
Profit     : $0 — gain hilang semua
```

## Split Variants

- `40/60` (partial/runner) — aggressive, biggest runner upside. **Default for spot.**
- `50/50` — balanced, recommended for medium-confidence setups.
- `60/40` — conservative, locks more profit early; good for chop regimes.
- `25/25/50` (TP1/TP2/runner) — for high-confluence swing setups with multiple resistance levels.

## Spot-Specific Considerations

Spot has properties perp doesn't:

- **No leverage** → no liquidation risk; worst case = SL kena (`−risk%`).
- **No funding** → can hold indefinitely; trailing pays off more on multi-day runs.
- **Long only** → trailing patterns above all assume long; mirror for hypothetical short-on-margin not applicable.
- **Higher fee impact** → Binance Spot taker `0.1%` (vs Futures `0.04–0.05%`); set fee_round_trip = `0.2%` in sizing.
- **Slippage on small caps** → use `0.05–0.15%` slippage simulation depending on liquidity.

Risk per trade can be more aggressive on spot (3–5%) than perp (1%) precisely
because there is no liquidation cliff. The user's spot paper config:

```text
equity         : $1000 paper
risk_per_trade : 5%   (= $50 worst-case SL loss)
fee_round_trip : 0.2% (taker × 2)
slippage       : 0.05%
```

## Activation Threshold Guidance

Pick activation based on TF and target RR:

| Setup TF | Activation | Trail offset    | Notes                          |
|----------|------------|-----------------|--------------------------------|
| 1h scalp | +1.5R      | peak − 1.5%     | Tight; spot scalp rare         |
| 4h swing | +2R or +5% | ATR(14) × 2.5   | Default for Medium             |
| 1D swing | +3R or +8% | ATR(14) × 3 OR peak − 5% | Default for Safe       |
| Position | +5R+       | EMA20 1D close  | For trend-rider, multi-week    |

## Position Sizing for Hybrid TP

`risk_dollar` is the FULL position's stop-distance × qty. Partial close at TP1
realizes profit but does NOT change the original `risk_dollar` budget — it
only reduces remaining exposure.

```text
entry         = 100
sl_initial    = 96     (-4%)
risk_pct      = 5%
equity        = 1000
risk_dollar   = 1000 × 0.05 = 50
sl_distance   = 4
qty_full      = 50 / (4 + 100 × 0.002) = 50 / 4.2 ≈ 11.90 units
notional_full = 11.90 × 100 = $1190 (uses ~119% of equity → CAP at equity)
```

Spot caveat: `notional ≤ equity` (no leverage). If `qty × entry > equity`,
size down to `qty = equity / entry`. The user's $1000 paper equity means a
$100-priced asset caps at 10 units, regardless of risk budget. Actual risk
realized = `qty × sl_distance` which may be < target risk.

```text
qty_capped       = min(qty_full, equity / entry) = min(11.90, 10) = 10
realized_risk_$  = 10 × 4 = 40   (vs target 50 — that's fine, don't force leverage)
realized_risk_%  = 4% of equity
```

After TP1 partial:

```text
qty_remaining = qty × 0.6 = 6 units
sl_new        = entry (BE)
exposure      = 6 × 100 = $600 cash equivalent in position
worst_case_$  = 6 × 0   = $0 from BE level → max give-back = realized profit only
```

## Implementation Notes for Spot Paper Executor

When the user asks Furina to build the spot paper executor, the trailing
state machine should track:

```python
{
  "status": "ACTIVE | TP1_HIT_BE | TRAILING | CLOSED",
  "entry_price": float,
  "qty_initial": float,
  "qty_remaining": float,
  "realized_pnl": float,           # cash from partial closes
  "sl_current": float,             # initial → BE → trailing
  "peak_price": float,             # max since entry, updated on each tick
  "trail_mode": "peak_offset | atr | ema",
  "trail_param": float,            # offset %, atr_mult, or ema_period
  "tp1_hit_at": iso8601,
  "trail_active_since": iso8601 | None,
}
```

On each markPrice / kline close:

1. Update `peak_price = max(peak_price, current)`.
2. If `status == ACTIVE` and `current >= entry × (1 + tp1_pct)`:
   - Realize partial: `realized_pnl += qty × tp1_close_pct × (current − entry)`.
   - Reduce qty: `qty_remaining = qty × (1 − tp1_close_pct)`.
   - Move SL: `sl_current = entry` (BE).
   - Status → `TP1_HIT_BE`.
3. If `status == TP1_HIT_BE` and `peak_price >= entry × (1 + trail_activate_pct)`:
   - Status → `TRAILING`.
   - Compute first trailing SL.
4. If `status == TRAILING`:
   - Recompute trail SL = `f(peak_price, trail_mode, trail_param)`.
   - Only ratchet up: `sl_current = max(sl_current, new_trail_sl)`.
5. If `current <= sl_current`:
   - Close remaining: `realized_pnl += qty_remaining × (sl_current − entry)`.
   - Status → `CLOSED`.

Never trail SL backward. Never lower SL once it's at BE. Never trail across
the entry price (would expose to loss after partial).

## When to Reject Trailing in Favor of Fixed TP

- **Choppy regime** (range, no trend) → trailing whipsaws; use fixed TP at range high.
- **Very high RR setup** with clear measured-move target → fixed TP captures the move; trailing exits earlier than the level.
- **News-driven move** → close on event; don't let trailing ride into post-news mean reversion.
- **Low-liquidity pair** → trailing SL fills slip badly; fixed TP/SL preferred.
