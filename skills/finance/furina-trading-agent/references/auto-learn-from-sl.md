# Auto-Learn From SL — System Reference

When the user said "otomatis learn by experience ketika hit sl dan pelajarin agar tidak terjadi lagi", the durable answer was a five-component pipeline that turns each SL hit into a classified lesson, clusters lessons into pattern proposals, and applies user-approved filters back into the scanner. This file is the canonical description of that system.

## Architecture (5 components)

```
SL_HIT closure
    ↓ reconciler enqueue (binance_real_reconciler.py SL_HIT branch)
sl_postmortem_queue.json
    ↓ */10min cron (postmortem analyzer)
sl_lessons.json   ← per-trade classified failure_mode + metrics
    ↓ weekly cron Mon 08:00 WIB (aggregator)
sl_rule_proposals.json   ← cluster ≥ N hits → proposal with pseudo_filter
    ↓ user approval (lesson_approve.py CLI)
sl_active_rules.json   ← filters loaded by scanner per signal
    ↓ scanner inline call (automatic_signal_scanner.py)
veto candidate setups before journal/notify
```

All files live in `~/.hermes/trading_journals/`. Active scripts live in `~/.hermes/scripts/`.

## File map

| File | Role |
|---|---|
| `automatic_signal_postmortem.py` | classify SL hits into failure modes |
| `automatic_signal_lesson_aggregator.py` | cluster lessons, generate proposals |
| `automatic_signal_active_rules.py` | filter registry + `apply_active_rules(ctx)` |
| `automatic_signal_lesson_approve.py` | CLI: APPROVE / REJECT / LIST / STATUS |
| `binance_real_reconciler.py` | enqueue on SL_HIT (best-effort try/except) |
| `automatic_signal_scanner.py` | calls `apply_active_rules` after setup build, before return |

State:

- `~/.hermes/trading_journals/sl_postmortem_queue.json` — list of journal IDs awaiting analysis
- `~/.hermes/trading_journals/sl_lessons.json` — classified lessons (append-only, dedup by trade id)
- `~/.hermes/trading_journals/sl_rule_proposals.json` — proposals with status `PENDING_APPROVAL` / `APPROVED` / `REJECTED`
- `~/.hermes/trading_journals/sl_active_rules.json` — only APPROVED filters, loaded by scanner each tick
- `~/.hermes/trading_journals/sl_approval_log.jsonl` — audit trail of decisions

## Failure modes (8 + 2 sentinels)

Each mode has a detection rule and an associated rule template (`RULE_TEMPLATES` in the aggregator). Decision tree priority (most specific first):

1. **LATE_ENTRY** — MFE never exceeded 0.3R (signal wrong from start)
2. **EMA_RECLAIM** — within first 3 bars after fill, price wicked through entry-TF EMA20 against direction and closed against signal
3. **TIGHT_SL** — risk_pct < 0.9% AND bars_to_sl ≤ 4
4. **FAKEOUT_NEAR_TP1** — MFE between 0.6R and 0.95R then reversed past entry
5. **VOLUME_REVERSAL** — vol ≥ 2.5x avg candle in opposite direction inside trade window
6. **ZONE_HOLD** — TP1 zone tested 3+ times during trade, never broke
7. **MOMENTUM_EXHAUSTION** — 1h EMA20/EMA50 cross flipped opposite during window
8. **BTC_DIVERGENCE** — BTC moved ≥ 1.5% against trade direction during window

Sentinel returns (no `metrics` key, do not crash on these):
- **MISSING_DATA** — core fields incomplete in journal record
- **NO_KLINES** — Binance returned empty klines for the window
- **UNCATEGORIZED** — no rule matched but trade did close at SL

## Proposal thresholds

The aggregator emits one proposal per `(failure_mode, scope, count_bucket)`:

- Short scope: last **14 days**, threshold **≥ 3 hits**
- Long scope: last **30 days**, threshold **≥ 5 hits**

`rule_key` is `<MODE>::<SCOPE>::<BUCKET>` where BUCKET ∈ {3, 5, 10, 20} so the same pattern re-fires at higher count milestones (e.g. `EMA_RECLAIM::14d::10` is a fresh proposal once 10 hits accumulate, even if `::3` was already approved). Existing proposals in `sl_rule_proposals.json` are skipped by `rule_key` to avoid spam.

## Filter registry pattern

`automatic_signal_active_rules.py` exposes:

```python
def apply_active_rules(ctx: dict) -> tuple[bool, list[str]]:
    """Returns (passes, reasons). passes=False vetoes the signal."""
```

`ctx` keys (must populate from scanner):

- `symbol`, `side`, `signal_tf`, `ctx_tf`, `bucket`
- `price`, `entry_low`, `entry_high`, `sl`, `tp1`
- `ema20`, `ema50`, `ema20_ctx`, `ema50_ctx`
- `recent_high`, `recent_low`
- `candles_signal`, `candles_context` — list of dicts with `o,h,l,c,v`
- `vol_ratio`, `atr`, `rsi`, `chg24`
- `btc_bias`, `btc_15m_ema20_slope`
- `mode_cfg`

