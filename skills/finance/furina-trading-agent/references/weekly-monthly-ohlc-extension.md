# Weekly + Monthly OHLC Extension (Pattern C)

Reference for the Pattern C scoring layer in `automatic_signal_scanner.py`. Pattern A (close-above-prev-H/L) and Pattern B (OHLC confluence) live in the SKILL.md body; this file is for the higher-TF Weekly + Monthly extension and the rule the user enforced about TF-of-pattern matching TF-of-mode.

## Why this exists

Channel @yourlittlething teaches Monthly + Weekly OHLC as the highest-weight S/R levels: prev W/M high and low define institutional supply/demand zones, and a candle that closes above prev W high (or below prev W low) is treated as the strongest continuation confirmation outside of macro events.

The intuition is correct. The deployment trap is enabling it on every mode.

## The TF-mismatch lesson (2026-06-07)

Initial deploy turned on `use_weekly_ohlc` and `use_monthly_ohlc` for Aggressive (15m/30m/1h) and Medium (1h/4h) too. Same-session revert. Reasoning the user accepted:

- A weekly close happens once every 7 days. By the time it prints, the institutional flow it represents is already 1-3 days into its move.
- An Aggressive 15m signal expects to be in and out within hours. The W/M boost adds score but the underlying trade horizon is wrong — by the time the W close ages into a tradeable level, the 15m setup has already triggered TP or SL on its own micro-structure.
- Same logic on Medium 1h/4h scalps. The setup closes within a day; weekly S/R is noise at that horizon.
- Safe (4h/1D, swing horizon, hold for days/weeks) is the only mode where the language of the pattern matches the language of the trade.

Generalization for any future scoring extension: **match the pattern's natural horizon to the mode's hold duration**. Don't reach for "more confluence is always better" — irrelevant confluence is just noise that inflates score without improving win rate.

## Final config

```python
# Aggressive (15m/30m/1h)
"use_close_above_ph": False,
"use_ohlc_confluence": False,
"use_weekly_ohlc": False,
"use_monthly_ohlc": False,
"min_score": 6, "max_score": 7,

# Medium (1h/4h)
"use_close_above_ph": False,
"use_ohlc_confluence": False,
"use_weekly_ohlc": False,
"use_monthly_ohlc": False,
"min_score": 7, "max_score": 9,

# Safe (4h/1D)  ← only mode with full OHLC stack
"use_close_above_ph": True,
"use_ohlc_confluence": True,
"use_weekly_ohlc": True,
"use_monthly_ohlc": True,
"min_score": 8, "max_score": 18,

# Counter-Trend (oversold bounce)
"use_close_above_ph": False,
"use_ohlc_confluence": False,
"use_weekly_ohlc": False,
"use_monthly_ohlc": False,
"min_score": 6, "max_score": 10,
```

## Implementation pattern (Safe mode, scanner core)

```python
# Klines fetch — guarded
cwk = None
cmn = None
if mode_cfg.get("use_weekly_ohlc"):
    try:
        cwk = klines(symbol, "1w", 12)   # need ≥ 3 (current + 2 prev)
    except Exception:
        cwk = None
if mode_cfg.get("use_monthly_ohlc"):
    try:
        cmn = klines(symbol, "1M", 6)
    except Exception:
        cmn = None

# LONG branch — after Pattern A "close above prev high (signal_tf)"
if mode_cfg.get("use_weekly_ohlc") and cwk and len(cwk) >= 3:
    prev_wh = cwk[-3]["h"]
    last_wclose = cwk[-2]["c"]
    if last_wclose > prev_wh:
        score += 2
        reason.append(f"Close above prev weekly high (${prev_wh:.4f})")
    wcnt, _ = ohlc_nearby(price, cwk, pct_thresh=1.0)
    if wcnt >= 2:
        score += 1
        reason.append(f"Weekly OHLC confluence ({wcnt} levels nearby)")
if mode_cfg.get("use_monthly_ohlc") and cmn and len(cmn) >= 3:
    prev_mh = cmn[-3]["h"]
    last_mclose = cmn[-2]["c"]
    if last_mclose > prev_mh:
        score += 2
        reason.append(f"Close above prev monthly high (${prev_mh:.4f})")

# SHORT branch — mirror with prev_wl / prev_ml; close < prev_wl/prev_ml
```

