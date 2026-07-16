# GMGN Validation Layer for Smart Money Move

Session-specific integration notes for adding GMGN as a secondary validation layer to Furina's Smart Money Move workflow.

## Goal

Use GMGN to enrich Birdeye smart-money alerts, not to auto-trade. Keep Birdeye top-trader discovery as the primary trigger, then add GMGN context to reduce false positives and improve alert quality.

## Credentials

- Generate Ed25519 key pair locally; upload the complete public key including `BEGIN PUBLIC KEY` and `END PUBLIC KEY` lines to `https://gmgn.ai/ai`.
- Query-only usage needs `GMGN_API_KEY` only.
- Trading/swap usage needs `GMGN_API_KEY + GMGN_PRIVATE_KEY`, but Smart Money Move should avoid private-key/swap configuration unless the user explicitly requests trade execution.
- Store secrets in `~/.hermes/secrets/smart_money.env` alongside `BIRDEYE_API_KEY` and `ETHERSCAN_API_KEY`:

```env
GMGN_API_KEY=gmgn_...
```

## CLI probes

GMGN CLI is accessible through `npx --yes gmgn-cli`. Export `GMGN_API_KEY` from the env file before probing.

```bash
set -a; . ~/.hermes/secrets/smart_money.env; set +a
npx --yes gmgn-cli market trending --chain base --interval 1h --limit 5 --raw
npx --yes gmgn-cli track smartmoney --chain base --limit 100 --side buy --raw
npx --yes gmgn-cli token security --chain base --address <token> --raw
npx --yes gmgn-cli token pool --chain base --address <token> --raw
npx --yes gmgn-cli token traders --chain base --address <token> --limit 20 --order-by profit --direction desc --raw
```

Supported GMGN chains observed for this use case: `eth`, `base`, `bsc`, `sol`.

## Integration Pattern

In `smart_money_alerter_birdeye.py`:

1. Import `subprocess` and define `GMGN_CHAIN = {"ethereum": "eth", "base": "base"}`.
2. Add `gmgn_enabled()` that returns true if `GMGN_API_KEY` exists.
3. Add `gmgn_cli(*args)` helper that runs `npx --yes gmgn-cli ... --raw` with `GMGN_API_KEY` in the subprocess env and parses JSON.
4. Add `gmgn_context(chain, token)` after aggregation, before marking alerts as alerted.
5. Keep alerting threshold Birdeye-driven; use GMGN to append context lines, not to suppress alerts unless explicitly requested.
6. Render source as `Birdeye Top Traders + GMGN validation` when GMGN key is present.
7. Add a `GMGN:` line with compact notes like `GMGN trending 1h rank #7 | security check OK | liq $420.0k | holders 1,234`.

## Good GMGN validation signals

- Token appears in `market trending` 1h list.
- Token appears in `track smartmoney --side buy` output.
- `token security` has no obvious honeypot / blacklist / cannot-sell flags.
- `token pool` or trending metadata reports enough liquidity.
- Holders and top-10-holder concentration look reasonable.

## Safety

- GMGN API docs warn to never expose API key, Ed25519/RSA private keys, or swap private keys in chat/logs/screenshots.
- For this user, Smart Money Move is an early-warning/validation topic, not an auto-buy bot.
- Alert copy should remain low-noise and actionable in Indonesian, with final disclaimer: `Bukan nasihat finansial; konfirmasi struktur teknikal sebelum entry.`

## Known operational note

Birdeye can return `Compute units usage limit exceeded`. Treat that as a quota/runtime state; do not hardcode it as a durable failure. GMGN validation runs only after Birdeye has produced candidate alerts unless the scanner is redesigned to use GMGN as a primary trigger.
