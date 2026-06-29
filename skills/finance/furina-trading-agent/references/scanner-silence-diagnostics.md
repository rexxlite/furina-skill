# Scanner Silence Diagnostics

When the user asks "kenapa belum ada signal?" or the scanner has been silent for 2+ days, run this systematic diagnostic before answering. Do NOT speculate — trace the actual rejection path.

## Two DIFFERENT questions — diagnose the right one

Distinguish these before answering (users conflate them, asked 3x on 2026-06-13):

- **"No signal fired"** → scanner-side. The scanner found no qualifying setup. Use Steps 1-5 below (filters, BTC bias, market regime).
- **"Signal fired (appeared in the topic / Hasil Trade) but NO order on Binance"** → executor-side. The signal passed the scanner but was rejected by an execution guard. Use the executor-rejection trace below — do NOT chase scanner filters.

### Executor-rejection trace ("signal keluar tapi gak ada order di Binance")

The signal record exists in the journal but `executor.status` is SKIPPED/ERROR (or the record was never written). Trace it:

```python
python3 -c "
import json
j=json.load(open('/root/.hermes/trading_journals/automatic_signal_real_journal.json'))
r=[x for x in j if x['symbol']=='SYMBOL_HERE'][-1]
ex=r.get('executor',{}) or {}
print('score:',r.get('score'),'| exstat:',ex.get('status'),'| skip:',ex.get('skip_reason'),'| err:',ex.get('error'))
print('entry_oid:',ex.get('entry_order_id'))
"
```

Then confirm against the venue (truth is Binance, not the journal):
`client._signed('GET','/fapi/v1/openOrders',{'symbol':SYM})` and `/fapi/v1/openAlgoOrders`.

**Execution guards are BY DESIGN, not bugs.** A valid signal can legitimately be skipped by any of these — explain them as features that protect quality/risk, not as failures:

1. **Asia session score-bump** (00-08 UTC = 07-15 WIB): old scanners need score ≥ min+1. Most common cause of "fires fine at night, dead every morning". Trial scanners are exempt via `ASIA_EXEMPT_RISK_MODELS`.
2. **Max 5 concurrent positions** → 6th skipped (`max_concurrent_5`) until a slot frees.
3. **Per-symbol cooldown** (6-8h) → prevents double entry on same coin.
4. **Symbol blacklist** (2+ losses in 14d → 48h cooldown).
5. **Symbol not on Binance Futures** (`symbol_not_on_futures`) → common for Alpha tokens lacking perp.
6. **Risk-manager pause** (daily drawdown breach sets PAUSE_FILE).

**Anomaly to watch:** notification printed (delivered to topic) but NO journal record from that timestamp AND no order on testnet → the cron run used the OLD code (a fix was patched after that run fired) OR a concurrent writer (reconciler shares the same journal file) raced the write. Re-run the scanner manually and re-check; if it now writes + places orders, the earlier run was pre-fix. Always state which run the notification came from before concluding.

**Critical: never use market orders.** Confirmed execution model = LIMIT entry at the signal price + SL + 3 TP placed together immediately (no waiting for price to "hit"). If a user worries it waits for a market hit, reassure: limit entry goes in instantly. Verify the full bracket (1 LIMIT + 1 STOP_MARKET SL + 3 TAKE_PROFIT_MARKET reduceOnly) on the venue.

## Step 1: Verify cron health

```bash
# Check last run time and status for all three scanners
for JOB_ID in c0873b287577 dd9e1f27f04d 8e51594b30d8; do
  echo "=== $JOB_ID ==="
  ls -lt ~/.hermes/cron/output/$JOB_ID/*.md 2>/dev/null | head -3
  # Check if last output was silent or had content
  LATEST=$(ls -t ~/.hermes/cron/output/$JOB_ID/*.md 2>/dev/null | head -1)
  if [ -n "$LATEST" ]; then
    grep "Status:" "$LATEST"
  fi
done
```

