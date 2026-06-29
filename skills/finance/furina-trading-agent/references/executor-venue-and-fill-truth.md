# Executor Venue and Fill Truth Lessons

Use this reference when maintaining Furina's automated Binance signal/execution stack.

## 2026-05-19 ORDIUSDT venue confusion

Symptom: user saw `ORDIUSDT Perp — HIT ENTRY` from the Automatic Signal monitor, checked real Binance Perps, and saw no activity.

Facts:
- Testnet journal (`automatic_signal_journal.json`) had ORDI `ACTIVE`, venue `binance_testnet`, entry order filled at 4.1200.
- Real journal (`automatic_signal_real_journal.json`) had same ORDI signal `executor.status=SKIPPED`, `skip_reason=max_concurrent_5`.
- Real Binance API confirmed ORDI position/orders/trades were all zero.

Root cause:
- Hasil Trade thread mixes testnet and real execution alerts.
- The testnet monitor header did not include `[TESTNET]`, while real reconciler uses `[REAL]`.
- Answering from testnet API alone was wrong when the user explicitly meant real account.

Durable rules:
1. When user asks about account activity, first clarify/check venue: real vs testnet.
2. Cross-check three sources before answering: notification job name, relevant journal (`*_real_journal` vs testnet journal), and matching Binance API account.
3. Testnet execution notifications must include `[TESTNET]`; real notifications must include `[REAL]`.
4. Executor-backed HIT ENTRY must be based on exchange fill confirmation (`real_entry_fill_price`, filled order, or trade), not only mark price touching the entry zone.
5. If real executor skipped a signal, say the exact skip reason and do not imply the signal entered real money.

Verification snippets:
- Real ORDI check: `BinanceRealClient('/root/.hermes/secrets/binance_real.env').position_risk('ORDIUSDT')`, `open_orders`, `open_algo_orders`, `user_trades`.
- Testnet ORDI check: `BinanceTestnetClient('/root/.hermes/secrets/binance_testnet.env')` with the same methods.
