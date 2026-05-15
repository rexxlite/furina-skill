# Automatic Signal System Pattern

Use this pattern when the user wants automated crypto trading signals delivered to a Telegram topic with journal/report tracking.

## Durable design

- Prefer a deterministic scanner script for high-frequency screening instead of asking the LLM to inspect all symbols every run.
- Let the script be silent when no setup passes filters; this prevents Telegram noise.
- Use Binance USDⓈ-M Futures API (`https://fapi.binance.com`) for perpetual symbols, klines, 24h quote volume, funding/premium, and OI where needed.
- Keep LLM analysis for explaining shortlisted setups or evolving the strategy, not for scanning hundreds of pairs every 15 minutes.

## Scanner risk profiles

### Conservative criteria

- Universe: liquid Binance USDT perpetual symbols, excluding stable/stable pairs.
- Timeframes: scalping 5m/15m plus intraday 1h context.
- Trend/structure: 15m and 1h EMA 20/50 alignment, breakout/breakdown or retest near recent structure.
- Momentum: RSI not extremely overextended.
- Volume: current 15m quote volume meaningfully above recent average.
- Risk: structural SL, no chase after oversized candle, RR to TP2 >= 1.5R.
- Cooldown per symbol to avoid repeated duplicate signals.

### Aggressive criteria

Use when the user explicitly asks for aggressive signals or wants more frequent generated signals:

- Expand the universe (lower 24h quote-volume threshold and scan more symbols).
- Shorten cooldown per symbol so fresh setups can recur sooner.
- Allow 15m trend/momentum setups when 1h is not strongly opposing, rather than requiring strict 15m+1h EMA alignment.
- Lower volume confirmation threshold while still requiring some volume/structure evidence.
- Allow wider ATR/risk range, but still reject structurally invalid RR or extreme chase candles.
- Label the signal as `AGGRESSIVE` in the Telegram title and journal row.

Do not remove risk controls entirely: aggressive means more permissive screening, not random signals.

## Scanner pitfalls

### Late short after extended dump (PUMP-style)

Avoid emitting late breakdown shorts after a coin has already dropped sharply intraday and is mid-bounce toward EMA/resistance. These setups look bearish on indicators but are statistically prone to stop-hunt reclaim before continuation.

Concrete filter (paste into the SHORT branch of the scanner before scoring):

```python
if chg24 < -5.0 and r15 < 35 and price > recent_low * 1.012:
    return None
if last["h"] >= e20_15 * 0.995 and last["c"] > last["o"]:
    return None
```

Where `chg24` is the 24h price change percent from `/fapi/v1/ticker/24hr` and `recent_low` is the lowest 15m low in the last 20 candles. Skip the short if a coin is already too late in its move.

### Stocks/commodities/indices listed as USDT perps

Binance lists tokenised stocks/indices/commodities (XAU, XAG, AMD, MSTR, EWY, INTC, NVDA, TSLA, AAPL, MSFT, GOOGL, AMZN, META, SPX, NASDAQ, COIN, HOOD, etc.) as USDT perps. The Automatic Signal topic is crypto-only. Keep an explicit `EXCLUDE_SYMBOLS` set in the scanner AND a `NON_CRYPTO` set in the daily report so legacy non-crypto rows already in the journal are also hidden. Add to both whenever a non-crypto symbol slips through. Treat any new SL post-mortem on a stock-shaped symbol as a signal to extend the exclusion list, not as a strategy issue.

## Binance Alpha display ticker convention

Binance Alpha symbols come in three layers and the system must keep them straight:

1. **Internal API symbol** — `ALPHA_154USDT`, `ALPHA_140USDT`, etc. This is what `fapi`-equivalent Alpha endpoints (`/bapi/defi/v1/public/alpha-trade/...`) accept for klines/ticker. Store as `internal_symbol` on every journal row.
2. **Alpha ID** — `ALPHA_154`, `ALPHA_140`. Useful as a stable join key against the Alpha token list. Store as `alpha_id`.
3. **User-facing ticker** — `SKYAI`, `FHE`, `ZKJ`, `MOG`. This is what the user sees and is the ONLY thing that should appear in signals, monitor alerts, daily reports, or `symbol` field of new journal rows.