Status meanings:
- `silent (empty output)` = script ran OK, found no signals (normal — this is the designed behavior)
- `script timed out` = hit the 120s cron hard limit (likely Binance 418 ban or too many symbols)
- `script failed` = script error (check stderr)

## Step 2: Check last actual signal

```bash
python3 -c "
import json
from pathlib import Path
j = Path.home() / '.hermes' / 'trading_journals' / 'automatic_signal_journal.json'
data = json.loads(j.read_text())
entries = data if isinstance(data, list) else data.get('entries', [])
for e in entries[-5:]:
    print(f\"{e.get('created_at','?')} | {e.get('symbol','?')} | {e.get('risk_model','?')} | {e.get('side','?')}\")
print(f'Total: {len(entries)}')
"
```

If last signal was 2+ days ago, proceed to Step 3.

## Step 3: Trace rejection reasons per symbol

This is the critical diagnostic. Write a debug script that replicates the scanner's filter chain and logs EXACTLY which filter rejects each symbol. The key filters in order:

1. **Indicators None** — EMA20/50, RSI, ATR couldn't compute (usually insufficient data)
2. **Low Volume Avg** — signal TF quote volume avg < $300K
3. **Candle Sanity** — candle range > 3.6×ATR or ATR/price < 0.0012
4. **BTC Bias Gate** — LONG blocked when `btc_bias == "bearish"`, SHORT blocked when `btc_bias == "bullish"`
5. **No Trend Alignment** — price not above/below EMA20/50 in the right direction
6. **Structure Conditions** — LONG needs `close > recent_high*0.992` AND `recent_high > prev_high*0.995`; SHORT needs `close < recent_low*1.008` AND `recent_low < prev_low*1.005`
7. **SHORT Safety Filters** — late-flush (chg24 < -5% + RSI < 35 + price > low*1.012), EMA20 reclaim (wick >= e20*0.995 + green body), post-flush reclaim (price > low*1.025)
8. **Close Above/Below Prev High/Low** — `use_close_above_ph`: LONG needs `cs[-2]["c"] > cs[-3]["h"]`, SHORT needs `cs[-2]["c"] < cs[-3]["l"]`. +1 score when fires. Implemented 2026-06-02.
9. **OHLC S/R Confluence** — `use_ohlc_confluence` (Medium/Safe only): counts OHLC levels (O/H/L/C) from signal TF + context TF within ±0.5% of price. Requires ≥3 levels from ≥2 TFs. +1 score when fires. Implemented 2026-06-02.
10. **Active Rules Veto** — auto-learned filters from past SLs

Run against top 15 symbols by volume and count rejections:

```python
# See /tmp/debug_scanner2.py pattern — trace each filter and tally rejection_reasons
```

### Common diagnostic outcomes

| Pattern | Meaning | Action |
|---------|---------|--------|
| `long_trend_but_btc_bearish: 8+` | BTC bearish blocks all longs | Normal in bearish BTC; explain to user |
| `short_late_flush` / `short_post_flush_reclaim` | Shorts blocked by safety filters | Normal — prevents chasing dumps |
| `no_trend_alignment: 10+` | Market in chop/range | No edge = no signal; correct behavior |
| `candle_sanity: 5+` | Abnormal volatility | Unusual; check if news event |
| All 15 pass filters but score < min | Scoring threshold too tight | Consider temporary threshold adjustment |
| All 15 get `indicators_none` | API data issue | Check Binance API health |
| Score passes but no output (silent vanish) | `apply_enhancements(mode=mode)` NameError — `mode` is local to `main()`, not accessible from `setup_for()`. The `try/except Exception: continue` in the scan loop silently swallows it. Fix: use `mode_cfg.get("label").lower().replace("-","_")` instead of bare `mode`. | Patch `automatic_signal_scanner.py` line with `apply_enhancements` call |

## Step 4: Check BTC bias separately

BTC bias is the #1 cause of prolonged scanner silence when the market is mixed (BTC bearish but alts bullish):

