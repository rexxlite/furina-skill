#!/usr/bin/env python3
"""
OI Divergence Scanner — Furina trial strategy (2026-06-12)
═══════════════════════════════════════════════════════════════════════

Open Interest (OI) reads the *quality* of a price move that price alone can't.
Four combinations:

  price ↑ + OI ↑  = new money entering, trend HEALTHY      → continuation LONG
  price ↑ + OI ↓  = short covering, rally FRAGILE          → fade (SHORT)
  price ↓ + OI ↑  = aggressive new shorts, downtrend STRONG → continuation SHORT
  price ↓ + OI ↓  = longs capitulating, downtrend EXHAUSTED → bounce (LONG)

This scanner fires on the two highest-conviction setups:
  1. CONTINUATION  : price↑+OI↑ (LONG) or price↓+OI↑ (SHORT) — fresh money confirms
  2. EXHAUSTION    : price↓+OI↓ (LONG bounce) or price↑+OI↓ (SHORT fade) — move hollow

Confirmation gates (avoid noise):
  - OI change must exceed OI_MIN_CHANGE_PCT over the window (real shift, not drift)
  - price change must exceed PRICE_MIN_CHANGE_PCT (actual move)
  - candle confirmation: last candle closes in signal direction
  - RSI not at the wrong extreme (don't LONG into RSI>75, don't SHORT into RSI<25)
  - 24h quote volume floor (liquidity)

Writes to the SAME real journal as automatic_signal so reconciler / monitor /
dashboard pick it up automatically, tagged risk_model="oi_divergence".

NO real money — executes to Binance testnet (demo) via binance_real_executor.
"""
from __future__ import annotations

import json
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Reuse battle-tested helpers from the main scanner
import automatic_signal_scanner as base

BASE = "https://fapi.binance.com"
JOURNAL_PATH = Path("/root/.hermes/trading_journals/automatic_signal_real_journal.json")

