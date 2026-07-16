# Scanner SL-Streak Diagnosis & Tuning Playbook

When a scanner produces 3+ consecutive SLs (or any cluster the user flags), follow this playbook instead of reacting to the latest loss. It applies to ANY Furina scanner — `automatic_signal_scanner.py`, `oi_divergence_scanner.py`, `funding_extreme_scanner.py`, `liq_cascade_scanner.py`, counter-trend, alpha, etc.

## Step 1 — Identify the offending scanner from journal cluster

Pull the recent closed trades. Look for:

- **Same scanner repeating** in the SL cluster (e.g. all 4 from `OI_DIV`).
- **Same side bias** (all LONG or all SHORT) — points to a market-regime mismatch.
- **Same time window** (all within hours) — distinguishes statistical noise from a structural break.

If the cluster spans multiple scanners, it's market regime; one scanner only = scanner tuning problem.

**For deeper diagnosis** — if the cluster correlates with a time-of-day pattern (e.g. all SLs in London hours), run a session-by-close-time analysis. See `references/scanner-session-analysis.md` for the income-API + journal cross-reference technique. This distinguishes "scanner is broken" from "scanner is fine but wrong session for its style".

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

Reference comparison (Furina scanner thresholds as of 2026-06-30):

- COU_4H: ≥7/10 (70%)
- MED_1H: ≥8/9 (89%)
- SAFE: ≥8/18 (44% — but with W/M OHLC confluence)
- OI_DIV: ≥4/5 (80%, raised from 3/5 on 2026-06-29)
- FUNDING: ≥5/6 (83%, raised from 4/6 on 2026-06-30 — see Step 2.5)
- LIQ_CASCADE: check current

## Step 2.5 — Score-vs-outcome correlation (decide: raise threshold vs pause)

Before raising `MIN_SCORE`, check whether score correlates with outcome at all.
If high-score trades also lose, a threshold bump won't fix it — the scanner's
edge is gone in this regime, not just letting weak signals through.

**Technique**: pull every closed trade for the scanner, print score + PnL side
by side, look for a cutoff where outcomes flip from bad to good.

```python
import json
j = json.load(open('/root/.hermes/trading_journals/automatic_signal_real_journal.json'))
trades = [r for r in j if (r.get('executor') or {}).get('bucket')=='FUNDING' and r.get('closed_at')]
for r in trades:
    ex = r.get('executor') or {}
    pnl = ex.get('real_net_pnl_usdt', 0)
    print(f"  {r.get('symbol'):12s} score={r.get('score')}/{r.get('scanner_min_score')} "
          f"side={r.get('side')} status={r.get('status')} pnl={pnl:+.2f}")
```

Then group by score level and compute WR + net per level:

| Pattern | Meaning | Action |
|---|---|---|
| Low-score trades lose, high-score trades win | Score IS predictive — threshold bump will help | Raise `MIN_SCORE` to the cutoff |
| High-score trades also lose | Score is NOT predictive — edge is gone in this regime | Do NOT raise threshold (kills signal volume for no gain). Pause scanner or investigate logic. |
| Too few trades to tell (≤4) | Insufficient data | Do NOT tune yet — let it run, collect more sample |
| All trades same score | Threshold already at floor, no granularity | Can't judge — need lower-threshold data or different approach |

**Concrete examples (2026-06-30):**

- **FUNDING** — score correlated with outcome. Score-4 signals: 1W/5L = −$7.07.
  Score-5 signals: 2W/1L = +$5.79. Clear cutoff at 4→5. **Action: raised
  MIN_SCORE 4→5.** Predicted: signal frequency drops ~60%, WR rises ~20→67%.
- **COU_4H** — score did NOT correlate. 4 trades: score 6.3 SL, score 7 SL,
  score 7.3 TP1, score 8.3 SL. High score (8.3) still SL. **Action: did NOT
  raise threshold — sample too small and no correlation. Left alone to collect
  more data.**

**Pitfall**: with ≤4 trades, any pattern is noise. Don't tune from 4 data points
unless the score-outcome correlation is dramatic (like FUNDING's 1W/5L vs 2W/1L
split). When in doubt, wait for more sample.

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

Drop in AFTER `setup_type, side, label = cls` and BEFORE the scoring block.

