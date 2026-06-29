# Scanner SL-Streak Diagnosis & Tuning Playbook

When a scanner produces 3+ consecutive SLs (or any cluster the user flags), follow this playbook instead of reacting to the latest loss. It applies to ANY Furina scanner — `automatic_signal_scanner.py`, `oi_divergence_scanner.py`, `funding_extreme_scanner.py`, `liq_cascade_scanner.py`, counter-trend, alpha, etc.

## Step 1 — Identify the offending scanner from journal cluster

Pull the recent closed trades. Look for:

- **Same scanner repeating** in the SL cluster (e.g. all 4 from `OI_DIV`).
- **Same side bias** (all LONG or all SHORT) — points to a market-regime mismatch.
- **Same time window** (all within hours) — distinguishes statistical noise from a structural break.

If the cluster spans multiple scanners, it's market regime; one scanner only = scanner tuning problem.

```bash
# Quick cluster pull
python3 -c "
import json
trades = json.load(open('/root/.hermes/trading_journals/automatic_signal_real_journal.json'))
sl = [t for t in trades if (t.get('executor') or {}).get('status','').startswith('SL_HIT')]
for t in sl[-10:]:
    print(t.get('closed_at'), t['symbol'], t['side'], t.get('risk_model'), 'score=', t.get('score'))
"
```

## Step 2 — Read the scanner config & scoring logic

For the offending scanner, check:

1. **`MIN_SCORE` threshold** — is it too permissive vs scanner's max? Anything ≤60% of max is suspect.
2. **Score base inflation** — does `score += 1` get awarded just for "pattern present"? That's a free point, not a confirmation. Effective threshold is `MIN_SCORE - free_points`.
3. **Market regime gate present?** — is there a `detect_btc_bias()` check? Counter-trend scanners (OI_DIV, COU, LIQ_CASCADE) need it. Trend-following scanners (BREAKOUT, AGGR) don't.
4. **RSI extremes** — does it reject "catching falling knife" cases?

Reference comparison (Furina scanner thresholds as of 2026-06-29):

- COU_4H: ≥7/10 (70%)
- MED_1H: ≥8/9 (89%)
- SAFE: ≥8/18 (44% — but with W/M OHLC confluence)
- OI_DIV: ≥4/5 (80%, raised from 3/5 on 2026-06-29)
- FUNDING: check current
- LIQ_CASCADE: check current

## Step 3 — Diagnose root cause before patching

Match the SL cluster pattern against the scanner's logic:

| Symptom | Likely cause | Fix |
|---|---|---|
| All LONG in down market | Missing BTC bias gate | Add `detect_btc_bias()` rejection |
| All same-side fills, mixed market | Threshold too low | Raise `MIN_SCORE` |
| Wins big, loses small but frequent | OK statistically — sample size too small | Don't react |
| Wins big, loses big — net negative | Scanner edge is gone in this regime | Pause scanner via cron, evaluate weekly |
| One scanner consistently bleeds 2+ weeks | Strategy doesn't work in current market — kill it | Remove cron + archive (precedent: RANGE_MR + BREAKOUT_RT removed 2026-06-26) |

## Step 4 — Patch procedure (safe-deploy)

```bash
# 1. Backup with timestamp
cp /root/.hermes/scripts/<scanner>.py /root/.hermes/scripts/<scanner>.py.bak.YYYYMMDD_HHMMSS

# 2. Patch via `patch` tool (replace MIN_SCORE constant, or insert bias gate)
# Place new gates AFTER classify() returns side, BEFORE scoring loop.

# 3. Compile + smoke-test
python3 -c "
import <scanner> as s
import automatic_signal_scanner as base
print('MIN_SCORE =', s.MIN_SCORE)
print('BTC bias 1h =', base.detect_btc_bias())
print('BTC bias 1d =', base.detect_btc_bias_long())
"

# 4. No cron restart needed — scanners auto-reload module each tick.
```

## Step 5 — BTC bias gate template (counter-trend scanners only)

Drop in AFTER `setup_type, side, label = cls` and BEFORE the scoring block:

```python
# ── BTC bias gate ───────────────────────────────────────────────────
# Counter-trend strategies fight the trend by nature; don't let them
# fight the BTC trend on top of that.
btc_bias = base.detect_btc_bias()  # uses 1h EMA20 vs EMA50
if btc_bias == "bearish" and side == "LONG":
    return None  # don't catch falling knife in downtrend
if btc_bias == "bullish" and side == "SHORT":
    return None  # don't fade rally in uptrend
# Neutral BTC → allow both (no clear direction to fight)
```

For STRONGER filter use `detect_btc_bias_long()` (1d EMA) — fewer signals, more conservative. Use 1h for moderate filter (default).

DO NOT use BTC bias gate on:
- Trend-following scanners (they ARE supposed to align with trend already)
- Cross-market scanners (alpha tokens often decouple from BTC)

## Step 6 — Eval window

After deploying a tuning change, set explicit eval window. DO NOT react before this window expires:

- **MIN_SCORE bumps**: 7 days minimum (need ~10+ signals at new threshold to judge)
- **New gate added**: 14 days (changes signal frequency, need to see across BTC regimes)
- **Scanner removal**: irreversible — make sure the 2-week eval shows clear negative net

Targets to validate:
- Signal frequency drop (expected, confirm it's not 0)
- WR ≥ pre-change baseline
- Net PnL ≥ pre-change baseline OR drawdown clearly smaller

## Step 7 — Always update memory + this reference

After deploying:
- Memory entry: scanner name + change + date + trigger (e.g. "4 SL streak SLX/RE/POWR/MANTA −$9.12") + backup filename + eval date.
- This reference: update the threshold comparison table in Step 2 with the new value.

## Anti-patterns

- **Reacting to single SL.** WR 52% scanner will have 4-loss streaks every ~20 sessions just statistically. Need cluster + cause hypothesis before patching.
- **Patching without backup.** Always `*.bak.YYYYMMDD_HHMMSS` first.
- **Lowering threshold to "get more signals".** Almost always wrong direction — more signals at lower quality = more drawdown.
- **Adding BTC gate to trend-following scanners.** They already align with trend; gate just double-filters and kills signal volume.
- **Removing scanners after 1 bad week.** Need 2+ weeks of net-negative data and clear cause hypothesis. Precedent: RANGE_MR/BREAKOUT_RT had 2-week negative eval before removal.

## Historical precedent

- 2026-06-29: OI_DIV MIN_SCORE 3→4 + BTC bias gate added. Trigger: 4 SL same-day (SLX/RE/POWR/MANTA, −$9.12) in BTC bearish regime, 3 of 4 were LONG.
- 2026-06-26: RANGE_MR + BREAKOUT_RT cron removed after 2-week eval (−$136 + −$85 net).
- 2026-06-07: Aggressive/Medium OHLC pattern usage removed — wrong TF for W/M S/R logic.
