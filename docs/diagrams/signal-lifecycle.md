# Signal Lifecycle

This diagram explains what happens after Furina finds a trading setup.

## Main Path

```mermaid
flowchart TD
    A[1. Scanner checks market] --> B{2. Setup valid?}
    B -- No --> C[Stay silent]
    C --> A

    B -- Yes --> D[3. Send Telegram signal]
    D --> E[4. Create journal entry]
    E --> F{5. Entry touched?}

    F -- No --> G[Expire signal]
    F -- Yes --> H[6. Position active]

    H --> I{7. First event?}
    I -- Stop loss --> J[Close as loss]
    I -- TP1 --> K[Take partial profit]

    K --> L[Move risk to safer level]
    L --> M{8. Next event?}
    M -- Breakeven stop --> N[Close breakeven or small win]
    M -- TP2 or TP3 --> O[Close as win]
    M -- Trailing stop --> P[Close by trailing stop]
```

## State Machine

```mermaid
stateDiagram-v2
    [*] --> Scanning
    Scanning --> Silent: setup fails
    Silent --> Scanning: next run
    Scanning --> AlertSent: setup passes
    AlertSent --> WaitingEntry
    WaitingEntry --> Expired: entry not touched
    WaitingEntry --> Active: entry touched
    Active --> ClosedLoss: SL hit
    Active --> Protected: TP1 hit
    Protected --> ClosedBreakeven: BE stop hit
    Protected --> ClosedWin: TP2 or TP3 hit
    Protected --> ClosedTrailing: trailing stop hit
    Expired --> [*]
    ClosedLoss --> [*]
    ClosedBreakeven --> [*]
    ClosedWin --> [*]
    ClosedTrailing --> [*]
```

## Meaning

- Silent means Furina found no high-quality setup.
- Waiting Entry means the signal exists, but price has not reached the entry area.
- Active means the trade is live and must be monitored.
- Protected means TP1 was hit and risk should be reduced.