The user's standing instruction: never use `ALPHA_xxx` raw IDs in any output. \"Aku gk tau itu pair apa.\"

### Resolving display ticker

Pull the Alpha token list and choose display ticker with this priority:

```python
data = req("/bapi/defi/v1/public/wallet-direct/buw/wallet/cex/alpha/all/token/list")
for t in data:
    aid = t.get("alphaId")
    cex = (t.get("cexCoinName") or "").strip()       # preferred: clean exchange ticker
    raw = (t.get("symbol") or "").strip()             # fallback: raw token name (may be lowercase or have spaces)
    if cex:
        display = cex.upper()                          # SKYAI, ZKJ, AIGENSYN
    elif raw:
        display = "".join(ch for ch in raw.upper() if ch.isalnum())  # 'Freedom of Money' → FREEDOMOFMONEY, 'quq' → QUQ
    else:
        continue
```

Some Alpha tokens have empty `cexCoinName` (e.g. `Mog`, `quq`, `Freedom of Money`). Sanitize to uppercase alphanumeric — never leave spaces or mixed case in `symbol`, because lowercase/space breaks the `r['symbol']` codepath that downstream tooling uses.

### Always call APIs with internal_symbol, never display

The scanner is the only place that looks up the display ticker; once the row is in the journal, **monitor and daily report must call the Alpha API using `internal_symbol`**, not `r['symbol']`:

```python
api_sym = r.get("internal_symbol") or r["symbol"]   # legacy rows fall back to symbol
p = price(api_sym)                                   # not price(r["symbol"])
```

Without this, a row whose `symbol` is `MOG` or `FREEDOMOFMONEY` will hit the Alpha ticker endpoint with a non-tradable identifier and fail silently — the position then never updates and never closes.

### Schema-migration step when changing display convention

When the display convention changes (e.g. switching from raw `ALPHA_xxxUSDT` to ticker), migrate the existing journal in the same session — don't leave stale formats. Match by `alpha_id` (or derive it from a legacy `ALPHA_xxxUSDT` symbol), look up the token map, and rewrite `symbol` + `name` while preserving `internal_symbol`. Verify by running the daily report once after migration and confirming all rows show clean tickers.

## Journal pattern

Store every emitted signal in a persistent journal (JSON/JSONL/SQLite) with at least:

- `id`, `created_at`, `symbol`, `side`
- `timeframe_context`
- `entry_low`, `entry_high`, `entry_mid`
- `sl`, `tp1`, `tp2`, `tp3`
- `initial_rr`, `status`, `invalidation`, `result_r`, `source`

Statuses should include: `WAITING_ENTRY`, `ACTIVE`, `TP1_HIT`, `TP2_HIT`, `TP3_HIT`, `SL_HIT`, `SL_HIT_AFTER_TP`, `INVALID`, `MANUAL_CLOSED`, `CLOSED`.

## Monitor pattern

The monitor cron is the script that watches open journal rows and emits TP/SL/HIT-ENTRY transitions to Hasil Trade.

### Required exclusions to avoid false alerts

The monitor MUST skip any row that has been finalized, even if `status` was set by an out-of-band action (manual close, daily evaluator, user correction):

```python
if r.get("status") in {"SL_HIT","TP3_HIT","CLOSED","MANUAL_CLOSED","INVALID"}: continue
if r.get("manual_closed_at") or r.get("closed_at"): continue
```

Without the second line, a position that was manually closed at profit can later swing back into SL and the monitor will emit a `SL HIT -1R` for a trade that was actually closed at +profit. This happened to XAGUSDT 2026-05-14: TP1+TP2 hit, manual closed at +1.21%, then 24h later harga balik dan monitor kirim "SL HIT -1R" yang menyesatkan.

### Wick-based ENTRY/SL detection on manual setups

