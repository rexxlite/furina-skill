# Trade Calendar — Percentage (PnL %) Display

The unified trading calendar at `/root/calendar_app/` builds `public/trades.json`
from three journals (Automatic Signal, Binance Alpha, Crypto Manual) and is
served via `python3 -m http.server 8765` + a cloudflared quick tunnel. The user
wants **R AND %** displayed together everywhere — per-day cell, monthly stats,
best/worst day, and inside the detail panel.

This file documents how to derive `pnl_pct` and how to surface it in the UI.

## Why derive at build time

The journals only carry `manual_close_pnl_pct` for `MANUAL_CLOSED` rows. For
TP/SL hits the journals carry `result_r` (R-multiple) and the price levels
(`entry_mid`, `tp1`, `tp2`, `tp3`, `sl`) but not a stored % field. Recomputing
at every front-end render is wasteful; we do it once in
`/root/calendar_app/build_unified.py` and cache to `trades.json`.

## Python helpers (drop into builder)

Place above `build()` so each normalized record can call `compute_pnl_pct(rec)`.

```python
def _side_pct(entry, exit_price, side):
    """Compute % PnL given entry, exit, and side (LONG/SHORT)."""
    if entry is None or exit_price is None or not entry:
        return None
    side = (side or "").upper()
    if side == "LONG":
        return (exit_price - entry) / entry * 100.0
    if side == "SHORT":
        return (entry - exit_price) / entry * 100.0
    return None


def compute_pnl_pct(rec):
    """
    Derive pnl_pct for a closed trade based on status + price levels.
    Honours an explicit pnl_pct (from MANUAL_CLOSED) if already set.
    """
    if rec.get("pnl_pct") is not None:
        return rec["pnl_pct"]
    status = rec.get("status") or ""
    entry = rec.get("entry_mid")
    side = rec.get("side")
    if status == "TP3_HIT":
        return _side_pct(entry, rec.get("tp3"), side)
    if status == "TP2_HIT":
        return _side_pct(entry, rec.get("tp2"), side)
    if status == "TP1_HIT":
        return _side_pct(entry, rec.get("tp1"), side)
    if status == "SL_HIT":
        return _side_pct(entry, rec.get("sl"), side)
    if status == "INVALID":
        return 0.0
    return None
```

In `build()` after the bucket-date filter, before sorting:

```python
# derive pnl_pct from price levels for trades that don't already have one
for t in trades:
    t["pnl_pct"] = compute_pnl_pct(t)
```

This MUTATES `pnl_pct` on every trade. For `MANUAL_CLOSED` rows the early
return preserves the stored value (which already has the correct sign for
LONG/SHORT). For TP/SL hits the function fills in a derived %. For
`ACTIVE`/`PENDING` it returns None — important, the front-end uses that to
hide a closed-style % on unrealized positions.

## Front-end (index.html) snippets

### `getDayResult` — extend with `netPct`

```js
function getDayResult(trades) {
  const closed = trades.filter(t => t.bucket_kind === 'closed' && typeof t.result_r === 'number');
  const closedPct = trades.filter(t => t.bucket_kind === 'closed' && typeof t.pnl_pct === 'number');
  const open = trades.filter(t => t.bucket_kind === 'open');
  const pending = trades.filter(t => t.bucket_kind === 'pending');
  const netR = closed.reduce((s, t) => s + (t.result_r || 0), 0);
  const netPct = closedPct.reduce((s, t) => s + (t.pnl_pct || 0), 0);
  const wins = closed.filter(t => t.result_r > 0).length;
  return { closed: closed.length, open: open.length, pending: pending.length,
           netR, netPct, wins, total: trades.length };
}
```

`closed` (R-based) and `closedPct` (%-based) are filtered separately because
some legacy rows have one but not the other. Sum `netPct` additively across
trades — these are independent positions, not a compounded equity curve.

### Per-day cell — center-aligned, symmetric, `tabular-nums`

User correction (2026-05-17): the day cell needs to look symmetric and clean,
not bottom-aligned text. Use a centered column inside the cell with three
short lines: a `WW·LL` win/loss badge (more useful than `Nt`), R, and %.
`tabular-nums` keeps digits aligned across cells so months don't look ragged.

Color rules per the user (after the second iteration on 2026-05-17):

- R uses full emerald-400 / rose-400 (it is the primary metric).
- % uses muted variants (`text-emerald-300/80` / `text-rose-300/80`) so the
  hierarchy is R-first, %-supporting. Do NOT put both in full saturation;
  the eye can't tell which is the headline.