# ── Tunables ───────────────────────────────────────────────────────────
OI_PERIOD = "15m"            # OI sampling period
OI_LOOKBACK = 8              # compare now vs 8 periods ago (~2h on 15m)
OI_MIN_CHANGE_PCT = 3.0      # OI must move ≥3% over window to count
PRICE_MIN_CHANGE_PCT = 1.5   # price must move ≥1.5% over window
SIGNAL_TF = "15m"            # execution timeframe
MIN_QUOTE_VOLUME_24H = 50_000_000  # liquidity floor
MAX_SYMBOLS = 60
COOLDOWN_HOURS = 6
RSI_LONG_MAX = 75            # don't LONG into severe overbought
RSI_SHORT_MIN = 25           # don't SHORT into severe oversold
PRICE_MAX_CHANGE_PCT = 20.0  # anti-flush: ignore abnormal moves (crash/delisting/pump)
ATR_SL_MULT = 1.5            # SL distance = ATR × mult
RR_TP = [1.0, 1.5, 2.5]      # TP1/TP2/TP3 as R multiples
MIN_SCORE = 4                # of 5 confirmation points (raised 3→4 on 2026-06-29 after 4-SL streak: filter thin signals, require 2+ real confirmations on top of base point)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def oi_history(symbol, period=OI_PERIOD, limit=30):
    """Fetch open-interest history. Returns list of {ts, oi, oi_val} or []."""
    url = f"{BASE}/futures/data/openInterestHist?" + urllib.parse.urlencode(
        {"symbol": symbol, "period": period, "limit": limit})
    req = urllib.request.Request(url, headers={"User-Agent": "Hermes-Furina-OIDiv/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            rows = json.loads(r.read().decode())
        out = []
        for k in rows:
            out.append({
                "ts": int(k["timestamp"]),
                "oi": float(k["sumOpenInterest"]),
                "oi_val": float(k["sumOpenInterestValue"]),
            })
        return out
    except Exception:
        return []


def pct_change(new, old):
    if old == 0:
        return 0.0
    return (new - old) / old * 100.0


def classify(price_chg, oi_chg):
    """Return (setup_type, side, label) or None."""
    p_up = price_chg > 0
    oi_up = oi_chg > 0
    if p_up and oi_up:
        return ("continuation", "LONG", "Price↑ + OI↑ — fresh money, trend healthy")
    if (not p_up) and oi_up:
        return ("continuation", "SHORT", "Price↓ + OI↑ — aggressive shorts, downtrend strong")
    if p_up and (not oi_up):
        return ("exhaustion", "SHORT", "Price↑ + OI↓ — short covering, rally fragile (fade)")
    if (not p_up) and (not oi_up):
        return ("exhaustion", "LONG", "Price↓ + OI↓ — longs capitulating, downside exhausted (bounce)")
    return None


def setup_for(symbol):
    """Evaluate one symbol. Returns a signal dict or None."""
    oih = oi_history(symbol, OI_PERIOD, OI_LOOKBACK + 2)
    if len(oih) < OI_LOOKBACK + 1:
        return None
    oi_now = oih[-1]["oi"]
    oi_then = oih[-1 - OI_LOOKBACK]["oi"]
    oi_chg = pct_change(oi_now, oi_then)
    if abs(oi_chg) < OI_MIN_CHANGE_PCT:
        return None

    candles = base.klines(symbol, SIGNAL_TF, OI_LOOKBACK + 60)
    if len(candles) < OI_LOOKBACK + 50:
        return None
    closes = [c["c"] for c in candles]
    price_now = closes[-1]
    price_then = closes[-1 - OI_LOOKBACK]
    price_chg = pct_change(price_now, price_then)
    if abs(price_chg) < PRICE_MIN_CHANGE_PCT:
        return None
    if abs(price_chg) > PRICE_MAX_CHANGE_PCT:
        return None  # anti-flush: abnormal move (crash/delisting/pump), skip

    cls = classify(price_chg, oi_chg)
    if not cls:
        return None
    setup_type, side, label = cls

    # ── BTC bias gate (added 2026-06-29 — Opsi C) ───────────────────────
    # OI_DIV is counter-trend by nature; don't fight the BTC trend.
    # Bearish BTC (1h EMA20 < EMA50 + price below) → skip LONG.
    # Bullish BTC (1h EMA20 > EMA50 + price above) → skip SHORT.
    # Neutral BTC → allow both (no clear direction to fight).
    btc_bias = base.detect_btc_bias()
    if btc_bias == "bearish" and side == "LONG":
        return None  # don't catch falling knife in downtrend
    if btc_bias == "bullish" and side == "SHORT":
        return None  # don't fade rally in uptrend

    # ── Scoring (5 confirmation points) ─────────────────────────────────
    score = 0
    reasons = [label]
    score += 1  # base: divergence pattern present + thresholds passed

    # 1. Magnitude of OI shift (strong conviction)
    if abs(oi_chg) >= OI_MIN_CHANGE_PCT * 2:
        score += 1
        reasons.append(f"OI shift strong {oi_chg:+.1f}%")

    # 2. Candle confirmation: last bar closes in signal direction
    last = candles[-1]
    bull_bar = last["c"] > last["o"]
    if (side == "LONG" and bull_bar) or (side == "SHORT" and not bull_bar):
        score += 1
        reasons.append("candle confirms direction")

    # 3. RSI not at the wrong extreme
    r = base.rsi(closes, 14)
    if r is not None:
        if side == "LONG" and r < RSI_LONG_MAX:
            score += 1
            reasons.append(f"RSI {r:.0f} ok for long")
        elif side == "SHORT" and r > RSI_SHORT_MIN:
            score += 1
            reasons.append(f"RSI {r:.0f} ok for short")

    # 4. For exhaustion setups, RSI confirming the reversal extreme adds weight
    if r is not None and setup_type == "exhaustion":
        if (side == "LONG" and r < 40) or (side == "SHORT" and r > 60):
            score += 1
            reasons.append(f"RSI {r:.0f} supports reversal")

    if score < MIN_SCORE:
        return None

    # ── Levels (ATR-based) ──────────────────────────────────────────────
    a = base.atr(candles, 14)
    if not a or a <= 0:
        return None
    entry = price_now
    sl_dist = a * ATR_SL_MULT
    if side == "LONG":
        sl = entry - sl_dist
        tps = [entry + sl_dist * r for r in RR_TP]
    else:
        sl = entry + sl_dist
        tps = [entry - sl_dist * r for r in RR_TP]

    return {
        "symbol": symbol, "side": side, "setup_type": setup_type,
        "entry": entry, "sl": sl, "tp1": tps[0], "tp2": tps[1], "tp3": tps[2],
        "oi_chg": oi_chg, "price_chg": price_chg, "score": score,
        "rsi": r, "atr": a, "reasons": reasons,
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
        if (row.get("risk_model") or "") != "oi_divergence":
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
                      (s["score"] == best["score"] and abs(s["oi_chg"]) > abs(best["oi_chg"]))):
                best = s
        except Exception:
            continue

    if not best:
        return  # silent — no setup

    em = best["entry"]
    rid = f"OID-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{best['symbol']}"
    rr = abs(best["tp2"] - em) / abs(em - best["sl"]) if abs(em - best["sl"]) > 0 else 0

    row = {
        "id": rid, "created_at": now_iso(), "symbol": best["symbol"], "side": best["side"],
        "timeframe_context": f"{SIGNAL_TF} signal + OI {OI_PERIOD}/{OI_LOOKBACK}p divergence",
        "entry_low": em, "entry_high": em, "entry_mid": em,
        "sl": best["sl"], "tp1": best["tp1"], "tp2": best["tp2"], "tp3": best["tp3"],
        "initial_rr": round(rr, 2), "status": "WAITING_ENTRY",
        "risk_model": "oi_divergence", "scanner_min_score": MIN_SCORE,
        "score": best["score"],
        "technique": f"OI divergence ({best['setup_type']})",
        "reason": " · ".join(best["reasons"]),
        "oi_change_pct": round(best["oi_chg"], 2),
        "price_change_pct": round(best["price_chg"], 2),
        "invalidation": f"Price menyentuh SL {fmt(best['sl'])} atau OI berbalik arah",
        "source": "oi_divergence_signal", "result_r": None,
    }
    journal.append(row)
    with open(JOURNAL_PATH, "w") as f:
        json.dump(journal, f, indent=2)

    # Execute to demo
    try:
        import binance_real_executor as bre
        res = bre.process_record_for_scanner(row)
        with open(JOURNAL_PATH, "w") as f:
            json.dump(journal, f, indent=2)
        notif = res.get("notification") if isinstance(res, dict) else None
    except Exception as e:
        notif = f"[oi-exec-error] {e}"

    arrow = "🟢 LONG" if best["side"] == "LONG" else "🔴 SHORT"

    # Percentage distance from entry for quick risk read
    def pct_from_entry(level):
        if em == 0:
            return 0.0
        return (level - em) / em * 100.0

    sl_pct = pct_from_entry(best["sl"])
    tp1_pct = pct_from_entry(best["tp1"])
    tp2_pct = pct_from_entry(best["tp2"])
    tp3_pct = pct_from_entry(best["tp3"])

    # Strip the "Price↑ + OI↑ — " prefix from the first reason for cleaner line
    setup_desc = best["reasons"][0]
    if " — " in setup_desc:
        pattern, narrative = setup_desc.split(" — ", 1)
    else:
        pattern, narrative = setup_desc, ""

    msg = (
        f"📡 OI Divergence Signal\n"
        f"\n"
        f"🪙 {best['symbol']} — {arrow}\n"
        f"🎯 Setup: {best['setup_type'].upper()}\n"
        f"   {pattern}"
    )
    if narrative:
        msg += f"\n   ({narrative})"
    msg += (
        f"\n\n"
        f"📍 Levels\n"
        f"• Entry: {fmt(em)}\n"
        f"• SL:    {fmt(best['sl'])}  ({sl_pct:+.2f}%)\n"
        f"• TP1:   {fmt(best['tp1'])}  ({tp1_pct:+.2f}%)\n"
        f"• TP2:   {fmt(best['tp2'])}  ({tp2_pct:+.2f}%)\n"
        f"• TP3:   {fmt(best['tp3'])}  ({tp3_pct:+.2f}%)\n"
        f"\n"
        f"📊 Metrics\n"
        f"• OI Δ:    {best['oi_chg']:+.1f}%  (2h)\n"
        f"• Price Δ: {best['price_chg']:+.1f}%  (2h)\n"
        f"• Score:   {best['score']}/5\n"
        f"• RR (TP2): {rr:.1f}"
    )
    if notif:
        msg += f"\n\n{notif}"
    print(msg)


if __name__ == "__main__":
    main()
