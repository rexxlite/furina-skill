#!/usr/bin/env python3
"""Monitor Binance Alpha signal journal and notify on HIT ENTRY / TP / SL transitions."""
from __future__ import annotations
import json, urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime, timezone

BASE="https://www.binance.com"
JOURNAL=Path.home()/".hermes"/"trading_journals"/"binance_alpha_signal_journal.json"

def req(path, params=None, timeout=12):
    url=BASE+path
    if params: url += "?"+urllib.parse.urlencode(params)
    request=urllib.request.Request(url, headers={"User-Agent":"Hermes-Furina-Alpha-Monitor/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as r:
        data=json.loads(r.read().decode())
    if isinstance(data,dict) and data.get("code") not in (None,"000000"):
        raise RuntimeError(str(data)[:200])
    return data.get("data",data)

def price(symbol):
    data=req("/bapi/defi/v1/public/alpha-trade/ticker", {"symbol":symbol})
    return float(data.get("lastPrice") or data.get("price") or data.get("close") or 0)

def load():
    if not JOURNAL.exists(): return []
    try: return json.loads(JOURNAL.read_text())
    except Exception: return []

def save(rows):
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    JOURNAL.write_text(json.dumps(rows, indent=2, ensure_ascii=False))

def fmt(x):
    if x is None: return "-"
    x=float(x)
    if abs(x)>=1000: return f"{x:,.1f}"
    if abs(x)>=100: return f"{x:,.2f}"
    if abs(x)>=1: return f"{x:,.4f}"
    return f"{x:.8f}".rstrip('0').rstrip('.')

def display_label(r):
    """Always render a user-facing ticker + alpha_id, never just the internal ALPHA_xxx ID."""
    sym=(r.get("symbol") or "").strip()
    aid=(r.get("alpha_id") or "").strip()
    # legacy rows where symbol was stored as internal ID like ALPHA_790USDT
    if sym.upper().startswith("ALPHA_"):
        sym=""
    if sym and aid: return f"{sym} ({aid})"
    if sym: return sym
    if aid: return aid
    return r.get("internal_symbol") or "?"

def hit_entry(r,p): return float(r["entry_low"]) <= p <= float(r["entry_high"])
def header(r,event): return f"## {display_label(r)} Alpha — {event}"

def setup_block(r):
    return (f"**Setup**\n"
            f"- Source: Binance Alpha\n"
            f"- Side: {r['side']}\n"
            f"- Entry area: {fmt(r['entry_low'])} – {fmt(r['entry_high'])}\n"
            f"- SL: {fmt(r['sl'])}\n"
            f"- TP1: {fmt(r['tp1'])}\n"
            f"- TP2: {fmt(r['tp2'])}\n"
            f"- TP3: {fmt(r['tp3'])}")

def note_hit_entry(r,p):
    return (f"{header(r,'HIT ENTRY')}\n\n"
            f"**Status:** Active\n"
            f"**Journal ID:** `{r['id']}`\n\n"
            f"{setup_block(r)}\n\n"
            f"**Update**\n- Entry hit price: {fmt(p)}\n- Action: pantau TP/SL")

def note_sl_fast(r,p):
    return (f"{header(r,'ENTRY TOUCHED + SL HIT')}\n\n"
            f"**Status:** Closed / -1R\n"
            f"**Journal ID:** `{r['id']}`\n\n"
            f"{setup_block(r)}\n\n"
            f"**Update**\n- Current price: {fmt(p)}\n- Result: **-1R**\n\n"
            f"Catatan: price bergerak cepat melewati entry sampai SL sebelum monitor sempat kirim HIT ENTRY terpisah.")

def note_sl(r,p):
    return (f"{header(r,'SL HIT')}\n\n"
            f"**Status:** Closed\n"
            f"**Journal ID:** `{r['id']}`\n\n"
            f"**Update**\n- Side: {r['side']}\n- Close price: {fmt(p)}\n- Result: **-1R**")

def note_tp(r,p,tp,result,closed=False):
    status="Closed / Full target" if closed else "Running profit"
    entry=float(r.get("entry_hit_price") or r.get("entry_mid") or ((float(r["entry_low"])+float(r["entry_high"]))/2))
    pnl_pct=(p-entry)/entry*100 if r["side"]=="LONG" else (entry-p)/entry*100
    risk_pct=abs(entry-float(r["sl"]))/entry*100
    tp1_rule = "\n- Action: **Take profit 50% dan pindahkan SL sisa posisi ke entry / BE**" if tp == "TP1" else ""
    full_close_note = "\n- Action: **TP max hit — posisi dianggap FULL CLOSE. Tidak perlu pantau TP/SL lanjutan.**" if closed else ""
    return (f"{header(r, tp+' HIT')}\n\n"
            f"**Status:** {status}\n"
            f"**Journal ID:** `{r['id']}`\n\n"
            f"**Setup**\n- Source: Binance Alpha\n- Side: {r['side']}\n- Entry: {fmt(entry)}\n- SL: {fmt(r.get('sl_current', r['sl']))} (**risk {risk_pct:.2f}%**)\n- TP1: {fmt(r['tp1'])}\n- TP2: {fmt(r['tp2'])}\n- TP3: {fmt(r['tp3'])}\n\n"
            f"**Update**\n- Hit price: {fmt(p)}\n- PnL from entry: **+{pnl_pct:.2f}%**\n- Result: **+{result}R**{tp1_rule}{full_close_note}")

def main():
    rows=load(); changed=False; notes=[]
    for r in rows:
        status=r.get("status")
        if status in {"SL_HIT","TP3_HIT","CLOSED","MANUAL_CLOSED","INVALID"}: continue
        if r.get("manual_closed_at") or r.get("closed_at"): continue
        if status not in {"WAITING_ENTRY","ACTIVE","TP1_HIT","TP2_HIT"}: continue
        side=r["side"]
        # Always use internal_symbol for API; fall back to symbol for legacy rows
        api_sym=r.get("internal_symbol") or r["symbol"]
        try: p=price(api_sym)
        except Exception: continue
        if not p: continue
        now=datetime.now(timezone.utc).isoformat(timespec="seconds")
        sl=float(r["sl"]); tp1=float(r["tp1"]); tp2=float(r["tp2"]); tp3=float(r["tp3"])
        if status=="WAITING_ENTRY":
            if side=="LONG" and p<=sl:
                r.update(status="SL_HIT", result_r=-1, entry_hit_at=now, entry_hit_price=r.get("entry_low"), closed_at=now, close_price=p)
                notes.append(note_sl_fast(r,p)); changed=True; continue
            if side=="SHORT" and p>=sl:
                r.update(status="SL_HIT", result_r=-1, entry_hit_at=now, entry_hit_price=r.get("entry_high"), closed_at=now, close_price=p)
                notes.append(note_sl_fast(r,p)); changed=True; continue
            if hit_entry(r,p):
                r.update(status="ACTIVE", entry_hit_at=now, entry_hit_price=p)
                notes.append(note_hit_entry(r,p)); changed=True
        if r.get("status") in {"ACTIVE","TP1_HIT","TP2_HIT"}:
            if side=="LONG":
                if p<=sl:
                    r.update(status="SL_HIT", result_r=-1, closed_at=now, close_price=p); notes.append(note_sl(r,p)); changed=True; continue
                if p>=tp3:
                    r.update(status="TP3_HIT", result_r=1.8 if r.get("tp1_hit_at") else 2.6, closed_at=now, close_price=p); notes.append(note_tp(r,p,"TP3","1.8" if r.get("tp1_hit_at") else "2.6",True)); changed=True; continue
                if r.get("status")!="TP2_HIT" and p>=tp2:
                    r.update(status="TP2_HIT", result_r=1.4 if r.get("tp1_hit_at") else 1.8, tp2_hit_at=now, last_price=p); notes.append(note_tp(r,p,"TP2","1.4" if r.get("tp1_hit_at") else "1.8")); changed=True; continue
                if r.get("status")=="ACTIVE" and p>=tp1:
                    r.update(status="TP1_HIT", result_r=0.5, tp1_hit_at=now, last_price=p, tp1_take_profit_pct=50, sl_current=(r.get("entry_hit_price") or r.get("entry_mid")), sl_moved_to_be_at=now); notes.append(note_tp(r,p,"TP1","0.5")); changed=True; continue
            else:
                if p>=sl:
                    r.update(status="SL_HIT", result_r=-1, closed_at=now, close_price=p); notes.append(note_sl(r,p)); changed=True; continue
                if p<=tp3:
                    r.update(status="TP3_HIT", result_r=1.8 if r.get("tp1_hit_at") else 2.6, closed_at=now, close_price=p); notes.append(note_tp(r,p,"TP3","1.8" if r.get("tp1_hit_at") else "2.6",True)); changed=True; continue
                if r.get("status")!="TP2_HIT" and p<=tp2:
                    r.update(status="TP2_HIT", result_r=1.4 if r.get("tp1_hit_at") else 1.8, tp2_hit_at=now, last_price=p); notes.append(note_tp(r,p,"TP2","1.4" if r.get("tp1_hit_at") else "1.8")); changed=True; continue
                if r.get("status")=="ACTIVE" and p<=tp1:
                    r.update(status="TP1_HIT", result_r=0.5, tp1_hit_at=now, last_price=p, tp1_take_profit_pct=50, sl_current=(r.get("entry_hit_price") or r.get("entry_mid")), sl_moved_to_be_at=now); notes.append(note_tp(r,p,"TP1","0.5")); changed=True; continue
    if changed: save(rows)
    if notes: print("\n\n".join(notes))

if __name__=="__main__": main()
