#!/usr/bin/env python3
"""Deterministic aggressive Binance USDT perpetual signal scanner.
Prints a Telegram-ready signal only when a high-quality setup exists; otherwise prints nothing.
Maintains journal at ~/.hermes/trading_journals/automatic_signal_journal.json.
"""
from __future__ import annotations

import json, math, os, time, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

BASE = "https://fapi.binance.com"
JOURNAL = Path.home() / ".hermes" / "trading_journals" / "automatic_signal_journal.json"
MAX_SYMBOLS = 100
COOLDOWN_HOURS = 8
QUOTE_MIN_VOLUME = 8_000_000  # 24h quote volume
# Crypto-only filter: Binance lists tokenized equities, commodities, and indices
# as perpetuals (TRADIFI_PERPETUAL with underlyingType EQUITY/COMMODITY/INDEX).
# Automatic Signal must only emit pure crypto setups.
ALLOWED_UNDERLYING_TYPES = {"COIN"}
ALLOWED_CONTRACT_TYPES = {"PERPETUAL"}
EXCLUDE_SUBTYPES = {"TradFi", "Index"}
# Hard manual blocklist as defense-in-depth in case Binance changes labels.
EXCLUDE_SYMBOLS = {
    "MSTRUSDT", "XAGUSDT", "XAUUSDT", "EWYUSDT", "COINUSDT", "NVDAUSDT", "TSLAUSDT",
    "AAPLUSDT", "MSFTUSDT", "GOOGLUSDT", "AMZNUSDT", "METAUSDT", "SPXUSDT", "NASDAQUSDT",
    "AMDUSDT", "INTCUSDT", "HOODUSDT", "CRCLUSDT", "PLTRUSDT", "COPPERUSDT", "EWJUSDT",
    "PAYPUSDT", "CLUSDT", "BZUSDT", "NATGASUSDT", "QQQUSDT", "SPYUSDT", "TSMUSDT", "MUUSDT",
    "XPTUSDT", "XPDUSDT", "DEFIUSDT", "BTCDOMUSDT", "ALLUSDT",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_json(path, params=None, timeout=12):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Hermes-Furina-Signal/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def klines(symbol, interval, limit):
    rows = get_json("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit})
    out = []
    for k in rows:
        out.append({
            "t": int(k[0]), "o": float(k[1]), "h": float(k[2]), "l": float(k[3]),
            "c": float(k[4]), "v": float(k[5]), "qv": float(k[7])
        })
    return out


def ema(vals, n):
    if len(vals) < n: return None
    k = 2/(n+1)
    e = mean(vals[:n])
    for v in vals[n:]: e = v*k + e*(1-k)
    return e


def rsi(vals, n=14):
    if len(vals) < n+1: return None
    gains=[]; losses=[]
    for a,b in zip(vals[-n-1:-1], vals[-n:]):
        d=b-a; gains.append(max(d,0)); losses.append(max(-d,0))
    ag=mean(gains); al=mean(losses)
    if al == 0: return 100.0
    rs=ag/al
    return 100 - 100/(1+rs)


def atr(candles, n=14):
    if len(candles) < n+1: return None
    trs=[]
    prev = candles[-n-1]["c"]
    for x in candles[-n:]:
        trs.append(max(x["h"]-x["l"], abs(x["h"]-prev), abs(x["l"]-prev)))
        prev=x["c"]
    return mean(trs)


def pct(a,b):
    return (a-b)/b*100 if b else 0


def load_journal():
    if not JOURNAL.exists(): return []
    try: return json.loads(JOURNAL.read_text())
    except Exception: return []


def save_journal(rows):
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    JOURNAL.write_text(json.dumps(rows, indent=2, ensure_ascii=False))


def recently_signaled(rows, symbol):
    cutoff = time.time() - COOLDOWN_HOURS*3600
    for r in rows:
        if r.get("symbol") == symbol:
            try:
                ts = datetime.fromisoformat(r["created_at"].replace("Z","+00:00")).timestamp()
                if ts > cutoff and r.get("status") in {"WAITING_ENTRY","ACTIVE","TP1_HIT","TP2_HIT"}:
                    return True
            except Exception: pass
    return False


def setup_for(symbol, btc_bias, signal_tf="15m"):
    # Automatic Signal rule: smallest TF is 15m. If no setup on 15m,
    # scanner escalates to 30m, then 1h. No 5m entries.
    c15 = klines(symbol, signal_tf, 96)
    c1h = klines(symbol, "1h", 80)
    closes15=[x["c"] for x in c15]; closes1h=[x["c"] for x in c1h]
    last=c15[-1]; price=last["c"]
    e20_15=ema(closes15[-50:],20); e50_15=ema(closes15,50)
    e20_1h=ema(closes1h[-50:],20); e50_1h=ema(closes1h,50)
    r15=rsi(closes15)
    a15=atr(c15)
    vol_avg=mean([x["qv"] for x in c15[-21:-1]])
    vol_ratio=last["qv"]/vol_avg if vol_avg else 0
    if vol_avg < 300_000:
        return None
    recent_high=max(x["h"] for x in c15[-21:-1])
    recent_low=min(x["l"] for x in c15[-21:-1])
    prev_high=max(x["h"] for x in c15[-49:-21])
    prev_low=min(x["l"] for x in c15[-49:-21])
    chg1h=pct(c1h[-1]["c"], c1h[-2]["c"])
    if not all([e20_15,e50_15,e20_1h,e50_1h,r15,a15]): return None
    # Avoid huge chase candles, ultra-low ATR, and late shorts after an extended flush.
    candle_range = last["h"] - last["l"]
    if candle_range > 3.6*a15 or a15/price < 0.0012: return None
    try:
        ticker_24h = get_json("/fapi/v1/ticker/24hr", {"symbol": symbol})
        chg24 = float(ticker_24h.get("priceChangePercent", 0))
    except Exception:
        chg24 = 0.0
    close_pos = (last["c"] - last["l"]) / candle_range if candle_range else 0.5
    score=0; side=None; reason=[]
    # LONG: aggressive 15m trend/momentum with 1h not strongly opposing
    if price > e20_15 > e50_15 and btc_bias != "bearish" and close_pos >= 0.55:
        if last["c"] > recent_high*0.992 or recent_high > prev_high*0.990:
            score += 3; reason.append("structure bullish / breakout-retest area")
        if vol_ratio >= 1.25: score += 2; reason.append(f"volume {vol_ratio:.1f}x avg")
        if 45 <= r15 <= 78: score += 1; reason.append(f"RSI {signal_tf} {r15:.0f}")
        if chg1h > 0: score += 1; reason.append("1H momentum positive")
        side="LONG"
    # SHORT
    elif price < e20_15 < e50_15 and btc_bias != "bullish" and close_pos <= 0.45:
        # Lesson from PUMPUSDT 2026-05-14: avoid late breakdown shorts after a large
        # 24h flush when the next candle is already reclaiming toward EMA/resistance;
        # these often become stop-hunt bounces before continuation.
        if chg24 < -5.0 and r15 < 35 and price > recent_low * 1.012:
            return None
        if last["h"] >= e20_15 * 0.995 and last["c"] > last["o"]:
            return None
        if last["c"] < recent_low*1.008 or recent_low < prev_low*1.010:
            score += 3; reason.append("structure bearish / breakdown-retest area")
        if vol_ratio >= 1.25: score += 2; reason.append(f"volume {vol_ratio:.1f}x avg")
        if 22 <= r15 <= 55: score += 1; reason.append(f"RSI {signal_tf} {r15:.0f}")
        if chg1h < 0: score += 1; reason.append("1H momentum negative")
        side="SHORT"
    if score < 6 or not side: return None
    # Build pullback entry, SL, TPs using ATR and structure. Require RR >= 1.5 to TP2.
    if side == "LONG":
        entry_high = price - 0.10*a15
        entry_low = max(e20_15, price - 0.55*a15)
        sl = min(recent_low, entry_low - 0.75*a15)
        risk = ((entry_low+entry_high)/2) - sl
        tp1 = ((entry_low+entry_high)/2) + risk*1.0
        tp2 = ((entry_low+entry_high)/2) + risk*1.8
        tp3 = ((entry_low+entry_high)/2) + risk*2.6
    else:
        entry_low = price + 0.10*a15
        entry_high = min(e20_15, price + 0.55*a15) if e20_15 > price else price + 0.55*a15
        sl = max(recent_high, entry_high + 0.75*a15)
        risk = sl - ((entry_low+entry_high)/2)
        tp1 = ((entry_low+entry_high)/2) - risk*1.0
        tp2 = ((entry_low+entry_high)/2) - risk*1.8
        tp3 = ((entry_low+entry_high)/2) - risk*2.6
    if risk <= 0: return None
    if risk / ((entry_low+entry_high)/2) > 0.035:
        return None
    rr = abs(tp2-((entry_low+entry_high)/2))/risk
    if rr < 1.5: return None
    technique = "Breakout-Retest Trend Continuation"
    if any("breakdown" in x for x in reason):
        technique = "Breakdown-Retest Trend Continuation"
    return dict(symbol=symbol, side=side, price=price, score=score, reason=reason, technique=technique, entry_low=entry_low, entry_high=entry_high, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3, rr=rr, r15=r15, vol_ratio=vol_ratio, signal_tf=signal_tf)


def fmt_price(x):
    if x >= 1000: return f"{x:,.1f}"
    if x >= 100: return f"{x:,.2f}"
    if x >= 1: return f"{x:,.4f}"
    return f"{x:.6f}"


def main():
    journal=load_journal()
    # Build crypto-only universe from exchangeInfo: only PERPETUAL contracts where
    # underlyingType=="COIN" and no TradFi/Index/commodity subtypes. This blocks
    # tokenized stocks (AMD, NVDA, TSLA, ...), commodities (XAU, COPPER, OIL, ...),
    # and ETF/index perps from ever entering the scanner pool.
    try:
        info=get_json("/fapi/v1/exchangeInfo")
        meta={s["symbol"]: s for s in info.get("symbols", []) if s.get("status")=="TRADING"}
    except Exception:
        meta={}
    tickers=get_json("/fapi/v1/ticker/24hr")
    def is_crypto(sym):
        m=meta.get(sym)
        if not m:
            # Without metadata, fall back to manual blocklist only.
            return sym not in EXCLUDE_SYMBOLS
        if m.get("contractType") not in ALLOWED_CONTRACT_TYPES: return False
        if m.get("underlyingType") not in ALLOWED_UNDERLYING_TYPES: return False
        subs=set(m.get("underlyingSubType") or [])
        if subs & EXCLUDE_SUBTYPES: return False
        return True
    universe=[t for t in tickers
              if t.get("symbol","").endswith("USDT")
              and t.get("symbol","") not in EXCLUDE_SYMBOLS
              and is_crypto(t.get("symbol",""))
              and float(t.get("quoteVolume",0)) >= QUOTE_MIN_VOLUME]
    universe=sorted(universe, key=lambda x: abs(float(x.get("priceChangePercent",0)))+math.log10(float(x.get("quoteVolume",1))), reverse=True)[:MAX_SYMBOLS]
    # Context bias uses simple 1h EMA if no setup object
    btc1h=klines("BTCUSDT","1h",60); bc=[x["c"] for x in btc1h]; be20=ema(bc[-50:],20); be50=ema(bc,50)
    btc_bias="neutral"
    if be20 and be50 and bc[-1] > be20 > be50: btc_bias="bullish"
    if be20 and be50 and bc[-1] < be20 < be50: btc_bias="bearish"
    best=None
    for tf in ["15m", "30m", "1h"]:
        for t in universe:
            sym=t["symbol"]
            if sym in {"USDCUSDT","BTCUSDT"} or recently_signaled(journal, sym):
                continue
            try:
                s=setup_for(sym, btc_bias, tf)
                if s and (best is None or s["score"] > best["score"] or (s["score"]==best["score"] and s["vol_ratio"]>best["vol_ratio"])):
                    best=s
            except Exception:
                continue
        if best:
            break
    if not best:
        return
    entry_mid=(best["entry_low"]+best["entry_high"])/2
    rid=f"AS-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{best['symbol']}"
    row={
        "id": rid, "created_at": now_iso(), "symbol": best["symbol"], "side": best["side"],
        "timeframe_context": f"{best['signal_tf']} signal + 1h context", "entry_low": best["entry_low"], "entry_high": best["entry_high"],
        "entry_mid": entry_mid, "sl": best["sl"], "tp1": best["tp1"], "tp2": best["tp2"], "tp3": best["tp3"],
        "initial_rr": round(best["rr"],2), "status": "WAITING_ENTRY", "risk_model": "aggressive", "technique": best["technique"], "reason": best["reason"], "invalidation": f"Price menyentuh SL {fmt_price(best['sl'])} atau struktur {best['signal_tf']} berbalik sebelum entry", "source":"automatic_signal", "result_r": None
    }
    journal.append(row); save_journal(journal)
    msg=f"""## {best['symbol']} Perp — SETUP {best['side']} AGGRESSIVE

**Status:** Planned setup / waiting entry
**Journal ID:** `{rid}`

**Market Context**
- Source: Binance USDⓈ-M Futures
- Price: {fmt_price(best['price'])}
- Risk mode: Aggressive
- Signal TF: {best['signal_tf']} + 1H context
- BTC bias: {btc_bias}

**Teknik**
- {best['technique']}

**Alasan {best['side']}**
- {chr(10).join('- ' + x for x in best['reason'][:4])}

**Entry Plan**
- Side: {best['side']}
- Entry area: {fmt_price(best['entry_low'])} – {fmt_price(best['entry_high'])}
- SL: {fmt_price(best['sl'])}
- TP1: {fmt_price(best['tp1'])}
- TP2: {fmt_price(best['tp2'])}
- TP3: {fmt_price(best['tp3'])}
- RR to TP2: ±{best['rr']:.2f}R

**No Trade Zone**
- Jangan chase jika price sudah jauh dari entry area.
- Invalid jika candle {best['signal_tf']} melebar ekstrem atau struktur berbalik.

**Best Call:** tunggu entry area, no chase.
**Invalidation:** {row['invalidation']}

_Edukasi/analisis, bukan jaminan profit._"""
    print(msg)

if __name__ == "__main__":
    main()
