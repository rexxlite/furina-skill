#!/usr/bin/env python3
"""Daily evaluator + report for Automatic Signal journal.

Behavior change requested by user:
- Don't show entry / SL / TP in the daily report.
- Show only RR and PnL percentage per position.
- Include both closed positions in the last 24h AND positions still open right now.
- Provide a combined total percentage = sum of closed % + sum of unrealized % on open positions.
"""
from __future__ import annotations
import json, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE="https://fapi.binance.com"
JOURNAL=Path.home()/".hermes"/"trading_journals"/"automatic_signal_journal.json"
EXPIRY_HOURS=18


def get_json(path, params=None, timeout=15):
    url=BASE+path
    if params: url += "?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url, headers={"User-Agent":"Hermes-Furina-Journal/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def load():
    if not JOURNAL.exists(): return []
    try: return json.loads(JOURNAL.read_text())
    except Exception: return []

def save(rows):
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    JOURNAL.write_text(json.dumps(rows, indent=2, ensure_ascii=False))

def ms(dt): return int(dt.timestamp()*1000)
def parse(s): return datetime.fromisoformat(s.replace("Z","+00:00"))


def klines(symbol, start_dt, end_dt):
    rows=get_json("/fapi/v1/klines", {"symbol":symbol,"interval":"5m","startTime":ms(start_dt),"endTime":ms(end_dt),"limit":1000})
    return [{"t":int(k[0]),"h":float(k[2]),"l":float(k[3]),"c":float(k[4])} for k in rows]


def mark_price(symbol):
    try:
        return float(get_json("/fapi/v1/ticker/price", {"symbol":symbol})["price"])
    except Exception:
        return None


def update_trade(r, now):
    if r.get("status") in {"TP3_HIT","SL_HIT","INVALID","CLOSED","MANUAL_CLOSED"}: return r
    if r.get("manual_closed_at"): return r
    created=parse(r["created_at"])
    try: candles=klines(r["symbol"], created, now)
    except Exception as e:
        r["last_eval_error"]=str(e); return r
    side=r["side"]; elo=float(r["entry_low"]); ehi=float(r["entry_high"]); sl=float(r["sl"])
    tp1=float(r["tp1"]); tp2=float(r["tp2"]); tp3=float(r["tp3"]); entry=float(r.get("entry_mid") or ((elo+ehi)/2))
    touched_entry = r.get("status") == "ACTIVE" or any(c["l"]<=ehi and c["h"]>=elo for c in candles)
    if not touched_entry:
        if now-created > timedelta(hours=EXPIRY_HOURS):
            r["status"]="INVALID"; r["closed_at"]=now.isoformat(timespec="seconds"); r["result_r"]=0; r["note"]="expired before entry"
        return r
    if r.get("status") == "WAITING_ENTRY":
        r["status"]="ACTIVE"; r["entry_filled_at"]=now.isoformat(timespec="seconds")
    risk = abs(entry-sl)
    best_status=r.get("status","ACTIVE"); result=None; closed=False; ambiguous=False
    for c in candles:
        if side=="LONG":
            hit_sl=c["l"]<=sl; hit1=c["h"]>=tp1; hit2=c["h"]>=tp2; hit3=c["h"]>=tp3
        else:
            hit_sl=c["h"]>=sl; hit1=c["l"]<=tp1; hit2=c["l"]<=tp2; hit3=c["l"]<=tp3
        if hit_sl and (hit1 or hit2 or hit3): ambiguous=True
        if hit3:
            best_status="TP3_HIT"; result=round(0.5*abs(tp1-entry)/risk + 0.5*abs(tp3-entry)/risk, 2); closed=True; break
        if hit2: best_status="TP2_HIT"; result=round(0.5*abs(tp1-entry)/risk + 0.5*abs(tp2-entry)/risk, 2)
        elif hit1 and best_status not in {"TP2_HIT"}:
            best_status="TP1_HIT"; result=round(0.5*abs(tp1-entry)/risk, 2)
            r["tp1_take_profit_pct"]=50; r["sl_current"]=entry
        if hit_sl:
            if result is None: result=-1.0
            best_status="SL_HIT_AFTER_TP" if result and result>0 else "SL_HIT"
            closed=True; break
    r["status"]=best_status
    if result is not None: r["result_r"]=round(result,2)
    if closed: r["closed_at"]=now.isoformat(timespec="seconds")
    if ambiguous: r["sequence_note"]="5m candle ambiguity: TP/SL touched in same candle; result uses conservative sequential estimate."
    return r


