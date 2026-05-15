#!/usr/bin/env python3
"""Automatic Binance Alpha signal scanner.
Prints a signal only when Alpha coin setup passes filters; otherwise silent.
"""
from __future__ import annotations
import json, math, time, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

BASE="https://www.binance.com"
JOURNAL=Path.home()/".hermes"/"trading_journals"/"binance_alpha_signal_journal.json"
MAX_SYMBOLS=120
COOLDOWN_HOURS=12
MIN_24H_QV=5_000

def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def req(path, params=None):
    url=BASE+path
    if params: url += "?"+urllib.parse.urlencode(params)
    r=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 Hermes-Furina-Alpha/1.0"})
    with urllib.request.urlopen(r,timeout=15) as f:
        data=json.loads(f.read().decode())
    if isinstance(data,dict) and data.get("code") not in (None,"000000"):
        raise RuntimeError(str(data)[:200])
    return data.get("data",data)

def candles(symbol, interval="15m", limit=100):
    rows=req("/bapi/defi/v1/public/alpha-trade/klines", {"symbol":symbol,"interval":interval,"limit":limit})
    out=[]
    for k in rows:
        out.append({"t":int(k[0]),"o":float(k[1]),"h":float(k[2]),"l":float(k[3]),"c":float(k[4]),"v":float(k[5]),"qv":float(k[7]),"n":int(k[8])})
    return out

def ticker(symbol): return req("/bapi/defi/v1/public/alpha-trade/ticker", {"symbol":symbol})
def ema(vals,n):
    if len(vals)<n: return None
    k=2/(n+1); e=mean(vals[:n])
    for v in vals[n:]: e=v*k+e*(1-k)
    return e
def rsi(vals,n=14):
    if len(vals)<n+1: return None
    gs=[]; ls=[]
    for a,b in zip(vals[-n-1:-1], vals[-n:]):
        d=b-a; gs.append(max(d,0)); ls.append(max(-d,0))
    ag=mean(gs); al=mean(ls)
    return 100 if al==0 else 100-100/(1+ag/al)
def atr(cs,n=14):
    if len(cs)<n+1: return None
    trs=[]; prev=cs[-n-1]["c"]
    for x in cs[-n:]:
        trs.append(max(x["h"]-x["l"],abs(x["h"]-prev),abs(x["l"]-prev))); prev=x["c"]
    return mean(trs)
def load():
    if not JOURNAL.exists(): return []
    try: return json.loads(JOURNAL.read_text())
    except Exception: return []
def save(rows):
    JOURNAL.parent.mkdir(parents=True,exist_ok=True); JOURNAL.write_text(json.dumps(rows,indent=2,ensure_ascii=False))
def recent(rows,sym):
    cutoff=time.time()-COOLDOWN_HOURS*3600
    for r in rows:
        if r.get("symbol")==sym:
            try:
                if datetime.fromisoformat(r["created_at"].replace("Z","+00:00")).timestamp()>cutoff and r.get("status") in {"WAITING_ENTRY","ACTIVE","TP1_HIT","TP2_HIT"}: return True
            except Exception: pass
    return False
def fmt(x):
    if abs(x)>=100: return f"{x:,.2f}"
    if abs(x)>=1: return f"{x:,.4f}"
    return f"{x:.8f}".rstrip('0').rstrip('.')

