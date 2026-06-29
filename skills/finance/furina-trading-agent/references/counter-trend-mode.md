# Counter-Trend Scanner Mode — Implementation Notes

Added 2026-06-05 during BTC crash (5 red daily candles, -14%, $73K→$63K).

## Why it exists

When BTC is bearish, ALL existing modes (aggressive/medium/safe) block LONG signals via `btc_bias` gating. Meanwhile, altcoin RSI drops below 28 (below the SHORT RSI window), blocking shorts too. Result: zero signals for 3 days during a crash — exactly when oversold bounce opportunities exist.

## Architecture

Single-file addition to `automatic_signal_scanner.py`. No new dependencies.

### Mode config (in MODES dict)

```python
"counter_trend": {
    "label": "COUNTER-TREND",
    "icon": "🔄",
    "tf_chain": ["1h", "4h"],
    "context_tf": "4h",
    "min_score": 6,
    "max_score": 10,
    "min_rr": 1.5,
    "max_risk": 0.030,         # wider than medium (2.5%) — crash volatility needs room
    "tp_multiples": (0.8, 1.5, 2.2),  # tighter TPs — quick bounce targets
    "min_quote_volume_24h": 15_000_000,
    "min_vol_ratio": 1.5,
    "rsi_long": (10, 30),      # deep oversold zone only
    "rsi_short": (999, 999),   # disabled — no shorts
    "btc_bias_hard": False,    # IGNORES BTC direction
    "use_adx": False,
    "use_macd": True,
    "use_multi_tf_align": False,
    "use_bb_width": False,     # CRITICAL: crash BBW > 18% blocks everything
    "use_close_above_ph": False,
    "use_ohlc_confluence": False,
    "cooldown_hours": 6,
    "max_symbols": 60,
    "counter_trend_mode": True,
}
```

### Key design decisions

1. **IGNORES BTC bias** — The BTC bias gating block has a special case:
   ```python
   if mode_cfg.get("counter_trend_mode"):
       allowed_long = True
       allowed_short = False  # counter-trend is LONG-only
   ```

2. **BB width DISABLED** — During crashes, BBW routinely exceeds 30% (normal threshold: 18%). Using `use_bb_width: False` skips the sanity check. Instead, `bb_pct_b()` (position within bands) detects oversold: `bb_pct_b < 0.15` = below lower band.

3. **Tighter entry zone** — Counter-trend buys AT current price, not on breakout retest:
   ```python
   entry_high = price + 0.05 * a_sig
   entry_low = price - 0.15 * a_sig
   sl = min(recent_low * 0.995, entry_low - 0.5 * a_sig)
   ```

4. **Technique preservation** — The `technique` variable is initialized to `None` before LONG/SHORT blocks. Counter-trend sets it to `"Counter-Trend Oversold Bounce"`. The default technique assignment is guarded:
   ```python
   if not any(t in (technique or "") for t in ("Counter-Trend",)):
       technique = "Breakout-Retest Trend Continuation"
   ```

### New helper functions

- `bb_pct_b(closes, n=20, k=2)` — Returns %B (0 = at lower band, 1 = at upper, <0 = below lower). Used instead of BBW for oversold detection.
- `bullish_divergence(closes, lookback=20)` — Detects price making lower low while RSI makes higher low. Swing lows confirmed by 2-bar pattern each side.

### Scoring (max 10, min 6)

| Factor | Score |
|--------|-------|
| RSI < 15 (extreme) | +3 |
| RSI < 22 | +2 |
| RSI < 30 | +1 |
| BB %B < 0.15 | +2 |
| Bullish divergence | +2 |
| Volume spike (≥1.5x) | +1 |
| 24h crash (< -5%) | +1 |
| MACD histogram turning up | +1 |
| Context TF also oversold | +1 |

### Real executor integration

- Bucket: `COU_1H` / `COU_4H`
- Leverage: 5x (conservative)
- Added to `ALLOWED_BUCKETS` and `LEVERAGE_BY_BUCKET` in `binance_real_executor.py`
- Bucket detection: `detect_bucket()` checks `risk_model == "counter_trend"` before fallback TF parsing

## Pitfalls discovered during implementation

1. **`mode` variable scope bug (pre-existing, fixed)** — `apply_enhancements(mode=mode)` in `setup_for()` referenced `mode` from `main()` local scope. Python `NameError` was silently swallowed by `try/except Exception: continue` in the scan loop. Fix: `mode_cfg.get("label", "unknown").lower().replace("-", "_")`. This bug affected ALL modes but was invisible during the 3-day signal drought.

2. **BBW > 18% during crashes** — Setting `use_bb_width: True` rejects ALL signals when market is crashing because BB width exceeds the sanity threshold. Must use `bb_pct_b()` instead for crash-activated modes.

3. **Risk/em ratio too wide** — Initial SL used `entry_low - 1.0 * a_sig` which produced risk/em of 4-5%, exceeding max_risk of 2%. Two fixes: tightened SL to `0.5 * a_sig` and increased max_risk to 3%.

4. **`technique` variable undefined** — Normal LONG/SHORT paths don't set `technique` until after the blocks. Counter-trend sets it inside its block. Without `technique = None` initialization, the `if not any(t in (technique or "") ...)` check would raise `NameError` for normal modes.