```bash
# Quick BTC bias check
python3 -c "
import sys, os; sys.path.insert(0, os.path.expanduser('~/.hermes/scripts'))
from automatic_signal_scanner import detect_btc_bias, detect_btc_bias_long
print(f'1H bias: {detect_btc_bias()}')
print(f'1D bias: {detect_btc_bias_long()}')
"
```

If `bearish`: all LONG setups are blocked across ALL modes (aggressive/medium/safe). This is by design.

## Step 5: Report to user

After running diagnostics, give the user:
1. Scanner health (running OK, last run time, status)
2. Days since last signal
3. Top rejection reason (e.g., "BTC bearish memblokir 8/15 long setups")
4. Whether this is normal market behavior or a code issue
5. Options: wait for market to improve, relax thresholds, or adjust BTC bias gate

## btc_bias_hard flag behavior (non-obvious)

The aggressive mode config says `btc_bias_hard: False` with comment "block only if extreme opposite", but the actual code has IDENTICAL gating in both branches:

```python
if mode_cfg["btc_bias_hard"]:
    # ... medium/safe path
    allowed_long = btc_bias != "bearish"
    allowed_short = btc_bias != "bullish"
else:
    # aggressive path — SAME LOGIC
    allowed_long = btc_bias != "bearish"
    allowed_short = btc_bias != "bullish"
```

The `btc_bias_hard` flag ONLY differs for Safe mode (which has `use_multi_tf_align=True`), where it adds a `btc_bias_long` (daily) check on top of the 1H check. For aggressive and medium, the behavior is identical regardless of the flag.

This means: when BTC is bearish, ALL modes block longs. When BTC is bullish, ALL modes block shorts. The "soft" vs "hard" distinction is about daily vs hourly bias gating on Safe mode only.

**Implication for user explanation:** Don't tell the user "aggressive mode has softer BTC bias gating" — that's misleading. It has the same gating. The difference is only in Safe mode's additional daily bias layer.

## Mixed-market pattern (BTC bearish + alts bullish)

This is the most common cause of multi-day scanner silence:

- BTC bearish → all longs blocked
- Alts actually trending up → short structure conditions fail (price > EMA20/50, close_pos > 0.45)
- Result: zero signals across all modes

This is CORRECT behavior — the scanner should not force trades in contradictory conditions. Explain to the user:
- "Market dalam fase mixed: BTC bearish tapi banyak altcoin naik sendiri"
- "Scanner tidak bisa long karena BTC bearish, dan tidak bisa short karena alts sebenarnya bullish"
- "Ini kondisi low-quality signal environment — lebih baik diam daripada memaksakan setup"

## Counter-Trend mode as crash solution

When BTC is bearish AND altcoins are deeply oversold (RSI < 30, BB %B < 0.15), the three trend-following modes will all be silent (longs blocked by BTC bias, shorts blocked by oversold RSI). This is exactly the condition the 🔄 Counter-Trend mode was designed for.

Counter-Trend mode differences from other modes:
- **Ignores BTC bias** — explicitly allows LONG when BTC is bearish
- **LONG-only** — no shorts (catching bounce, not chasing continuation)
- **Oversold gate** — requires RSI < 30 + (BB %B < 0.15 OR volume spike)
- **Tighter TP** — 0.8R/1.5R/2.2R (quick profit taking)
- **BB width disabled** — crash conditions produce BBW > 18% which would block signals

When diagnosing multi-day silence, check if counter-trend mode is also silent:
```bash
cd ~/.hermes/scripts && python3 automatic_signal_scanner.py --mode counter_trend 2>/dev/null
```

If counter-trend is ALSO silent despite oversold conditions, check:
1. `risk/em > max_risk` — crash ATR is wide, SL may be too far even at 0.5×ATR
2. `score < 6` — need at least RSI deeply oversold + BB oversold + one more factor
3. `vol_ratio < 1.5` — during crashes, volume is already elevated so ratio to avg may not spike