def analyze(symbol):
    t=ticker(symbol); qv=float(t.get("quoteVolume") or 0); trades=int(t.get("count") or 0)
    if qv<MIN_24H_QV or trades<20: return None
    c15=candles(symbol,"15m",100); c1h=candles(symbol,"1h",80)
    # Require actual trading activity in recent candles
    if sum(x["qv"] for x in c15[-8:]) <= 0: return None
    cl=[x["c"] for x in c15]; cl1=[x["c"] for x in c1h]; price=cl[-1]
    e20=ema(cl[-50:],20); e50=ema(cl,50); e20h=ema(cl1[-50:],20); e50h=ema(cl1,50); rrsi=rsi(cl); aa=atr(c15)
    if not all([e20,e50,e20h,e50h,rrsi,aa]) or aa/price<0.002: return None
    last=c15[-1]; vol_avg=mean([x["qv"] for x in c15[-21:-1] if x["qv"]>=0]) or 1
    vr=last["qv"]/vol_avg
    recent_high=max(x["h"] for x in c15[-21:-1]); recent_low=min(x["l"] for x in c15[-21:-1])
    prev_high=max(x["h"] for x in c15[-49:-21]); prev_low=min(x["l"] for x in c15[-49:-21])
    side=None; score=0; reasons=[]
    if price>e20>e50 and price>e20h>e50h and last["c"]>recent_high*0.998 and recent_high>=prev_high*0.995 and 50<=rrsi<=70:
        side="LONG"; score=5; reasons=["trend 15m/1h bullish", "breakout/retest structure", f"RSI {rrsi:.0f}"]
    elif price<e20<e50 and price<e20h<e50h and last["c"]<recent_low*1.002 and recent_low<=prev_low*1.005 and 30<=rrsi<=50:
        side="SHORT"; score=5; reasons=["trend 15m/1h bearish", "breakdown/retest structure", f"RSI {rrsi:.0f}"]
    if side and vr>=1.3: score+=2; reasons.append(f"volume {vr:.1f}x avg")
    if not side or score<6: return None
    if side=="LONG":
        el=max(e20, price-0.55*aa); eh=price-0.10*aa; sl=min(recent_low, el-0.75*aa); entry=(el+eh)/2; risk=entry-sl; tp1=entry+risk; tp2=entry+1.8*risk; tp3=entry+2.6*risk
    else:
        el=price+0.10*aa; eh=price+0.55*aa; sl=max(recent_high, eh+0.75*aa); entry=(el+eh)/2; risk=sl-entry; tp1=entry-risk; tp2=entry-1.8*risk; tp3=entry-2.6*risk
    if risk<=0 or abs(tp2-entry)/risk<1.5: return None
    return {"symbol":symbol,"side":side,"score":score,"price":price,"entry_low":min(el,eh),"entry_high":max(el,eh),"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"rr":abs(tp2-entry)/risk,"reasons":reasons,"qv":qv,"vr":vr}

def alpha_token_map():
    """Return tradable Alpha IDs mapped to user-facing token metadata.

    Binance alpha-trade exchange-info uses internal symbols like ALPHA_154USDT.
    The UI/token list maps that to a real ticker (e.g. SKYAI). We always emit a
    user-facing ticker — never the raw ALPHA_xxx ID.

    Display priority: cexCoinName (clean upper ticker) → symbol uppercased & sanitized.
    """
    data=req("/bapi/defi/v1/public/wallet-direct/buw/wallet/cex/alpha/all/token/list")
    out={}
    for t in data if isinstance(data,list) else []:
        aid=t.get("alphaId")
        if not aid or t.get("offline") or t.get("fullyDelisted") or t.get("cexOffDisplay"):
            continue
        cex=(t.get("cexCoinName") or "").strip()
        raw=(t.get("symbol") or "").strip()
        if cex:
            display=cex.upper()
        elif raw:
            display="".join(ch for ch in raw.upper() if ch.isalnum())
        else:
            continue
        if not display: continue
        out[aid]={"display_symbol":display,"name":t.get("name") or display,"alpha_id":aid,"volume24h":float(t.get("volume24h") or 0),"liquidity":float(t.get("liquidity") or 0)}
    return out

def main():
    rows=load()
    amap=alpha_token_map()
    info=req("/bapi/defi/v1/public/alpha-trade/get-exchange-info")
    syms=[]
    for s in info.get("symbols",[]):
        base=s.get("baseAsset")
        if s.get("status")=="TRADING" and s.get("quoteAsset")=="USDT" and base in amap:
            meta=amap[base]
            syms.append((s["symbol"], meta))
    syms=sorted(syms, key=lambda x: x[1].get("volume24h",0), reverse=True)[:MAX_SYMBOLS]
    best=None
    for sym, meta in syms:
        if recent(rows,meta["display_symbol"]): continue
        try:
            s=analyze(sym)
            if s:
                s.update(meta)
            if s and (best is None or s["score"]>best["score"] or (s["score"]==best["score"] and s["qv"]>best["qv"])): best=s
        except Exception: continue
    if not best: return
    entry=(best["entry_low"]+best["entry_high"])/2; rid=f"BA-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{best['display_symbol']}"
    row={"id":rid,"created_at":now_iso(),"symbol":best["display_symbol"],"alpha_id":best.get("alpha_id"),"internal_symbol":best["symbol"],"side":best["side"],"timeframe_context":"15m/1h Binance Alpha","entry_low":best["entry_low"],"entry_high":best["entry_high"],"entry_mid":entry,"sl":best["sl"],"tp1":best["tp1"],"tp2":best["tp2"],"tp3":best["tp3"],"initial_rr":round(best["rr"],2),"status":"WAITING_ENTRY","source":"binance_alpha_signal","result_r":None}
    rows.append(row); save(rows)
    print(f"""## {best['display_symbol']} ({best.get('alpha_id')}) Alpha — SETUP {best['side']}

- Token: **{best['display_symbol']}** ({best.get('name') or best['display_symbol']})
- Source: Binance Alpha {best.get('alpha_id')} | Internal pair: `{best['symbol']}` | TF: 15m/1h
- Price: {fmt(best['price'])}
- Reason: {', '.join(best['reasons'][:4])}
- Entry: {fmt(best['entry_low'])}–{fmt(best['entry_high'])}
- SL: {fmt(best['sl'])}
- TP1: {fmt(best['tp1'])} | TP2: {fmt(best['tp2'])} | TP3: {fmt(best['tp3'])}
- RR: ±{best['rr']:.2f}R to TP2

**Best Call:** tunggu price masuk entry area; no chase.
**Invalid if:** price menyentuh SL {fmt(best['sl'])} atau struktur 15m berbalik sebelum entry.

Journal ID: `{rid}`

_Bukan nasihat finansial; gunakan position sizing dan konfirmasi manual._""")
if __name__=="__main__": main()
