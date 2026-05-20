# Smart Money Move Flow

Pipeline used by the Smart Money Move topic to turn on-chain wallet activity into concise alerts.

```mermaid
flowchart LR
    Start([Cron tick]) --> Traders[Fetch top traders from Birdeye]
    Traders --> WalletTx[Fetch recent wallet swaps]
    WalletTx --> BuyFilter{Received risk token and sent stable or native?}
    BuyFilter -- No --> Drop1[Drop transaction]
    BuyFilter -- Yes --> NoiseFilter{Stable, wrapped, LST, or yield token?}
    NoiseFilter -- Yes --> Drop2[Drop token]
    NoiseFilter -- No --> MinBuy{Buy size above threshold?}
    MinBuy -- No --> Drop3[Ignore small buy]
    MinBuy -- Yes --> Record[(Record recent buy)]

    Record --> Aggregate[Aggregate by token and distinct wallet]
    Aggregate --> Threshold{Wallet and USD threshold met?}
    Threshold -- No --> Silent[Stay silent]
    Threshold -- Yes --> GMGN[GMGN validation layer]

    GMGN --> Validate[Check trending, smart-money tape, security, liquidity, holders]
    Validate --> Cooldown{Token in cooldown?}
    Cooldown -- Yes --> Silent
    Cooldown -- No --> Alert[Send Telegram alert]
    Alert --> Mark[(Mark cooldown)]
```

The goal is early discovery, not automatic execution. GMGN is used as an extra validation layer on top of Birdeye discovery.
