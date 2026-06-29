# Demo/Testnet → Real Mainnet Switch (Furina)

Procedure + techniques from the 2026-06-26 live switch. The system is a **single
codebase** — there is no separate "demo" vs "real" program. The ONLY differences
between testnet and mainnet are `BASE_URL` + API key/secret in
`/root/.hermes/secrets/binance_real.env`. Flip those and the same executor/
reconciler/scanners trade real money. So the switch is mostly about *safety
sequencing*, not code changes.

## Golden rule: KILL flag FIRST, confirm LAST

The user (operator) gates real-money go-live on diligence, not eagerness. Never
release the killswitch without an explicit final "ya, lepas flag" at the
point-of-no-return.

Ordered sequence (do NOT reorder):
1. `touch /root/.hermes/EXEC_KILL_REAL` — freeze executor so nothing fires mid-switch.
   - KILL_FILE checked at binance_real_executor.py ~L58; PAUSE_FILE ~L59. When the
     flag file exists the executor exits before placing any order.
2. Backup the current (testnet) env: `cp binance_real.env binance_real.env.bak.testnet.<ts>`.
3. Write the new mainnet env. **Pitfall:** `write_file` and long tool-arg strings
   corrupt 64-char API keys/secrets (truncation/escaping). Write the env via the
   terminal using shell variables instead:
   ```bash
   K='...'; S='...'
   printf 'BINANCE_API_KEY=%s\nBINANCE_API_SECRET=%s\nBINANCE_BASE_URL=https://fapi.binance.com\nPAPER_MODE=False\n' "$K" "$S" > /root/.hermes/secrets/binance_real.env
   chmod 600 /root/.hermes/secrets/binance_real.env
   ```
   Verify with `awk '{print length}'` that key+secret are both len=64. Mainnet
   BASE_URL = `https://fapi.binance.com` (testnet = `https://testnet.binancefuture.com`).
4. Verify the key works AND inspect the account BEFORE releasing the flag. Write a
   throwaway probe (e.g. /tmp/verify_real_key.py) that prints BASE_URL, available
   USDT balance, and **all open positions**. Confirm: (a) balance reads, (b) no
   *unexpected* positions. In this switch 3 unexpected positions showed up
   (ARX/KORU/NEAR) — they turned out to be the user's own manual entries. STOP and
   ask the user about any position you didn't open.
5. Adjust config for the smaller real equity (see "Re-sizing" below).
6. Archive testnet journals; reset real journals to `[]` (see "Journal hygiene").
7. Ask the user the final confirmation question. ONLY after "ya" →
   `rm /root/.hermes/EXEC_KILL_REAL` to go live.
8. Watch the first scanner that fires real money: verify sizing (~equity×risk% loss
   at SL) and that the SL order is placed alongside the entry.

## Re-sizing for a smaller real account

Boosts/leverage calibrated on a $1000 testnet are too aggressive on a $300 real
account. For the 2026-06-26 $300 switch:
- `EQUITY_CAP = 300.0` (nominal; actual available ~$285, rest is margin on the
  user's manual positions which share the same pool).
- `RISK_PCT = 0.01` FLAT, `RISK_PCT_BY_BUCKET = {}` (drop all per-bucket boosts —
  recalibrate later with real fills, not testnet-tuned numbers).
- `MAX_CONCURRENT_POSITIONS = 6` (down from 10).
- `LEVERAGE_BY_BUCKET` left untouched (OI_DIV/COU 5x, FUNDING/LIQ/ALPHA 4x, default 8x).

**Why MAX_CONCURRENT=6 is NOT a margin constraint.** Simulation over 217 actual
trades (margin = notional/leverage): 6 slots ≈ $108 margin (36% of $300), 10 slots
≈ $180 (60%). Margin fits 10 easily. The real binding limit is **aggregate
drawdown** — crypto is highly correlated, a market-wide dump can hit many SLs at
once. Worst case 6 positions stopped out simultaneously at flat 1% = -6% = -$18.
That correlated-drawdown ceiling, not margin, is why you cap concurrency.

**Leverage ≠ risk.** Position qty = equity × risk% ÷ (entry-to-SL distance), so
risk-per-trade is fixed by RISK_PCT regardless of leverage. Higher leverage only
moves the liquidation price further behind the SL (more buffer) and frees margin.
Don't let the user conflate "5x leverage" with "5% risk" — surface this whenever
leverage comes up.

## Manual / external position guard (section 2b3)

The user trades manually on the SAME real account Furina uses (one-way CROSSED
mode), so margin is shared and a scanner firing on a symbol the user holds manually
would ADD-TO / NETT-AGAINST their position and hijack its TP/SL.

Guard added in binance_real_executor.py **section 2b3** (after the same-symbol
guard 2b2, ~L832, placed after `sym_upper` is defined ~L797):
- Pull live `positionRisk` via `client.position_risk()`.
- For the candidate symbol, if there is an OPEN position on Binance but NO active
  Furina record in the journal for that symbol → skip with
  `skip_reason = manual_position_held_{sym}`.
- **Self-healing, no hardcoded symbol list** — it reads live state each run, so it
  automatically adapts when the user opens/closes manual positions on other pairs.

This complements section 2b2 (same-symbol guard: one active Furina position per
pair across all scanners, `symbol_already_active_X`).

Note Furina's own slot accounting is journal-based (`FURINA_PREFIX="FRR-"`
clientOrderId; active_count counted from Furina journal records), so manual
positions never consume a MAX_CONCURRENT slot — but they DO consume shared margin
and must be stood aside from. The reconciler SL-GUARD will also yell NAKED for any
manual position lacking a stop; verify the user's manual positions already carry
STOP+TP before go-live (probe their open orders).

