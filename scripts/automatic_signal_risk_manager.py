#!/usr/bin/env python3
"""Risk manager: notify BE SL + trailing stop rule when running PnL >= 5%."""
from __future__ import annotations
import json, urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime, timezone
BASE='https://fapi.binance.com'
JOURNAL=Path.home()/'.hermes'/'trading_journals'/'automatic_signal_journal.json'

def get_json(path, params=None, timeout=12):
    url=BASE+path
    if params: url += '?' + urllib.parse.urlencode(params)
    req=urllib.request.Request(url, headers={'User-Agent':'Hermes-Furina-Risk-Manager/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read().decode())

def price(sym): return float(get_json('/fapi/v1/ticker/price', {'symbol':sym})['price'])
def load():
    if not JOURNAL.exists(): return []
    try: return json.loads(JOURNAL.read_text())
    except Exception: return []
def save(rows):
    JOURNAL.parent.mkdir(parents=True, exist_ok=True); JOURNAL.write_text(json.dumps(rows, indent=2, ensure_ascii=False))
def fmt(x):
    x=float(x)
    if x>=1000: return f'{x:,.1f}'
    if x>=100: return f'{x:,.2f}'
    if x>=1: return f'{x:,.4f}'
    return f'{x:.6f}'

def main():
    rows=load(); changed=False; notes=[]; now=datetime.now(timezone.utc).isoformat(timespec='seconds')
    for r in rows:
        if r.get('status') not in {'ACTIVE','TP1_HIT','TP2_HIT'}: continue
        if r.get('trailing_5pct_notified'): continue
        entry=r.get('entry_hit_price') or r.get('entry_mid')
        if not entry: continue
        try: p=price(r['symbol'])
        except Exception: continue
        pnl=(p-entry)/entry*100 if r['side']=='LONG' else (entry-p)/entry*100
        if pnl >= 5.0:
            r['trailing_5pct_notified']=True
            r['trailing_activated_at']=now
            r['trailing_activated_price']=p
            r['recommended_sl']='ENTRY/BREAKEVEN'
            r['recommended_order_type']='TRAILING_STOP_1.5_PERCENT'
            changed=True
            notes.append(f"""## {r['symbol']} Perp — RISK UPDATE

**Status:** Running profit ≥ 5%
**Journal ID:** `{r['id']}`

**Action Rule**
- Ubah SL ke: **Entry / Breakeven**
- Ganti order type: **Trailing Stop 1.5%**

**Position**
- Side: {r['side']}
- Entry: {fmt(entry)}
- Current price: {fmt(p)}
- Running PnL: **+{pnl:.2f}%**
- Old SL: {fmt(r['sl'])}

**Tujuan:** lock profit dan ubah trade jadi good risk / no-loss setup.""")
    if changed: save(rows)
    if notes: print('\n\n'.join(notes))
if __name__=='__main__': main()
