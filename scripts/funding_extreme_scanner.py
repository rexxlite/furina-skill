#!/usr/bin/env python3
"""
Funding Rate Extreme Scanner — Furina trial strategy (2026-06-13)
═══════════════════════════════════════════════════════════════════════

Funding rate = the 8h fee longs/shorts pay each other on perps.
  funding very POSITIVE = longs crowded/over-leveraged → squeeze risk → bias SHORT
  funding very NEGATIVE = shorts crowded/over-leveraged → squeeze risk → bias LONG

This is CONTRARIAN — it fades the crowd at exhaustion, the opposite of the
trend scanners. But funding extreme alone is NOT a signal: in strong trends
funding can stay extreme for days. So confirmation is mandatory.

Confirmation gates (must have, or no fire):
  - funding beyond FUNDING_THRESHOLD (abs) — real crowding, not noise
  - candle reversal in signal direction (rejection / close turning back)
  - RSI not screaming the wrong way (don't SHORT into deep oversold)
  - NOT a strong structural trend (ADX < TREND_ADX_MAX & price near EMA200)
    → if it IS a strong trend, extreme funding is justified, skip
  - 24h quote volume floor (liquidity)

Exit philosophy (mean-reversion toward fair value):
  - conservative TP (RR 1.0 / 1.5 / 2.5) — funding reversion is modest
  - SL beyond the recent swing extreme (if crowd was right, thesis is wrong)

Writes to the SAME real journal, tagged risk_model="funding". Executes to
Binance testnet (demo). NO real money.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import automatic_signal_scanner as base

BASE = "https://fapi.binance.com"
JOURNAL_PATH = Path("/root/.hermes/trading_journals/automatic_signal_real_journal.json")

# ── Tunables ───────────────────────────────────────────────────────────
SIGNAL_TF = "1h"                 # execution timeframe
FUNDING_THRESHOLD = 0.0004       # 0.04% per 8h — extreme (normal ~0.01%)
FUNDING_STRONG = 0.0008          # 0.08%+ = very extreme (bonus score)
TREND_ADX_MAX = 30.0             # above this = real trend, funding justified → skip
EMA200_DIST_MAX = 0.10           # if price >10% from EMA200 = strong trend, skip
RSI_LONG_MAX = 70                # don't LONG into overbought
RSI_SHORT_MIN = 30               # don't SHORT into oversold
MIN_QUOTE_VOLUME_24H = 50_000_000
MAX_SYMBOLS = 80
COOLDOWN_HOURS = 8
# ── RR fix (2026-06-17 after audit) ─────────────────────────────────────
# Audit of 4 closed trades: WR 50% but avg win +$5.85 vs avg loss -$8.74 →
# RR 0.67 (losing by structure). Cause: SL was ATR×1.5 (wide) while TP1 sat at
# RR 1.0 (near). On a TP1 hit only ~40% closed + rest to BE → tiny locked
# profit; on SL → full wide loss. Asymmetric. Fix: tighten SL to ATR×1.0 and
# push the TP ladder out so the first partial is worth the risk taken.
ATR_SL_MULT = 1.0               # was 1.5 — tighter stop, funding reversion is fast
RR_TP = [1.5, 2.5, 4.0]         # was [1.0, 1.5, 2.5] — first partial now ≥ risk
MIN_SCORE = 4                    # of 6 confirmation points


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Hermes-Furina-Funding/1.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode())


def premium_index_all():
    """Fetch funding + mark price for ALL perp symbols in one call."""
    try:
        return get_json(f"{BASE}/fapi/v1/premiumIndex")
    except Exception:
        return []


def setup_for(symbol, funding_rate):
    """Evaluate one symbol given its current funding rate. Returns dict or None."""
    if abs(funding_rate) < FUNDING_THRESHOLD:
        return None

    # Funding positive → crowd long → SHORT.  Negative → crowd short → LONG.
    side = "SHORT" if funding_rate > 0 else "LONG"

    candles = base.klines(symbol, SIGNAL_TF, 220)
    if len(candles) < 200:
        return None
    closes = [c["c"] for c in candles]
    price = closes[-1]
    last = candles[-1]

    # ── Anti-trend gate: if a strong structural trend, extreme funding is
    #    justified — don't fade it. ──────────────────────────────────────
    adx_val = base.adx(candles, 14)
    if adx_val is not None and adx_val >= TREND_ADX_MAX:
        return None
    ema200 = base.ema(closes, 200)
    if ema200 and ema200 > 0:
        dist = abs(price - ema200) / ema200
        if dist > EMA200_DIST_MAX:
            return None  # price far from mean = strong trend, skip

    # ── Scoring (6 points) ──────────────────────────────────────────────
    score = 1  # base: funding extreme + thresholds + not strong trend
    reasons = [f"Funding {funding_rate*100:+.3f}% ({'longs' if side=='SHORT' else 'shorts'} crowded) → fade {side}"]

    # 1. Very extreme funding
    if abs(funding_rate) >= FUNDING_STRONG:
        score += 1
        reasons.append("funding VERY extreme")

    # 2. Candle reversal confirmation
    bull_bar = last["c"] > last["o"]
    if (side == "LONG" and bull_bar) or (side == "SHORT" and not bull_bar):
        score += 1
        reasons.append("candle confirms reversal")

    # 3. Rejection wick at the extreme
    rng = last["h"] - last["l"]
    if rng > 0:
        lower_wick = (min(last["o"], last["c"]) - last["l"]) / rng
        upper_wick = (last["h"] - max(last["o"], last["c"])) / rng
        if side == "LONG" and lower_wick >= 0.3:
            score += 1
            reasons.append("rejection wick down")
        elif side == "SHORT" and upper_wick >= 0.3:
            score += 1
            reasons.append("rejection wick up")

    # 4. RSI not at the wrong extreme + ideally supporting reversal
    r = base.rsi(closes, 14)
    if r is not None:
        if side == "LONG" and r < RSI_LONG_MAX:
            score += 1
            reasons.append(f"RSI {r:.0f} ok for long")
        elif side == "SHORT" and r > RSI_SHORT_MIN:
            score += 1
            reasons.append(f"RSI {r:.0f} ok for short")

    # 5. RSI confirms reversal extreme
    if r is not None:
        if (side == "LONG" and r < 40) or (side == "SHORT" and r > 60):
            score += 1
            reasons.append(f"RSI {r:.0f} supports reversal")

    if score < MIN_SCORE:
        return None

    # ── Levels ──────────────────────────────────────────────────────────
    a = base.atr(candles, 14)
    if not a or a <= 0:
        return None
    entry = price
    sl_dist = a * ATR_SL_MULT
    if side == "LONG":
        sl = entry - sl_dist
        tps = [entry + sl_dist * m for m in RR_TP]
    else:
        sl = entry + sl_dist
        tps = [entry - sl_dist * m for m in RR_TP]

    return {
        "symbol": symbol, "side": side, "entry": entry, "sl": sl,
        "tp1": tps[0], "tp2": tps[1], "tp3": tps[2],
        "funding": funding_rate, "adx": adx_val, "rsi": r, "atr": a,
        "score": score, "reasons": reasons,
    }


def build_volume_map():
    """symbol → 24h quote volume, for liquidity filtering."""
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

    vmap = {}
    for t in tickers:
        sym = t.get("symbol", "")
        if not sym.endswith("USDT") or sym in base.EXCLUDE_SYMBOLS:
            continue
        qv = float(t.get("quoteVolume", 0))
        if qv < MIN_QUOTE_VOLUME_24H or not is_crypto(sym):
            continue
        vmap[sym] = qv
    return vmap


def recently_signaled(journal, symbol):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_HOURS)
    for row in journal:
        if row.get("symbol") != symbol or (row.get("risk_model") or "") != "funding":
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

    vmap = build_volume_map()
    pidx = premium_index_all()
    # Build funding map for liquid symbols only
    candidates = []
    for p in pidx:
        sym = p.get("symbol", "")
        if sym not in vmap:
            continue
        try:
            fr = float(p.get("lastFundingRate", 0))
        except (TypeError, ValueError):
            continue
        if abs(fr) >= FUNDING_THRESHOLD:
            candidates.append((sym, fr))

    # Sort by funding extremity (most extreme first), cap work
    candidates.sort(key=lambda x: abs(x[1]), reverse=True)
    candidates = candidates[:MAX_SYMBOLS]

    best = None
    for sym, fr in candidates:
        if recently_signaled(journal, sym):
            continue
        try:
            s = setup_for(sym, fr)
            if s and (best is None or s["score"] > best["score"] or
                      (s["score"] == best["score"] and abs(s["funding"]) > abs(best["funding"]))):
                best = s
        except Exception:
            continue

    if not best:
        return  # silent

    em = best["entry"]
    rid = f"FND-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{best['symbol']}"
    rr = abs(best["tp2"] - em) / abs(em - best["sl"]) if abs(em - best["sl"]) > 0 else 0

    row = {
        "id": rid, "created_at": now_iso(), "symbol": best["symbol"], "side": best["side"],
        "timeframe_context": f"{SIGNAL_TF} signal + funding extreme {best['funding']*100:+.3f}%",
        "entry_low": em, "entry_high": em, "entry_mid": em,
        "sl": best["sl"], "tp1": best["tp1"], "tp2": best["tp2"], "tp3": best["tp3"],
        "initial_rr": round(rr, 2), "status": "WAITING_ENTRY",
        "risk_model": "funding", "scanner_min_score": MIN_SCORE,
        "score": best["score"],
        "technique": "Funding rate extreme (contrarian fade)",
        "reason": " · ".join(best["reasons"]),
        "funding_rate_pct": round(best["funding"] * 100, 4),
        "invalidation": f"Price menyentuh SL {fmt(best['sl'])} atau funding normalisasi",
        "source": "funding_signal", "result_r": None,
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
        notif = f"[funding-exec-error] {e}"

    arrow = "🟢 LONG" if best["side"] == "LONG" else "🔴 SHORT"
    crowd = "longs over-leveraged" if best["side"] == "SHORT" else "shorts over-leveraged"
    msg = (
        f"📈 Funding Rate Extreme Signal\n\n"
        f"🪙 {best['symbol']} — {arrow}\n"
        f"🎯 Contrarian fade ({crowd})\n\n"
        f"📍 Levels\n"
        f"• Entry: {fmt(em)}\n"
        f"• SL:    {fmt(best['sl'])}\n"
        f"• TP1:   {fmt(best['tp1'])}\n"
        f"• TP2:   {fmt(best['tp2'])}\n"
        f"• TP3:   {fmt(best['tp3'])}\n\n"
        f"📊 Metrics\n"
        f"• Funding: {best['funding']*100:+.3f}% / 8h\n"
        f"• ADX:     {best['adx']:.0f}" + (f" · RSI {best['rsi']:.0f}" if best['rsi'] else "") + "\n"
        f"• Score:   {best['score']}/6 · RR(TP2) {rr:.1f}"
    )
    if notif:
        msg += f"\n\n{notif}"
    print(msg)


if __name__ == "__main__":
    main()
