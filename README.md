# Furina Skills

Personal collection of Hermes Agent skills and automation scripts used by Furina (an Indonesian-speaking trading & general-purpose assistant persona running on [Hermes Agent](https://hermes-agent.nousresearch.com/docs)).

## Layout

```
skills/      # Hermes skill modules (SKILL.md + linked references/scripts/templates)
scripts/     # Standalone Python scripts wired to Hermes cron jobs
```

### Skills

Skills are organized by domain. Each skill lives in `skills/<category>/<name>/SKILL.md` and is loaded by the Hermes Agent runtime when relevant tasks come up. Highlights in this repo:

- `finance/furina-trading-agent` — main trading-assistant persona, tone, journal & report formats
- `finance/binance-alpha-trading` — read-only analysis playbook for Binance Alpha tokens
- `autonomous-ai-agents/*` — delegate work to Claude Code, Codex, OpenCode, Hermes Agent
- `creative/*`, `media/*`, `productivity/*`, `mlops/*`, `software-development/*`, etc. — general-purpose Hermes skills

### Scripts

Standalone scripts that back automated cron jobs (mostly trading automation):

- `binance_alpha_signal_scanner.py` — scans Binance Alpha tokens every 15m and emits a signal when setup passes filters
- `binance_alpha_signal_monitor.py` — monitors open Binance Alpha signals and notifies on entry / TP / SL hits
- `binance_alpha_daily_report.py` — daily 07:00 WIB Binance Alpha journal report
- `automatic_signal_scanner.py` / `automatic_signal_monitor.py` / `automatic_signal_daily_report.py` / `automatic_signal_risk_manager.py` — same trio for Binance USDT-M perpetual aggressive scanner
- `crypto_volume_breakout_alert.py` — large volume + price breakout alert
- `top_marketcap_move_alert.py` — top market-cap move alert (4H / 1D ±1%)

All trading scripts are **read-only**: they call public Binance REST endpoints, never sign orders, never touch private accounts.

## Disclaimer

Bukan nasihat finansial. Trading involves risk; use proper position sizing and manual confirmation. The signals and reports produced by these scripts are tooling output, not investment advice.

## License

Personal use. No license granted; please ask before redistributing.