- Source dots get a dark outer ring (`box-shadow: 0 0 0 1.5px rgba(15,23,42,0.85)`)
  so they read clearly against any cell background.

```js
const rColor   = r.netR   > 0 ? 'text-emerald-400'    : r.netR   < 0 ? 'text-rose-400'    : 'text-slate-500';
const pctColor = r.netPct > 0 ? 'text-emerald-300/80' : r.netPct < 0 ? 'text-rose-300/80' : 'text-slate-500';
const rText   = r.closed > 0 ? `${r.netR   >= 0 ? '+' : ''}${r.netR.toFixed(2)}R`  : '';
const pctText = r.closed > 0 ? `${r.netPct >= 0 ? '+' : ''}${r.netPct.toFixed(1)}%` : '';
const wins   = r.closed > 0 ? trades.filter(t => t.bucket_kind === 'closed' && typeof t.result_r === 'number' && t.result_r > 0).length : 0;
const losses = r.closed - wins;
const wlText = r.closed > 0 ? `${wins}W·${losses}L` : `${r.total}t`;
const openBadge = r.open ? `<span class="text-amber-400 ml-0.5">+${r.open}o</span>` : '';

grid.innerHTML += `
  <div class="day-cell ${hasData ? 'has-data' : ''} ${bg} border ${border} rounded-lg aspect-square flex flex-col p-1.5 gap-1" data-date="${key}">
    <div class="flex items-center justify-between">
      <div class="text-[13px] font-bold ${isToday ? 'text-indigo-400' : 'text-slate-200'} leading-none tabular-nums">${d}</div>
      <div class="flex gap-1 items-center">${dots}</div>
    </div>
    ${hasData ? `
      <div class="flex-1 flex flex-col items-center justify-center text-center gap-0.5">
        <div class="text-[10px] text-slate-400 leading-none tabular-nums">${wlText}${openBadge}</div>
        ${rText   ? `<div class="text-[13px] font-bold   ${rColor}   leading-none tabular-nums">${rText}</div>`   : ''}
        ${pctText ? `<div class="text-[10px] font-medium ${pctColor} leading-none tabular-nums">${pctText}</div>` : ''}
      </div>
    ` : '<div class="flex-1"></div>'}
  </div>
`;
```

CSS for the source dot (add once in the page `<style>`):

```css
.source-dot {
  width: 6px; height: 6px; border-radius: 9999px;
  box-shadow: 0 0 0 1.5px rgba(15,23,42,0.85);
}
```

Notes:

- Padding `p-1.5` plus `gap-1` keeps the date+dots row, the centered metric
  block, and the cell edge breathing-friendly.
- Empty cells emit `<div class="flex-1"></div>` so heights stay equal across
  the row even on weeks where some days have no trades.
- `WW·LL` is the user's preferred top-line in the cell (after the 2026-05-17
  redesign); `Nt` count alone was too vague.
- Show `+1.0%` not `+1.00%` in the per-day cell to keep characters under the
  cell width on narrow viewports. Stats row keeps two decimals.

### Stats row — uniform 6 cards, every card 3-line layout

User correction (2026-05-17 second pass): "tambahkan juga persentasenya
diatas dengan kotak baru, perbaiki tampilan trade, rr dan persentase
didalam tanggal, buat lebih baik dan simetris". After splitting Net % into
its own card, the row had 4 single-line cards (Total / WR / Net R / Net %)
and 2 double-line cards (Best / Worst Day) — visually asymmetric and the
single-line cards looked empty.

Fix: every card uses **label / big value / small sub-text** (3 lines) so
heights match. Each card uses `flex flex-col` with the sub-text pinned to
the bottom via `mt-auto pt-1`. All numeric DOMs use `tabular-nums`.