## leverage_setup position-side bug fix (root cause of naked-window)

Symptom: 26 signals ERROR'd with `leverage_setup: ... Position side cannot be
changed ...` (plus 5 with "Leverage X not valid"). These errors fire BEFORE any
order is placed (bucket/lev/margin fields are None on the ERROR record), so they
are NOT themselves a source of naked positions — but the same fragile setup block
was the root cause behind the few-minute naked window the SL-GUARD has to patch, so
fix it before go-live.

Old code tolerated only `-4048`. Fix (binance_real_executor.py ~L525-533):
- Split `set_margin_mode` and `set_leverage` into TWO separate try blocks.
- Tolerate the full set of benign "already set / cannot be changed" codes:
  `{-4046, -4048, -4061, -4067, -4068}` plus a message match on
  `"cannot be changed"` / `"no need to change"`. These are non-fatal because qty is
  computed from the SL distance, not from leverage.
- Add automatic leverage step-down `20→10→8→5→3→2→1` to handle "Leverage X not
  valid" (symbol's max leverage is below the configured value).

## Journal hygiene on switch

- Archive testnet journals rather than deleting:
  `automatic_signal_real_journal.json` + `binance_alpha_real_journal.json` →
  `*.testnet_archive_<ts>.json`.
- Reset the live journals to `[]` so eval/dashboard start clean on real fills.
- Leave any open testnet positions hanging on the testnet account — they're on a
  different BASE_URL and no longer reachable once you've switched, which is fine.

## Removing losing scanners before real money

Use the 2-week per-bucket eval to prune. In the 12–26 Jun eval (344 closed, net
+$24.50) two scanners dragged the book: RANGE_MR (45 cls, WR 30%, −$136.69) and
BREAKOUT_RT (110 cls, WR 43%, −$85.69). Removing both lifts net to +$247. Remove
their cron jobs (RANGE_MR `787a2130c7e1`, BREAKOUT_RT `96b10463c57f`) — the bucket
config can stay in the executor; with no cron calling it, it's dormant.

## Pre-flight interrogation: answer from code, not memory

The user runs a layered due-diligence interrogation before sending API keys
("tindakan saat hit TP1/TP2/TP-max?", "evaluasi saat hit SL?", "ghost trade &
posisi tanpa SL ditangani?"). Answer EACH by reading the actual code (grep+read),
confirm the guard exists, and proactively fix root-cause bugs first. Verified
guards: SL-GUARD watchdog `ensure_stop_loss_guard` (reconciler ~L559) re-places
STOP_MARKET each tick + alerts "MANUAL ACTION NEEDED" if repair fails; ghost-trade
cross-reference in automatic_signal_monitor.py (`load_real_ex_status`) requires a
confirmed real fill before notifying. Be honest about residual windows (the
few-minute naked gap before the watchdog patches) rather than overclaiming.