OHLC confluence helper auto-includes W/M:

```python
if side and mode_cfg.get("use_ohlc_confluence"):
    tf_map = {signal_tf: cs}
    if ctx_tf != signal_tf:
        tf_map[ctx_tf] = cctx
    if cwk:
        tf_map["1W"] = cwk
    if cmn:
        tf_map["1M"] = cmn
    conf_total, conf_detail = ohlc_confluence(price, tf_map, pct_thresh=0.5)
    ...
```

## Pitfalls (apply for any pattern scoring extension)

1. **Klines fetch must be guarded.** Thinly-traded symbols on Binance perp may have <3 weeks of history. `try/except` + `len >= 3` check, never assume.

2. **Binance interval case sensitivity.** Weekly is `1w` (lowercase), monthly is `1M` (uppercase). `1W` returns `-1120 Invalid interval`. Same trap whenever you add new TFs.

3. **Always raise `max_score` proportional to new bonuses.** Safe got +2 (W high) +1 (W nearby) +2 (M high) = +5 max, so 14 → 18. If you forget, perfect setups become mathematically unreachable and the score gets compressed against the ceiling — no signals fire even though the logic looks right.

4. **`cs[-2]`, not `cs[-1]`.** Always use the last *completed* candle for close-above checks. `cs[-1]` is the in-progress candle and produces false signals on every wick.

5. **Don't sprinkle the pattern across modes** without matching horizons. The TF-mismatch revert happened because we extrapolated "more confluence = better" from Safe to Aggressive/Medium. It's not a generalizable conclusion.

6. **Cron auto-reloads scripts on each tick.** No restart needed after editing scanner config or scoring. The next scheduled run picks up the change.

## Verification recipe (run after any scanner scoring extension)

Save as `/tmp/verify_scanner_scoring.py`:

```python
import sys; sys.path.insert(0, "/root/.hermes/scripts")
import automatic_signal_scanner as ass

# 1. Syntax + config sanity
import ast
src = open("/root/.hermes/scripts/automatic_signal_scanner.py").read()
ast.parse(src)
print("Syntax OK")

for name, cfg in ass.MODES.items():
    print(f"{name:14s} | min={cfg['min_score']:2d} max={cfg['max_score']:2d} "
          f"weekly={cfg.get('use_weekly_ohlc', False)} "
          f"monthly={cfg.get('use_monthly_ohlc', False)}")

# 2. Live klines + scoring path on a known-truthy symbol
cwk = ass.klines("BNBUSDT", "1w", 12)
cmn = ass.klines("BNBUSDT", "1M", 6)
prev_wh, last_wc = cwk[-3]["h"], cwk[-2]["c"]
prev_mh, last_mc = cmn[-3]["h"], cmn[-2]["c"]
print(f"BNBUSDT W: close={last_wc:.2f} prev_high={prev_wh:.2f}  "
      f"{'BREAK' if last_wc > prev_wh else 'no break'}")
print(f"BNBUSDT M: close={last_mc:.2f} prev_high={prev_mh:.2f}  "
      f"{'BREAK' if last_mc > prev_mh else 'no break'}")
```

Expected: at least one major (BNB, BTC, ETH, SOL) shows a break in the live data, proving the scoring path is hot. If every symbol shows "no break", check that you're using the right TF case (`1w` vs `1W`, `1M` vs `1m`).

## Backup convention

Before any scoring change, snapshot the scanner:

```bash
cp /root/.hermes/scripts/automatic_signal_scanner.py \
   /root/.hermes/scripts/automatic_signal_scanner.py.bak.$(date +%Y%m%d_%H%M%S)
```

Restore is a one-liner if a deploy regresses signal flow:

```bash
cp /root/.hermes/scripts/automatic_signal_scanner.py.bak.<timestamp> \
   /root/.hermes/scripts/automatic_signal_scanner.py
```

Cron picks up the restore on next tick.
