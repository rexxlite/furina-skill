# LLM Entry Gate (Mode 1) — judgment layer before real-money entries

Added 2026-06-30. A way to insert an LLM as a **final veto-only gate** on top of the
deterministic rule-based scanners, WITHOUT letting the LLM touch risk management.

## The three modes the user may ask for (clarify which one)

When the user says "trade using the LLM", it can mean very different things. Always
disambiguate before building:

- **Mode 1 — LLM as final gate (BUILT, recommended):** scanner fires candidate →
  LLM reviews context → APPROVE / VETO only. LLM never sets size/SL/TP. Lowest risk,
  highest value-per-effort.
- **Mode 2 — LLM as signal generator (full autopilot):** no scanner; LLM reads raw
  market data and invents entries. HIGH RISK — flag hard: hallucinated levels,
  non-deterministic (can't backtest), latency, cost, provider-outage = blind. If user
  insists, build with strict deterministic guards + shadow/paper first.
- **Mode 3 — co-pilot manual:** user asks, LLM answers with data, user executes. Safe,
  no auto-trade.

User chose **Mode 1** this session (good instinct — they initially leaned Mode 2 but
accepted the Mode 1 reasoning).

## Architecture (binance_real_executor.py)

Injection point: in the per-record path, **right before `execute_signal()` is called**
(after ALL deterministic guards have passed: KILL/PAUSE → daily limits → bucket
allowlist → blacklist → same-symbol → manual-position guard → asia-session →
max-concurrent). The LLM is the LAST gate before the order hits Binance, so it only
ever sees candidates that are already safe-by-construction.

Module: `/root/.hermes/scripts/llm_entry_gate.py`, function `evaluate(record) -> dict`
returning `{"approved": bool, "verdict": "APPROVE"/"VETO"/"ERROR"/"BYPASS", "reason",
"confidence", "shadow"}`.

Executor wiring (guard `if not PAPER_MODE:`), on `not gate["approved"]`:
set `executor.status=SKIPPED`, `skip_reason="llm_veto"`, attach `executor.llm_gate=gate`,
emit a `🧠 [LLM-GATE] SYMBOL SIDE VETOED — reason` notification, return skipped.
On approve, still attach `executor.llm_gate` for audit, then continue to `execute_signal`.

## Non-negotiable design rules

1. **LLM can ONLY APPROVE or VETO.** It never changes size, SL, TP, or risk. Those stay
   100% deterministic Python. One hallucination must not be able to drain the account.
2. **FAIL-OPEN.** Provider error/timeout/garbage JSON → `approved=True` (log the failure).
   Rationale: the upstream deterministic guards already make every candidate safe; the
   LLM is an extra filter, not a dependency. An Anthropic/provider outage must never
   freeze a system that was profitable without the LLM. Wrap the whole gate call in the
   executor in a defensive try/except too (double fail-open).
3. **Three toggle files** (env-free, flip without redeploy):
   - `/root/.hermes/LLM_GATE_SHADOW` present → evaluate + log verdict but ALWAYS approve
     (collect agreement data before trusting the veto).
   - `/root/.hermes/LLM_GATE_OFF` present → bypass entirely (verdict BYPASS).
   - neither → enforce (VETO actually blocks).
4. **Log every verdict** to `/root/.hermes/trading_journals/llm_gate_log.jsonl`
   (ts, symbol, side, scanner, score, verdict, confidence, reason, shadow, elapsed_s,
   cost_usd, enforced).
5. **Always start in SHADOW mode**, same discipline as the testnet→mainnet switch. Run
   3–7 days, then audit: how many VETOs were correct (trade would have hit SL) vs wrong
   (would have hit TP). Only flip to enforce if the gate demonstrably adds edge. If it
   buries profit, leave it off — zero cost since shadow never blocked anything.

## Provider call (compute.virtuals.io)

OpenAI-compatible. **Verify the endpoint with a real curl before building anything** —
don't assume the chat-session provider is callable programmatically from cron:

```
POST https://compute.virtuals.io/v1/chat/completions
Authorization: Bearer <acp-... key from config.yaml model.api_key>
{"model":"anthropic-claude-opus-4-8","messages":[...],"max_tokens":600,"temperature":0}
```

Observed: HTTP 201, ~1.7s latency, returns OpenAI-shape `choices[0].message.content`,
plus a `cost.usd` field (~$0.002/call with prompt caching). ~60 entries/day ≈ $0.13/day.
The key lives in `config.yaml` under `model.api_key` (current setup uses
`model.provider: custom` + `base_url: https://compute.virtuals.io/v1`).

Robust JSON parse: strip ```code fences```, then slice first `{` … last `}` before
`json.loads` — the model sometimes wraps the JSON in prose despite instructions.

## Prompt shape that worked

Give the LLM: symbol, side, scanner bucket, score vs min_score, planned entry/SL/TP,
scanner reasoning, BTC bias (1h + 1D via `base.detect_btc_bias()` /
`detect_btc_bias_long()`), and a compact indicator snapshot (RSI 15m/1h, EMA20/50 1h,
ATR 15m, last 6×1h OHLC, EMA20 4h) built from `base.klines()` (reuse the scanner's
helpers so the gate adds minimal extra Binance calls). Instruct: "default to APPROVE
unless a concrete, specific reason this hits SL; be conservative with vetoes — the
scanner has a real edge; only veto clear traps." Demand strict JSON:
`{"verdict","confidence","reason (<=20 words)"}`.

Verified behaviour both directions: stale entry ($2400 vs live $1583, ~52% away) →
VETO conf 0.95; sane entry near price + RSI oversold → APPROVE conf 0.6 with a nuanced
note ("BTC bearish is only concern") — exactly the judgment the rules can't express.

## Pitfall

`execute_code`-style auto-redaction can mangle an API key/config block when writing the
module via write_file (keys get masked, adjacent lines merge). After writing, re-read the
config lines (ENDPOINT/API_KEY/MODEL/TIMEOUT/MAX_TOKENS) and fix any corruption before
running the compile check.
