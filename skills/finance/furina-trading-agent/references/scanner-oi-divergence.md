# OI Divergence Scanner — `oi_divergence_scanner.py`

**Status:** ACTIVE (real mainnet, tuned 2026-06-29)
**Risk model tag:** `oi_divergence` — emoji 📡
**Source:** `scripts/oi_divergence_scanner.py` (366 lines)

## Thesis

Open Interest divergence: when OI shifts hard but price does not follow, the
move is leveraged positioning, not conviction. Price tends to snap toward the
OI shift direction once the squeeze resolves.

- OI rising + price flat = positions building, breakout imminent
- OI falling + price moving = unwinding, move likely exhausted (reversion)

This is structurally counter-trend, so it needs a trend filter — it must not
fight the BTC trend (gate added 2026-06-29 after a 4-SL streak in a downtrend).

## Parameters

- Signal timeframe: `15m`
- OI period: `15m`, lookback 8 bars (~2h)
- OI min change: 3.0% over window
- Price min change: 1.5% over window
- Price max change: 20.0% (anti-flush)
- Universe: top 60 USDT perp by 24h quote volume (floor $50M)
- Cooldown: 6 hours per symbol
- RSI long max: 75 (no LONG into severe overbought)
- RSI short min: 25 (no SHORT into severe oversold)
- ATR SL multiplier: 1.5
- RR TP: [1.0, 1.5, 2.5]
- Min score: 4 of 5

## Scoring (5 points, need 4)

1. Base point — divergence pattern present + thresholds passed
2. OI shift strong — abs(oi_chg) >= 2x OI_MIN_CHANGE_PCT
3. Candle confirms direction — last bar closes in signal direction
4. RSI not at wrong extreme — RSI ok for the side
5. Exhaustion RSI — for reversal setups, RSI at the reversal extreme

## BTC bias gate (added 2026-06-29)

After classify() determines side, before scoring:
- BTC 1h bias bearish (EMA20 < EMA50, price below both) → skip LONG
- BTC 1h bias bullish (EMA20 > EMA50, price above both) → skip SHORT
- BTC neutral → allow both

Uses `base.detect_btc_bias()` from `automatic_signal_scanner.py`.

## Tuning history

- 2026-06-29: MIN_SCORE 3 → 4 + added BTC bias gate. Trigger: 4 consecutive SL
  same day (SLX/RE/POWR/MANTA, -$9.12) in a downtrend market, all LONGs that
  fought BTC. The gate blocks catching falling knives; threshold 4 filters
  thin signals that only had base + 1 confirmation. Target: signal count down
  50-70%, win rate >= 55%.

## Exit philosophy

Standard ATR-based SL (1.5x ATR), TP ladder at 1R/1.5R/2.5R. Managed by the
executor trailing state machine: TP1 closes 30% and moves SL to breakeven,
TP2 trails SL to TP1, runner exits by trailing stop or TP3.

## Bucket / leverage

- Executor bucket: OI_DIV
- Leverage: 5x (CROSSED)
- Risk: flat 1% per trade (sizing from SL distance)
