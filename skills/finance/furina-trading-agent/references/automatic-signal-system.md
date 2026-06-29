# Automatic Signal System Pattern

Use this pattern when the user wants automated crypto trading signals delivered to a Telegram topic with journal/report tracking.

## Durable design

- Prefer a deterministic scanner script for high-frequency screening instead of asking the LLM to inspect all symbols every run.
- Let the script be silent when no setup passes filters; this prevents Telegram noise.
- Use Binance USDⓈ-M Futures API (`https://fapi.binance.com`) for perpetual symbols, klines, 24h quote volume, funding/premium, and OI where needed.
- Keep LLM analysis for explaining shortlisted setups or evolving the strategy, not for scanning hundreds of pairs every 15 minutes.

## Scanner risk profiles (multi-mode)

The scanner is parameterized by `--mode {aggressive|medium|safe}` and the same script handles all three. Each mode has a `MODES[mode]` dict with TF chain, indicator gates, score threshold, RR floor, max risk, TP multiples, volume floor, cooldown, and label/icon. The journal records the actual `risk_model` per signal so reports can split per mode.

### ⚡ Aggressive

- TF chain: `15m → 30m → 1h` (first match wins), context TF `1h`
- Indicators: EMA20/50, RSI14, ATR14, volume ratio, structure (breakout/breakdown-retest), close_pos
- Score threshold: ≥ 6/7. Volume floor 24h: $8M. Volume ratio min: 1.25×.
- RSI gates: LONG 45–78, SHORT 22–55. BTC bias: soft (block only if extreme opposite).
- TP multiples: 1.0R / 1.8R / 2.6R. Min RR to TP2: 1.5. Max risk: 3.5%. Cooldown: 8h.
- Cron: `*/15 * * * *`.
- Use this mode for momentum scalping. Many signals/day, more invalidations expected.

### 🔹 Medium

