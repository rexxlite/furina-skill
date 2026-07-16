# Daily Profit Target & Loss Limit — Hard Stops

Two symmetric risk management mechanisms that pause all new entries based on
realized PnL for the day:

- **Profit target (+$10)**: locks in morning gains, prevents "afternoon give-back"
- **Loss limit (−$10)**: stops bleeding, prevents revenge trading after a bad streak

Both reuse the same PAUSE_FILE infrastructure and reset at UTC rollover.

## When this applies

- User reports a recurring pattern: Furina profitable in morning, gives it back
  in afternoon/evening → profit target
- User asks "gimana mekanisme kalau minus? tidak ada stop juga?" → loss limit
  (symmetric to profit target, user-approved 2026-06-30)
- User asks for a mechanism to "stop trading once profit hits $X"
- User asks to "lock in" daily gains or "stop bleeding" at a daily loss cap
- Any discussion of daily take-profit, daily target, profit lock, loss limit,
  or throttle

## Mechanism — reuse PAUSE_FILE, do NOT build a separate system

The risk manager (`binance_real_risk_manager.py`) already owns the PAUSE_FILE
(`/root/.hermes/EXEC_PAUSE_REAL`) and the executor already checks it as gate #2
(see operational-systems.md section 6). The daily profit target is just a
NEW REASON to set the same flag. Do not create a second pause file or a second
gate — that creates divergent states.

### Config (in `binance_real_risk_manager.py`)

```python
DAILY_PROFIT_TARGET = 10.0  # $10 realized profit → PAUSE (hard stop)
DAILY_LOSS_LIMIT = -10.0    # -$10 realized loss → PAUSE (hard stop, symmetric)
```

### Logic — combined profit + loss check in one API call

Both checks share a single `income_history` API call (rate-limit friendly).
Inserted after baseline validation, BEFORE drawdown check. No flip-flop:
once either flag is set, it stays set until UTC rollover reset.

```python
# ── Daily realized PnL checks (hard stop) ──────────────────────────
# Profit target: realized ≥ +$10 → PAUSE (lock profit, no give-back)
# Loss limit:    realized ≤ -$10 → PAUSE (stop bleeding, no revenge trades)
profit_hit = state.get("profit_target_hit_today")
loss_hit = state.get("daily_loss_limit_hit_today")
if not profit_hit and not loss_hit:
    try:
        start_ms = int(datetime.strptime(today, "%Y-%m-%d")
                      .replace(tzinfo=timezone.utc).timestamp() * 1000)
        incomes = client.income_history(income_type="REALIZED_PNL",
                                        start_time_ms=start_ms, limit=100)
        realized_today = sum(float(x.get("income", 0)) for x in incomes)
    except Exception:
        realized_today = None  # API fail → skip checks, don't crash

    if realized_today is not None:
        if realized_today >= DAILY_PROFIT_TARGET:
            PAUSE_FILE.touch()
            state["profit_target_hit_today"] = True
            state["profit_target_amount"] = round(realized_today, 2)
            save_state(state)
            print(f"🎯 [REAL Risk] DAILY PROFIT TARGET HIT — ${realized_today:.2f}...")
            return {"status": "profit_target_paused", "realized_today": realized_today}

        if realized_today <= DAILY_LOSS_LIMIT:
            PAUSE_FILE.touch()
            state["daily_loss_limit_hit_today"] = True
            state["daily_loss_amount"] = round(realized_today, 2)
            save_state(state)
            print(f"🛑 [REAL Risk] DAILY LOSS LIMIT HIT — ${realized_today:.2f}...")
            return {"status": "loss_limit_paused", "realized_today": realized_today}
```

### Reset at UTC rollover (in the new-day block)

```python
if not baseline:
    state["daily_baseline"] = {"date": today, "equity": equity}
    state["alerted_today"] = False
    state["profit_target_hit_today"] = False      # reset daily profit lock
    state["daily_loss_limit_hit_today"] = False   # reset daily loss lock
    if PAUSE_FILE.exists():
        PAUSE_FILE.unlink()
```

### Executor skip-reason differentiation

The executor's PAUSE_FILE gate (section 6 of operational-systems.md) must
distinguish "profit target hit" / "loss limit hit" / "drawdown breach" so
skip_reason is accurate for audit:

```python
if PAUSE_FILE.exists():
    reason = "risk_paused"
    msg = "EXEC_PAUSE_REAL flag present"
    try:
        rs = json.loads(Path("/root/.hermes/trading_journals/real_risk_state.json").read_text())
        if rs.get("profit_target_hit_today"):
            reason = "profit_target_hit"
            msg = f"Daily profit target hit (${rs.get('profit_target_amount', '?')} realized) — hard stop"
        elif rs.get("daily_loss_limit_hit_today"):
            reason = "daily_loss_limit_hit"
            msg = f"Daily loss limit hit (${rs.get('daily_loss_amount', '?')} realized) — hard stop, no revenge trades"
    except Exception:
        pass
    # ... rest of skip logic with reason + msg ...
```

## Design decisions (user-approved)

- **Hard stop, not soft throttle.** Once target/limit hit, ALL new entries
  blocked. No "reduce risk to 0.5%" or "raise threshold by +1" — those still
  allow losses. The user explicitly chose hard stop for both profit and loss.
