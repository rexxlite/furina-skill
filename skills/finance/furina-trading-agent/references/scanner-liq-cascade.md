# Liquidation Cascade Scanner — `liq_cascade_scanner.py`

**Status:** ACTIVE (real mainnet)
**Risk model tag:** `liq_cascade` — emoji 💥
**Source:** `scripts/liq_cascade_scanner.py` (302 lines)

## Thesis

After a violent liquidation wipeout, price is often over-extended and snaps
back fast. This is a SCALP counter-trend setup — catch the bounce after panic.

Binance blocked the public liquidation feed (allForceOrders → HTTP 400), so
cascades are detected via PROXY from klines:

- Volume spike (current bar volume >> recent average) = forced flow
- Large range bar (ATR expansion) = violent move
- Long rejection wick in the cascade direction = liquidations cleared + reversal
- Over-extension (price stretched from a short EMA) = stop-run done

LONG bounce (most common — long liquidations flush price DOWN):
big red/down bar + volume spike + long lower wick + oversold = fade UP

SHORT (short squeeze flushes price UP then fails):
big green/up bar + volume spike + long upper wick + overbought = fade DOWN

This is fast and risky ("catching a falling knife") — tight SL, quick TP,
conservative leverage. Lowest-priority trial scanner.

## Parameters

- Signal timeframe: `5m` (fast — cascades are short-lived)
- Volume spike multiplier: 3.0x (current vol >= 3x average of prior bars)
- Volume lookback: 20 bars
- Range spike multiplier: 2.0x (cascade bar range >= 2x ATR = violent)
- Wick min: 0.4 (rejection wick >= 40% of bar range)
- Min cascade move: 2.5%
- Max cascade move: 25.0% (anti-flush)
- RSI oversold: 35 (LONG bounce)
- RSI overbought: 65 (SHORT fade)
- Universe: top 60 USDT perp by 24h quote volume (floor $50M)
- Cooldown: 3 hours (short — scalp setup, allow re-entry sooner)
- ATR SL multiplier: 1.2 (tight stop beyond the wick)
- RR TP: [1.0, 1.5, 2.0] (quick scalp targets)
- Min score: 4 of 6

## Scoring (6 points, need 4)

1. Huge volume — vol_ratio >= 3x (gate contributes base)
2. Dominant rejection wick — wick in reversal direction
3. RSI oversold / overbought — aligned with the fade
4. Strong ATR expansion — range >= 2x ATR
5. Over-extension — price stretched from EMA20
6. Base — cascade pattern present + thresholds passed

## Exit philosophy

Scalp. Tight SL beyond the rejection wick (1.2x ATR), quick TP ladder
(1R / 1.5R / 2R). Not a trend trade — take the bounce and leave.

## Performance (testnet eval, 13d)

Net +$4.92, win rate 67% (highest WR of all scanners, but small sample and
small absolute PnL — scalp sizing is conservative).

## Bucket / leverage

- Executor bucket: LIQ_CASCADE
- Leverage: 4x (CROSSED)
- Risk: flat 1% per trade
