#!/usr/bin/env python3
import json, urllib.request, statistics, time

BASE='https://api.binance.com'

def get(path):
    with urllib.request.urlopen(BASE+path, timeout=15) as r:
        return json.loads(r.read().decode())

try:
    tickers=get('/api/v3/ticker/24hr')
    usdt=[]
    for t in tickers:
        s=t.get('symbol','')
        if not s.endswith('USDT'): continue
        if any(x in s for x in ['UPUSDT','DOWNUSDT','BULLUSDT','BEARUSDT']): continue
        qv=float(t.get('quoteVolume') or 0)
        if qv>=10_000_000:
            usdt.append((qv,s,t))
    usdt=sorted(usdt, reverse=True)[:120]
    alerts=[]
    for _,s,t in usdt:
        try:
            kl=get(f'/api/v3/klines?symbol={s}&interval=1h&limit=25')
            if len(kl)<22: continue
            vols=[float(k[5]) for k in kl[:-1]]
            last=kl[-1]
            last_vol=float(last[5])
            avg=statistics.mean(vols[-20:]) if vols[-20:] else 0
            openp=float(last[1]); close=float(last[4]); high=float(last[2])
            pct=(close-openp)/openp*100 if openp else 0
            prev_high=max(float(k[2]) for k in kl[-21:-1])
            vol_ratio=last_vol/avg if avg else 0
            quote_vol=float(t.get('quoteVolume') or 0)
            # Big bullish breakout: volume surge + price displacement + breaks recent 20h high.
            if vol_ratio>=3.0 and pct>=4.0 and close>prev_high and quote_vol>=20_000_000:
                alerts.append({
                    'symbol':s,'price':close,'pct':pct,'vol_ratio':vol_ratio,
                    'prev_high':prev_high,'quote_vol':quote_vol
                })
        except Exception:
            continue
        time.sleep(0.03)
    alerts=sorted(alerts, key=lambda x:(x['vol_ratio'], x['pct']), reverse=True)[:5]
    if alerts:
        lines=['## 🚨 Volume Breakout Besar', '', '- Source: Binance Spot 1H', '- Kriteria: volume ≥3x avg 20 candle + close break high 20H + candle ≥4%', '']
        for a in alerts:
            lines.append(f"- {a['symbol']}: price {a['price']:.6g} | 1H {a['pct']:.2f}% | vol {a['vol_ratio']:.1f}x | break > {a['prev_high']:.6g}")
        lines += ['', '**Best Call:** Watch retest; jangan chase candle panjang.', '**Invalid if:** close balik bawah area breakout.']
        print('\n'.join(lines))
except Exception as e:
    # Non-zero would alert error; keep quiet for transient API issue.
    pass
