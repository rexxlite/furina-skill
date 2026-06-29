#!/usr/bin/env python3
"""
Breakout-Retest Scanner — Furina trial strategy (2026-06-13)
═══════════════════════════════════════════════════════════════════════

Upgrades the BB-squeeze idea from a single score-point into a full setup with
better entry timing. Three phases:

  Phase 1 — SQUEEZE   : Bollinger Band Width compressed (low volatility coil)
  Phase 2 — BREAKOUT  : an expansion candle closes beyond the range + volume rises
  Phase 3 — RETEST    : price pulls back to the broken level → ENTER there
                        (not chasing the first breakout candle)

Why retest > chase: the retest filters fakeouts (if it doesn't hold, skip) and
gives a much tighter stop → better RR. Trade-off: strong breakouts sometimes
never retest (we miss those). That's acceptable — quality over quantity.

Direction:
  bullish breakout (close above recent high after squeeze) → LONG on retest of that high
  bearish breakout (close below recent low after squeeze)  → SHORT on retest of that low

Confirmation gates:
  - prior squeeze: BBW in the lowest band of its recent range
  - breakout candle had above-average volume
  - retest holds: price came back to the level (within tolerance) and is rejecting it
  - momentum aligned (RSI / EMA)

TF 1h. Writes to the SAME real journal, tagged risk_model="breakout_retest".
Executes to Binance testnet (demo). NO real money.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import automatic_signal_scanner as base

JOURNAL_PATH = Path("/root/.hermes/trading_journals/automatic_signal_real_journal.json")

# ── Tunables ───────────────────────────────────────────────────────────
SIGNAL_TF = "1h"
LOOKBACK = 120                   # bars to analyze
BBW_SQUEEZE_PCTILE = 0.30        # squeeze = BBW in lowest 30% of recent range
SQUEEZE_WINDOW = 40              # bars to measure BBW percentile over
BREAKOUT_WINDOW = 20             # the range whose high/low defines the breakout level
BREAKOUT_MAX_BARS_AGO = 8        # breakout must have happened within last N bars
RETEST_TOLERANCE = 0.012         # price within 1.2% of broken level = retest zone
VOL_CONFIRM_MULT = 1.3           # breakout candle vol ≥ 1.3× average
MIN_QUOTE_VOLUME_24H = 50_000_000
MAX_SYMBOLS = 60
COOLDOWN_HOURS = 8
ATR_SL_MULT = 1.2
RR_TP = [1.0, 2.0, 3.0]          # momentum trade — let winners run
MIN_SCORE = 3                    # of 4 (base + 3 of {squeeze,volume,RSI-healthy})

# ── Directional / macro gates (added 2026-06-23 after segment audit) ────
# Segment audit (106 closed): SHORT = 20W/32L 38.5%WR -$41.94, LONG = 26W/28L
# 48.1%WR -$51.61. Both sides bled but SHORT worst, and breakout_retest had NO
# macro filter at all (unlike range_mr). 40 full-SL hits = -$334.9 dominated.
# Fix: (1) LONG-only — fade/breakdown shorts fight the macro uptrend; (2) LONG
# breakouts must be above the 4h EMA50 (only trade breakouts WITH the higher-TF
# trend, not counter-trend pops that retest then fail).
SHORT_ENABLED = False            # LONG-only
LONG_MTF_TF = "4h"               # higher timeframe to confirm long bias
LONG_MTF_EMA = 50                # price must be ≥ this EMA on 4h to allow LONG


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def bbw_series(closes, n=20, k=2):
    """Bollinger Band Width for each bar where computable. Returns list aligned to closes tail."""
    out = []
    for i in range(len(closes)):
        window = closes[max(0, i - n + 1):i + 1]
        if len(window) < n:
            out.append(None)
            continue
        mean = sum(window) / n
        var = sum((x - mean) ** 2 for x in window) / n
        sd = var ** 0.5
        if mean == 0:
            out.append(None)
        else:
            out.append((2 * k * sd) / mean)  # width relative to price
    return out


def setup_for(symbol):
    """Detect a breakout-retest setup. Returns dict or None."""
    candles = base.klines(symbol, SIGNAL_TF, LOOKBACK)
    if len(candles) < SQUEEZE_WINDOW + BREAKOUT_WINDOW + 5:
        return None
    closes = [c["c"] for c in candles]
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    vols = [c.get("v", 0) for c in candles]

    bbw = bbw_series(closes, 20, 2)

    # ── Find a breakout in the last BREAKOUT_MAX_BARS_AGO bars ───────────
    # The breakout level = the high/low of the BREAKOUT_WINDOW bars BEFORE the
    # breakout candle. We scan recent bars for a close that broke that range
    # AND was preceded by a squeeze.
    best = None
    for bars_ago in range(1, BREAKOUT_MAX_BARS_AGO + 1):
        idx = len(candles) - 1 - bars_ago      # breakout candle index
        if idx - BREAKOUT_WINDOW < 0 or idx - 1 < 0:
            continue
        # squeeze must have existed just before the breakout
        bbw_at = bbw[idx - 1]
        if bbw_at is None:
            continue
        window_bbw = [b for b in bbw[max(0, idx - SQUEEZE_WINDOW):idx] if b is not None]
        if len(window_bbw) < 10:
            continue
        sorted_bbw = sorted(window_bbw)
        thresh = sorted_bbw[int(len(sorted_bbw) * BBW_SQUEEZE_PCTILE)]
        was_squeeze = bbw_at <= thresh

        prior_high = max(highs[idx - BREAKOUT_WINDOW:idx])
        prior_low = min(lows[idx - BREAKOUT_WINDOW:idx])
        bo_close = closes[idx]

        # volume confirm on breakout candle
        avg_vol = sum(vols[max(0, idx - 20):idx]) / max(1, len(vols[max(0, idx - 20):idx]))
        vol_ok = avg_vol > 0 and vols[idx] >= avg_vol * VOL_CONFIRM_MULT

        direction = None
        level = None
        if bo_close > prior_high:
            direction = "LONG"
            level = prior_high
        elif bo_close < prior_low:
            direction = "SHORT"
            level = prior_low
        else:
            continue

        # ── Retest check: current price back near the broken level ──────
        price = closes[-1]
        dist = abs(price - level) / level if level > 0 else 1
        if dist > RETEST_TOLERANCE:
            continue  # not retesting yet
        # price should be holding the level (above for long, below for short
        # is the breakout side; on retest we want it reclaiming)
        if direction == "LONG" and price < level * (1 - RETEST_TOLERANCE):
            continue
        if direction == "SHORT" and price > level * (1 + RETEST_TOLERANCE):
            continue

        cand = {
            "direction": direction, "level": level, "bo_idx": idx,
            "was_squeeze": was_squeeze, "vol_ok": vol_ok, "bars_ago": bars_ago,
            "prior_high": prior_high, "prior_low": prior_low,
        }
        # prefer the most recent valid breakout
        if best is None:
            best = cand

    if not best:
        return None

    direction = best["direction"]
    level = best["level"]
    price = closes[-1]
    last = candles[-1]

    # ── Directional / macro gates (2026-06-23) ──────────────────────────
    if direction == "SHORT" and not SHORT_ENABLED:
        return None  # LONG-only: shorts fight the macro uptrend
    if direction == "LONG":
        htf = base.klines(symbol, LONG_MTF_TF, LONG_MTF_EMA + 30)
        if len(htf) < LONG_MTF_EMA + 5:
            return None
        htf_closes = [c["c"] for c in htf]
        htf_ema = base.ema(htf_closes, LONG_MTF_EMA)
        if htf_ema is None or htf_closes[-1] < htf_ema:
            return None  # 4h below EMA50 → breakout is counter-trend, skip

    # ── Scoring (REWORKED 2026-06-21: score-inversion fix) ──────────────
    # Audit (93 closed): old scoring rewarded over-extension. RSI≥50 + EMA50
    # alignment gave HIGHER score to breakouts that had already run too far →
    # retest entry landed at end-of-move → fakeout/reversal. Result was inverted:
    #   score4 WR42% +$52 | score5 WR46% -$54 | score6 WR29% -$65.
    # Fix: (1) retest rejection candle is now a MANDATORY GATE (best fakeout
    # filter), (2) drop EMA50 alignment (the over-extension reward), (3) RSI
    # becomes a HEALTHY-ZONE check (reject over-extended RSI), not a ≥50 reward.
    # Max score now 5; MIN_SCORE 3 (base + 2 real confirmations).
    r = base.rsi(closes, 14)

    # GATE 1: retest rejection candle is mandatory (was optional +1)
    bull_bar = last["c"] > last["o"]
    rejection_ok = (direction == "LONG" and bull_bar) or (direction == "SHORT" and not bull_bar)
    if not rejection_ok:
        return None  # no rejection at retest → skip (this is the fakeout filter)

    # GATE 2: reject over-extended RSI (the core lesson — don't chase exhausted moves)
    if r is not None:
        if direction == "LONG" and r > 70:
            return None  # already overbought, breakout exhausted
        if direction == "SHORT" and r < 30:
            return None  # already oversold, breakdown exhausted

    score = 1  # base: breakout + retest zone reached + rejection confirmed
    reasons = [f"{direction} breakout-retest @ {fmt(level)} ({best['bars_ago']}h ago), rejection confirmed"]

    if best["was_squeeze"]:
        score += 1
        reasons.append("preceded by BB squeeze")
    if best["vol_ok"]:
        score += 1
        reasons.append("breakout volume confirmed")

    # RSI in HEALTHY zone (not over-extended) — aligned but with room to run
    if r is not None:
        if direction == "LONG" and 48 <= r <= 68:
            score += 1
            reasons.append(f"RSI {r:.0f} healthy bullish (room to run)")
        elif direction == "SHORT" and 32 <= r <= 52:
            score += 1
            reasons.append(f"RSI {r:.0f} healthy bearish (room to run)")

    if score < MIN_SCORE:
        return None

    # ── Levels ──────────────────────────────────────────────────────────
    a = base.atr(candles, 14)
    if not a or a <= 0:
        return None
    entry = price
    sl_dist = a * ATR_SL_MULT
    if direction == "LONG":
        sl = level - sl_dist        # below the retested level
        tps = [entry + sl_dist * m for m in RR_TP]
    else:
        sl = level + sl_dist
        tps = [entry - sl_dist * m for m in RR_TP]

    risk = abs(entry - sl)
    if risk <= 0:
        return None

    return {
        "symbol": symbol, "side": direction, "entry": entry, "sl": sl,
        "tp1": tps[0], "tp2": tps[1], "tp3": tps[2],
        "level": level, "rsi": r, "atr": a, "score": score, "reasons": reasons,
        "bars_ago": best["bars_ago"],
    }


def build_universe():
    tickers = base.get_json("/fapi/v1/ticker/24hr")
    try:
        info = base.get_json("/fapi/v1/exchangeInfo")
        meta = {s["symbol"]: s for s in info.get("symbols", []) if s.get("status") == "TRADING"}
    except Exception:
        meta = {}

    def is_crypto(sym):
        if sym in base.EXCLUDE_SYMBOLS:
            return False
        b = sym.removesuffix("USDT")
        if any(k in b for k in base.COMMODITY_KEYWORDS):
            return False
        m = meta.get(sym)
        if not m:
            return True
        if m.get("contractType") not in base.ALLOWED_CONTRACT_TYPES:
            return False
        if m.get("underlyingType") not in base.ALLOWED_UNDERLYING_TYPES:
            return False
        if set(m.get("underlyingSubType") or []) & base.EXCLUDE_SUBTYPES:
            return False
        return True

    uni = [t for t in tickers
           if t.get("symbol", "").endswith("USDT")
           and t.get("symbol", "") not in base.EXCLUDE_SYMBOLS
           and is_crypto(t.get("symbol", ""))
           and float(t.get("quoteVolume", 0)) >= MIN_QUOTE_VOLUME_24H]
    uni = sorted(uni, key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)[:MAX_SYMBOLS]
    return [t["symbol"] for t in uni]


def recently_signaled(journal, symbol):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_HOURS)
    for row in journal:
        if row.get("symbol") != symbol or (row.get("risk_model") or "") != "breakout_retest":
            continue
        try:
            ca = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            if ca > cutoff:
                return True
        except Exception:
            continue
    return False


def fmt(p):
    if p >= 100:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:.4f}"
    return f"{p:.6f}"


def main():
    try:
        journal = json.load(open(JOURNAL_PATH)) if JOURNAL_PATH.exists() else []
    except Exception:
        journal = []

    universe = build_universe()
    best = None
    for sym in universe:
        if recently_signaled(journal, sym):
            continue
        try:
            s = setup_for(sym)
            if s and (best is None or s["score"] > best["score"]):
                best = s
        except Exception:
            continue

    if not best:
        return  # silent

    em = best["entry"]
    rid = f"BRT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{best['symbol']}"
    rr = abs(best["tp2"] - em) / abs(em - best["sl"]) if abs(em - best["sl"]) > 0 else 0

    row = {
        "id": rid, "created_at": now_iso(), "symbol": best["symbol"], "side": best["side"],
        "timeframe_context": f"{SIGNAL_TF} signal + breakout-retest",
        "entry_low": em, "entry_high": em, "entry_mid": em,
        "sl": best["sl"], "tp1": best["tp1"], "tp2": best["tp2"], "tp3": best["tp3"],
        "initial_rr": round(rr, 2), "status": "WAITING_ENTRY",
        "risk_model": "breakout_retest", "scanner_min_score": MIN_SCORE,
        "score": best["score"],
        "technique": "Breakout-retest (squeeze → break → retest entry)",
        "reason": " · ".join(best["reasons"]),
        "breakout_level": best["level"],
        "invalidation": f"Price tembus balik SL {fmt(best['sl'])} (retest gagal)",
        "source": "breakout_retest_signal", "result_r": None,
    }
    journal.append(row)
    with open(JOURNAL_PATH, "w") as f:
        json.dump(journal, f, indent=2)

    try:
        import binance_real_executor as bre
        res = bre.process_record_for_scanner(row)
        with open(JOURNAL_PATH, "w") as f:
            json.dump(journal, f, indent=2)
        notif = res.get("notification") if isinstance(res, dict) else None
    except Exception as e:
        notif = f"[brt-exec-error] {e}"

    arrow = "🟢 LONG" if best["side"] == "LONG" else "🔴 SHORT"
    msg = (
        f"🚀 Breakout-Retest Signal\n\n"
        f"🪙 {best['symbol']} — {arrow}\n"
        f"🎯 Retest @ {fmt(best['level'])} ({best['bars_ago']}h after breakout)\n\n"
        f"📍 Levels\n"
        f"• Entry: {fmt(em)}\n"
        f"• SL:    {fmt(best['sl'])}\n"
        f"• TP1:   {fmt(best['tp1'])}\n"
        f"• TP2:   {fmt(best['tp2'])}\n"
        f"• TP3:   {fmt(best['tp3'])}\n\n"
        f"📊 Metrics\n"
        + (f"• RSI: {best['rsi']:.0f}\n" if best['rsi'] else "")
        + f"• Score:   {best['score']}/6 · RR(TP2) {rr:.1f}"
    )
    if notif:
        msg += f"\n\n{notif}"
    print(msg)


if __name__ == "__main__":
    main()
