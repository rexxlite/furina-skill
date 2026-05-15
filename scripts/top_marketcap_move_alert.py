#!/usr/bin/env python3
"""Alert when top market-cap crypto assets move >= +/-1% on 4h or 1d.

Silent when no new alerts. Designed for Hermes no_agent cron.
"""
import json
import os
import time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.parse import urlencode

STATE_PATH = os.path.expanduser("~/.hermes/state/top_marketcap_move_alert_state.json")
COINGECKO = "https://api.coingecko.com/api/v3/coins/markets"
BINANCE_FAPI = "https://fapi.binance.com"
THRESHOLD = 1.0
TOP_N = 10  # interpret user request "top 10% marketcap" as top 10 market-cap crypto assets
TIMEFRAMES = ["4h", "1d"]

# CoinGecko IDs that commonly differ from ticker symbols or are not Binance USDT perps.
SYMBOL_OVERRIDES = {
    "staked-ether": "ETH",
    "wrapped-bitcoin": "BTC",
}


def get_json(url, params=None, timeout=12):
    if params:
        url = url + "?" + urlencode(params)
    req = Request(url, headers={"User-Agent": "HermesMarketAlert/1.0"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def load_state():
    try:
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, sort_keys=True)
    os.replace(tmp, STATE_PATH)


def get_top_marketcap():
    data = get_json(COINGECKO, {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": TOP_N,
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "24h",
    })
    coins = []
    for c in data:
        base = SYMBOL_OVERRIDES.get(c.get("id"), (c.get("symbol") or "").upper())
        if not base or base in {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE"}:
            continue
        coins.append({
            "name": c.get("name"),
            "base": base,
            "symbol": base + "USDT",
            "market_cap_rank": c.get("market_cap_rank"),
            "market_cap": c.get("market_cap"),
        })
    return coins


def futures_symbol_exists(symbol):
    try:
        get_json(BINANCE_FAPI + "/fapi/v1/ticker/price", {"symbol": symbol})
        return True
    except Exception:
        return False


def kline_change(symbol, interval):
    kl = get_json(BINANCE_FAPI + "/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": 1})[0]
    open_time = int(kl[0])
    open_price = float(kl[1])
    high = float(kl[2])
    low = float(kl[3])
    close = float(kl[4])
    change = (close - open_price) / open_price * 100.0
    return {
        "open_time": open_time,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "change": change,
    }


def fmt_num(x):
    if x >= 1000:
        return f"{x:,.2f}"
    if x >= 1:
        return f"{x:.4f}".rstrip("0").rstrip(".")
    return f"{x:.8f}".rstrip("0").rstrip(".")


def main():
    state = load_state()
    alerts = []
    source_note = "CoinGecko top market cap + Binance USDT-M Futures klines"
    try:
        coins = get_top_marketcap()
    except Exception as e:
        print(f"Top MarketCap Move Alert: data tidak tersedia — CoinGecko gagal: {e}")
        return

    for coin in coins:
        symbol = coin["symbol"]
        if not futures_symbol_exists(symbol):
            continue
        for tf in TIMEFRAMES:
            try:
                d = kline_change(symbol, tf)
            except Exception:
                continue
            chg = d["change"]
            if abs(chg) < THRESHOLD:
                continue
            direction = "UP" if chg >= THRESHOLD else "DOWN"
            key = f"{symbol}:{tf}:{d['open_time']}:{direction}"
            if state.get(key):
                continue
            state[key] = int(time.time())
            alerts.append((coin, tf, d, direction))

    # prune old state > 3 days
    cutoff = int(time.time()) - 3 * 86400
    state = {k: v for k, v in state.items() if int(v) >= cutoff}
    save_state(state)

    if not alerts:
        return  # silent

    now = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M UTC+7")
    lines = [
        "## MarketCap Move Alert",
        f"Time: {now}",
        "Trigger: top market-cap crypto | TF 4H/1D | move ≥ ±1%",
        "",
    ]
    up = [a for a in alerts if a[3] == "UP"]
    down = [a for a in alerts if a[3] == "DOWN"]

    def append_group(title, icon, items):
        if not items:
            return
        lines.append(f"**{icon} {title}**")
        for coin, tf, d, _ in items:
            sign = "+" if d["change"] > 0 else ""
            rank = coin.get("market_cap_rank") or "?"
            lines.extend([
                f"- **{coin['symbol']}** | Rank: #{rank} | TF: {tf.upper()}",
                f"  Move: **{sign}{d['change']:.2f}%**",
                f"  Price: {fmt_num(d['close'])}",
                f"  Range: {fmt_num(d['low'])} – {fmt_num(d['high'])}",
            ])
        lines.append("")

    append_group("Move Up", "🟢", up)
    append_group("Move Down", "🔴", down)

    # Keep output clean for Alert Market: no source/footer/trading note.
    print("\n".join(lines).rstrip())


if __name__ == "__main__":
    main()
