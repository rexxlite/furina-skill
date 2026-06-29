# Bulk Market Scanning via Binance API

## Overview

Pattern for scanning ALL Binance USDT-M perpetual pairs for technical conditions (RSI, BB, momentum, etc.) using parallel API calls. Faster and more reliable than TradingView MCP for bulk screening.

## When to Use

- User asks "berapa pair yang oversold?" / "scan semua pair untuk kondisi X"
- RSI overbought/oversold screening across the full USDT-M universe
- Bulk BB squeeze detection, volume anomaly scanning, momentum screening
- Multi-TF confluence detection (pairs appearing on multiple timeframes)

## Architecture

```
1. Fetch exchangeInfo → get all active USDT-M symbols (~580-600)
2. Parallel download klines via ThreadPoolExecutor(workers=50)
3. Calculate indicator per symbol (RSI, BB, etc.)
4. Filter by condition (e.g., RSI < 30)
5. Sort and report, optionally group by multi-TF confluence
```

## Pitfalls

- **Sequential API calls timeout.** 587 symbols × 1 kline request each = ~10+ minutes sequential. Must use parallel downloads.
- **ThreadPoolExecutor workers=50** is safe for Binance rate limits (1200 req/min weight) when ONLY fetching klines. Each kline request = ~1-5 weight. 50 workers × 587 symbols ≈ 12 batches, completes in ~30-60 seconds.
- **Workers=50 can trigger 418 ban when combined with heavy endpoints.** Adding `ticker/24hr` (high weight) on top of parallel klines in the same session caused a 418 IP ban (2026-06-01). For production cron scripts that also fetch volume rankings, reduce to `workers=20` and add `time.sleep(0.05)` between submissions.
- **Binance HTTP 418 = IP soft ban (10-30 min).** Distinct from 429 (rate limit). When 418 hits, back off 60s and retry. Build retry logic into production scripts: `for i in range(retries): ... if r.status_code in (418,429): time.sleep(60); continue`.
- **TradingView MCP unreliable for bulk scans.** `smart_volume_scanner` with `rsi_range` filter often returns empty for Binance. `coin_analysis` fails with JSON parse errors on Binance exchange. Use direct API instead.
- **execute_code sandbox doesn't have `terminal` function.** Must use `from hermes_tools import terminal` or run via `terminal` tool directly with heredoc.
- **Kline limit=100 is sufficient for RSI-14** (needs 15+ candles minimum, 100 gives enough history for stable EMA-smoothed RSI).

## Script Template — RSI Bulk Scan

```python
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# 1. Get all active USDT-M symbols
r = requests.get('https://fapi.binance.com/fapi/v1/exchangeInfo', timeout=10)
syms = [s['symbol'] for s in r.json()['symbols']
        if s['symbol'].endswith('USDT') and s['status'] == 'TRADING']

# 2. RSI calculator
def calc_rsi(sym, interval='1h', period=14):
    try:
        r = requests.get(
            f'https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval={interval}&limit=100',
            timeout=8
        )
        data = r.json()
        if not isinstance(data, list) or len(data) < period + 1:
            return None
        closes = [float(d[4]) for d in data]
        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i-1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        # EMA-smoothed RSI (Wilder's smoothing)
        ag = sum(gains[:period]) / period
        al = sum(losses[:period]) / period
        for j in range(period, len(gains)):
            ag = (ag * (period-1) + gains[j]) / period
            al = (al * (period-1) + losses[j]) / period
        rs = ag / al if al > 0 else 100
        rsi = 100 - 100 / (1 + rs)
        return (sym, closes[-1], rsi)
    except:
        return None

# 3. Parallel scan
def scan_rsi(interval='1h', threshold=30, direction='below'):
    results = []
    with ThreadPoolExecutor(max_workers=50) as ex:
        futures = {ex.submit(calc_rsi, s, interval): s for s in syms}
        for f in as_completed(futures):
            result = f.result()
            if result:
                _, _, rsi = result
                if direction == 'below' and rsi < threshold:
                    results.append(result)
                elif direction == 'above' and rsi > threshold:
                    results.append(result)
    results.sort(key=lambda x: x[2])
    return results

# 4. Multi-TF confluence
def scan_multi_tf_rsi(threshold=30):
    """Find pairs oversold on multiple timeframes."""
    tf_results = {}
    for tf in ['1h', '4h', '1d']:
        tf_results[tf] = {r[0]: r for r in scan_rsi(interval=tf, threshold=threshold)}

    # Find confluences
    all_pairs = set()
    for tf in tf_results:
        all_pairs.update(tf_results[tf].keys())

    confluences = []
    for sym in all_pairs:
        tfs_present = [tf for tf in tf_results if sym in tf_results[tf]]
        if len(tfs_present) >= 2:
            avg_rsi = sum(tf_results[tf][sym][2] for tf in tfs_present) / len(tfs_present)
            confluences.append((sym, tfs_present, avg_rsi))

    confluences.sort(key=lambda x: x[2])
    return confluences, tf_results
```

## Multi-TF Confluence Interpretation

Pairs appearing oversold on MULTIPLE timeframes simultaneously are stronger reversal candidates:

- **1H + 4H oversold** — short-term momentum exhaustion with medium-term confirmation
- **4H + 1D oversold** — deeper pullback, potential swing/position entry
- **1H + 4H + 1D oversold** — rare, strongest signal (e.g., DRIFT 1H:19.43 + 4H:19.17)

Single-TF oversold is weaker — could be noise on 1H, or extended trend on 1D.

## Other Conditions to Scan

Same pattern works for:
- **BB squeeze**: `BB_width < 0.02` (tight squeeze → breakout imminent)
- **Volume spike**: `volume > 3x 20-period average`
- **RSI overbought**: `RSI > 70`
- **EMA cross**: `EMA20 crosses above EMA50`
- **ATR expansion**: `ATR > 1.5x 20-period ATR average`

Just replace the indicator calculation and filter condition.

## Production Alert Script Pattern

When building a cron-triggered scanner that alerts only on NEW triggers (not repeating the same pairs every run):

### 1. Volume Top N Filtering

Use `ticker/24hr` to rank pairs by 24h quote volume, then take top N. This reduces scan scope and noise:

```python
r = requests.get('https://fapi.binance.com/fapi/v1/ticker/24hr', timeout=10)
tickers = r.json()
usdt = [t for t in tickers if t['symbol'].endswith('USDT')]
usdt.sort(key=lambda x: float(x.get('quoteVolume', 0)), reverse=True)
top_symbols = [t['symbol'] for t in usdt[:100]]  # Top 100 by volume
```

**Pitfall:** `ticker/24hr` for ALL symbols is a heavy endpoint. Fetch it ONCE at script start, not per-symbol.

### 2. Crypto-Only Filter

Exclude tokenized stocks, indices, gold, and forex from scanner output. User explicitly requires pure crypto only (2026-06-01):

```python
NON_CRYPTO = {
    # Gold / commodities
    'XAU', 'XAUT', 'PAXG', 'SILVER', 'OIL',
    # Tokenized stocks
    'AAPL', 'TSLA', 'GOOGL', 'MSFT', 'AMZN', 'META', 'NVDA', 'NFLX', 'AMD',
    'INTC', 'COIN', 'MSTR', 'BA', 'DIS', 'PYPL', 'SQ', 'UBER', 'SHOP',
    'BABA', 'NIO', 'JD', 'PDD', 'LI', 'XPEV', 'PLTR', 'SOFI', 'RIVN',
    'HOOD', 'ABNB', 'DKNG', 'SNAP', 'PINS', 'SPOT', 'U', 'RBLX', 'DASH',
    'ARM', 'SMCI', 'CRWD', 'PANW', 'ZS', 'NET', 'DDOG', 'MDB', 'SNOW',
    'GME', 'AMC',
    # Indices
    'SP500', 'NASDAQ', 'DJI', 'DAX', 'NIKKEI', 'HSI', 'FTSE',
    # Forex
    'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'NZD',
}

crypto = [t for t in usdt if t['symbol'].replace('USDT', '') not in NON_CRYPTO]
```

Apply this filter BEFORE volume ranking so non-crypto pairs don't occupy top-N slots.

### 3. State-Based Dedup (Alert-Only-New Pattern)

For cron alert scripts, track which pairs have already been alerted. Only emit NEW triggers:

```python
STATE_FILE = '/tmp/scanner_state.json'

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

# In main:
old_state = load_state()
new_state = {}
new_triggers = []

for result in scan_results:
    key = f"{result['symbol']}|{result['tf']}"
    new_state[key] = {'rsi': result['rsi'], 'ts': time.time()}
    if key not in old_state:
        new_triggers.append(result)

save_state(new_state)

# Only report if there are new triggers or exited pairs
exited = [k for k in old_state if not k.startswith('_') and k not in new_state]
if not new_triggers and not exited:
    return  # Silent — no output = no Telegram message for no_agent crons
```

**Key behavior:**
- Pair alerted → stays in state → not re-alerted next run
- Pair exits condition → reported as "exited" → removed from state
- Pair re-enters after exiting → alerted again as new trigger
- Heartbeat every 6h (`_heartbeat` key) prevents silent death

### 4. Multi-TF Filter for Alert Scripts

User preference (2026-06-01): require oversold on ≥2 timeframes to reduce noise:

```python
# Collect per-TF results
sym_tfs = {}
for tf_key, results in tf_results.items():
    for r in results:
        sym_tfs.setdefault(r['symbol'], []).append(r)

# Filter: only symbols on ≥2 timeframes
multi_tf = {sym: rs for sym, rs in sym_tfs.items() if len(rs) >= 2}
```

### 5. Cron Job Registration

```python
# In Hermes:
cronjob create \
  --name "RSI Oversold Alert" \
  --schedule "0 * * * *" \
  --script rsi_oversold_scanner.py \
  --no_agent true \
  --deliver "telegram:<chat_id>:<thread_id>"
```

Script field is filename only (no path, no args). `no_agent=true` = zero LLM credits.

### Complete Production Pattern Summary

```
Volume Top N (100) → Crypto-only filter → Parallel RSI scan (workers=20)
→ Multi-TF confluence (≥2) → State dedup → Alert new triggers only
→ Silent on no changes → Heartbeat every 6h
```

This pattern was used for `rsi_oversold_scanner.py` (job `3a541463ebf1`).