For automated scanners the monitor can treat any 15m wick crossing into entry zone as ENTRY_HIT, because the journal only contains setups the scanner believes in. For **manual Crypto-topic setups** journaled at the user's request, this is dangerous: the user may not have actually placed the order. If the user says "entry belum filled" or "kok bisa SL? entry aja belum?", reset the journal status to `MANUAL_REVIEW`, pause the monitor cron, and rely on the user to confirm fills going forward. The OSMO 2026-05-14 case showed this pattern.

### TP3 / TP max full-close note

When a position closes at TP3 (or whichever TP is the max defined for that journal type), the monitor message must say explicitly that the position is fully closed and no further TP/SL monitoring is needed. The user dislikes ambiguity between "TP3 hit but still running" and "TP3 hit and trade is over". Concrete pattern:

```python
full_close_note = "\n- Action: **TP max hit — posisi dianggap FULL CLOSE. Tidak perlu pantau TP/SL lanjutan.**" if closed else ""
# append `{full_close_note}` after the result line in the TP message
```

Apply to every monitor (Automatic Signal monitor, Binance Alpha monitor, etc.).

## Daily report pattern

The daily report is delivered at the user's reset hour (07:00 WIB) to the Hasil Trade topic. It is a fixed format the user has converged on; do not casually change it.

### Window: reset-based, not rolling 24h

The window starts at the most recent 07:00 WIB reset (= 00:00 UTC), not `now - 24h`. A signal closed at 23:00 WIB yesterday must NOT appear in today's report; only signals closed after 07:00 WIB today appear. Concrete:

```python
today_reset = now.replace(hour=0, minute=0, second=0, microsecond=0)  # 00:00 UTC == 07:00 WIB
if now < today_reset:
    today_reset -= timedelta(days=1)
since = today_reset
```

### Bucketing rule for cross-day positions

Positions that opened yesterday and closed today belong to **today's report**, bucketed by `closed_at` (not `created_at`). Always filter `closed_at >= since` for the closed list. Open positions that are still active appear under "Posisi Open Sekarang" with PnL/RR estimates and graduate to closed bucket on the day they actually close.

### Header must include date

The user wants the report headed with the human-readable date and month, not just an ISO timestamp:

```
## Automatic Signal — Daily Report — 14 May 2026

Window: 14 May 2026 07:00 WIB → 14 May 2026 22:38 WIB
```

Generate via `(now + timedelta(hours=7)).strftime("%d %B %Y")` for the header and `%d %b %Y %H:%M WIB` for the window line.

### Required fields, no entry/SL/TP detail

The user explicitly does not want entry, SL, or TP levels in the daily report. Only RR + percentage per row. The summary section must include:

- Closed sejak reset: count, win count, loss count
- Open/active sekarang + waiting entry count
- Winrate (closed valid)
- Net RR closed | Avg RR
- **Performa Persentase Gabungan** block:
  - Win total: sum of all positive PnL%
  - Loss total: sum of all negative PnL% (signed, so it shows as negative)
  - Net (Win - Loss): the algebraic sum
  - Open est total: sum of unrealized PnL% on currently active positions
  - **Combined total**: closed total + open total

The "Net (Win - Loss)" row was a deliberate user request to make total dump magnitude visible alongside total win magnitude. Don't collapse them into a single line.

### "Trade Hari Ini (ringkas)" section

After the detailed Closed/Open lists, append a flat ringkas section that the user can scan in one glance. Format per line: `- <SHORT_TICKER>: ±X.XX%`, with `(open)` suffix on still-active positions. Skip `INVALID` rows. The user gave the literal example `btc: +5%`, so keep it as bare ticker + percent — no side, no status, no RR.

### Display ticker shortening

Strip exchange suffix and notional prefix for display so the report stays readable:

```python
def short_name(symbol):
    s = symbol
    for suf in ("USDT","USDC","USD"):
        if s.endswith(suf): s = s[:-len(suf)]; break
    if s.startswith("1000"): s = s[4:]   # 1000LUNCUSDT → LUNC, 1000PEPEUSDT → PEPE
    return s or symbol
```

