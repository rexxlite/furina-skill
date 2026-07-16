# LLM Entry Gate + Centralized Score-Bonus Wiring

Two reusable patterns for evolving Furina's deterministic scanner→executor
pipeline: (1) inserting an LLM as a final APPROVE/VETO gate without giving it
control over money math, and (2) applying a cross-scanner score bonus from one
central helper. Both were deployed 2026-06-30.

---

## A. LLM Entry Gate (Mode 1 — final gate, not signal generator)

### Design philosophy (the part the user cares about)
The user asked to "trade using the LLM directly." Before building, ALWAYS
clarify which of three architectures they mean:
- **Mode 1 (gate):** scanner generates candidates, LLM only APPROVE/VETO before
  execution. Deterministic math (size/SL/TP/limits) stays 100% Python.
- **Mode 2 (generator):** LLM replaces scanners as the signal source.
- **Mode 3 (hybrid):** mix.

Mode 1 is the safe, realistic choice and the one the user picked. It keeps the
scanner as the cheap/fast candidate generator and adds judgment only at the
final step. **The LLM may NEVER change size, SL, TP, or leverage** — one
hallucination must not be able to drain the account. It can only veto a
clearly-bad entry.

### Mandatory pre-flight before writing any code
The deliverable is a working gate backed by real tool output, never a plausible
stub. Verify the provider + model actually work with a real call FIRST:
1. Confirm provider is in `~/.hermes/config.yaml` (compute.virtuals.io block).
2. Fire a real `curl` to `https://compute.virtuals.io/v1/chat/completions`
   (OpenAI-compatible) with the model `anthropic-claude-opus-4-8`, asking for a
   fixed JSON reply. Confirm HTTP 2xx, latency, and clean JSON.
3. Fire a realistic trade-gate scenario and confirm the model returns
   **parseable structured JSON** (`{verdict, confidence, reason}`) — if it can't
   emit clean JSON the executor can't read its decision and the plan is dead.
4. Confirm it VETOes an obviously-bad entry (e.g. entry price 50% away from spot,
   or shorting a strong uptrend) AND approves a sane one. Test both directions.

Provider facts (2026-06): compute.virtuals.io, OpenAI-compatible, key `acp-...`
in config, ~$0.002/call, ~1.7s latency. Prompt caching makes repeat calls cheap.

### Integration point
Insert the gate in `binance_real_executor.py` at the LAST guard position —
right before `execute_signal()` is called (line ~980), AFTER every deterministic
guard has passed (KILL/PAUSE, daily profit/loss limits, bucket allowlist,
blacklist, same-symbol guard, manual-position guard, asia-session, max-concurrent).
This way the LLM only ever sees candidates that already survived all mechanical
filters — it's the final judgment layer, not a replacement for any guard.

### Module contract (`llm_entry_gate.py`)
- `evaluate(rec) -> (verdict, confidence, reason)` where verdict ∈ {APPROVE, VETO}.
- Pull a COMPACT market snapshot only (RSI 15m/1h, EMA20/50, ATR, last ~6h price
  action, BTC bias 1h+1D). Reuse `automatic_signal_scanner` (`base`) helpers —
  `base.klines()`, `base.detect_btc_bias()`, `base.detect_btc_bias_long()` — so
  the gate adds minimal extra Binance API load.
- **FAIL-OPEN:** any provider error/timeout/bad-JSON → APPROVE (logged). An
  Anthropic/provider outage must NOT freeze the whole system. No-trade-on-error
  would make the gate a single point of failure for the entire executor.
- Only run when `PAPER_MODE == False`.

### Executor wiring behavior
- VETO → executor returns SKIPPED with `skip_reason=llm_veto`, sends notif
  `🧠 [LLM-GATE] SYMBOL SIDE VETOED — <reason>`.
- APPROVE → proceed to `execute_signal()` normally.

### Toggle flags (deploy shadow first, then enforce)
- `touch /root/.hermes/LLM_GATE_SHADOW` → gate evaluates + logs verdict but does
  NOT block (log-only). **Deploy in shadow first.**
- `touch /root/.hermes/LLM_GATE_OFF` → bypass gate entirely.
- Remove `LLM_GATE_SHADOW` → enforce (VETO actually blocks).

### Rollout methodology (mirrors the user's testnet→mainnet discipline)
1. Deploy in SHADOW. Gate runs on every real signal, logs verdict to
   `/root/.hermes/trading_journals/llm_gate_log.jsonl` (fields:
   verdict/confidence/reason/enforced/shadow/cost_usd/elapsed_s), but doesn't block.
