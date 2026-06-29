# Furina Skills

Personal collection of [Hermes Agent](https://hermes-agent.nousresearch.com/docs)
skills and automation scripts for **Furina** — a disciplined, risk-first
trading-analysis persona that runs a 24/7 autonomous Binance USDT-M perpetual
paper and live trading system.

Furina scans the market with multiple statistical-edge scanners, validates
signals through a layered gate pipeline, manages positions with a trailing
TP/SL state machine, and reports everything to Telegram topics and a web
dashboard in near real-time.

> **Not financial advice.** Everything in this repo is tooling output for
> personal use. Trading involves risk; use proper position sizing and manual
> confirmation.

## Layout

```
skills/          # Hermes skill modules (SKILL.md + linked references)
scripts/         # Standalone Python scripts wired to Hermes cron jobs
docs/diagrams/   # Mermaid diagrams that explain Furina's automation flows
```

## Architecture & pipelines

The system is documented as Mermaid diagrams so the full flow is readable
without running anything:

- **[Decision Pipeline](docs/diagrams/decision-pipeline.md)** — the full
  signal-to-managed-position pipeline: scanner fire, 8 sequential executor
  gates, order submission, reconciler fill handling, and the trailing TP/SL
  state machine. This is the core map of how a signal becomes a managed trade.
- **[System Architecture](docs/diagrams/system-architecture.md)** — high-level
  map of data sources, the Hermes runtime, Furina decision modules, and outputs.
- **[Signal Lifecycle](docs/diagrams/signal-lifecycle.md)** — state machine from
  setup detection through entry, TP/SL, breakeven, trailing, and close.
- **[Smart Money Move Flow](docs/diagrams/smart-money-flow.md)** — Birdeye
  wallet discovery plus GMGN validation pipeline.
- **[Cron Schedule](docs/diagrams/cron-schedule.md)** — conceptual cadence for
  scanners, monitors, alerts, and reports.

### The trading pipeline at a glance

1. **Scan** — ten scanners (aggressive / medium / safe / counter-trend / alpha
   + oi_divergence / funding / liq_cascade / breakout_retest) scan multi-TF.
   A signal needs at least 4 of 7 confirmations: multi-TF alignment, volume,
   Bollinger squeeze, RSI + MACD, price action, smart volume, TA + sentiment.
2. **Gate** — the executor runs eight sequential validation gates (valid levels,
   symbol on perp, bucket allowed, blacklist cooldown, same-symbol guard,
   Asia-session score filter, max concurrent, sizing). Any failure skips the
   signal with a granular reason — no order is placed.
3. **Submit** — a LIMIT entry is placed; SL and TP algos follow after the entry
   fills (reduce-only orders need an existing position).
4. **Reconcile** — a reconciler runs every 5 minutes: detects fills, places
   SL/TP, and runs an SL-guard every tick that re-places any naked stop.
5. **Manage** — TP1 closes a partial leg and moves SL to breakeven; TP2 trails
   SL to TP1; the runner exits by trailing stop or TP3. Every transition syncs
   to the dashboard in near real-time.

See the [decision pipeline diagram](docs/diagrams/decision-pipeline.md) for the
full gate order and trailing logic.

## Skills

Skills are organized by domain. Each skill lives in
`skills/<category>/<name>/SKILL.md` and is loaded by the Hermes Agent runtime
when a relevant task comes up. Highlights in this repo:

- `finance/furina-trading-agent` — the main trading-assistant persona, tone,
  journal and report formats, plus 39 reference files covering the full
  production system: scanner logic, execution, risk guards, dashboard,
  auto-learn-from-SL pipeline, and remediation methodology.
- `finance/binance-alpha-trading` — read-only analysis playbook for Binance
  Alpha tokens.
- `autonomous-ai-agents/*` — delegate work to Claude Code, Codex, OpenCode,
  Hermes Agent.
- `creative/*`, `media/*`, `productivity/*`, `mlops/*`, `software-development/*`,
  etc. — general-purpose Hermes skills.

## Scripts

Standalone scripts that back automated cron jobs (mostly trading automation):

- `automatic_signal_scanner.py` — multi-scanner market scan across timeframes
  and statistical edges; writes signals to the journal when confirmations pass.
- `automatic_signal_monitor.py` — monitors open signals and notifies on entry,
  TP, SL, and breakeven events (cross-references the real journal to avoid
  ghost-trade false notifications).
- `automatic_signal_daily_report.py` — daily signal and trade status report.
- `automatic_signal_risk_manager.py` — watches drawdown and account risk;
  auto-pauses on daily drawdown breach and auto-kills on catastrophic drawdown.
- `binance_alpha_signal_scanner.py` — scans Binance Alpha tokens every 15m and
  emits a signal when setup filters pass.
- `binance_alpha_signal_monitor.py` — monitors open Binance Alpha signals and
  notifies on entry / TP / SL hits.
- `binance_alpha_daily_report.py` — daily Binance Alpha journal report.
- `crypto_volume_breakout_alert.py` — large volume + price breakout alert.
- `top_marketcap_move_alert.py` — top market-cap move alert (4H / 1D).

All scripts in this repo are **read-only**: they call public Binance REST
endpoints and never sign orders. The managed execution layer (order signing,
reconciliation, trailing stops) is documented conceptually in the
`furina-trading-agent` skill references and runs from the operator's private
deployment.

## Risk management

- **Flat 1% risk per trade** across all scanners (position size derived from
  the SL distance, not from leverage).
- **Max 6 concurrent positions** — limits aggregate drawdown, not margin. Worst
  case 6 simultaneous SL hits = -6%.
- **Leverage 4-5x by bucket** — only affects margin lockup and liquidation
  distance; it does not set risk.
- **Risk manager** runs every 5 minutes: auto-PAUSE on 5% daily drawdown,
  auto-KILL on 10% catastrophic drawdown.
- **SL-guard** runs every reconciler tick — re-places any naked stop and alerts.
- **Manual killswitch** — a single flag file freezes the executor instantly for
  maintenance or emergency.

## Disclaimer

Not financial advice. The signals and reports produced by these scripts are
tooling output, not investment advice. Trading involves risk; use proper
position sizing and manual confirmation.

## License

Personal use. No license granted; please ask before redistributing.