```html
<section class="grid grid-cols-2 md:grid-cols-6 gap-3 mb-6">
  <div class="bg-slate-900 rounded-xl p-4 border border-slate-800 flex flex-col">
    <div class="text-xs text-slate-400">Total Trade</div>
    <div class="text-2xl font-bold mt-1 tabular-nums" id="stat-total">—</div>
    <div class="text-[11px] text-slate-500 mt-auto pt-1" id="stat-total-sub">—</div>
  </div>
  <div class="bg-slate-900 rounded-xl p-4 border border-slate-800 flex flex-col">
    <div class="text-xs text-slate-400">Win Rate</div>
    <div class="text-2xl font-bold mt-1 text-emerald-400 tabular-nums" id="stat-wr">—</div>
    <div class="text-[11px] text-slate-500 mt-auto pt-1" id="stat-wr-sub">—</div>
  </div>
  <div class="bg-slate-900 rounded-xl p-4 border border-slate-800 flex flex-col">
    <div class="text-xs text-slate-400">Net R</div>
    <div class="text-2xl font-bold mt-1 tabular-nums" id="stat-r">—</div>
    <div class="text-[11px] text-slate-500 mt-auto pt-1" id="stat-r-sub">—</div>
  </div>
  <div class="bg-slate-900 rounded-xl p-4 border border-slate-800 flex flex-col">
    <div class="text-xs text-slate-400">Net %</div>
    <div class="text-2xl font-bold mt-1 tabular-nums" id="stat-pct">—</div>
    <div class="text-[11px] text-slate-500 mt-auto pt-1" id="stat-pct-sub">—</div>
  </div>
  <div class="bg-slate-900 rounded-xl p-4 border border-slate-800 flex flex-col">
    <div class="text-xs text-slate-400">Best Day</div>
    <div class="text-lg font-bold mt-1 text-emerald-400 tabular-nums" id="stat-best">—</div>
    <div class="text-[11px] text-slate-400 mt-auto pt-1 tabular-nums" id="stat-best-sub">—</div>
  </div>
  <div class="bg-slate-900 rounded-xl p-4 border border-slate-800 flex flex-col">
    <div class="text-xs text-slate-400">Worst Day</div>
    <div class="text-lg font-bold mt-1 text-rose-400 tabular-nums" id="stat-worst">—</div>
    <div class="text-[11px] text-slate-400 mt-auto pt-1 tabular-nums" id="stat-worst-sub">—</div>
  </div>
</section>
```

Sub-text content (must be meaningful — placeholders like "—" make the row
look unfinished):

| Card        | Big value           | Sub-text                       |
|-------------|---------------------|--------------------------------|
| Total Trade | `94`                | `81 closed · 13 open/pending`  |
| Win Rate    | `40%`               | `32W / 49L`                    |
| Net R       | `+18.52R`           | `avg +0.23R / trade`           |
| Net %       | `+46.76%`           | `avg +0.51% / trade`           |
| Best Day    | `16 · +22.3R`       | `+100.18%`                     |
| Worst Day   | `15 · -8.4R`        | `-30.11%`                      |

Render logic — colour each card's big value by its own sign, set sub-text
via `textContent` (not innerHTML) when the content is plain string:

```js
const closedCount = closed.length;
const losses = closedCount - wins;
document.getElementById('stat-total').textContent = monthTrades.length;
document.getElementById('stat-total-sub').textContent =
  closedCount ? `${closedCount} closed · ${monthTrades.length - closedCount} open/pending` : '—';

document.getElementById('stat-wr').textContent = closedCount ? `${(wins/closedCount*100).toFixed(0)}%` : '—';
document.getElementById('stat-wr-sub').textContent = closedCount ? `${wins}W / ${losses}L` : '—';

const rEl = document.getElementById('stat-r');
rEl.textContent = `${netR >= 0 ? '+' : ''}${netR.toFixed(2)}R`;
rEl.className = 'text-2xl font-bold mt-1 tabular-nums ' + (netR >= 0 ? 'text-emerald-400' : 'text-rose-400');
const avgR = closedCount ? netR / closedCount : 0;
document.getElementById('stat-r-sub').textContent =
  closedCount ? `avg ${avgR >= 0 ? '+' : ''}${avgR.toFixed(2)}R / trade` : '—';

const pctEl = document.getElementById('stat-pct');
pctEl.textContent = `${netPct >= 0 ? '+' : ''}${netPct.toFixed(2)}%`;
pctEl.className = 'text-2xl font-bold mt-1 tabular-nums ' + (netPct >= 0 ? 'text-emerald-400' : 'text-rose-400');
const avgPct = closedPct.length ? netPct / closedPct.length : 0;
document.getElementById('stat-pct-sub').textContent =
  closedPct.length ? `avg ${avgPct >= 0 ? '+' : ''}${avgPct.toFixed(2)}% / trade` : '—';
```

### Best / Worst day — two-line card (R top, % bottom)

Keep the card height matching the rest of the row by stacking, not crowding
on one line:

