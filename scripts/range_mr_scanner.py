#!/usr/bin/env python3
"""
Range Mean-Reversion Scanner — Furina trial strategy (2026-06-12)
═══════════════════════════════════════════════════════════════════════

Closes the BIGGEST gap in the system: every existing scanner is trend-following,
so they bleed (whipsaw) in sideways/choppy markets. This scanner is the opposite —
it ONLY fires when the market is ranging, and fades extremes back to the mean.

Core logic:
  REGIME GATE   : ADX < ADX_MAX (no trend) — if trending, stay out entirely
  LONG setup    : price at/below lower Bollinger Band (%B ≤ LOW_PCTB)
                  + RSI oversold → fade UP toward the mid-band
  SHORT setup   : price at/above upper Bollinger Band (%B ≥ HIGH_PCTB)
                  + RSI overbought → fade DOWN toward the mid-band

Confirmation gates:
  - rejection wick at the extreme (price poked the band and got rejected)
  - RSI extreme aligned with the fade direction
  - range must be "clean": price has respected the bands recently (not breaking out)

Exit philosophy (mean-reversion):
  - TP = mid-band (VWAP-like mean) primarily — conservative, high win-rate
  - SL = just beyond the band (if band breaks, the range is dead → bail fast)
  - This is NOT a trend trade; profit per trade is modest, win-rate is the edge.

Writes to the SAME real journal as automatic_signal, tagged
risk_model="range_mr". NO real money — executes to Binance testnet (demo).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import automatic_signal_scanner as base

BASE = "https://fapi.binance.com"
JOURNAL_PATH = Path("/root/.hermes/trading_journals/automatic_signal_real_journal.json")

# ── Tunables ───────────────────────────────────────────────────────────
SIGNAL_TF = "1h"             # execution timeframe (range setups want some structure)
ADX_MAX = 20.0               # regime gate: only fire when ADX < this (ranging)
BB_N = 20                    # Bollinger period
BB_K = 2                     # Bollinger std-dev multiplier
LOW_PCTB = 0.05              # %B ≤ this = at/below lower band → LONG
HIGH_PCTB = 0.95             # %B ≥ this = at/above upper band → SHORT
RSI_OS = 35                  # RSI oversold threshold (LONG)
RSI_OB = 65                  # RSI overbought threshold (SHORT)
MIN_QUOTE_VOLUME_24H = 50_000_000
MAX_SYMBOLS = 60
COOLDOWN_HOURS = 8
SL_BAND_BUFFER = 0.5         # SL = band ± (band_width × this buffer fraction of ATR)
ATR_SL_MULT = 1.0            # SL beyond entry by ATR × mult (range stops are tight)
MIN_SCORE = 4                # of 5 confirmation points (raised 2026-06-23: cut coin-flip marginals)
MIN_BAND_WIDTH_PCT = 2.0     # range must have enough width to be tradeable
MAX_BAND_WIDTH_PCT = 12.0    # too wide = volatile, not a clean range

# ── SHORT-side MTF gate (added 2026-06-17 after audit) ──────────────────
# Audit of 15 closed trades: LONG = 6W/4L +$13.56 (healthy), SHORT = 0W/5L
# -$37.24 (every single short hit SL). Root cause: in a macro uptrend, price
# poking the upper band is a BREAKOUT continuation, not a reversion signal.
# The 1h ADX<20 gate doesn't see the higher-TF bullish bias. Fix: only allow
# SHORT when the 4h trend is NOT bullish (price at/below 4h EMA50). LONG is
# unrestricted — it aligns with the macro uptrend and already prints money.
SHORT_MTF_TF = "4h"          # higher timeframe to confirm short bias
SHORT_MTF_EMA = 50           # price must be ≤ this EMA on 4h to allow SHORT
SHORT_ENABLED = False        # LONG-only (2026-06-23: SHORT was 2W/7L 22%WR -$23.92, even with 4h gate; macro uptrend kills every fade-short)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def setup_for(symbol):
    """Evaluate one symbol for a range mean-reversion setup. Returns dict or None."""
    candles = base.klines(symbol, SIGNAL_TF, 120)
    if len(candles) < 60:
        return None
    closes = [c["c"] for c in candles]

    # ── REGIME GATE: must be ranging ────────────────────────────────────
    adx_val = base.adx(candles, 14)
    if adx_val is None or adx_val >= ADX_MAX:
        return None  # trending or unknown → not our market

    # ── Bollinger position ──────────────────────────────────────────────
    bb = base.bb_width(closes, BB_N, BB_K)
    if not bb:
        return None
    upper, mid, lower, width_pct = bb
    if width_pct < MIN_BAND_WIDTH_PCT or width_pct > MAX_BAND_WIDTH_PCT:
        return None  # range too tight (no room) or too wide (not clean)

    pctb = base.bb_pct_b(closes, BB_N, BB_K)
    if pctb is None:
        return None

    price = closes[-1]
    last = candles[-1]

    side = None
    if pctb <= LOW_PCTB:
        side = "LONG"
    elif pctb >= HIGH_PCTB:
        side = "SHORT"
    else:
        return None  # not at an extreme

    # ── SHORT-side MTF gate: block shorts that fight the higher-TF uptrend ──
    # (audit: SHORT was 0W/5L because price poking the upper band in a macro
    #  uptrend is breakout continuation, not reversion). Allow SHORT only when
    #  4h price is at/below its EMA50 (no bullish higher-TF bias).
    if side == "SHORT":
        if not SHORT_ENABLED:
            return None
        htf = base.klines(symbol, SHORT_MTF_TF, SHORT_MTF_EMA + 30)
        if len(htf) < SHORT_MTF_EMA + 5:
            return None  # not enough higher-TF history → skip the short
        htf_closes = [c["c"] for c in htf]
        htf_ema = base.ema(htf_closes, SHORT_MTF_EMA)
        if htf_ema is None or htf_closes[-1] > htf_ema:
            return None  # 4h still bullish → don't short into the trend

    # ── Scoring (5 confirmation points) ─────────────────────────────────
    score = 1  # base: ranging regime + at band extreme
    reasons = [f"ADX {adx_val:.0f} (ranging) · %B {pctb:.2f} at {'lower' if side=='LONG' else 'upper'} band"]

    # 1. RSI extreme aligned
    r = base.rsi(closes, 14)
    if r is not None:
        if side == "LONG" and r <= RSI_OS:
            score += 1
            reasons.append(f"RSI {r:.0f} oversold")
        elif side == "SHORT" and r >= RSI_OB:
            score += 1
            reasons.append(f"RSI {r:.0f} overbought")

    # 2. Rejection wick at the extreme
    rng = last["h"] - last["l"]
    if rng > 0:
        lower_wick = (min(last["o"], last["c"]) - last["l"]) / rng
        upper_wick = (last["h"] - max(last["o"], last["c"])) / rng
        if side == "LONG" and lower_wick >= 0.35:
            score += 1
            reasons.append("rejection wick (buyers stepping in)")
        elif side == "SHORT" and upper_wick >= 0.35:
            score += 1
            reasons.append("rejection wick (sellers stepping in)")

    # 3. Candle starting to turn back toward mean
    bull_bar = last["c"] > last["o"]
    if (side == "LONG" and bull_bar) or (side == "SHORT" and not bull_bar):
        score += 1
        reasons.append("candle turning toward mean")

    # 4. Range respected recently — price hasn't closed beyond band by >2% (clean range)
    beyond = (price < lower * 0.98) or (price > upper * 1.02)
    if not beyond:
        score += 1
        reasons.append("range intact (no breakout)")

    if score < MIN_SCORE:
        return None

    # ── Levels ──────────────────────────────────────────────────────────
    a = base.atr(candles, 14)
    if not a or a <= 0:
        return None
    entry = price
    if side == "LONG":
        sl = min(lower, entry) - a * ATR_SL_MULT
        tp1 = mid                      # primary target: the mean
        tp2 = mid + (upper - mid) * 0.5
        tp3 = upper                    # stretch: opposite band
    else:
        sl = max(upper, entry) + a * ATR_SL_MULT
        tp1 = mid
        tp2 = mid - (mid - lower) * 0.5
        tp3 = lower

    # sanity: RR to TP1 must be positive and reasonable
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    rr1 = abs(tp1 - entry) / risk
    if rr1 < 0.5:
        return None  # mean too close, not worth the risk

    return {
        "symbol": symbol, "side": side, "entry": entry, "sl": sl,
        "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "adx": adx_val, "pctb": pctb, "width_pct": width_pct,
        "rsi": r, "atr": a, "score": score, "reasons": reasons,
        "rr1": rr1,
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
        if row.get("symbol") != symbol:
            continue
        if (row.get("risk_model") or "") != "range_mr":
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
        if sym in {"USDCUSDT"} or recently_signaled(journal, sym):
            continue
        try:
            s = setup_for(sym)
            if s and (best is None or s["score"] > best["score"] or
                      (s["score"] == best["score"] and s["rr1"] > best["rr1"])):
                best = s
        except Exception:
            continue

    if not best:
        return  # silent

    em = best["entry"]
    rid = f"RMR-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{best['symbol']}"
    rr = abs(best["tp2"] - em) / abs(em - best["sl"]) if abs(em - best["sl"]) > 0 else 0

    row = {
        "id": rid, "created_at": now_iso(), "symbol": best["symbol"], "side": best["side"],
        "timeframe_context": f"{SIGNAL_TF} signal + range mean-reversion (ADX<{ADX_MAX:.0f})",
        "entry_low": em, "entry_high": em, "entry_mid": em,
        "sl": best["sl"], "tp1": best["tp1"], "tp2": best["tp2"], "tp3": best["tp3"],
        "initial_rr": round(rr, 2), "status": "WAITING_ENTRY",
        "risk_model": "range_mr", "scanner_min_score": MIN_SCORE,
        "score": best["score"],
        "technique": "Range mean-reversion (BB fade)",
        "reason": " · ".join(best["reasons"]),
        "adx": round(best["adx"], 1), "bb_pctb": round(best["pctb"], 3),
        "bb_width_pct": round(best["width_pct"], 2),
        "invalidation": f"Price tembus band ke SL {fmt(best['sl'])} (range pecah)",
        "source": "range_mr_signal", "result_r": None,
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
        notif = f"[rmr-exec-error] {e}"

    arrow = "🟢 LONG" if best["side"] == "LONG" else "🔴 SHORT"

    def pct_from_entry(level):
        if em == 0:
            return 0.0
        return (level - em) / em * 100.0

    sl_pct = pct_from_entry(best["sl"])
    tp1_pct = pct_from_entry(best["tp1"])
    tp2_pct = pct_from_entry(best["tp2"])
    tp3_pct = pct_from_entry(best["tp3"])

    # First reason often duplicates the band touch info — keep it as the headline
    headline = best["reasons"][0]

    msg = (
        f"📐 Range Mean-Reversion Signal\n"
        f"\n"
        f"🪙 {best['symbol']} — {arrow}\n"
        f"🎯 Setup: BB FADE (mean-reversion)\n"
        f"   {headline}\n"
        f"\n"
        f"📍 Levels\n"
        f"• Entry: {fmt(em)}\n"
        f"• SL:    {fmt(best['sl'])}  ({sl_pct:+.2f}%)\n"
        f"• TP1:   {fmt(best['tp1'])}  ({tp1_pct:+.2f}%)  ← mean\n"
        f"• TP2:   {fmt(best['tp2'])}  ({tp2_pct:+.2f}%)\n"
        f"• TP3:   {fmt(best['tp3'])}  ({tp3_pct:+.2f}%)\n"
        f"\n"
        f"📊 Metrics\n"
        f"• ADX:    {best['adx']:.0f}  (ranging, < {ADX_MAX:.0f})\n"
        f"• %B:     {best['pctb']:.2f}\n"
        f"• BBW:    {best['width_pct']:.1f}%\n"
        f"• Score:  {best['score']}/5\n"
        f"• RR (TP2): {rr:.1f}"
    )
    if notif:
        msg += f"\n\n{notif}"
    print(msg)


if __name__ == "__main__":
    main()
