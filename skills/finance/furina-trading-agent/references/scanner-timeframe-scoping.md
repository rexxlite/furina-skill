# Scanner Pattern × Timeframe Scoping (Furina Auto Signal)

When integrating a new technical pattern into `automatic_signal_scanner.py`, decide
**which scan modes** it applies to. Wrong timeframe → noise, false positives, late
chases. This is not a "more is better" knob.

## Rule of thumb

A pattern's natural lookback window must match (or be shorter than) the mode's
holding horizon. If the pattern is built on Weekly/Monthly candles and the mode
takes scalp trades that close in <8 hours, the pattern is broken for that mode.

## Furina mode horizons (current)

| Mode | Signal TF | Context TF | Hold horizon | Cooldown |
|---|---|---|---|---|
| **Aggressive** | 15m / 30m / 1h | 1h | minutes-to-hours | 8h |
| **Medium** | 1h / 4h | 4h | hours-to-day | 16h |
| **Safe** | 4h / 1d | 1d | day-to-week | 24h |
| **Counter-Trend** | varies (oversold) | — | hours-to-day | special |

## Pattern × mode applicability matrix

Patterns from the @yourlittlething ("Little Things") fundamental-analysis
channel — Monthly/Weekly OHLC as S/R + Close Above Prev High as confirmation:

| Pattern | Aggressive | Medium | Safe | Counter-Trend | Reason |
|---|---|---|---|---|---|
| Close Above/Below Prev High (intra-TF, signal_tf candles) | ❌ | ❌ | ✅ | ❌ | Sub-1h breakouts have low survivorship; only 4h/1d closes carry signal |
| OHLC confluence (signal_tf + context_tf) | ❌ | ❌ | ✅ | ❌ | Multi-TF S/R only meaningful at swing horizon |
| Close Above Prev **Weekly** High | ❌ | ❌ | ✅ | ❌ | Weekly close > prev W high is multi-day move; a 15m scalper cannot ride it |
| Close Above Prev **Monthly** High | ❌ | ❌ | ✅ | ❌ | Monthly break = institutional signal, days-to-weeks horizon |
| Weekly OHLC nearby (1% confluence) | ❌ | ❌ | ✅ | ❌ | Weekly S/R irrelevant to a 1h scalp's TP/SL |

**Counter-Trend** is mean-reversion (RSI oversold + BB %B), so trend-following
S/R patterns are off-thesis by design.

## Why Aggressive/Medium got cut from W/M

Initial implementation (2026-06-07) gave Weekly/Monthly OHLC bonus points to
all four modes. User correction: scalp/intraday modes don't care about weekly
or monthly S/R, and a "close above prev weekly high" at 09:00 may already be
retraced by 11:00 — pattern is too slow to react on. Final config:

```python
# Aggressive
"use_close_above_ph": False,
"use_ohlc_confluence": False,
"use_weekly_ohlc": False,
"use_monthly_ohlc": False,

# Medium
"use_close_above_ph": False,
"use_ohlc_confluence": False,
"use_weekly_ohlc": False,
"use_monthly_ohlc": False,

# Safe (full power)
"use_close_above_ph": True,
"use_ohlc_confluence": True,
"use_weekly_ohlc": True,
"use_monthly_ohlc": True,

# Counter-Trend (untouched)
"use_close_above_ph": False,
"use_ohlc_confluence": False,
"use_weekly_ohlc": False,
"use_monthly_ohlc": False,
```

`max_score` rebalanced accordingly: Aggressive 7, Medium 9, Safe 18,
Counter-Trend 10. Scoring path itself is gated by `mode_cfg.get(...)` flags,
so Aggressive/Medium skip the 1w/1M `klines()` calls entirely → also saves
Binance API rate-limit budget.

## Scoring weights (Safe only)

When enabled (Safe mode):

| Confirmation | Score |
|---|---|
| Close Above Prev High (signal TF) | +1 |
| OHLC confluence ≥3 levels from ≥2 TFs | +1 |
| Close Above Prev Weekly High | +2 |
| Weekly OHLC ≥2 levels within 1% | +1 |
| Close Above Prev Monthly High | +2 |

SHORT branch is the mirror (close below prev L for each).

## Implementation guards (must keep)

1. **Wrap fetch in try/except** — `klines(sym, "1w", 12)` and `klines(sym, "1M", 6)`
   can fail on illiquid symbols or new listings; fallback to `cwk = None` and
   skip the scoring block.
2. **Length sanity check** — `if cwk and len(cwk) >= 3` before indexing
   `cwk[-3]` (need current + 2 prev candles minimum).
3. **Use `cs[-2]` not `cs[-1]`** — last bar may not be closed yet; second-to-
   last is always closed.
4. **Per-mode flag gate** — fetch + scoring both gated by
   `mode_cfg.get("use_weekly_ohlc")` so disabling the flag fully no-ops.

## When adding a new pattern

Before wiring it into `MODES` config:

1. Identify the pattern's natural horizon (lookback bars × TF resolution).
2. Match against the mode's hold horizon table above.
3. If pattern horizon > 3× mode horizon → **disable for that mode**.
4. Compute new `max_score` per mode and update simultaneously, or `min_score`
   gating breaks.
5. Test live with `setup_for(symbol, mode_cfg, btc_bias, btc_bias_long, signal_tf)`
   on majors before deploying — anti-flush filters may reject everything in
   extreme markets, that's expected behavior, not a bug.
