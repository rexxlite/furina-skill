# System Architecture

High-level map of the Furina skill and automation stack.

```mermaid
flowchart TB
    subgraph Inputs[Market and On-chain Inputs]
        Binance[Binance Futures and Spot APIs]
        Birdeye[Birdeye top traders]
        GMGN[GMGN token, market, and smart-money data]
        PublicFeeds[Public market and news feeds]
    end

    subgraph Runtime[Hermes Agent Runtime]
        Skills[Hermes skills]
        Cron[Scheduled cron jobs]
        Scripts[Python automation scripts]
        State[(Local state, journals, cooldown DBs)]
    end

    subgraph Intelligence[Decision Layers]
        Scanners[Signal scanners]
        SmartMoney[Smart Money Move pipeline]
        Alerts[Market alert filters]
        Risk[Risk manager and reconciler]
    end

    subgraph Outputs[User-facing Outputs]
        Telegram[Telegram topics]
        Reports[Daily reports]
        Journal[Trade calendar and journals]
    end

    Binance --> Scripts
    Birdeye --> Scripts
    GMGN --> Scripts
    PublicFeeds --> Skills
    Skills --> Cron
    Cron --> Scripts
    Scripts --> State
    Scripts --> Scanners
    Scripts --> SmartMoney
    Scripts --> Alerts
    Scripts --> Risk
    Scanners --> Telegram
    SmartMoney --> Telegram
    Alerts --> Telegram
    Risk --> Telegram
    State --> Reports
    State --> Journal
```

Core idea: Furina uses skills for behavior and playbooks, scripts for repeatable automation, and cron jobs to keep market monitoring alive without manual prompting.
