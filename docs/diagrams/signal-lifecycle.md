# Signal Lifecycle

Lifecycle of a Furina-generated trading signal from detection to final report.

```mermaid
stateDiagram-v2
    [*] --> Scanning
    Scanning --> NoSetup: filters fail
    NoSetup --> Scanning: next cron tick

    Scanning --> SetupDetected: confluence passes
    SetupDetected --> AlertSent: send Telegram signal
    AlertSent --> WaitingEntry: journal created

    WaitingEntry --> Expired: entry not touched in time
    WaitingEntry --> Active: entry touched or filled

    Active --> StoppedOut: SL hit
    Active --> TP1Hit: TP1 hit
    TP1Hit --> BreakevenProtected: move stop to BE when rules allow
    BreakevenProtected --> TP2Hit: TP2 hit
    TP2Hit --> TP3Hit: TP3 hit

    BreakevenProtected --> ClosedBreakeven: BE stop hit
    TP2Hit --> ClosedTrailing: trailing stop hit
    TP3Hit --> ClosedWin: final target hit
    StoppedOut --> ClosedLoss
    Expired --> [*]
    ClosedBreakeven --> [*]
    ClosedTrailing --> [*]
    ClosedWin --> [*]
    ClosedLoss --> [*]
```

This diagram is intentionally risk-first: every active signal must have a defined invalidation path, not only upside targets.
