# System Architecture

This diagram shows the system in four simple layers: data comes in, Hermes runs jobs, Furina makes decisions, and Telegram/reporting receives the output.

## Simple Overview

```mermaid
flowchart TD
    A[1. Market data sources] --> B[2. Hermes automation runtime]
    B --> C[3. Furina decision modules]
    C --> D[4. User outputs]

    A1[Binance market data] --> A
    A2[Birdeye smart wallets] --> A
    A3[GMGN token validation] --> A

    B1[Skills] --> B
    B2[Cron jobs] --> B
    B3[Python scripts] --> B

    C1[Signal scanners] --> C
    C2[Smart Money Move] --> C
    C3[Risk manager] --> C

    D --> D1[Telegram topics]
    D --> D2[Daily reports]
    D --> D3[Trade journals]
```

## Detailed Component Map

```mermaid
flowchart LR
    subgraph Data[1. Data Sources]
        Binance[Binance APIs]
        Birdeye[Birdeye]
        GMGN[GMGN]
    end

    subgraph Hermes[2. Hermes Runtime]
        Cron[Cron jobs]
        Scripts[Automation scripts]
        State[(Local state and cooldowns)]
    end

    subgraph Furina[3. Furina Logic]
        Signals[Trading signal scanners]
        Smart[Smart Money Move]
        Risk[Risk and reconciler]
        Alerts[Market alerts]
    end

    subgraph User[4. Outputs]
        TG[Telegram]
        Reports[Reports]
        Journals[Journals]
    end

    Binance --> Scripts
    Birdeye --> Scripts
    GMGN --> Scripts
    Cron --> Scripts
    Scripts --> State
    Scripts --> Signals
    Scripts --> Smart
    Scripts --> Risk
    Scripts --> Alerts
    Signals --> TG
    Smart --> TG
    Risk --> TG
    Alerts --> TG
    State --> Reports
    State --> Journals
```

## How to Read

- Data Sources: external market/on-chain APIs Furina reads.
- Hermes Runtime: the scheduler and scripts that keep workflows running.
- Furina Logic: the filters that decide whether something is important.
- Outputs: where users see the result.
