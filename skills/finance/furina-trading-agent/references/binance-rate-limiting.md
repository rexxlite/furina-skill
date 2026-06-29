# Binance Rate Limiting for Scanner Scripts

## HTTP Status Codes

| Code | Meaning | Duration | Action |
|------|---------|----------|--------|
| 200  | OK      | —        | Normal |
| 418  | IP soft ban (I'm a Teapot) | 10–30 min | Stop all calls, wait, or switch IP |
| 429  | Rate limit exceeded | Retry-After header | Honor Retry-After, then resume |
| 403  | IP banned (harder) | Hours | Must switch IP |
| 5xx  | Binance server error | Transient | Retry with backoff |

**Key distinction:** 418 is a **soft IP ban**, not a per-endpoint rate limit. It means Binance's anti-abuse system flagged the IP for too many requests in a short window. ALL endpoints from that IP will return 418 until the ban expires.

## Weight Budget

Binance USDⓈ-M Futures uses a weight system:
- `GET /fapi/v1/klines` → weight 1
- `GET /fapi/v1/ticker/24hr` (all symbols) → weight 40
- `GET /fapi/v1/ticker/24hr?symbol=X` → weight 1
- `GET /fapi/v1/exchangeInfo` → weight 1
- `GET /fapi/v1/depth?limit=100` → weight 2
- `GET /fapi/v1/depth?limit=1000` → weight 20

Limit: ~2400 weight/min per IP (undocumented, varies).

## Scanner Call Patterns (Current)

### Aggressive Mode (15m/30m/1h)
- `max_symbols = 50` (reduced from 100 on 2026-06-01)
- Per symbol: 2 klines calls (signal TF + context TF) + 1 ticker/24hr call = 3 calls
- 3 timeframes scanned (15m → 30m → 1h, stops on first signal)
- Worst case: 50 × 3 × 3 = 450 calls, all sequential
- Weight: ~450 × 1 = 450 weight (OK for budget, but burst pattern triggers 418)

### Medium Mode (1h/4h)
- `max_symbols = 80`
- Per symbol: 2 klines + 1 ticker = 3 calls
- 2 timeframes
- Worst case: 80 × 3 × 2 = 480 calls

### Safe Mode (4h/1D)
- `max_symbols = 60`
- Per symbol: 2 klines + 1 ticker + 3 extra klines (15m/1h/4h for MTF align) = up to 6 calls
- 2 timeframes
- Worst case: 60 × 6 × 2 = 720 calls

### Counter-Trend Mode (1h/4h, oversold bounce)
- `max_symbols = 60`
- Per symbol: 2 klines + 1 ticker = 3 calls
- 2 timeframes
- Worst case: 60 × 3 × 2 = 360 calls
- Cron offset: `9,24,39,54 * * * *` (staggered from other scanners)

## Why Sequential urllib Triggers 418

The scanner uses `urllib.request.urlopen()` in a tight loop — no delay between calls. Binance sees:
1. 50+ requests in <5 seconds from same IP
2. Pattern repeats every 15 minutes
3. Anti-abuse system flags IP → 418

The retry logic makes it worse: on 418, the script retries with backoff (1s, 2s, 4s, 8s), adding 15s per failed symbol. With 50 symbols, that's potentially 750s of retry wait → 120s cron timeout.

## Mitigations

### Quick fix: Add inter-call delay
```python
import time
# After each symbol's API calls:
time.sleep(0.15)  # 150ms between symbols → ~50 symbols in ~8s
```

### Better fix: Async with token bucket (batch-execution-patterns skill)
Convert to `aiohttp` + `TokenBucket(rate_per_sec=20, capacity=30)` + `Semaphore(10)`.

### Nuclear option: Proxy rotation
Use multiple exit IPs via proxy list. Not yet implemented.

## Diagnostic Commands

```bash
# Check if IP is currently banned
curl -s -o /dev/null -w "%{http_code}" https://fapi.binance.com/fapi/v1/ping
# 200 = OK, 418 = banned, 000 = network/proxy issue

# Check 9router proxy (does NOT proxy Binance — for other services only)
curl -s -o /dev/null -w "%{http_code}" --proxy http://localhost:20128 https://fapi.binance.com/fapi/v1/ping
# 000 = proxy doesn't forward to Binance (expected)

# Time a single API call
time curl -s https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT\&interval=15m\&limit=120 > /dev/null
```

## Cron Job Schedule Overlap (2026-06-01 lesson)

Multiple `no_agent=true` cron jobs running at the same minute all hit Binance API simultaneously, causing `-1003` rate limit errors even when each individual script is lightweight. This is a separate vector from the scanner burst pattern above — it affects the always-on monitoring/alerting layer, not just scanners.

**Problem pattern:** Jobs with `*/5 * * * *`, `* * * * *`, and fixed `0 H * * *` all converge at `:00`, `:05`, `:10`, etc. At each convergence point, 6+ Binance API clients fire requests within the same 1-2 second window.

**Fix: Stagger all Binance-hitting cron jobs so no two share the same minute.**

Current staggered schedule (applied 2026-06-01):

| Minute(s) | Job | Frequency |
|-----------|-----|-----------|
| `:01/:06/:11/...` | Binance REAL Risk Manager | */5min |
| `:02/:07/:12/...` | Binance REAL Reconciler | */5min |
| `:03/:08/:13/...` | Binance Perp Funding Alert | */5min |
| `:04/:14/:24/...` | Spot Paper Risk Manager | */5min |
| `:09/:19/:29/...` | Auto-Learn Postmortem | */5min |
| `:05` | Binance Top Volume Signal | hourly |
| `:42` | Binance Top Volume Hourly | every 3h |
| `:13` | Top Gainers & Losers | every 6h |
| `:15/:45` | Volume Breakout Alert | */30min |
| `:07` | Auto Signal Daily Report | daily |
| `:23` | Alpha Daily Report | daily |
| `:41` | Spot Paper Daily Report | daily |
| `:17` | Macro Calendar Alert | daily |
| `:31` | Market Asia | daily |
| `:44` | Market Europe | daily |
| `:19` | Market US | daily |

**User preference (2026-06-01):** Randomize minute offsets to avoid predictable traffic patterns. Don't cluster at `:00` or `:05`. When adding new Binance-hitting cron jobs, pick a minute not already used.

**Pitfall:** `* * * * *` (every minute) scripts like `binance_large_prints.py` and `price_alert_checker.py` still hit `:00` along with everything else — but they're lightweight (single API call each). The real danger is the `*/5min` cluster. If every-minute scripts cause issues, consider merging them into a single script that batches calls.

## Affected Cron Jobs

| Job | Script | Schedule | max_symbols |
|-----|--------|----------|-------------|
| `c0873b287577` | aggressive | */15 min | 50 |
| `dd9e1f27f04d` | medium | 5,35 * * * * | 80 |
| `8e51594b30d8` | safe | 10 */2 * * * | 60 |
| `5c9d39b5f895` | counter_trend | 9,24,39,54 * * * * | 60 |
| `639ab0dd265e` | binance_alpha | */15 min | varies |
