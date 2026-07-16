# Smart Money Wallets — Furina Subsystem

The cron job `Smart Money Move — Birdeye top traders ETH+Base` runs every 15 minutes and alerts Telegram thread `-100XXXXXXXXXX:1549` ("smart money move") when a top-PnL on-chain trader buys a non-stable token with significant USD volume on Ethereum or Base.

## Architecture: dual backend, Birdeye-primary

- **Primary:** `~/.hermes/scripts/smart_money_alerter_birdeye.py` — auto-discovers top traders via Birdeye `/trader/gainers-losers` and pulls their swaps via `/trader/txs/seek_by_time`. No manual wallet list needed.
- **Fallback:** `~/.hermes/scripts/smart_money_alerter.py` — polls a curated wallet list via Etherscan V2 (ETH only on free tier) + Blockscout (Base, no key). Use this when Birdeye rate-limits exhaust or for specific wallets the user wants to follow that aren't in the leaderboard.

The active cron job points to the Birdeye script. Switch by editing the cron's `script` field (`cronjob action='update'`).

## Files

- `~/.hermes/scripts/smart_money_alerter_birdeye.py` — primary alerter (Birdeye)
- `~/.hermes/scripts/smart_money_alerter.py` — fallback alerter (curated list)
- `~/.hermes/data/smart_money_wallets.json` — wallet list config (only used by fallback)
- `~/.hermes/data/smart_money_state.db` — SQLite state (recent_buys, alert_cooldown, trader_meta, scan_state). Shared by both backends.
- `~/.hermes/secrets/smart_money.env` — `BIRDEYE_API_KEY=...` + `ETHERSCAN_API_KEY=...` + optional `GMGN_API_KEY=...` (chmod 600)

## Birdeye API plan

Free Standard tier: 1 req/sec, ~30k req/month. Current cron config:

- 10 traders × 2 chains × 96 ticks/day = 1,920 trader-list calls + ~1,920 trader-tx calls = ~3,840 req/day = ~115k/month
- **This exceeds 30k/month.** Realistic budget is to skip Ethereum scan some ticks, or upgrade plan.

Mitigations available in code:
- `RATE_LIMIT_SLEEP = 1.3` enforces 1.3s between calls
- Script gracefully handles `Too many requests` 429 with backoff and `RATE_LIMIT` exception that aborts the current chain early
- If quota-exhausted, fall back to `smart_money_alerter.py` (curated list, Etherscan-based, no Birdeye)

## Tunables (Birdeye script)

```python
TRADER_PAGE_LIMIT  = 10        # how many top traders per chain per tick
TRADER_TYPE        = "today"   # "today" | "yesterday" | "1W"
TRADER_MIN_PNL     = 25_000.0  # only follow traders with ≥$25k PnL today
TRADER_MIN_TRADES  = 5         # minimum trade count
WINDOW_HOURS       = 6         # rolling aggregation window
MIN_WALLETS        = 1         # ≥1 qualified trader is enough (single-wallet alpha mode)
MIN_TOTAL_USD      = 10_000.0  # but the buys on that token must total ≥$10k
COOLDOWN_HOURS     = 12        # silence per-token after alert
MIN_BUY_USD        = 1_500.0   # ignore individual buys < $1.5k
MAX_TOKENS_PER_RUN = 5         # cap alerts per cron tick
```

## Noise filtering (CRITICAL)

The Birdeye PnL leaderboard surfaces traders who often park USD in yield tokens or rotate wrapped/staked variants. These show up as huge "buys" but carry zero alpha signal. The script blocks them via:

1. **`NOISE_TOKEN_BLOCKLIST`** — explicit address blocklist for known yield/LST/stable tokens (sUSDS, sDAI, rETH, stETH, wstETH, weETH, USDe, sUSDe, USDG, BUSD, FRAX, PYUSD, GUSD, etc.)
2. **`NOISE_SYMBOLS`** — symbol blocklist (SUSDS, SDAI, WSTETH, RETH, USDG, FDUSD, TUSD, FRAX, BUSD, etc.)
3. **`is_noise_symbol()` heuristic** — auto-skips short symbols ending in or starting with "USD" (≤6 chars), catches new stablecoins automatically
4. **Stable-pair requirement** — only counts as a buy when the trader sent stable/native (USDC, WETH, USDT, DAI). Token-to-token swaps are skipped (ambiguous).

**When you spot noise leaking through** (e.g. some new yield token):
1. Add the contract address to `NOISE_TOKEN_BLOCKLIST` (per chain)
2. Add the symbol to `NOISE_SYMBOLS`
3. Both lists are at the top of `smart_money_alerter_birdeye.py`

## Trader labeling

The script auto-labels wallets in `trader_meta` table based on PnL:

- **WHALE** — PnL ≥ $100k today
- **SMART** — PnL ≥ $25k today
- **TRADER** — anything qualifying (≥ $25k base threshold, but below $25k flagged via `TRADER_MIN_PNL` cutoff)

## Vetting a candidate wallet

When the user drops an address and asks whether it qualifies as smart money, run this sequence before touching `smart_money_wallets.json`:

1. **Multi-chain balance + tx-count via Etherscan V2** — check chainids 1 (Ethereum), 42161 (Arbitrum), 137 (Polygon) with free key. `result:"0x0"` on every supported chain = strong disqualifier.
2. **Base coverage via Blockscout** (no key needed) — check `coin_balance`, `has_token_transfers`, `has_logs`.
3. **Birdeye leaderboard presence check** — if wallet is a real top trader, it shows up in `/trader/txs/seek_by_time`.
4. **DeBank profile** — use browser to load `https://debank.com/profile/<addr>`. Check TVF (Time Value of First), total balance, per-chain breakdown.

**Disqualifier checklist** — reject if ANY of these are true:
- TVF < 30 days (fresh wallet, no track record)
- Total balance $0 across all chains
- Zero tx count on Ethereum, Arbitrum, Polygon
- Only activity is testnet or a single airdrop claim
- Not on Birdeye trader leaderboard for any chain
- DeBank shows it as a contract or labeled bridge / router / CEX hot wallet

## Switching backends

```python
# In cron config:
script="smart_money_alerter_birdeye.py"   # primary (auto-discover via Birdeye)
script="smart_money_alerter.py"           # fallback (curated list via Etherscan)
```

Both scripts share the same SQLite DB (`smart_money_state.db`) and write the same alert format, so switching is seamless.

## Maintenance cadence

- **Weekly:** scan recent_buys table for noise leakage. Add new yield/stable tokens to blocklist as they appear.
- **Monthly:** review `trader_meta` table. If a "WHALE" wallet now has neutral PnL, the leaderboard will rotate it out automatically.
- **After every alert:** note in trading journal whether the alert led to a profitable trade.

## Trading and safety rules

- Smart money alerts are **leading indicators**, not buy signals.
- Always cross-reference with technical structure on the entry timeframe before trading.
- Top PnL traders are wrong ~30-40% of the time even on individual entries.
- Always include: "Bukan nasihat finansial; konfirmasi struktur teknikal sebelum entry."
- Never claim guaranteed profit.

## GMGN validation layer

Reference: `references/gmgn-validation.md` documents the GMGN query-only validation layer used to enrich Smart Money Move alerts with trending, smart-money tape, token security, and pool/liquidity context.
