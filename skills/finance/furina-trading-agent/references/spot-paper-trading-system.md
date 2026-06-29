# Spot Paper Trading System

User-vetted design (2026-05-24) for the Spot Signal topic — long-only Binance Spot signals running through paper-trading first before any real-money lane.

## Locked Configuration

| Parameter | Value | Reasoning |
|---|---|---|
| Starting equity (paper) | $1000 | Round number, easy mental %-math |
| Risk per trade | 5% ($50 max loss) | Spot has no liquidation; can run hotter than perp's 1% |
| Fee rate | 0.1% (taker) | Binance Spot taker baseline |
| Slippage | 0.05% | Per leg (entry + exit) |
| Fee round-trip in sizing | `0.2%` notional cushion | `qty = risk / (sl_distance + entry × 0.002)` |
| Max concurrent positions | 5 | Diversification cap |
| Max new positions per hour | 3 | Floods → bad fills |
| Max position % of equity | 40% | **Hard cap; no leverage = notional ≤ equity** |
| TP1 partial close | 40% of qty | Hybrid (option E) default split |
| Trailing mode | ATR(14, 4h) × 2.5 from peak | Adaptive to volatility |
| Trailing activation | At TP1 hit (not earlier) | Don't trail too early; let setup breathe |
| Fallback exit | 1D candle close < EMA20 | Catches trend failures trailing misses |
| WAITING_ENTRY expiry | 36h | Spot swings need wider window than perp |

The `max_position_pct_of_equity = 40%` cap is what kept BNBUSDT DCA Zone from sizing to full $50 risk in the first test — SL distance was ~3%, full-risk notional would have been ~$1700, but unlevered spot can't exceed $400 (40% × $1000). This is the right behavior, not a bug. Document the cap clearly so the user doesn't think the executor is broken.

## Five Strategies (long-only)

| Strategy | TF chain | Min score | Min RR | Max risk | Notes |
|---|---|---|---|---|---|
| `medium` | 1h → 4h | 7/9 | 2.0R | 4% | EMA breakout-retest, ADX≥18, MACD aligned |
| `safe` | 4h → 1d | 8/12 | 2.5R | 2.5% | Multi-TF EMA align (1h+4h), ADX≥25 |
| `dca_zone` | 4h | 6/9 | 2.5R | 5% | Pullback to EMA50/EMA100 in 1D uptrend, bullish reaction wick |
| `swing_breakout` | 1d | 6/9 | 3.0R | 6% | 1D break of prior swing high + retest hold, ADX≥22 |
| `dip_buy_os` | 1h → 4h | 6/9 | 2.0R | 4% | RSI<30 at recent_low support + bullish reaction + optional divergence |

All strategies block longs when BTC bias is bearish on the relevant timeframe (1h for short-TF strategies, 1d for swing strategies).

## File Layout

```
/root/.hermes/scripts/
  automatic_signal_spot_scanner.py   # multi-mode CLI: --mode {medium|safe|dca_zone|swing_breakout|dip_buy_os}
  spot_paper_executor.py             # virtual fill executor, state manager
  spot_paper_risk_manager.py         # fill confirmation + hybrid trailing daemon (cron */5)
  spot_paper_daily_report.py         # daily report at 07:00 WIB

/root/.hermes/spot_paper_state.json          # equity / cash / counters
/root/.hermes/trading_journals/
  spot_paper_journal.json                    # all spot paper signals + executor + status
```

State machine:

```
WAITING_ENTRY → ACTIVE → TP1_HIT → TRAILING → CLOSED (TP3 / trail / EMA20-1D fallback)
                  └────────────────┴─────────→ SL_HIT (any SL touch)
                  └→ INVALID (entry never filled within 36h, or gap-down through SL pre-fill)
```

## Cron Layout (when topic ID is set)