- **Realized PnL only, not equity.** Uses Binance income API REALIZED_PNL sum
  since 00:00 UTC. Not total equity (which includes uPnL that can swing back).
  Only locked-in profits/losses count.
- **No flip-flop.** Once either flag is set True, it stays True until UTC
  rollover reset. Even if open positions later swing the other way, entries
  stay paused. Prevents "entry → PnL swings → entry again" churn.
- **Symmetric +$10 / −$10.** User chose the same dollar amount for both
  directions. $10 = 3.3% of $300 equity. Lock profit at +3.3%, stop bleeding
  at −3.3%. Balanced daily range.
- **Existing positions still managed.** PAUSE only blocks NEW entries. The
  reconciler continues to manage TP/SL/BE on open positions. This is correct —
  locking profit doesn't mean abandoning open trades.
- **Auto-reset at UTC midnight (07:00 WIB).** The new-day block clears both
  flags and the PAUSE_FILE. No manual intervention needed to resume next day.
- **Single API call for both checks.** Profit and loss checks share one
  `income_history` call — rate-limit friendly. Don't split into two calls.

## Verification after deployment

```bash
# 1. Compile check
python3 -c "import binance_real_risk_manager; print('OK')"

# 2. Dry run — check today's realized PnL vs target
python3 << 'PYEOF'
import sys; sys.path.insert(0, '/root/.hermes/scripts')
from binance_real_client import BinanceRealClient
from datetime import datetime, timezone
client = BinanceRealClient()
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
start_ms = int(datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
incomes = client.income_history(income_type="REALIZED_PNL", start_time_ms=start_ms, limit=100)
realized = sum(float(x.get("income", 0)) for x in incomes)
print(f"Realized today: ${realized:.4f}")
print(f"Target: $10.00")
print(f"Status: {'WOULD PAUSE' if realized >= 10.0 else 'below target — no pause'}")
PYEOF

# 3. Check state file
cat /root/.hermes/trading_journals/real_risk_state.json
# Should NOT contain profit_target_hit_today=True unless target was hit

# 4. Run risk manager
python3 /root/.hermes/scripts/binance_real_risk_manager.py --debug
```

## Tuning the limits

- $10 = 3.3% of $300 equity (real mainnet starting balance)
- Based on 3-day data: Furina can earn +$8-10 in Asia session (07-15 WIB)
  before give-back starts in London/US
- Loss limit symmetric at −$10: prevents the "8 SL streak in one afternoon"
  pattern (2026-06-29: 8 SLs totaling −$18 in one afternoon/evening)
- If equity grows to $600, consider raising both to ±$20 (keep ~3.3% ratio)
- If target is too low: Furina stops early on good days, misses larger runs
- If target is too high: rarely triggers, doesn't prevent give-back
- If loss limit is too tight: stops Furina on a normal bad day before it can
  recover (but user chose hard stop deliberately — no revenge trades)
- **Tune via `DAILY_PROFIT_TARGET` and `DAILY_LOSS_LIMIT` constants only.**
  Do not make them dynamic (e.g. "% of equity") without user approval — the
  user chose fixed dollar amounts deliberately. Keep them symmetric unless
  the user says otherwise.

## Interaction with other risk controls

| Control | Trigger | Effect | Coexists? |
|---|---|---|---|
| Daily profit target | Realized PnL ≥ +$10 | PAUSE new entries | Yes — checked first |
| Daily loss limit | Realized PnL ≤ −$10 | PAUSE new entries | Yes — checked second |
| Daily drawdown (5%) | Equity ≤ baseline × 0.95 | PAUSE new entries | Yes — checked after PnL checks |
| Catastrophic (10%) | Equity ≤ baseline × 0.90 | KILL (manual reset) | Yes — overrides everything |

Profit target and loss limit are mutually exclusive (realized can't be both
≥+$10 and ≤−$10). Both share one API call. Drawdown is equity-based and can
fire alongside either if uPnL swings hard after realized triggers. The code
checks profit → loss → drawdown → catastrophic in order; first trigger wins
and returns early.

## Pitfalls

- **API failure on income_history → skip profit check, don't crash.** The
  `try/except` returns `realized_today = None` and the `if realized_today is
  not None` guard skips the pause. A transient API error should never crash
  the risk manager or falsely pause trading.
- **`limit=100` on income_history may truncate on high-activity days.** If
  Furina closes 100+ trades in one UTC day, the earliest REALIZED_PNL events
  get dropped. For $300 equity at 1% risk, this is unlikely (~$3/trade × 100
  = $300 = 100% equity turnover). But if equity or trade frequency grows,
  raise the limit or paginate.
- **Do not use TOTAL equity (wallet + uPnL) for the check.** uPnL is
  unrealized and can swing back. Only REALIZED_PNL from income API is locked-in.
  The user explicitly chose realized-only.
- **UTC midnight reset, not WIB midnight.** The baseline reset happens at
  00:00 UTC = 07:00 WIB. This means the "day" for profit target purposes
  starts at 07:00 WIB. Trades closed between 00:00-07:00 WIB count toward
  the PREVIOUS day's target. This is consistent with the drawdown baseline
  reset logic — do not change one without changing both.
