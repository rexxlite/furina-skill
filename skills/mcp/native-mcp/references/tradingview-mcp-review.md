# tradingview-mcp Review Notes

Use when the user asks to review/install `atilaahmettaner/tradingview-mcp` or similar third-party trading MCP servers.

## Repo Summary

- GitHub: `https://github.com/atilaahmettaner/tradingview-mcp`
- PyPI package: `tradingview-mcp-server`
- Entrypoint: `tradingview-mcp`
- Language: Python, MIT license
- Purpose: MCP server for market/trading analysis.

## Main Capabilities Observed

Tools discovered during `hermes mcp test tradingview`: 27, including:

- `top_gainers`, `top_losers`
- `bollinger_scan`, `rating_filter`
- `coin_analysis`
- `consecutive_candles_scan`, `advanced_candle_pattern`
- `volume_breakout_scanner`, `volume_confirmation_analysis`, `smart_volume_scanner`
- `multi_timeframe_analysis`, `multi_agent_analysis`
- `market_sentiment`, `financial_news`, `combined_analysis`
- `backtest_strategy`, `compare_strategies`, `walk_forward_backtest_strategy`
- `yahoo_price`, `market_snapshot`

Data sources observed from source:

- `tradingview-ta`
- `tradingview-screener`
- Yahoo Finance service
- Reddit JSON API sentiment service
- RSS feeds: CoinDesk, CoinTelegraph, Reuters business/company feeds

## Safety Review Pattern

Before installing third-party MCP servers, inspect first and summarize before making changes:

1. Read README and package metadata (`pyproject.toml`, package scripts, dependencies).
2. Inspect server entrypoint and registered MCP tools.
3. Search source for risky patterns: `subprocess`, `os.system`, `eval`, `exec`, destructive filesystem calls, credential handling.
4. Check whether API keys/secrets are required.
5. Prefer disabling MCP sampling for untrusted/third-party servers unless the user explicitly wants server-initiated LLM calls.
6. Only after review looks acceptable, configure the server.

## Known-Good Hermes Config

```yaml
mcp_servers:
  tradingview:
    command: /root/.local/bin/uvx
    args:
      - --from
      - tradingview-mcp-server
      - tradingview-mcp
    timeout: 120
    connect_timeout: 120
    sampling:
      enabled: false
```

`connect_timeout: 120` helps first-run `uvx` installs. The server supports stdio by default.

## Verification

```bash
hermes mcp list
hermes mcp test tradingview
```

A successful test should connect over stdio and discover the tools. Existing running Hermes/Gateway sessions may need `/reload-mcp` or restart before the tools appear in conversation.

## Caveats

- The project is third-party and not necessarily official TradingView infrastructure.
- Treat output as an analysis aid, not a guaranteed trading signal.
- Network/API availability and public-source rate limits may affect results.