2. Collect 3-7 days of verdicts. Audit: for each VETO, did the trade (that still
   ran because shadow) actually hit SL (gate was right) or TP (gate cost profit)?
   For each APPROVE, what happened?
3. Only flip to ENFORCE once data shows the gate adds edge.
4. **CAVEAT — shadow verdicts are NOT enforced retroactively.** Signals evaluated
   during shadow still executed. When reading the log, only verdicts with
   `enforced:true` actually blocked anything. Don't confuse "gate said VETO" with
   "trade was blocked" until after the enforce flip.

The user may say "flip" to go straight to enforce with limited data — that's
their call. Just be explicit that early samples (e.g. 3 verdicts) are too small
to conclude the gate adds edge.

### Verification of the flip
Confirm effective mode from the gate's OWN logic, not from memory: SHADOW flag
absent + OFF flag absent + `LLM_GATE_ENABLED True`. Show the user the actual flag
state, not an assertion that it's enforcing.

---

## B. Centralized MAJORS score-bonus wiring across scanners

### The insight (answer to "why does Furina never trade BTC/ETH/SOL?")
Majors are NOT excluded from the universe — `build_universe()` takes the top
60-80 symbols by 24h quote volume, and BTC/ETH/SOL are literally rank #1/2/3.
The reason Furina rarely trades them is the **signal logic**: the scanners hunt
extremes (OI divergence, funding extremes, liquidation cascades). Blue-chips
have deep institutional liquidity and are highly efficient, so they rarely
produce the extreme anomalies these scanners fire on. Micro-caps produce those
extremes constantly — which is also why they're pump-and-dump traps. So the
scanner architecture structurally biased Furina toward low-quality names.

When the user asks a "why does the system never do X" question, VERIFY against
the actual universe-building + signal code before answering — don't guess. It's
usually signal logic, not a hard exclusion.

### The fix (Opsi A — quality tilt, not exclusion)
Add a small +1 score bonus for blue-chips. This makes major signals easier to
fire (need 1 fewer confirmation) while micro-caps still fire but need 1 more
real confirmation. Nothing is excluded — it just tilts firing toward quality.

### Wiring pattern (centralize once, call everywhere)
1. Define ONE source of truth in `automatic_signal_scanner.py` (the shared base
   module), next to `EXCLUDE_SYMBOLS`/`COMMODITY_KEYWORDS`:
   - `MAJOR_SYMBOLS` = set of ~20 blue-chip perps (BTC/ETH/SOL/BNB/XRP/ADA/DOGE/
     AVAX/LINK/TRX/DOT/MATIC/LTC/BCH/SUI/TON/NEAR/APT/UNI/HBAR).
   - `is_major(sym)` — case-insensitive membership.
   - `majors_score_bonus(sym)` — returns +1 for majors else 0.
2. Wire into each scanner immediately BEFORE its `MIN_SCORE` / `min_score` gate:
   - Scanners that `import automatic_signal_scanner as base` (OI_DIV, FUNDING,
     LIQ_CASCADE): `mb = base.majors_score_bonus(symbol); if mb: score += mb;
     reasons.append("major (blue-chip +1)")`.
   - The 4 trend scanners (aggressive/medium/safe/counter_trend) ALL share
     `setup_for(symbol, mode_cfg, ...)` inside `automatic_signal_scanner.py` — a
     SINGLE edit right before `if not side or score < mode_cfg["min_score"]:`
     (line ~860) covers all four. Call `majors_score_bonus(symbol)` directly (no
     `base.` prefix — same module).
3. `symbol` must be in scope at the scoring site — verify it's the first param of
   each `setup_for()` before patching.

### Pitfall
Before editing a scanner, confirm it's actually ACTIVE (has an enabled cron).
RANGE_MR and BREAKOUT_RT were deleted (lost money in 2wk eval) — don't waste
edits on dead scanners. `cronjob action=list` to check enabled state.

### Verify after wiring
Compile every touched scanner, then unit-test the helper: majors → +1,
micro-caps (incl. the ones that just hit SL) → +0, and a lowercase symbol → +1
(case-insensitivity). Show the truth table, don't assert it.

### Next step if it works (Opsi B)
After a 7-day eval comparing WR of major vs micro-cap signals, if majors prove
safer/profitable, the follow-up is a DEDICATED majors trend-following scanner —
trend-following suits large-cap character far better than anomaly-hunting does.