def closed_pct(r):
    """Realized percentage from entry to close.

    Priority: compute from entry + close_price (most reliable). If close_price missing,
    fall back to TP/SL trigger price based on status. Only use manual_close_pnl_pct as
    last resort because historical entries had it stored incorrectly for some SL hits.
    """
    entry = r.get("entry_hit_price") or r.get("entry_mid")
    close = r.get("close_price")
    if close is None:
        status = r.get("status")
        if status == "TP3_HIT": close = r.get("tp3")
        elif status == "TP2_HIT": close = r.get("tp2")
        elif status == "TP1_HIT": close = r.get("tp1")
        elif status in ("SL_HIT","SL_HIT_AFTER_TP"): close = r.get("sl")
    if entry is None or close is None:
        if r.get("manual_close_pnl_pct") is not None:
            try: return float(r["manual_close_pnl_pct"])
            except Exception: pass
        return None
    try:
        e=float(entry); c=float(close)
    except Exception:
        return None
    if e == 0: return None
    pct=(c-e)/e*100
    if r.get("side")=="SHORT": pct=-pct
    return pct


# Symbols that aren't real crypto (stocks, commodities, indices) - excluded from report
NON_CRYPTO = {"AMDUSDT","MSTRUSDT","XAGUSDT","XAUUSDT","COINUSDT","HOODUSDT","NVDAUSDT","TSLAUSDT","AAPLUSDT"}


def short_name(symbol):
    """Strip USDT/USD suffix and the 1000-prefix for display."""
    s = symbol
    for suf in ("USDT","USDC","USD"):
        if s.endswith(suf): s = s[:-len(suf)]; break
    if s.startswith("1000"): s = s[4:]
    return s or symbol


def open_pct(r, price):
    if price is None: return None
    entry = r.get("entry_hit_price") or r.get("entry_mid")
    if entry is None: return None
    try: e=float(entry)
    except Exception: return None
    if e == 0: return None
    pct=(price-e)/e*100
    if r.get("side")=="SHORT": pct=-pct
    return pct


def fmt_pct(p):
    if p is None: return "-"
    sign="+" if p>=0 else ""
    return f"{sign}{p:.2f}%"


def fmt_r(r):
    v=r.get("result_r")
    if v is None or v=="manual_close": return "-"
    try: v=float(v)
    except Exception: return str(v)
    sign="+" if v>=0 else ""
    return f"{sign}{v:.2f}R"