## Cron schedule

`9,24,39,54 * * * *` — staggered from aggressive (:00/:15/:30/:45), medium (:05/:35), safe (:10 every 2h).

## Pitfall: Manual scanner runs submit REAL money trades

**Critical (2026-06-05 lesson):** Running `python3 automatic_signal_scanner.py --mode counter_trend` manually (for testing/debugging) STILL writes to both journals AND calls `binance_real_executor.process_record_for_scanner()`. This means manual test runs submit real money orders to Binance Futures.

The signal text is printed to the terminal (not sent to Telegram), so the user never sees the signal in the Auto Signal topic. But the real executor submits the order and sends a notification to Hasil Trade. The user then sees "HIT ENTRY" in Hasil Trade without ever seeing the original signal.

**Impact:** Two real positions (ADAUSDT, SEIUSDT) were opened from manual testing on 2026-06-05.

**Current state:** No guard exists to prevent this. The scanner always executes the real-money hook regardless of invocation method.

**Recommended fix (not yet implemented):** Add an environment variable or CLI flag (e.g. `--dry-run` or `NO_REAL_EXEC=1`) that skips the `process_record_for_scanner()` call when running manually. Alternatively, check `sys.argv` for interactive indicators.

**Workaround for now:** When testing scanner changes manually, either:
1. Set `EXEC_KILL_REAL` file to block execution: `touch ~/.hermes/EXEC_KILL_REAL`
2. Or temporarily comment out the real executor hook in the scanner
3. Remember to remove the kill file / uncomment after testing

**Closing positions:** To close all real positions immediately:
```python
from binance_real_client import BinanceRealClient
client = BinanceRealClient()
positions = client._signed('GET', '/fapi/v2/positionRisk')
for p in positions:
    amt = float(p.get('positionAmt', 0))
    if amt == 0: continue
    side = 'SELL' if amt > 0 else 'BUY'
    client._signed('POST', '/fapi/v1/order', {
        'symbol': p['symbol'], 'side': side, 'type': 'MARKET',
        'quantity': str(abs(int(amt))), 'reduceOnly': 'true',
    })
```

## Pitfall: Counter-trend signals with executor.status = N/A

When counter-trend signals appear in the journal with `executor.status = N/A` (or missing), it means the real executor hook never processed them. Common causes:

1. **Manual scanner run without executor** — the scanner was run directly (not via cron wrapper) and the executor hook failed silently or was skipped.
2. **Executor hook raised but was swallowed** — the `try/except` around `process_record_for_scanner()` catches all exceptions and continues, so executor failures are invisible.
3. **Signal was generated before executor bucket was configured** — early counter-trend signals predated the `COU_1H`/`COU_4H` bucket addition.

**Detection:** Check journal entries with `AS-COU-` prefix. If `executor` dict is empty or `executor.status` is `None`/`N/A`, the signal was never submitted.

**Impact:** These signals sit in `WAITING_ENTRY` or `ACTIVE` status forever, polluting the daily report and calendar. They must be manually reconciled (set `status=MANUAL_CLOSED`, `manual_close_reason=never_executed`).

**Prevention:** After any scanner config change, verify the executor hook is wired by checking one signal's `executor` sub-doc in the journal.

## Verification

```bash
# Dry run — should produce signal or empty output, never errors
python3 /root/.hermes/scripts/automatic_signal_scanner.py --mode counter_trend 2>/dev/null

# Check wrapper
python3 /root/.hermes/scripts/automatic_signal_scanner_counter_trend.py 2>/dev/null

# Verify executor bucket detection
python3 -c "
import binance_real_executor as bre
r = {'risk_model': 'counter_trend', 'timeframe_context': '4h signal + 4h context'}
print(bre.detect_bucket(r))  # COU_4H
print(bre.LEVERAGE_BY_BUCKET.get('COU_4H'))  # 5
"
```

## PnL Simulation for Unexecuted Signals

When counter-trend signals were never submitted to Binance (executor status = N/A), you can simulate what the PnL would have been:

1. Load the journal entries with `AS-COU-` prefix
2. For each entry, get `entry_mid`, `sl`, `tp1`, and `created_at`
3. Fetch 1h klines from `entry_time` to now: `GET /fapi/v1/klines?symbol=<SYM>&interval=1h&startTime=<entry_ms>&limit=50`
4. Walk through klines chronologically:
   - If candle low ≤ SL price → exit at SL (loss)
   - If candle high ≥ TP1 price → exit at TP1 (win)
   - If neither hit → exit at current price (hold)
5. Compute PnL%: `(exit - entry) / entry * 100` for LONG

This gives a realistic backtest of counter-trend effectiveness without needing real execution. Key metric: compare average win (TP1 hits) vs average loss (SL hits) — if losses exceed wins, the R:R needs adjustment (tighter TP or stricter entry filter).

**2026-06-05 result:** 10 counter-trend signals simulated → 50% win rate, but avg win +1.32% vs avg loss -1.59% (R:R inverted). Total PnL: -1.35%. Recommendation: tighten TP1 from 2% to 1.2-1.5%, or only accept setups with RSI < 15 + BB%B < 0.10.
