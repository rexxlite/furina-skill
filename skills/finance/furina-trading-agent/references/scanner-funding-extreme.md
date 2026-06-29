# Funding Extreme Scanner — `funding_extreme_scanner.py`

**Status:** ACTIVE (real mainnet)
**Risk model tag:** `funding` — emoji 📈
**Source:** `scripts/funding_extreme_scanner.py` (329 lines)

## Thesis

Funding rate = the 8h fee longs/shorts pay each other on perpetuals.

- Funding very POSITIVE = longs crowded / over-leveraged → squeeze risk → bias SHORT
- Funding very NEGATIVE = shorts crowded / over-leveraged → squeeze risk → bias LONG

This is CONTRARIAN — it fades the crowd at exhaustion, the opposite of the
trend scanners. But funding extreme alone is NOT a signal: in strong trends
funding can stay extreme for days. Confirmation is mandatory.

## Parameters

- Signal timeframe: `1h`
- Funding threshold: 0.04% per 8h (extreme; normal ~0.01%)
- Funding strong: 0.08%+ (very extreme, bonus score)
- Trend ADX max: 30.0 (above this = real trend, funding justified → skip)
- Universe: top 80 USDT perp by 24h quote volume (floor $50M)
- Cooldown: 8 hours per symbol
- RSI long max: 70 (no LONG into overbought)
- RSI short min: 30 (no SHORT into oversold)
- ATR SL multiplier: 1.0 (tighter than default — funding reversion is fast)
- RR TP: [1.5, 2.5, 4.0] (first partial now >= risk)
- Min score: 4 of 6

## Scoring (6 points, need 4)

1. Funding beyond threshold (gate, not a point)
2. Funding very extreme — abs(funding) >= FUNDING_STRONG (0.08%)
3. Candle confirms reversal — close turning back against the crowd
4. Rejection wick — wick in the reversal direction (longs/shorts trapped)
5. RSI not at wrong extreme — RSI ok for the side
6. RSI supports reversal — RSI at the exhaustion extreme

## Confirmation gates (hard skips)

- Funding beyond FUNDING_THRESHOLD (abs) — real crowding, not noise
- Candle reversal in signal direction
- RSI not screaming the wrong way
- NOT a strong structural trend (ADX < 30 and price near EMA200) — if it IS a
  strong trend, extreme funding is justified, skip
- 24h quote volume floor (liquidity)

## Exit philosophy

Mean-reversion toward fair value. Conservative TP ladder (1.5R / 2.5R / 4R) —
funding reversion is modest so the first partial must cover risk. SL beyond
the recent swing extreme (if the crowd was right, thesis is wrong).

## Tuning history

- ATR_SL_MULT lowered 1.5 → 1.0 (funding reversion is fast, tight stop is fine)
- RR_TP shifted [1.0, 1.5, 2.5] → [1.5, 2.5, 4.0] (first partial >= risk)

## Performance (testnet eval, 13d, 2026-06-12 to 2026-06-26)

Net +$78.79, win rate 54%. Second-best scanner behind OI_DIV (+$145).

## Bucket / leverage

- Executor bucket: FUNDING
- Leverage: 4x (CROSSED)
- Risk: flat 1% per trade