```
*/30 * * * *   automatic_signal_spot_scanner.py --mode medium       → telegram:GROUP:THREAD
*/30 * * * *   automatic_signal_spot_scanner.py --mode safe         → telegram:GROUP:THREAD  (offset minute 5)
*/30 * * * *   automatic_signal_spot_scanner.py --mode dca_zone     → telegram:GROUP:THREAD  (offset minute 10)
*/30 * * * *   automatic_signal_spot_scanner.py --mode swing_breakout → telegram:GROUP:THREAD (offset minute 15)
*/30 * * * *   automatic_signal_spot_scanner.py --mode dip_buy_os   → telegram:GROUP:THREAD  (offset minute 20)
*/5  * * * *   spot_paper_risk_manager.py                           → telegram:GROUP:THREAD  (no_agent=true, early-exits silent)
0    7 * * *   spot_paper_daily_report.py                           → telegram:GROUP:THREAD
```

All scanners must be `no_agent=true`. Stagger the offsets to avoid burst hitting Binance Spot rate limits.

## Sizing Math (worked example)

Equity $1000, signal: BNBUSDT entry $654.87, SL $635.29 (-3.0%), risk 5%.

```python
risk_dollar     = 1000 * 0.05            # = $50
sl_distance     = 654.87 - 635.29        # = $19.58
fee_cushion     = 654.87 * 0.002         # = $1.31  (0.2% round-trip)
qty_full_risk   = 50 / (19.58 + 1.31)    # = 2.394 BNB
notional_full   = 2.394 * 654.87         # = $1568  ← exceeds 40% cap of $400
notional_capped = min(1568, 400)         # = $400
qty_capped      = 400 / 654.87           # = 0.611 BNB
real_risk       = 0.611 * 19.58          # = $11.96  (effective 1.2% risk, not 5%)
```

When the position cap kicks in, the actual risk goes down; document this in the executor sub-doc as `notional_planned: 400` vs `risk_dollar_planned: 50`. The user sees both numbers in `executor` and can reason about it.

## Hybrid Trailing Cash Math (worked example)

User's confusion: "TP1 ambil 40% di +5%, $42 jadi sisa $42?"

Correct mechanics: partial close = X% of QTY, not X% of profit.

```text
Buy 1 ETH @ $100, modal $100
+5% hit (price $105):
  TP1 close 40% × 1 ETH = 0.4 ETH @ $105 → +$42 cash
  Sisa: 0.6 ETH (worth $63 di harga $105)
  SL sisa → BE = $100
  Trailing aktif

Skenario A — harga lanjut naik:
  peak $115 → trail SL = peak - ATR×2.5 (misal -3% = $111.55)
  harga turun close $111 → exit 0.6 ETH @ ~$111
  Total cash: $42 + (0.6 × $111) = $108.6 → +$8.6 (+8.6%)

Skenario B — harga balik turun setelah TP1:
  harga ke BE $100 → SL sisa kena
  Total cash: $42 + (0.6 × $100) = $102 → +$2 (+2%)

Skenario C — tanpa hybrid (full hold):
  harga $115 lalu balik ke BE $100, exit di $100
  Total: $0 (semua gain hilang)
```

Always walk through Skenario A + B + C when the user questions partial-close logic. The point is asymmetric outcomes: best case ride a runner, worst case still small win.

## Spot vs Perp Differences (cheat sheet)

| Aspect | Spot | Perp |
|---|---|---|
| Direction | LONG only | LONG + SHORT |
| Leverage | 1x (no leverage) | up to 20x (capped per source) |
| Liquidation | None | Yes — capital can hit zero |
| Funding | None | Every 8h, can be ±1% extreme |
| Holding cost | Zero (excluding opportunity cost) | Funding accumulates on long holds |
| Risk per trade | 3-5% (no liquidation risk) | 1% (liquidation risk) |
| Notional cap | `≤ equity` (hard) | `≤ equity × leverage_cap` |
| Position size | `risk / sl_distance` then clamp to equity | `risk / sl_distance` then check leverage cap |
| Fee structure | 0.1% taker × 2 = 0.2% round-trip | 0.045% taker × 2 = 0.09% round-trip |
| Trailing pays off most when | Multi-day swing trends | Same, but funding eats into long holds |
| Best strategies | DCA zone, swing breakout, dip buy oversold | Aggressive scalp 15m/30m, breakout-retest |

