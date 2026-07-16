# Scanner Performance by Trading Session

Technique for evaluating whether a scanner's edge is session-dependent. Use when a scanner's SL cluster correlates with time-of-day, or when diagnosing whether a scanner is "structurally broken" vs "wrong session for its style".

## When to run this

- A scanner has an SL streak but only during certain hours (user flags "London jelek", etc.)
- Deciding whether to add a session filter (blunt skip during bad hours) vs a logic fix
- Evaluating a counter-trend scanner that might be getting trampled in trending sessions
- Periodic scanner health check (weekly/monthly)

## The technique — income API + journal cross-reference

Two data sources combined:

1. **Binance income API** (`/fapi/v1/income`) — gives per-event REALIZED_PNL with precise UTC timestamps. Ground truth for what actually closed and when.
2. **Journal** (`automatic_signal_real_journal.json`) — gives scanner bucket attribution (`executor.bucket` / `risk_model`) and net PnL per closed trade (`executor.real_net_pnl_usdt`).

The income API alone doesn't tell you which scanner a trade came from. The journal alone may miss trades or have stale PnL. Cross-reference: use the journal for bucket attribution, income API for timestamp precision if needed.

## Session windows (UTC → WIB)

Crypto perps trade 24/7, but institutional hours cluster liquidity:

- **Asia**: 00:00-08:00 UTC (07:00-15:00 WIB) — choppy, lower volume, counter-trend friendly
- **London pure**: 08:00-13:00 UTC (15:00-20:00 WIB) — Europe open, trend starts forming
- **London+US overlap**: 13:00-16:30 UTC (20:00-23:30 WIB) — peak hours, most trending/volatile
- **US pure**: 16:30-21:00 UTC (23:30-04:00 WIB) — US afternoon, trend continuation or reversal
- **Off-hours**: 21:00-24:00 UTC (04:00-07:00 WIB) — thin

WIB = UTC+7. Adjust if the user's timezone changes.

## Script — per-session breakdown by close time

```python
import json
from datetime import datetime, timezone, timedelta
WIB = timezone(timedelta(hours=7))

j = json.load(open('/root/.hermes/trading_journals/automatic_signal_real_journal.json'))
closed = [r for r in j if r.get('status') in ('SL_HIT','TP1_HIT','TP2_HIT','TP3_HIT','SL_HIT_BE','MANUAL_CLOSED','CLOSED') and r.get('closed_at')]

def session(h, m):
    t = h + m/60
    if 0 <= t < 8:   return 'Asia'
    if 8 <= t < 13:  return 'London_pure'
    if 13 <= t < 16.5: return 'London+US_overlap'
    if 16.5 <= t < 21: return 'US_pure'
    return 'Off'

stats = {}
for r in closed:
    ca = r.get('closed_at', '')
    try:
        dt = datetime.fromisoformat(ca.replace('Z', '+00:00')).astimezone(WIB)
    except Exception:
        continue
    s = session(dt.hour, dt.minute)
    ex = r.get('executor') or {}
    pnl = ex.get('real_net_pnl_usdt') or 0
    bucket = ex.get('bucket') or r.get('risk_model', '?')
    d = stats.setdefault(s, {'n': 0, 'wins': 0, 'pnl': 0.0, 'sl': 0, 'buckets': {}})
    d['n'] += 1
    d['wins'] += 1 if pnl > 0 else 0
    d['pnl'] += pnl
    if r.get('status') == 'SL_HIT': d['sl'] += 1
    d['buckets'][bucket] = d['buckets'].get(bucket, 0) + 1

for s in ['Asia', 'London_pure', 'London+US_overlap', 'US_pure', 'Off']:
    d = stats.get(s)
    if not d: continue
    wr = 100 * d['wins'] / d['n'] if d['n'] else 0
    bk = ', '.join('%s:%d' % (k, v) for k, v in sorted(d['buckets'].items(), key=lambda x: -x[1])[:3])
    print('  %-20s | N=%2d | WR=%3.0f%% | pnl=%+8.3f | SLs=%d | %s' % (s, d['n'], wr, d['pnl'], d['sl'], bk))
```

