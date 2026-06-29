#!/usr/bin/env python3
"""
Liquidation Cascade Reversal Scanner — Furina trial strategy (2026-06-13)
═══════════════════════════════════════════════════════════════════════

After a violent liquidation wipeout, price is often over-extended and snaps
back fast. This is a SCALP counter-trend setup — catch the bounce after panic.

NOTE: Binance blocked the public liquidation feed (allForceOrders → HTTP 400),
so we detect cascades via PROXY from klines:
  - volume SPIKE (current bar volume >> recent average) = forced flow
  - large RANGE bar (ATR expansion) = violent move
  - long REJECTION WICK in the cascade direction = liquidations cleared + reversal
  - over-extension (price stretched from a short EMA) = stop-run done

LONG bounce setup (most common — long liquidations flush price DOWN):
  big red/down bar + volume spike + long lower wick + oversold = fade UP

SHORT setup (short squeeze flushes price UP then fails):
  big green/up bar + volume spike + long upper wick + overbought = fade DOWN

This is fast & risky ("catching a falling knife") — tight SL, quick TP,
conservative leverage. Lowest-priority trial scanner.

TF 5m (fast). Writes to the SAME real journal, tagged risk_model="liq_cascade".
Executes to Binance testnet (demo). NO real money.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import automatic_signal_scanner as base

JOURNAL_PATH = Path("/root/.hermes/trading_journals/automatic_signal_real_journal.json")

# ── Tunables ───────────────────────────────────────────────────────────
SIGNAL_TF = "5m"                 # fast — cascades are short-lived
VOL_SPIKE_MULT = 3.0             # current vol ≥ 3× average of prior bars = forced flow
VOL_LOOKBACK = 20                # bars to average volume over
RANGE_SPIKE_MULT = 2.0           # cascade bar range ≥ 2× ATR = violent
WICK_MIN = 0.4                   # rejection wick ≥ 40% of bar range
MIN_CASCADE_MOVE_PCT = 2.5       # cascade bar must move ≥ this %
MAX_CASCADE_MOVE_PCT = 25.0      # anti-flush: ignore crash/delisting beyond this
RSI_OS = 35                      # oversold for LONG bounce
RSI_OB = 65                      # overbought for SHORT fade
MIN_QUOTE_VOLUME_24H = 50_000_000
MAX_SYMBOLS = 60
COOLDOWN_HOURS = 3               # short — scalp setup, allow re-entry sooner
ATR_SL_MULT = 1.2                # tight stop beyond the wick
RR_TP = [1.0, 1.5, 2.0]          # quick scalp targets
MIN_SCORE = 4                    # of 6 confirmation points


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def setup_for(symbol):
    """Detect a liquidation-cascade reversal. Returns dict or None."""
    candles = base.klines(symbol, SIGNAL_TF, VOL_LOOKBACK + 60)
    if len(candles) < VOL_LOOKBACK + 30:
        return None
    closes = [c["c"] for c in candles]
    vols = [c.get("v", 0) for c in candles]
    last = candles[-1]

    # ── Volume spike check ──────────────────────────────────────────────
    avg_vol = sum(vols[-VOL_LOOKBACK - 1:-1]) / VOL_LOOKBACK
    if avg_vol <= 0:
        return None
    vol_ratio = vols[-1] / avg_vol
    if vol_ratio < VOL_SPIKE_MULT:
        return None  # no forced flow

    # ── Cascade bar magnitude ───────────────────────────────────────────
    bar_open, bar_close = last["o"], last["c"]
    bar_high, bar_low = last["h"], last["l"]
    rng = bar_high - bar_low
    if rng <= 0:
        return None
    move_pct = abs(bar_close - bar_open) / bar_open * 100.0
    if move_pct < MIN_CASCADE_MOVE_PCT or move_pct > MAX_CASCADE_MOVE_PCT:
        return None

    a = base.atr(candles, 14)
    if not a or a <= 0:
        return None
    if rng < a * RANGE_SPIKE_MULT:
        return None  # not violent enough

    # ── Direction + wick ────────────────────────────────────────────────
    down_bar = bar_close < bar_open
    lower_wick = (min(bar_open, bar_close) - bar_low) / rng
    upper_wick = (bar_high - max(bar_open, bar_close)) / rng

    side = None
    if down_bar and lower_wick >= WICK_MIN:
        side = "LONG"   # long liquidations flushed down, lower wick = buyers stepped in
    elif (not down_bar) and upper_wick >= WICK_MIN:
        side = "SHORT"  # short squeeze up, upper wick = sellers stepped in
    else:
        return None

    # ── Scoring (6 points) ──────────────────────────────────────────────
    score = 1  # base: vol spike + violent bar + rejection wick + magnitude
    reasons = [f"Cascade {move_pct:.1f}% move · vol {vol_ratio:.1f}× · "
               f"{'lower' if side=='LONG' else 'upper'} wick {(lower_wick if side=='LONG' else upper_wick)*100:.0f}%"]

    # 1. Extreme volume spike
    if vol_ratio >= VOL_SPIKE_MULT * 1.7:
        score += 1
        reasons.append(f"huge volume {vol_ratio:.1f}×")

    # 2. Very long rejection wick
    w = lower_wick if side == "LONG" else upper_wick
    if w >= 0.55:
        score += 1
        reasons.append("dominant rejection wick")

    # 3. RSI extreme aligned
    r = base.rsi(closes, 14)
    if r is not None:
        if side == "LONG" and r <= RSI_OS:
            score += 1
            reasons.append(f"RSI {r:.0f} oversold")
        elif side == "SHORT" and r >= RSI_OB:
            score += 1
            reasons.append(f"RSI {r:.0f} overbought")

    # 4. Range expansion strong (≥3× ATR)
    if rng >= a * 3.0:
        score += 1
        reasons.append("strong ATR expansion")

    # 5. Over-extension from EMA20 (stop-run done)
    ema20 = base.ema(closes, 20)
    if ema20 and ema20 > 0:
        ext = abs(bar_close - ema20) / ema20
        if ext >= 0.02:
            score += 1
            reasons.append(f"over-extended {ext*100:.1f}% from EMA20")

    if score < MIN_SCORE:
        return None

    # ── Levels ──────────────────────────────────────────────────────────
    entry = closes[-1]
    sl_dist = a * ATR_SL_MULT
    if side == "LONG":
        sl = bar_low - sl_dist * 0.3      # just beyond the cascade low
        tps = [entry + sl_dist * m for m in RR_TP]
    else:
        sl = bar_high + sl_dist * 0.3
        tps = [entry - sl_dist * m for m in RR_TP]

    risk = abs(entry - sl)
    if risk <= 0:
        return None

    return {
        "symbol": symbol, "side": side, "entry": entry, "sl": sl,
        "tp1": tps[0], "tp2": tps[1], "tp3": tps[2],
        "vol_ratio": vol_ratio, "move_pct": move_pct, "rsi": r, "atr": a,
        "score": score, "reasons": reasons,
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
        if row.get("symbol") != symbol or (row.get("risk_model") or "") != "liq_cascade":
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
            if s and (best is None or s["score"] > best["score"] or
                      (s["score"] == best["score"] and s["vol_ratio"] > best["vol_ratio"])):
                best = s
        except Exception:
            continue

    if not best:
        return  # silent

    em = best["entry"]
    rid = f"LIQ-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{best['symbol']}"
    rr = abs(best["tp2"] - em) / abs(em - best["sl"]) if abs(em - best["sl"]) > 0 else 0

    row = {
        "id": rid, "created_at": now_iso(), "symbol": best["symbol"], "side": best["side"],
        "timeframe_context": f"{SIGNAL_TF} signal + liquidation cascade reversal",
        "entry_low": em, "entry_high": em, "entry_mid": em,
        "sl": best["sl"], "tp1": best["tp1"], "tp2": best["tp2"], "tp3": best["tp3"],
        "initial_rr": round(rr, 2), "status": "WAITING_ENTRY",
        "risk_model": "liq_cascade", "scanner_min_score": MIN_SCORE,
        "score": best["score"],
        "technique": "Liquidation cascade reversal (volume-spike proxy)",
        "reason": " · ".join(best["reasons"]),
        "vol_ratio": round(best["vol_ratio"], 2), "cascade_move_pct": round(best["move_pct"], 2),
        "invalidation": f"Price tembus SL {fmt(best['sl'])} (cascade lanjut)",
        "source": "liq_cascade_signal", "result_r": None,
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
        notif = f"[liq-exec-error] {e}"

    arrow = "🟢 LONG" if best["side"] == "LONG" else "🔴 SHORT"
    kind = "long liquidations flushed down" if best["side"] == "LONG" else "short squeeze failed"
    msg = (
        f"💥 Liquidation Cascade Signal\n\n"
        f"🪙 {best['symbol']} — {arrow}\n"
        f"🎯 Bounce scalp ({kind})\n\n"
        f"📍 Levels\n"
        f"• Entry: {fmt(em)}\n"
        f"• SL:    {fmt(best['sl'])}\n"
        f"• TP1:   {fmt(best['tp1'])}\n"
        f"• TP2:   {fmt(best['tp2'])}\n"
        f"• TP3:   {fmt(best['tp3'])}\n\n"
        f"📊 Metrics\n"
        f"• Cascade: {best['move_pct']:.1f}% · vol {best['vol_ratio']:.1f}×\n"
        + (f"• RSI: {best['rsi']:.0f}\n" if best['rsi'] else "")
        + f"• Score:   {best['score']}/6 · RR(TP2) {rr:.1f}"
    )
    if notif:
        msg += f"\n\n{notif}"
    print(msg)


if __name__ == "__main__":
    main()