## Pitfalls

- **TP1 trigger uses mark price ≥ TP1**. Spot doesn't have mark price — use `/api/v3/ticker/price`. Don't accidentally call `/fapi/v1/...` futures endpoints; that's a different universe.
- **Universe filtering**: Binance Spot has more leveraged tokens (UP/DOWN/BULL/BEAR) than perp does. Check `LEVERAGED_TOKEN_SUFFIXES` and `isSpotTradingAllowed=true`. Also exclude stable-stable pairs (USDC/USDT, FDUSD/USDT).
- **EMA20 1D fallback** on the trailing daemon must read from `/api/v3/klines` with `interval=1d`. Spot 1D candle close is at 00:00 UTC; user lives in WIB so a "1D close" appears at 07:00 WIB. Don't fire fallback exit on intraday candle progress, only on closed 1D candles.
- **Recompute equity** on every state change: `equity = starting_equity + total_realized_pnl - total_fees_paid`. Don't track open MTM in equity (only in display) — that prevents oscillation when prices move.
- **WAITING_ENTRY gap-down through SL**: if 5m candle's low ≤ SL before entry band ever touched, mark INVALID (not SL_HIT) — entry was never filled, so no real loss occurred on paper.
- **Partial close fee accounting**: TP1 fee is `qty_close × tp1_price × 0.001`, separate from entry fee. Track `executor.fees_paid` as cumulative.
- **No real money on this lane.** The executor never calls Binance trade endpoints. If the user later wants live spot, build a separate `binance_spot_real_executor.py` with its own creds and journal — do NOT extend the paper executor with a real-flag toggle.

## Verification Recipe

Before wiring cron:

```bash
# 1. Reset state to known baseline
python3 /root/.hermes/scripts/spot_paper_executor.py reset

# 2. Run each strategy at least once manually
for m in medium safe dca_zone swing_breakout dip_buy_os; do
  echo "=== $m ===";
  timeout 90 python3 /root/.hermes/scripts/automatic_signal_spot_scanner.py --mode "$m";
done

# 3. Inspect journal — at least one entry should appear if any strategy fired
cat /root/.hermes/trading_journals/spot_paper_journal.json | python3 -m json.tool | head -60

# 4. Check executor sub-doc has PLANNED status with sane qty/notional
python3 /root/.hermes/scripts/spot_paper_executor.py status

# 5. Risk manager smoke test (should be silent if WAITING_ENTRY hasn't been touched yet)
python3 /root/.hermes/scripts/spot_paper_risk_manager.py

# 6. Daily report dry-run
python3 /root/.hermes/scripts/spot_paper_daily_report.py
```

Only after all six green, register the cron jobs.

## Telegram Thread ID — Required Format

Topic target must be `telegram:-100XXXXXXXXXX:<THREAD_ID>` where `<THREAD_ID>` is a 1-5 digit integer (real examples: `466`, `570`, `829`, `1549`).

Common user mistake: giving the group ID minus its `100` prefix (e.g. `-2264984442`) thinking that's the thread ID. It's not — that's still the group, just truncated. When the user provides what looks like a 10-digit number that doesn't fit, ask them to:

1. Open the topic in Telegram
2. Forward 1 message to `@userinfobot` → bot returns `Thread ID: <NNN>`

**Or** copy the topic link: right-click topic → Copy Link → URL is `t.me/c/<GROUP_ID>/<THREAD_ID>/<MSG_ID>`. The middle segment is the thread ID.

Never set `target` to a placeholder like `PENDING_THREAD_ID` and forget about it; if the user hasn't given a valid ID by end of session, leave the cron jobs UNREGISTERED. Cron with bad target will spam errors.
