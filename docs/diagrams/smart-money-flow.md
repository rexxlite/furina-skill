# Smart Money Move Flow

This diagram explains how Furina turns wallet activity into a Smart Money Move alert.

## Simple Overview

```mermaid
flowchart TD
    A[1. Find profitable wallets] --> B[2. Read their recent buys]
    B --> C[3. Remove noise tokens]
    C --> D[4. Group buys by token]
    D --> E[5. Validate token with GMGN]
    E --> F{6. Alert worthy?}
    F -- No --> G[Stay silent]
    F -- Yes --> H[Send Smart Money Move alert]
```

## Detailed Filter Flow

```mermaid
flowchart TD
    Start[Start every 15 minutes] --> Birdeye[Fetch Birdeye top traders]
    Birdeye --> Swaps[Fetch wallet swap history]
    Swaps --> BuyCheck{Is this a real buy?}

    BuyCheck -- No --> IgnoreTx[Ignore transaction]
    BuyCheck -- Yes --> NoiseCheck{Is token noise?}

    NoiseCheck -- Yes --> IgnoreToken[Ignore stable, wrapped, LST, or yield token]
    NoiseCheck -- No --> SizeCheck{Buy size large enough?}

    SizeCheck -- No --> IgnoreSmall[Ignore small buy]
    SizeCheck -- Yes --> Store[Store buy in local database]

    Store --> Aggregate[Group by token and count wallets]
    Aggregate --> Threshold{Meets wallet and USD threshold?}

    Threshold -- No --> Silent[No alert]
    Threshold -- Yes --> GMGN[Check GMGN data]

    GMGN --> Confirm[Trending, smart-money tape, security, liquidity, holders]
    Confirm --> Cooldown{Already alerted recently?}

    Cooldown -- Yes --> Silent
    Cooldown -- No --> Alert[Send Telegram alert]
```

## What GMGN Adds

- Confirms whether the token is trending.
- Checks smart-money buy tape from another source.
- Adds basic token safety and liquidity context.
- Helps reduce low-quality Birdeye-only alerts.