def main():
    now=datetime.now(timezone.utc)
    rows=load()
    if not rows:
        print("## Automatic Signal — Daily Report\n\nBelum ada sinyal yang tercatat di jurnal.")
        return
    for r in rows: update_trade(r, now)
    save(rows)

    # Window starts at the most recent 07:00 WIB reset (00:00 UTC). The user wants the daily report
    # to reset every day at 07:00 WIB, so signals closed before today's reset are not re-listed.
    today_reset = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if now < today_reset:
        today_reset -= timedelta(days=1)
    since=today_reset

    # Final closed states only — TP1_HIT/TP2_HIT are partial closes that remain open
    closed_states={"TP3_HIT","SL_HIT","SL_HIT_AFTER_TP","INVALID","MANUAL_CLOSED","CLOSED"}
    closed_recent=[]
    for r in rows:
        if r.get("symbol") in NON_CRYPTO: continue
        if r.get("status") not in closed_states and not r.get("manual_closed_at"): continue
        ts_str=r.get("closed_at") or r.get("manual_closed_at") or r.get("created_at")
        try: ts=parse(ts_str)
        except Exception: continue
        if ts >= since:
            closed_recent.append(r)

    open_rows=[r for r in rows if r.get("status") in {"WAITING_ENTRY","ACTIVE","TP1_HIT","TP2_HIT"} and not r.get("manual_closed_at") and not r.get("closed_at") and r.get("symbol") not in NON_CRYPTO]
    # Drop WAITING_ENTRY from "open positions" PnL since user is only counting actual exposure
    active_rows=[r for r in open_rows if r.get("status") in {"ACTIVE","TP1_HIT","TP2_HIT"}]

    closed_lines=[]; total_closed_pct=0.0; total_win_pct=0.0; total_loss_pct=0.0; total_r=0.0; wins=0; losses=0
    for r in closed_recent:
        pct=closed_pct(r)
        if pct is not None:
            total_closed_pct += pct
            if pct >= 0: total_win_pct += pct
            else: total_loss_pct += pct  # negative
        rr=r.get("result_r")
        try:
            rrf=float(rr) if rr not in (None,"manual_close") else 0
            total_r += rrf
            if rrf>0: wins+=1
            elif rrf<0: losses+=1
        except Exception: pass
        closed_lines.append(f"- {short_name(r['symbol'])} {r['side']} | {r.get('status')} | RR: {fmt_r(r)} | PnL: {fmt_pct(pct)}")

    open_lines=[]; total_open_pct=0.0
    for r in active_rows:
        price=mark_price(r["symbol"])
        pct=open_pct(r, price)
        if pct is not None: total_open_pct += pct
        # estimated R = pct% of position / risk% of position. Use INITIAL SL so post-TP1 BE
        # doesn't create absurd RR estimates when sl_current == entry.
        est_r=None
        try:
            entry=float(r.get("entry_hit_price") or r.get("entry_mid"))
            sl=float(r.get("sl"))
            if entry and sl and entry!=sl and pct is not None:
                risk_pct=abs(entry-sl)/entry*100
                if risk_pct>0: est_r=pct/risk_pct
        except Exception: pass
        est_r_str=f"{'+' if (est_r or 0)>=0 else ''}{est_r:.2f}R" if est_r is not None else "-"
        open_lines.append(f"- {short_name(r['symbol'])} {r['side']} | {r.get('status')} | RR est: {est_r_str} | PnL est: {fmt_pct(pct)}")

    valid_count=len([r for r in closed_recent if r.get("status")!="INVALID"])
    winrate=(wins/valid_count*100) if valid_count else 0
    avg_r=(total_r/valid_count) if valid_count else 0
    net_pct = total_win_pct + total_loss_pct  # win is +, loss is -
    combined_pct = total_closed_pct + total_open_pct

    # WIB display window (UTC+7)
    wib_now = now + timedelta(hours=7)
    wib_since = since + timedelta(hours=7)
    date_label = wib_now.strftime("%d %B %Y")

    lines=[
        f"## Automatic Signal — Daily Report — {date_label}",
        "",
        f"Window: {wib_since.strftime('%d %b %Y %H:%M WIB')} → {wib_now.strftime('%d %b %Y %H:%M WIB')}",
        "",
        "**Ringkasan Utama**",
        f"- Closed sejak reset: {len(closed_recent)} (Win {wins} / Loss {losses})",
        f"- Open/active sekarang: {len(active_rows)} (waiting entry: {len(open_rows)-len(active_rows)})",
        f"- Winrate (closed valid): {winrate:.1f}%",
        f"- Net RR closed: {total_r:+.2f}R | Avg RR: {avg_r:+.2f}R",
        "",
        "**Performa Persentase Gabungan**",
        f"- Win total: {fmt_pct(total_win_pct)}",
        f"- Loss total: {fmt_pct(total_loss_pct)}",
        f"- Net (Win - Loss): {fmt_pct(net_pct)}",
        f"- Open est total: {fmt_pct(total_open_pct)}",
        f"- **Combined total: {fmt_pct(combined_pct)}**",
        "",
        "**Hasil Closed (sejak reset)**",
    ]
    if closed_lines:
        lines.extend(closed_lines)
    else:
        lines.append("- Tidak ada posisi closed sejak reset 07:00 WIB.")
    lines.append("")
    lines.append("**Posisi Open Sekarang**")
    if open_lines:
        lines.extend(open_lines)
    else:
        lines.append("- Tidak ada posisi active.")
    lines.append("")
    lines.append("**Trade Hari Ini (ringkas)**")
    quick_lines=[]
    for r in closed_recent:
        if r.get("status")=="INVALID": continue
        pct=closed_pct(r)
        if pct is None: continue
        quick_lines.append(f"- {short_name(r['symbol'])}: {fmt_pct(pct)}")
    for r in active_rows:
        price=mark_price(r["symbol"])
        pct=open_pct(r, price)
        if pct is None: continue
        quick_lines.append(f"- {short_name(r['symbol'])}: {fmt_pct(pct)} (open)")
    if quick_lines:
        lines.extend(quick_lines)
    else:
        lines.append("- Belum ada trade.")
    lines.append("")
    lines.append("_Edukasi/analisis, bukan jaminan profit._")
    print("\n".join(lines))


if __name__=="__main__": main()
