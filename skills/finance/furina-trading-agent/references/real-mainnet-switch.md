# Demo/Testnet → Real Mainnet Switch (Furina)

Procedure + techniques from the 2026-06-26 live switch. The system is a **single
codebase** — there is no separate "demo" vs "real" program. The ONLY differences
between testnet and mainnet are `BASE_URL` + API key/secret in
`/root/.hermes/secrets/binance_real.env`. Flip those and the same executor/
reconciler/scanners trade real money. So the switch is mostly about *safety
sequencing*, not code changes.

**The switch is BIDIRECTIONAL** — the exact same procedure runs real→testnet
(2026-07-06) as testnet→real (2026-06-26). Only the target BASE_URL + key differ.
Testnet BASE_URL = `https://testnet.binancefuture.com`, mainnet =
`https://fapi.binance.com`. Testnet wallet is a fixed faucet amount (e.g. 5000
USDT) which `EQUITY_CAP` still caps down to the configured nominal ($300).

**Env var names (verify, don't assume):** `binance_real_client.py` (ENV_PATH
`/root/.hermes/secrets/binance_real.env`, ~L38, L64-66) reads
`BINANCE_REAL_API_KEY`, `BINANCE_REAL_API_SECRET`, `BINANCE_REAL_BASE_URL` — note
the `_REAL_` infix. Do NOT write `BINANCE_API_KEY`/`BINANCE_BASE_URL` (a plain
`printf` template with the wrong names produces a file the client can't read).
Grep `binance_real_client.py` for `env[` / `env.get(` to confirm the exact keys
before writing the env.

**Before cutting the OLD key loose, check for orphaned positions.** Probe the
still-active account for open positions FIRST. In the 2026-07-06 switch the old
real key was already invalid (HTTP 401 -2015) so nothing could be orphaned, and
the Furina journal showed zero active records — but confirm both (live
positionRisk if the key still works, AND journal ACTIVE/WAITING_ENTRY/PENDING/
SUBMITTED/PARTIAL scan) before proceeding. Any live position you can't close
because the key died stays stranded on that account.

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
   printf 'BINANCE_REAL_API_KEY=%s\nBINANCE_REAL_API_SECRET=%s\nBINANCE_REAL_BASE_URL=https://fapi.binance.com\nPAPER_MODE=False\n' "$K" "$S" > /root/.hermes/secrets/binance_real.env
   chmod 600 /root/.hermes/secrets/binance_real.env
   ```
   **CRITICAL — exact var names.** `binance_real_client.py` (~L64-66) reads
   `BINANCE_REAL_API_KEY`, `BINANCE_REAL_API_SECRET`, `BINANCE_REAL_BASE_URL` —
   all with the `_REAL_` infix. Do NOT write the unprefixed `BINANCE_API_KEY` /
   `BINANCE_BASE_URL` forms; the client raises `KeyError` on load and nothing
   trades. Mainnet BASE_URL = `https://fapi.binance.com`, testnet =
   `https://testnet.binancefuture.com`.
   **Pitfall — output masking hides len verification.** The terminal masks lines
   containing `API_KEY`/`API_SECRET`, so `awk '{print length}'` prints `*** chars>`
   instead of the number. Verify lengths with a Python one-liner that parses the
   env into a dict and prints only `len(...)` + a head/tail slice (e.g.
   `key[:6]+'...'+key[-4:]`) — never the raw value. Both key and secret must be
   len=64.
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

## Reverse switch: Real Mainnet → Demo/Testnet

Same mechanics, opposite direction (done 2026-07-06). Only `BINANCE_REAL_BASE_URL`
+ key/secret change. Sequence mirrors the go-live but the final confirmation is
still gated the same way (KILL flag first, `rm` only after explicit "ya, lepas
flag").
1. `touch /root/.hermes/EXEC_KILL_REAL` first.
2. Backup the current real env: `cp binance_real.env binance_real.env.bak.real.<ts>`.
3. **Check for orphaned real positions BEFORE cutting the connection.** Probe the
   real account for open positions — if any exist they'll be left hanging on
   mainnet once you switch BASE_URL. Note: the outgoing real key is often already
   revoked by the user (probe returns `HTTP 401 code=-2015 Invalid API-key`),
   which conveniently means nothing can be orphaned — but confirm via the Furina
   journal too (`status in {ACTIVE,WAITING_ENTRY,PENDING,SUBMITTED,PARTIAL}`).
   Empty journal + dead key = clean to switch.
4. Write testnet env with `BINANCE_REAL_BASE_URL=https://testnet.binancefuture.com`
   and the testnet key/secret (same `_REAL_` var names).
5. Verify the testnet key live: reload the client, read USDT wallet + open
   positions. A fresh testnet account reads ~5000 USDT faucet balance.
6. **EQUITY_CAP still governs sizing even when the wallet is huge.** Executor uses
   `min(available_balance, EQUITY_CAP)`, so a 5000-USDT testnet wallet with
   `EQUITY_CAP=300.0` still sizes every trade off $300 — "modal $300, risk sama
   seperti sebelumnya" needs NO config edit if EQUITY_CAP/RISK_PCT are already at
   the $300 values. Verify the config block, don't blindly re-write it.
7. Archive the mainnet journals → `*.mainnet_archive_<ts>.json`, reset live
   journals to `[]`, and reset `real_risk_state.json` → `{}` so the daily
   profit-target / loss-limit counter starts clean on the new venue.
8. Ask final confirmation, then `rm EXEC_KILL_REAL`. On testnet the LLM entry gate
   is optional — offer SHADOW (log-only, more signals flow for data collection)
   vs ENFORCE.

## Testnet listing mismatch: scan mainnet, execute testnet (`symbol_not_on_futures`)

On testnet, scanners still `build_universe()` from **mainnet** data
(`https://fapi.binance.com` is hardcoded in each scanner's `BASE`), but the
executor trades on **testnet** (`BINANCE_REAL_BASE_URL`). Testnet lists fewer
perps (~570) than mainnet, so any signal on a mainnet-only symbol dies at the
executor with `skip_reason = symbol_not_on_futures`. Observed 2026-07-06: REUSDT
LONG (FUNDING, score 5) fired but skipped — REUSDT exists on mainnet, not on
testnet. This is NOT a liquidity/gate rejection and NOT a bug; it's a venue
listing gap. When the user asks "belum ada signal?" on testnet, check
`executor.skip_reason` — `symbol_not_on_futures` means the symbol isn't listed on
the execution venue, distinct from `manual_position_held`, `llm_veto`,
`asia_session_score_too_low`, or a thin-book depth reject.

Two ways to handle (user's choice; recommend option 2 for representative testnet
results):
1. Leave as-is — accept that some good signals hang because testnet doesn't list
   the symbol. Simplest, realistic for paper testing.
2. Filter `build_universe()` to intersect with the testnet perp list (one extra
   `exchangeInfo` call against `BINANCE_REAL_BASE_URL` per scan) so scanners only
   emit executable signals.

To enumerate testnet perps: GET
`https://testnet.binancefuture.com/fapi/v1/exchangeInfo`, keep
`status=='TRADING' and contractType=='PERPETUAL'`.

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