```js
const dailyR = Object.entries(byDate)
  .filter(([k]) => k.startsWith(monthPrefix))
  .map(([k, v]) => {
    const c    = v.filter(t => t.bucket_kind === 'closed' && typeof t.result_r === 'number');
    const cPct = v.filter(t => t.bucket_kind === 'closed' && typeof t.pnl_pct === 'number');
    return {
      date: k,
      r:   c.reduce((s, t) => s + t.result_r, 0),
      pct: cPct.reduce((s, t) => s + t.pnl_pct, 0),
    };
  }).filter(x => x.r !== 0);

if (dailyR.length) {
  const best  = dailyR.reduce((a, b) => a.r > b.r ? a : b);
  const worst = dailyR.reduce((a, b) => a.r < b.r ? a : b);
  document.getElementById('stat-best').innerHTML  =
    `${best.date.slice(8,10)} · +${best.r.toFixed(1)}R<div class="text-xs text-slate-400 font-normal mt-0.5">+${best.pct.toFixed(2)}%</div>`;
  document.getElementById('stat-worst').innerHTML =
    `${worst.date.slice(8,10)} · ${worst.r.toFixed(1)}R<div class="text-xs text-slate-400 font-normal mt-0.5">${worst.pct.toFixed(2)}%</div>`;
}
```

### Detail panel — summary + per-trade card

Summary line gets a `Net %` clause beside `Net R`:

```js
document.getElementById('detail-summary').innerHTML = `
  <span class="text-slate-300">${r.total} trade</span> ·
  <span class="text-emerald-400">${wins}W</span> /
  <span class="text-rose-400">${losses}L</span>
  ${r.open ? ` · <span class="text-amber-400">${r.open} open</span>` : ''}
  ${r.pending ? ` · <span class="text-slate-400">${r.pending} pending</span>` : ''}
  · Net R: <span class="${r.netR   >= 0 ? 'text-emerald-400' : 'text-rose-400'} font-bold">${r.netR   >= 0 ? '+' : ''}${r.netR.toFixed(2)}R</span>
  · Net %: <span class="${r.netPct >= 0 ? 'text-emerald-400' : 'text-rose-400'} font-bold">${r.netPct >= 0 ? '+' : ''}${r.netPct.toFixed(2)}%</span>
`;
```

Per-trade card displays both R and % side-by-side instead of either-or:

```js
const rParts = [];
if (typeof t.result_r === 'number') {
  const rc = t.result_r > 0 ? 'text-emerald-400' : t.result_r < 0 ? 'text-rose-400' : 'text-slate-400';
  rParts.push(`<span class="${rc} font-bold">${t.result_r > 0 ? '+' : ''}${t.result_r.toFixed(2)}R</span>`);
}
if (typeof t.pnl_pct === 'number') {
  const pc = t.pnl_pct > 0 ? 'text-emerald-400' : t.pnl_pct < 0 ? 'text-rose-400' : 'text-slate-400';
  rParts.push(`<span class="${pc} font-bold">${t.pnl_pct > 0 ? '+' : ''}${t.pnl_pct.toFixed(2)}%</span>`);
}
const resultText = rParts.join(' <span class="text-slate-600">·</span> ');
```

Treat zero as neutral (slate-400) so an `INVALID` `0.00%` doesn't show green.

## Hosting setup (for reference)

- Static files served from `/root/calendar_app/public/` by
  `python3 -m http.server 8765` (PID running in that cwd).
- Public URL via cloudflared quick tunnel:
  `cloudflared tunnel --url http://127.0.0.1:8765 --no-autoupdate`,
  log written to `/var/log/calendar-tunnel.log`. Grep for the
  `https://*.trycloudflare.com` URL there. Quick tunnels are ephemeral —
  on cloudflared restart the URL changes; tail the log for the new one.
- Builder runs every minute via Hermes cron job
  `Trading Calendar — Build unified trades` calling
  `/root/.hermes/scripts/calendar_build_unified.py` (which is the same logic
  as `/root/calendar_app/build_unified.py`).

After editing the builder or HTML, run
`cd /root/calendar_app && python3 build_unified.py` once to refresh
`public/trades.json` immediately instead of waiting for the next cron tick;
the front-end auto-refetches every 60s with a `?t=<timestamp>` cache-bust.

## Verification

Quick sanity test after building:

```bash
python3 -c "
import json
trades = json.load(open('/root/calendar_app/public/trades.json'))
print('total:', len(trades))
print('closed:', sum(1 for t in trades if t['bucket_kind']=='closed'))
print('has result_r:', sum(1 for t in trades if t.get('result_r') is not None))
print('has pnl_pct: ', sum(1 for t in trades if t.get('pnl_pct') is not None))
"
```

`has pnl_pct` should equal the closed count after the derivation step;
`has result_r` may be slightly lower because some `MANUAL_CLOSED` rows store
only `manual_close_pnl_pct` and not an R-multiple.