Apply this to every line in Closed, Open, and Trade Hari Ini. Keep the raw symbol in the journal — only display is shortened.

### closed_pct must fall back when close_price is missing

Many SL/TP rows have `close_price=None` because the monitor wrote the status but not the close price (or was patched after the fact). Computing PnL purely from `close_price` then shows `PnL: -` for half the table. Use this priority instead:

```python
def closed_pct(r):
    entry = r.get("entry_hit_price") or r.get("entry_mid")
    close = r.get("close_price")
    if close is None:
        st = r.get("status")
        if st == "TP3_HIT": close = r.get("tp3")
        elif st == "TP2_HIT": close = r.get("tp2")
        elif st == "TP1_HIT": close = r.get("tp1")
        elif st in ("SL_HIT","SL_HIT_AFTER_TP"): close = r.get("sl")
    if entry is None or close is None:
        if r.get("manual_close_pnl_pct") is not None:
            try: return float(r["manual_close_pnl_pct"])
            except: pass
        return None
    e=float(entry); c=float(close)
    pct=(c-e)/e*100
    if r.get("side")=="SHORT": pct=-pct
    return pct
```

`manual_close_pnl_pct` is intentionally **last resort**, not first. Historical entries had it stored with wrong sign for some SL hits (XAG showed +1.21% for an SL, AIGENSYN showed +6.50% for an SL). Computing from entry+trigger price is more reliable than trusting that field.

### closed_states must exclude partial-close statuses

`TP1_HIT` and `TP2_HIT` are partial closes — the position is still open in market with a trailed SL. They must NOT appear in the Hasil Closed list, only in Posisi Open. Use:

```python
closed_states = {"TP3_HIT","SL_HIT","SL_HIT_AFTER_TP","INVALID","MANUAL_CLOSED","CLOSED"}
```

Without this, a TP1_HIT row would show up as both Closed (with partial RR) and Open (with current PnL est), double-counting the PnL into Combined total.

### Open RR estimate must use INITIAL SL, not BE SL

Once TP1 hits, the monitor moves `sl_current` to entry/BE. If you compute open RR as `pnl% / abs(entry - sl_current)/entry%`, you get absurd values (e.g. +108R) because the BE risk is near zero. Always use the INITIAL `r['sl']` as the denominator for open RR estimates:

```python
sl = float(r.get("sl"))  # NOT r.get("sl_current") or r.get("sl")
```

## Hermes cron pattern

For robust high-frequency signals, prefer `no_agent=true` script cron jobs that deliver directly to the mapped Telegram topic:

- Scanner schedule: `*/15 * * * *`
- Monitor schedule: `*/5 * * * *`
- Daily report: `0 7 * * *`
- Delivery target format: `telegram:<chat_id>:<thread_id>`

This is more stable and lower-noise than a prompt-only agent job for every scan.

## Post-SL learning protocol

The user expects every SL on Automatic Signal / Binance Alpha to be analyzed, and any extractable lesson to be encoded as scanner code, monitor code, or skill update — not just narrated in chat. Workflow:

1. Read the journal record for the SL'd symbol (entry, SL, status transitions, technique, reason).
2. Pull the actual klines around entry/SL from the appropriate Binance API to verify what really happened (was it a wick stop-hunt, a structural failure, a stocks-shaped symbol that shouldn't have been emitted, an artefact bug, etc.).
3. Classify: scanner false positive, monitor bug, market structure surprise, or correct loss within expected SL distribution.
4. If scanner false positive → patch the scanner with a concrete filter and add the case to "Scanner pitfalls" above.
5. If monitor bug → patch the monitor and add the case to "Monitor pattern" above.
6. If correct loss → no patch, but record the case in this references file under a "noted losses" section if a pattern emerges across multiple SLs.

The user said: "setiap ada setup sl kamu otomatis pelajarin kesalahan kamu agar tidak mengulangnya lagi" — treat post-SL learning as a standing instruction, not a one-off.