- TF chain: `1h → 4h`, context TF `4h`
- Adds: **ADX(14) ≥ 20** (Wilder's), **MACD histogram aligned** (bullish & rising for LONG; bearish & falling for SHORT)
- Score threshold: ≥ 7/9. Volume floor 24h: $20M. Volume ratio min: 1.4×.
- RSI gates: LONG 50–72, SHORT 28–50. BTC bias: hard gate (no LONG vs bearish BTC, no SHORT vs bullish BTC).
- TP multiples: 1.0R / 2.0R / 3.2R. Min RR to TP2: 2.0. Max risk: 2.5%. Cooldown: 16h.
- Cron: `5,35 * * * *` (offset to avoid overlapping with the aggressive scanner's `*/15` runs).
- Use this mode for swing setups. 2–6 signals/day in normal markets.

### 🛡️ Safe

- TF chain: `4h → 1D`, context TF `1D`
- Adds: **multi-TF EMA alignment** (15m + 1h + 4h must all be aligned the same direction), **ADX ≥ 25**, **BB width sanity** (reject squeeze < 2% and exhaustion > 18%)
- Score threshold: ≥ 8/12. Volume floor 24h: $40M. Volume ratio min: 1.3×.
- RSI gates: LONG 50–65, SHORT 35–50. BTC bias: hard gate on **both 1H and 1D** (the daily bias must also not contradict).
- TP multiples: 1.0R / 2.5R / 4.0R. Min RR to TP2: 2.5. Max risk: 1.5%. Cooldown: 24h.
- Cron: `10 */2 * * *` (every 2h, minute 10 — multi-TF data fetch is heavy).
- Use this mode for position trades. 0–2 signals/day, sometimes zero for days in choppy markets. **Do not loosen filters when SAFE goes silent**; silence is the design.

### 🔄 Counter-Trend (added 2026-06-05)

- TF chain: `1h → 4h`, context TF `4h`
- **LONG-only** — no shorts. Designed to catch oversold bounces during market crashes.
- **Ignores BTC bias** — explicitly allows LONG when BTC is bearish (the whole point is counter-trend)
- **Oversold gate**: requires RSI < 30 + (BB %B < 0.15 OR volume spike ≥ 1.5×)
- **Scoring**: RSI deeply oversold (<15) +3, RSI oversold (<22) +2, BB below lower band +2, bullish divergence +2, crash condition +1, MACD turning up +1, context TF oversold +1
- Score threshold: ≥ 6/10. Volume floor 24h: $15M. Volume ratio min: 1.5×.
- **BB width check disabled** (`use_bb_width: False`) — crash conditions produce BBW > 18% which blocks signals. Uses `bb_pct_b()` instead.
- TP multiples: 0.8R / 1.5R / 2.2R (quick profit taking — bounce trades)
- Max risk: 3.0%. Cooldown: 6h.
- Entry: tight zone near current price (±0.05-0.15×ATR), SL below recent low (0.5×ATR below entry)
- Cron: `9,24,39,54 * * * *` (offset from other scanners)
- Wrapper: `automatic_signal_scanner_counter_trend.py`
- Use this mode during crashes when BTC bearish + alt RSI < 30. Other modes will be silent (longs blocked by BTC bias, shorts blocked by oversold RSI).
- **Risk/em pitfall**: In crashes, recent_low can be far below current price. Combined with wide ATR, risk/em can exceed max_risk. Mitigated by tight SL (0.5×ATR) and increased max_risk (3%).

### Helper functions unique to counter-trend

```python
def bb_pct_b(closes, n=20, k=2):
    """Position within Bollinger Bands. 0 = at lower, 1 = at upper, <0 = below lower."""
    bb = bb_width(closes, n, k)
    if not bb: return None
    upper, middle, lower, _ = bb
    width = upper - lower
    if width == 0: return 0.5
    return (closes[-1] - lower) / width

def bullish_divergence(closes, lookback=20):
    """Price makes lower low but RSI makes higher low = bullish divergence."""
    # Swing-low detection with 2-bar confirmation each side
    # Returns True if last two swing lows show price_lower_low + rsi_higher_low
```

### BTC bias gating override

Counter-trend mode has a special BTC bias gate that bypasses the normal `btc_bias_hard` logic:

```python
if mode_cfg.get("counter_trend_mode"):
    allowed_long = True      # counter-trend explicitly IGNORES BTC direction
    allowed_short = False     # counter-trend is LONG-only
elif mode_cfg["btc_bias_hard"]:
    # ... normal medium/safe gating
else:
    # ... normal aggressive gating
```

### Implementation notes

- Run the same `automatic_signal_scanner.py` with different `--mode` flags rather than maintaining three forks. Mode-specific configuration lives in a single `MODES = {...}` dict.
- Journal row id prefix carries the mode: `AS-AGG-...`, `AS-MED-...`, `AS-SAF-...`. The `risk_model` field is set from the mode flag, so monitor / daily report can group results per mode.
- Cooldowns are per-mode but shared in one journal: a symbol that emitted on Aggressive can still emit on Medium/Safe later because the risk profile and entry are different. This is intentional.
- Output format: every signal uses the 7-layer screening template (see main SKILL.md → "7-Layer Screening Signal Template"). Header gets a mode badge (⚡/🔹/🛡️/🔄) plus the 7-layer report with pass/fail icons.

### Critical bug fix: `mode` variable scope in setup_for() (2026-06-05)

When adding counter-trend mode, a latent bug was discovered: `apply_enhancements(mode=mode)` at line ~819 of `setup_for()` referenced a bare `mode` variable that only exists as a local in `main()`. Since `setup_for()` is a module-level function, it cannot access `main()`'s locals — this caused a `NameError`. The error was **silently swallowed** by the `try/except Exception: continue` in the scan loop's inner iteration, making signals that passed ALL checks vanish without any error output.

This bug affected ALL modes (aggressive, medium, safe) but was invisible because:
1. No signals were generated during the 3-day BTC crash period
2. The error only manifests when a signal actually reaches the enhancements block

**Fix:** Replace `mode=mode` with `mode=mode_cfg.get("label", "unknown").lower().replace("-", "_")`. This derives the mode name from the config dict (which IS a function parameter) instead of relying on an out-of-scope variable.

**Lesson:** When `setup_for()` or any module-level function needs data from `main()`, pass it as a parameter or derive it from existing parameters. Never rely on `main()` locals being accessible. The `try/except Exception: continue` pattern in the scan loop makes this class of bug especially dangerous — it converts hard errors into silent signal loss.

Do not remove risk controls entirely: aggressive means more permissive screening, not random signals.

## Crypto-only universe filter via exchangeInfo

Binance lists tokenized stocks/ETFs/commodities as USDT perpetuals. They are tagged in `/fapi/v1/exchangeInfo` with:

- `contractType = "TRADIFI_PERPETUAL"` (vs `"PERPETUAL"` for crypto)
- `underlyingType = "EQUITY" | "COMMODITY" | "INDEX"` (vs `"COIN"` for crypto)
- `underlyingSubType` containing `"TradFi"` or `"Index"`

The exchangeInfo filter is the **primary** crypto-only gate; `EXCLUDE_SYMBOLS` is just defense-in-depth for edge cases:

```python
info = get_json("/fapi/v1/exchangeInfo")
meta = {s["symbol"]: s for s in info.get("symbols", []) if s.get("status") == "TRADING"}

def is_crypto(sym):
    m = meta.get(sym)
    if not m:
        return sym not in EXCLUDE_SYMBOLS  # fallback when metadata missing
    if m.get("contractType") not in {"PERPETUAL"}: return False
    if m.get("underlyingType") not in {"COIN"}: return False
    subs = set(m.get("underlyingSubType") or [])
    if subs & {"TradFi", "Index"}: return False
    return True
```

Apply this in BOTH the scanner and any other Binance-perp-touching cron (large prints, volume breakout, market cap move). When a new tokenized stock pair appears (e.g. SNDK, CRCL, CL appeared 2026-05), the exchangeInfo filter catches it automatically — no code change needed.

## Scanner pitfalls

### btc_bias_hard flag is misleading (aggressive vs medium/safe)

The aggressive mode config has `btc_bias_hard: False` with comment "block only if extreme opposite", but the actual code has IDENTICAL bias gating in both branches — `allowed_long = btc_bias != "bearish"` and `allowed_short = btc_bias != "bullish"`. The `btc_bias_hard` flag ONLY adds behavior for Safe mode (which has `use_multi_tf_align=True`), where it gates on both 1H AND daily bias. For aggressive and medium, longs are always blocked when BTC is bearish regardless of the flag. Do not tell the user "aggressive has softer BTC bias gating" — it does not.

This means prolonged silence when BTC is bearish + alts are bullish is expected: longs blocked by BTC bias, shorts fail because alts are trending up. See `references/scanner-silence-diagnostics.md` for the full diagnostic workflow.

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

The user explicitly does not want entry, SL, or TP levels in the daily report. Only RR + percentage per row.

**2026-05-28: Paper sections removed.** The daily report now shows ONLY real Binance perp execution data. The old "Paper Signal Result", "Paper Closed", "Paper Open Sekarang" sections are eliminated. The script reads from `automatic_signal_real_journal.json` and only displays rows where `executor.status` is active/closed.

Stale entries in `automatic_signal_journal.json` with `executor.status in (None, 'NONE')` must be invalidated before the daily report runs — otherwise they create phantom "open" positions that were never actually submitted to Binance. Bulk invalidation pattern:

```python
for r in data:
    if r.get("status") in {"ACTIVE", "TP1_HIT", "TP2_HIT", "WAITING_ENTRY"}:
        exec_info = r.get("executor", {})
        if not exec_info or exec_info.get("status") in (None, "NONE"):
            r["status"] = "INVALID"
            r["invalidated_reason"] = "no_executor_never_filled"
            r["closed_at"] = now_iso()
```

The summary section must include:
- Closed sejak reset: count, win count, loss count
- Open/active sekarang + waiting entry count
- Winrate (closed valid)
- Net RR closed | Avg RR
- **Performa Persentase Gabungan** block (MANDATORY — see Daily Report Format in main SKILL.md)

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

- Scanner (Aggressive): `*/15 * * * *`
- Scanner (Medium): `5,35 * * * *` — offset from `*/15` so they don't co-fire
- Scanner (Safe): `10 */2 * * *` — every 2h, multi-TF heavy
- Monitor: `*/5 * * * *`
- Daily report: `0 7 * * *`
- Delivery target format: `telegram:<chat_id>:<thread_id>`

This is more stable and lower-noise than a prompt-only agent job for every scan.

### Pitfall: Binance HTTP 418 "I'm a teapot" + empty-cache stuck

Binance Futures returns HTTP 418 with body `{"code":-1003,"msg":"Way too many requests; IP(...) banned until <unix_ms>"}` when a single IP exceeds the request weight budget. Triggers seen in this environment:

- Hitting `/fapi/v1/ticker/24hr` (heavy ~40 weight) every minute on top of bursts of aggTrade calls
- ThreadPool with 14+ workers fanning out across 200+ symbols simultaneously
- Multiple cron jobs polling Binance Futures within the same minute (large_prints + automatic_signal scanners + volume breakout)

Mitigations to apply in any Binance-touching script:

1. `http_json` retry with backoff on 418/429 — respect `Retry-After` header, cap at 30s.
2. Keep `HTTP_WORKERS` ≤ 6, `MAX_SYMBOLS` ≤ 100 per market per cron tick.
3. Cache `/exchangeInfo` and `/ticker/24hr` results for 30 minutes; do not refetch every tick.
4. Stagger cron schedules across the minute (`*/15`, `5,35`, `10 */2`) so different jobs don't co-fire on the same Binance IP within the same second.

**Empty-cache stuck pattern (large_prints v1 bug, 2026-05-15):** if the symbol-list fetch fails during a ban, an empty list `[]` got stored into the cache. The next tick's stale-check looked at the timestamp (still fresh), saw "not stale", and reused the empty list — silently scanning zero symbols indefinitely. Fix: treat empty rows as stale, and on refetch, fall back to the previous good cache instead of overwriting with empty:

```python
has_empty = any(len(rows) == 0 for rows, _ in cached.values())
stale = (not cached or has_empty or any(now - r[1] > REFRESH for r in cached.values()))
if stale:
    out = {m: fetch_top_symbols(m) for m in markets}
    for market, rows in out.items():
        if not rows and market in cached and cached[market][0]:
            out[market] = cached[market][0]   # keep previous good cache
            continue
        upsert_cache(market, rows)
```

After resolving any 418, verify recovery by hitting a single small endpoint like `/fapi/v1/ticker/price?symbol=BTCUSDT` (HTTP 200 + JSON body) before re-running the full scan.

## Post-SL learning protocol

The user expects every SL on Automatic Signal / Binance Alpha to be analyzed, and any extractable lesson to be encoded as scanner code, monitor code, or skill update — not just narrated in chat. Workflow:

1. Read the journal record for the SL'd symbol (entry, SL, status transitions, technique, reason).
2. Pull the actual klines around entry/SL from the appropriate Binance API to verify what really happened (was it a wick stop-hunt, a structural failure, a stocks-shaped symbol that shouldn't have been emitted, an artefact bug, etc.).
3. Classify: scanner false positive, monitor bug, market structure surprise, or correct loss within expected SL distribution.
4. If scanner false positive → patch the scanner with a concrete filter and add the case to "Scanner pitfalls" above.
5. If monitor bug → patch the monitor and add the case to "Monitor pattern" above.
6. If correct loss → no patch, but record the case in this references file under a "noted losses" section if a pattern emerges across multiple SLs.

The user said: "setiap ada setup sl kamu otomatis pelajarin kesalahan kamu agar tidak mengulangnya lagi" — treat post-SL learning as a standing instruction, not a one-off.
