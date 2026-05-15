#!/usr/bin/env python3
import json, time, math, os, urllib.request, statistics
from datetime import datetime, timezone

JOURNAL='/root/.hermes/trading_journal/automatic_signal.jsonl'
STATE='/root/.hermes/trading_journal/automatic_signal_state.json'
os.makedirs(os.path.dirname(JOURNAL), exist_ok=True)
BASE='https://fapi.binance.com'

def get(path):
    with urllib.request.urlopen(BASE+path, timeout=12) as r:
        return json.loads(r.read().decode())

def klines(sym, interval, limit=120):
    data=get(f'/fapi/v1/klines?symbol={sym}&interval={interval}&limit={limit}')
    return [{'o':float(x[1]),'h':float(x[2]),'l':float(x[3]),'c':float(x[4]),'v':float(x[5]),'t':int(x[0])} for x in data]

def ema(vals, n):
    k=2/(n+1); e=vals[0]
    for v in vals[1:]: e=v*k+e*(1-k)
    return e

def atr(ks, n=14):
    trs=[]
    for i in range(1,len(ks)):
        trs.append(max(ks[i]['h']-ks[i]['l'], abs(ks[i]['h']-ks[i-1]['c']), abs(ks[i]['l']-ks[i-1]['c'])))
    return statistics.mean(trs[-n:]) if len(trs)>=n else None

def load_open():
    res=[]
    if os.path.exists(JOURNAL):
        for line in open(JOURNAL):
            try:
                j=json.loads(line)
                if j.get('status')=='open': res.append(j)
            except: pass
    return res

def recent_symbols():
    syms=set()
    now=time.time()
    if os.path.exists(JOURNAL):
        for line in open(JOURNAL):
            try:
                j=json.loads(line); ts=j.get('created_ts',0)
                if now-ts < 6*3600: syms.add(j.get('symbol'))
            except: pass
    return syms

def append(j):
    with open(JOURNAL,'a') as f: f.write(json.dumps(j, separators=(',',':'))+'\n')

def fmt(x):
    if x>=100: return f'{x:.2f}'
    if x>=1: return f'{x:.4f}'
    return f'{x:.6f}'

try:
    tickers=get('/fapi/v1/ticker/24hr')
    candidates=[t for t in tickers if t.get('symbol','').endswith('USDT') and float(t.get('quoteVolume',0))>15_000_000 and abs(float(t.get('priceChangePercent',0)))>=0.5]
    candidates=sorted(candidates, key=lambda x: abs(float(x.get('priceChangePercent',0))) * math.log10(max(float(x.get('quoteVolume',1)),10)), reverse=True)[:90]
    opened={x['symbol'] for x in load_open()}
    recent=recent_symbols()
    signals=[]
    for t in candidates:
        sym=t['symbol']
        if sym in opened or sym in recent: continue
        try:
            k15=klines(sym,'15m',120); k1h=klines(sym,'1h',120)
            c15=[x['c'] for x in k15]; c1=[x['c'] for x in k1h]
            price=c15[-1]
            e20_15,e50_15=ema(c15[-60:],20),ema(c15[-80:],50)
            e20_1,e50_1=ema(c1[-60:],20),ema(c1[-80:],50)
            a=atr(k15,14)
            if not a or a/price<0.0012 or a/price>0.055: continue
            vol_avg=statistics.mean([x['v'] for x in k15[-31:-1]])
            vol_ratio=k15[-1]['v']/vol_avg if vol_avg else 0
            high20=max(x['h'] for x in k15[-21:-1]); low20=min(x['l'] for x in k15[-21:-1])
            pct=float(t['priceChangePercent'])
            side=None; reason=''
            if e20_15>e50_15 and price>e20_15 and pct>0:
                breakout=price>high20 and vol_ratio>=1.25
                pullback=abs(price-e20_15)/price<0.020 and k15[-1]['c']>k15[-1]['o'] and vol_ratio>=0.85
                trend_setup=(price>e20_15 and vol_ratio>=0.95 and k15[-1]['c']>k15[-2]['h'])
                htf_ok=e20_1>e50_1 or c1[-1]>e20_1
                if htf_ok and (breakout or pullback or trend_setup):
                    side='LONG'; reason='AGGRESSIVE: bullish 15M + '+('breakout volume' if breakout else ('pullback/retest area' if pullback else 'momentum continuation setup'))
            elif e20_15<e50_15 and price<e20_15 and pct<0:
                breakdown=price<low20 and vol_ratio>=1.25
                pullback=abs(price-e20_15)/price<0.020 and k15[-1]['c']<k15[-1]['o'] and vol_ratio>=0.85
                trend_setup=(price<e20_15 and vol_ratio>=0.95 and k15[-1]['c']<k15[-2]['l'])
                htf_ok=e20_1<e50_1 or c1[-1]<e20_1
                if htf_ok and (breakdown or pullback or trend_setup):
                    side='SHORT'; reason='AGGRESSIVE: bearish 15M + '+('breakdown volume' if breakdown else ('pullback/retest area' if pullback else 'momentum continuation setup'))
            if not side: continue
            if side=='LONG':
                entry_low=price-a*0.25; entry_high=price+a*0.10; sl=min(low20, price-a*1.4); risk=(entry_high-sl); tp1=entry_high+risk*1.5; tp2=entry_high+risk*2.2; tp3=entry_high+risk*3.0
            else:
                entry_low=price-a*0.10; entry_high=price+a*0.25; sl=max(high20, price+a*1.4); risk=(sl-entry_low); tp1=entry_low-risk*1.5; tp2=entry_low-risk*2.2; tp3=entry_low-risk*3.0
            if risk/price>0.045 or risk/price<0.0018: continue
            sig={'id':f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{sym}",'created_utc':datetime.now(timezone.utc).isoformat(),'created_ts':time.time(),'symbol':sym,'side':side,'entry_low':entry_low,'entry_high':entry_high,'sl':sl,'tp1':tp1,'tp2':tp2,'tp3':tp3,'rr_tp1':1.5,'rr_tp2':2.2,'rr_tp3':3.0,'status':'open','source':'binance_usdt_perp','risk_model':'aggressive','reason':reason,'price_at_signal':price,'vol_ratio':vol_ratio}
            signals.append(sig)
            if len(signals)>=1: break
        except Exception:
            continue
    if not signals:
        raise SystemExit(0)
    s=signals[0]; append(s)
    msg=f"## {s['symbol']} Perp — SETUP {s['side']} AGGRESSIVE\n\n- Source: Binance USDT-M Perp | TF: 15M + 1H\n- Price: {fmt(s['price_at_signal'])}\n- Reason: {s['reason']} | Vol ratio: {s['vol_ratio']:.2f}x\n- Entry: {fmt(s['entry_low'])} - {fmt(s['entry_high'])}\n- SL: {fmt(s['sl'])}\n- TP1: {fmt(s['tp1'])} | TP2: {fmt(s['tp2'])} | TP3: {fmt(s['tp3'])}\n- RR: 1.5R / 2.2R / 3.0R\n\n**Best Call:** Aggressive setup; entry boleh jauh, tunggu area entry / konfirmasi 15M tetap valid.\n**Invalid if:** candle 15M close melewati SL / struktur trend 1H berubah.\n\nJournal ID: `{s['id']}`"
    print(msg)
except SystemExit:
    pass
except Exception as e:
    print(f'Automatic Signal scanner error: {e}')
