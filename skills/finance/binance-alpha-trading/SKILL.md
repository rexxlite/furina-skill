---
name: binance-alpha-trading
description: read-only binance alpha trading analysis for agents that need to evaluate alpha tokens, scan watchlists, interpret volume/momentum/liquidity, compare binance alpha data with alpha-volume rankings, and produce conditional trading plans. use when the user asks for binance alpha token analysis, alpha volume ranking, breakout/momentum checks, watchlist scoring, or trade-readiness reports using binance rest api market data and https://alpha-volume.vercel.app/. this skill must not execute trades or provide guaranteed-profit claims.
---

# Binance Alpha Trading

## Purpose

Use this skill to analyze Binance Alpha tokens with public market data, alpha-volume rankings, and a consistent technical-analysis workflow. The skill is read-only: collect data, score opportunities, produce watchlists or conditional plans, and refuse to execute trades.

## Default workflow

1. Clarify scope only when needed: single token, top-volume scan, new listings, contract-enabled tokens, tokenized securities, or trading competition tokens.
2. Resolve the Alpha symbol from Binance Alpha token list or exchange info. Alpha symbols can include token IDs such as `ALPHA_175USDT`.
3. Collect public data:
   - Binance Alpha ticker, klines, aggregated trades, token list, or exchange info.
   - Binance Spot market context for BTCUSDT, ETHUSDT, and BNBUSDT when market regime matters.
   - alpha-volume board as a supplemental ranking/volume source.
4. Validate freshness and source quality. Treat Binance as primary. Treat alpha-volume as third-party supplemental data.
5. Score trend, momentum, volume impulse, breakout structure, liquidity, and downside risk using `references/analysis-playbook.md`.
6. Return a concise report in the user's language with stance, data used, key signals, conditional plan, and risk notes.

## Use the bundled analyzer script

Use `scripts/analyze_alpha.py` when you need repeatable candle scoring or when the user provides raw kline/candle data.

Examples:

```bash
python scripts/analyze_alpha.py --symbol ALPHA_175USDT --interval 1h --limit 120 --ticker --pretty
```

```bash
python scripts/analyze_alpha.py --input candles.json --pretty
```

The script performs read-only analysis and outputs JSON including SMA20, EMA12/EMA26, MACD, RSI14, volume ratio versus 20-candle average, breakout reference, invalidation reference, and stance.

## Data-source references

Read `references/binance-alpha-api.md` when choosing endpoints, resolving symbols, or explaining data-source limitations.

Read `references/analysis-playbook.md` when producing a watchlist, trade-readiness score, conditional entry plan, or report.

## Display rule: never show raw `ALPHA_xxx` IDs to the user

Binance Alpha's exchange-info, klines, and ticker endpoints all key off internal IDs like `ALPHA_790USDT`. These IDs are meaningless to the user — they need the ticker (e.g. `BSB`).

Rules for any output that reaches the user (signals, monitor alerts, daily reports, watchlists):

- Always resolve `alphaId → ticker` via `/bapi/defi/v1/public/wallet-direct/buw/wallet/cex/alpha/all/token/list`. Use `cexCoinName` if present, otherwise sanitized uppercase `symbol`.
- Header format: `<TICKER> (<ALPHA_ID>) Alpha — …` so the user sees both the human ticker and the internal ID.
- Persist both `symbol` (ticker) and `alpha_id` in the journal row, plus `internal_symbol` (e.g. `ALPHA_790USDT`) for API calls.
- Use `internal_symbol` for every Binance Alpha API call (klines, ticker, monitor). Never call the API with the human ticker.
- Add a legacy fallback: if `symbol` in an old journal row starts with `ALPHA_`, treat it as missing ticker and fall back to `alpha_id` for display.

See `scripts/binance_alpha_signal_scanner.py`'s `alpha_token_map()` and `display_label(r)` helpers in the monitor/daily report scripts as the reference implementation.

## Trading and safety rules

- Never place orders, sign requests, withdraw funds, or call private account endpoints from this skill.
- Do not ask for API keys unless the user explicitly changes the scope to authenticated account review. Public Alpha analysis does not need keys.
- If the user asks to execute a trade, state that this skill is analysis-only and provide a conditional checklist instead.
- Never claim certainty, guaranteed profit, or risk-free trades.
- Always include stale-data and liquidity caveats when data is incomplete.
- Always include a short risk notice: "Bukan nasihat finansial; gunakan position sizing dan konfirmasi manual."

## Output style

For Indonesian users, write in Bahasa Indonesia and keep the report actionable.

For the user's **Binance Alpha** Telegram topic, this topic is specifically for **automatic trading signals for coins that exist on Binance Alpha**. Use the same text structure as Automatic Signal, not the old watchlist-only format:

```md
## <SYMBOL> Alpha — SETUP <LONG/SHORT>

- Source: Binance Alpha / alpha-volume | TF: <timeframes>
- Price: <current price at signal>
- Reason: <short confluence reason>
- Entry: <planned entry area/range>
- SL: <structural invalidation>
- TP1: <level> | TP2: <level> | TP3: <level>
- RR: <R values>

**Best Call:** <concise execution note; note if entry is a planned limit area>
**Invalid if:** <clear invalidation>

Journal ID: `<id>`
```

Rules for automatic Binance Alpha signals:

- Only screen coins that are present in Binance Alpha / alpha-volume source.
- Use public read-only market data only; never execute trades.
- Signal must include entry area, SL, TP1/TP2/TP3, RR, invalidation, and journal ID.
- If data is incomplete or liquidity is poor, stay silent for scheduled scans.
- Do not claim guaranteed listing/profit.
- Always include: "Bukan nasihat finansial; gunakan position sizing dan konfirmasi manual."