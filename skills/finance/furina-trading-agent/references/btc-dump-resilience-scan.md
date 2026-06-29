# BTC Dump Resilience Scan

## Overview

Workflow for identifying which altcoins held up (or gained) during a BTC crash. Useful for:
- Building a watchlist of strong relative performers
- Identifying coins with independent buyer conviction
- Finding accumulation candidates during market-wide selloffs
- Post-dump recovery trade setups

## When to Use

- User asks "coin mana yang tidak ikut dump?" / "yang kuat saat BTC jatuh"
- User wants to find resilient altcoins after a BTC crash
- Post-crash recovery analysis / watchlist building
- Comparing altcoin performance during a specific BTC drawdown period

## Architecture

```
1. Define BTC dump period (e.g., June 1-2 open→close)
2. Fetch all USDT Spot pairs from Binance (ticker/24hr, filter >$1M volume)
3. Fetch 2 daily klines per symbol for the dump period (startTime/endTime)
4. Calculate total_change = (dump_close - dump_open) / dump_open * 100
5. Categorize: GREEN (up), RESILIENT (dump < BTC), CRASHED (dump > BTC)
6. Sort and report with volume context
```

## Implementation Pattern

```python
import json, urllib.request, time
from datetime import datetime

# 1. Define dump period timestamps
START = int(datetime(2026, 6, 1).timestamp() * 1000)
END = int(datetime(2026, 6, 4).timestamp() * 1000)  # +1 day for safety

# 2. Get all USDT pairs with volume > $1M
# PITFALL: ticker/24hr is large — save to file, not inline parse
urllib.request.urlretrieve(
    "https://api.binance.com/api/v3/ticker/24hr",
    "/tmp/tickers.json"
)
with open("/tmp/tickers.json") as f:
    tickers = json.load(f)

# Stablecoins and wrapped tokens to skip
SKIP = {'USDCUSDT', 'USD1USDT', 'FDUSDUSDT', 'TUSDUSDT', 'DAIUSDT',
        'BUSDUSDT', 'USDPUSDT', 'PYUSDUSDT', 'AEURUSDT', 'EURUSDT',
        'GBPUSDT', 'BFUSDUSDT', 'WBETHUSDT', 'STETHUSDT', 'WBTCUSDT',
        'BETHUSDT', 'PAXGUSDT'}

symbols = [t['symbol'] for t in tickers
           if t['symbol'].endswith('USDT')
           and t['symbol'] not in SKIP
           and float(t.get('quoteVolume', 0)) > 1_000_000]

# 3. Fetch klines per symbol — sequential with delay
results = []
for sym in symbols:
    try:
        url = (f"https://api.binance.com/api/v3/klines?"
               f"symbol={sym}&interval=1d&startTime={START}&endTime={END}&limit=3")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        if len(data) >= 2:
            j1_open = float(data[0][1])
            j2_close = float(data[1][4])
            total_change = ((j2_close - j1_open) / j1_open) * 100
            j1_change = ((float(data[0][4]) - j1_open) / j1_open) * 100
            j2_change = ((j2_close - float(data[1][1])) / float(data[1][1])) * 100
            vol_usd = float(data[0][5]) * float(data[0][4]) + float(data[1][5]) * j2_close
            results.append({
                "symbol": sym,
                "j1_change": j1_change,
                "j2_change": j2_change,
                "total_change": total_change,
                "vol_usd": vol_usd,
                "price": j2_close
            })
        time.sleep(0.05)  # 50ms delay to avoid burst
    except Exception:
        pass

# 4. Categorize
btc_change = -9.38  # BTC's own total_change for the period
results.sort(key=lambda x: x["total_change"], reverse=True)

green = [r for r in results if r["total_change"] > 0]
resilient = [r for r in results if btc_change < r["total_change"] <= 0]
crashed = [r for r in results if r["total_change"] <= btc_change]
```

## Pitfalls

- **Wrong year timestamps:** `datetime(2025, 6, 1)` instead of `datetime(2026, 6, 1)` produces completely different data with no error. Always verify system year first.
- **Interval case:** Use `1d` not `1D` for daily klines. Binance rejects uppercase D.
- **ticker/24hr size:** ~200KB response. Must save to file then `json.load()`. Inline `terminal()` parsing truncates and fails.
- **Sequential with delay:** 197+ symbols × 50ms ≈ 10 seconds. Acceptable. Parallel is faster but risks 418 IP ban when combined with other API calls in the same session.
- **Volume filter matters:** Without the >$1M volume filter, you get hundreds of illiquid micro-cap pairs with meaningless price changes.
- **Stablecoin exclusion:** Pairs like USDCUSDT, USD1USDT show ~0% change and pollute the resilient category.

## Output Categories

| Category | Definition | Signal |
|----------|-----------|--------|
| 🟢 GREEN | Total change > 0% | Independent buyer conviction, watchlist candidate |
| 🟡 RESILIENT | 0% ≥ change > BTC change | Held up better than BTC, relative strength |
| 🔴 CRASHED | Change ≤ BTC change | Dumped as hard or harder than BTC |

## Interpretation Guide

- **GREEN with high volume** ($50M+) = strongest conviction. Large caps holding green during BTC dump is rare and significant.
- **GREEN with low volume** (<$10M) = could be thin-orderbook noise. Cross-check with order book depth.
- **RESILIENT large caps** = defensive rotation targets. Money flowing from BTC into these.
- **CRASHED but recovering fast** = potential bounce trades but higher risk.
- **CRASHED with high volume** = genuine panic selling, avoid catching knives.

## Example Output Format (Telegram)

```
🟢 34 coins naik saat BTC dump -9.4%

🏆 Top picks (volume > $50M):
- ZEC +7.2% ($462M vol)
- NEAR +13.2% ($327M vol)
- WLD +9.3% ($235M vol)
- ENA +7.2% ($64M vol)

🟡 Resilient (dump < BTC): 105 coins
🔴 Crashed (dump > BTC): 58 coins
Worst: ALLO -37.6%
```