Filter functions return `None` (pass) or `str` (veto reason). Bucket scoping: `buckets_targeted=[]` means "all buckets"; otherwise the rule only applies when current bucket matches one targeted.

The scanner call site is wrapped in `try/except ImportError` so the active-rules module is optional. Filter exceptions are caught per-rule and logged to stderr — a buggy filter must never break the scanner.

## Cron jobs

- `7174c69bbf27` — `automatic_signal_postmortem.py` every 10 min, deliver=local (silent unless queue non-empty)
- `6fdba77cc862` — `automatic_signal_lesson_aggregator.py --notify` weekly Mon 08:00 WIB → topic 129

## CLI

```bash
# Inspect
python3 ~/.hermes/scripts/automatic_signal_lesson_approve.py LIST
python3 ~/.hermes/scripts/automatic_signal_lesson_approve.py STATUS

# Decide
python3 ~/.hermes/scripts/automatic_signal_lesson_approve.py APPROVE EMA_RECLAIM::14d::3
python3 ~/.hermes/scripts/automatic_signal_lesson_approve.py REJECT  EMA_RECLAIM::14d::3 "too aggressive"

# Manual postmortem (one-shot or backfill)
python3 ~/.hermes/scripts/automatic_signal_postmortem.py --id <JOURNAL_ID>
python3 ~/.hermes/scripts/automatic_signal_postmortem.py --backfill

# Cluster report (no proposals saved)
python3 ~/.hermes/scripts/automatic_signal_lesson_aggregator.py --report
```

## Pitfalls

1. **`metrics` key is NOT always present.** When `classify()` returns `MISSING_DATA` or `NO_KLINES` it omits `metrics`. The CLI summary path must `res.get("metrics")` and fall back to a short warning line, not `res["metrics"]` directly. (Caught during 2026-05-26 backfill — KeyError after 49 successful classifications.)

2. **Symbol resolver matters for paper journal.** Some legacy paper rows have `symbol` only on the top-level record, others have it under `executor.symbol` or `execution.symbol`. The `find_trade()` and `classify()` helpers must check both.

3. **Don't trust BUCKET label format.** Real journals use `AGGR_30M`, `AGGR_15M`, `AGGR_1H`, `MED_1H`, `SAFE_4H`. Paper journals sometimes carry only `risk_model` (`aggressive`, `medium`, `safe`). The aggregator merges both naming styles into `buckets_breakdown` Counter — when reading proposals, target both formats in `buckets_targeted` if writing a bucket-scoped filter.

4. **Reconciler hook is best-effort.** The SL_HIT branch wraps the queue write in `try/except` and swallows errors silently. Postmortem queueing must never block trade closure. If the queue file is corrupted, the analyzer's `load_queue()` returns `[]` and the cron just no-ops next tick.

5. **Don't auto-patch scanner code from approved rules.** APPROVE only marks the rule active; the actual filter logic lives in `FILTER_REGISTRY` which must be hand-written per failure_mode. Adding a new failure mode means BOTH (a) classifier branch in postmortem AND (b) filter function in active_rules. The system propagates KNOWN modes only — it doesn't generate filter code from natural language.

6. **Filter must apply to ALL scanner modes, not just the bucket where the lesson came from.** When `buckets_targeted=[]` (default), the filter runs for every signal. This is intentional — an EMA_RECLAIM pattern that hurt AGGR signals is also bad signal hygiene for MEDIUM/SAFE. Only set `buckets_targeted` if the user explicitly wants the rule scoped.

7. **Counting open trades from the journal at SL_HIT time is fine, but don't try to compute realized P&L from `executor.real_pnl_usdt` if the field is missing on older rows.** Use `(entry - sl) / entry * qty * leverage` as fallback or skip the loss-attribution display for that row.

## Adding a new failure mode

1. Add classifier branch in `automatic_signal_postmortem.py` → `classify()` decision tree, before `UNCATEGORIZED`.
2. Add `RULE_TEMPLATES["NEW_MODE"]` entry in `automatic_signal_lesson_aggregator.py` with `title`, `rationale`, `pseudo_filter`, `scanner_section`.
3. Add `_filter_new_mode(ctx)` function in `automatic_signal_active_rules.py` returning `None` or veto reason; register in `FILTER_REGISTRY`.
4. Run `--backfill` to retroactively classify past SL hits with the new mode.
5. Verify with `--report` that the new mode shows up in clusters before letting the weekly aggregator run.

## Approval workflow expectations

- Aggregator weekly cron emits proposals to topic 129. User reviews via Telegram, replies with the suggested CLI command, Furina runs it.
- After APPROVE, scanner picks up the new active rule on next tick — no reload needed (it reads `sl_active_rules.json` per call).
- After REJECT, the rule is marked rejected; the SAME rule_key won't be re-proposed, but a HIGHER bucket (`::5` after `::3` was rejected at 3 hits) will fire fresh because `rule_key` differs. This is intentional — escalation past explicit rejection requires the user to reject again at the new threshold.
- The system does NOT auto-patch scanner code. APPROVE only activates the configured filter. If the lesson requires a filter that doesn't exist yet in `FILTER_REGISTRY`, the proposal becomes documentation, not enforcement, until the filter is hand-written.