**Use the 2-LAYER version as default** (1h + 1D). A 1h-only gate is insufficient — see pitfall below.

```python
# ── BTC bias gate (2-layer: 1h fast + 1D macro) ─────────────────────
# Counter-trend strategies fight the trend by nature; don't let them
# fight the BTC trend on top of that. BOTH layers must not fight.
# 1h bearish → skip LONG. 1h bullish → skip SHORT.
# 1D bearish → skip LONG even if 1h is neutral (sideways inside downtrend).
# 1D bullish → skip SHORT even if 1h is neutral.
# Only allow a side if NEITHER TF disagrees with it.
btc_bias = base.detect_btc_bias()        # 1h EMA20 vs EMA50
btc_bias_d = base.detect_btc_bias_long()  # 1D EMA20 vs EMA50
if btc_bias == "bearish" and side == "LONG":
    return None  # 1h downtrend — don't catch falling knife
if btc_bias == "bullish" and side == "SHORT":
    return None  # 1h uptrend — don't fade rally
if btc_bias_d == "bearish" and side == "LONG":
    return None  # macro downtrend, 1h sideways = still don't buy
if btc_bias_d == "bullish" and side == "SHORT":
    return None  # macro uptrend, 1h sideways = still don't short
```

**Minimal (1h-only) variant** — use ONLY when you want a permissive gate and accept that sideways-on-1h-inside-macro-trend cases will leak through:

```python
btc_bias = base.detect_btc_bias()  # 1h only
if btc_bias == "bearish" and side == "LONG": return None
if btc_bias == "bullish" and side == "SHORT": return None
```

### PITFALL — single-TF bias gate leaks sideways-in-trend cases (learned 2026-06-29)

A 1h-only gate returns `"neutral"` when BTC 1h EMA20 ≈ EMA50 (sideways). But BTC can be sideways on 1h WHILE the 1D macro is in a clear downtrend. In that state the 1h gate allows LONG, and counter-trend LONGs get chopped up as the macro downtrend resumes.

**Concrete incident:** OI_DIV had a 1h-only gate added at 17:06 WIB. At 17:42 WIB a RAVE LONG score-5 signal fired — BTC 1h was "neutral" so the gate allowed it. BTC 1D was "bearish". RAVE hit SL at 18:47 WIB (−$2.39). The 1D layer was added at ~20:00 WIB the same evening. After the 1D layer, `LONG -> BLOCKED` when 1D is bearish regardless of 1h state.

**Lesson:** for counter-trend scanners, always start with the 2-layer gate. A single-TF gate is a half-fix that will leak within hours during a macro-trending-but-intraday-choppy regime.

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

- 2026-06-30: FUNDING MIN_SCORE 4→5. Trigger: 5-day analysis showed FUNDING WR 20% (1W/4L from closed trades), net −$3.74. Score-vs-outcome correlation (Step 2.5) revealed clear cutoff: score-4 signals went 1W/5L = −$7.07, score-5 signals went 2W/1L = +$5.79. Raised threshold to filter score-4 signals while preserving score-5+ signals. COU_4H (WR 25%, 4 trades) was NOT tuned — score did not correlate with outcome (score 8.3 still SL) and sample was too small. Backup: `funding_extreme_scanner.py.bak.20260630_*`.
- 2026-06-29 (evening): OI_DIV bias gate upgraded 1h-only → 2-layer (1h + 1D). Trigger: RAVE LONG score-5 passed the 1h gate (1h neutral) and hit SL (−$2.39) — BTC 1D was bearish the whole time. Added 1D layer so LONG is blocked when 1D is bearish regardless of 1h state. Same-day continuation of the 17:06 patch.
- 2026-06-29 (17:06): OI_DIV MIN_SCORE 3→4 + 1h-only BTC bias gate added. Trigger: 4 SL same-day (SLX/RE/POWR/MANTA, −$9.12) in BTC bearish regime, 3 of 4 were LONG. Session analysis later same day showed the SL cluster continued into London+US overlap (8 SLs total, −$18) — see `references/scanner-session-analysis.md`.
- 2026-06-26: RANGE_MR + BREAKOUT_RT cron removed after 2-week eval (−$136 + −$85 net).
- 2026-06-07: Aggressive/Medium OHLC pattern usage removed — wrong TF for W/M S/R logic.