**To isolate one scanner**: add `if ex.get('bucket') != 'OI_DIV': continue` inside the loop. Compare the target scanner's per-session WR vs the all-scanner baseline to see if it's session-structural or scanner-specific.

## Interpretation guide

| Pattern | Meaning | Action |
|---|---|---|
| Scanner WR roughly equal across sessions | No session dependency | Look elsewhere for the edge problem |
| Counter-trend scanner (OI_DIV, LIQ, COU) bad in London+US overlap, good in Asia/US-pure | Structural — counter-trend gets trampled in trending peak hours | Session filter OR bias gate (prefer bias gate — it adapts to regime, session filter is blunt) |
| Trend-following scanner bad in Asia, good in London+US | Structural — trend needs liquidity to form | Session filter is reasonable here |
| All scanners bad in one session | Market regime that day, not structural | Don't patch scanners — wait for regime change |
| One scanner bad everywhere | Scanner edge is gone | 2-week eval → remove cron (precedent: RANGE_MR, BREAKOUT_RT) |

## Key insight — counter-trend vs peak hours (2026-06-29)

OI_DIV (counter-trend: fades crowd via OI/price divergence) per-session WR over 3 days, 62 closed trades:

- Asia (choppy): WR 62%, +$7.41
- London pure: WR 44%, −$0.77
- **London+US overlap (trending): WR 42%, −$10.67** ← structurally bad
- US pure (choppy again): WR 73%, +$9.31
- Off-hours: WR 60%, +$3.65

Counter-trend scanners need choppy/sideways conditions to fade extremes. Peak hours (London+US overlap) are when trends form and run — exactly when fading fails. This is NOT a bug in OI_DIV; it's the scanner's nature. The fix is a bias gate (block counter-trend when macro trend is clear) rather than a blunt session filter, because the bias gate adapts when BTC regime flips.

## Pitfalls

- **Sample size.** 3 days / 12 trades per session is small. A session can look bad from one BTC regime. Confirm with 7-14 days before treating a session as structurally bad.
- **Close-time vs entry-time — and which to lead with.** This script buckets by CLOSE time. A trade entered in Asia can close in London. For entry-time analysis, swap `closed_at` for `created_at` / `entry_hit_at`. Both views are useful — close-time shows when PnL realized, entry-time shows when the signal fired.
- **WORKFLOW LESSON (learned 2026-06-29): when diagnosing TODAY's SL streak, lead with ENTRY-time analysis of TODAY's trades only.** Do NOT lead with a 3-day aggregate by close-time and recommend a session filter from that. The 3-day close-time aggregate can show a session (e.g. London+US overlap 20-23:30 WIB) as worst, but TODAY's SLs may have been entered in a completely different window (e.g. 10:00-17:00 WIB). A session filter placed on the aggregate-worst session would not have prevented today's losses. Concrete incident: Furina recommended blocking 20-23:30 WIB based on 3-day close-time data; user pushed back ("kan trade minus yang tadi siang dan sore?"); re-analysis by entry-time showed 7 of 8 SLs today were entered in 10:00-17:00 WIB (Asia + London pure), zero in 20-23:30. The recommendation was wrong. The correct diagnosis was OI_DIV LONG vs BTC 1D downtrend (not session-dependent), which the 1D bias gate addresses. **Lesson: for today's streak, pull today's entries by `submitted_at`/`created_at` first. Use the multi-day aggregate only for structural questions, not for today's fix.**
- **WIB conversion.** Always convert UTC → WIB before bucketing, or the session windows shift. The user reads WIB.
- **Don't session-filter prematurely.** A session filter is a blunt instrument that kills signal volume. Try a bias gate or threshold bump first — they adapt to regime. Reserve session filters for cases where the structural mismatch is confirmed over 2+ weeks and logic fixes didn't work.
