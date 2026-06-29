# Scanner Remediation Methodology — fixing a losing scanner

When a scanner is bleeding (negative net / sub-breakeven WR) and the user wants it
fixed, **do NOT jump straight to tweaking score thresholds or parameters.** This
session (2026-06-23, range_mr + breakout_retest) proved that blind parameter tuning
can make things *worse*: a prior 06-21 "score-inversion fix" on breakout_retest moved
WR 44%→39% and net −$28→−$65. The fix touched scoring; the real bleed was directional.

## The procedure (evidence before action)

1. **A first, then B — stop the bleed before you study it.**
   If the user approves, `cronjob action=pause` the offending scanner job(s)
   immediately so no new bad signals fire while you diagnose. Re-`resume` only after
   the fix is in and syntax/smoke-tested. ("A sekarang dan B sambil jalan" = pause now,
   fix, resume running with the new filter.)

2. **Segment the journal — aggregate WR hides the real problem.** Read
   `/root/calendar_app/public/trades.json` and break each losing scanner down by:
   - **LONG vs SHORT** (almost always one side carries the loss — in a macro uptrend,
     SHORT fades/breakdowns bleed; both scanners here had SHORT as the worst segment:
     breakout_retest SHORT 38.5%WR −$42, range_mr SHORT 22%WR 2W/7L −$24).
   - **BEFORE vs AFTER the last code change** (split on the rework date). This tells you
     whether your *previous* fix helped or hurt. If AFTER is worse, the last change was
     wrong-headed — revert its premise, don't pile another tweak on top.
   - **Exit-kind breakdown** (`executor.close_kind` / status): count SL_HIT vs SL_BE_HIT
     vs TP1/2/3 and sum net USD per kind. A huge `SL_HIT` bucket = entries are wrong
     (bad direction / no macro filter), not that TPs are mis-sized.

3. **Field mapping for the audit** (trades.json):
   - net USD = `executor.real_net_pnl_usdt`
   - R-multiple = `result_r`
   - scanner key = `scanner_label.key` (fallback `risk_model`)
   - closed states = {TP1_HIT, TP2_HIT, TP3_HIT, SL_HIT, MANUAL_CLOSED, CLOSED}
   - `execute_code` is blocked in cron mode → use `write_file` a `/tmp/*.py` script +
     `terminal python3` instead.

4. **Fix the ROOT segment, not the score.** The three highest-leverage structural
   fixes (in order tried this session):
   - **LONG-only** (`SHORT_ENABLED = False`) when SHORT is the bleeding side and the
     macro regime is up. Removes a structural loss, doesn't just trim it.
   - **Add a higher-TF macro gate** the scanner was missing — e.g. only LONG when 4h
     price ≥ 4h EMA50 (`base.ema(htf_closes, 50)`), so you trade WITH the higher-TF
     trend. range_mr already had this for shorts; breakout_retest had no macro filter at
     all — that was the gap. Copy the proven gate across scanners.
   - **Raise MIN_SCORE by 1** to cut coin-flip marginal entries — but only as a
     secondary trim, and only if max_score leaves headroom (breakout_retest max is 4, so
     its MIN_SCORE stayed at 3; range_mr max 5 → raised 3→4).

5. **Verify before resume.** `python3 -m py_compile` both scripts; check the helper
   you rely on exists (`python3 -c "import automatic_signal_scanner as b; print(hasattr(b,'ema'))"`);
   run each scanner once manually (`timeout 120 python3 scanner.py`) — silent + exit 0
   is the expected/good outcome (gates legitimately reject when no clean setup exists).
   Backup first: `cp scanner.py scanner.py.bak.B.$(date +%Y%m%d_%H%M%S)`.

6. **Report with the segment table, then commit to a follow-up gate.** Show the
   user the LONG/SHORT split and the before/after-change split (that's what makes the
   diagnosis credible), state the 3 fixes plainly, and set a concrete decision rule for
   next review: "if LONG-only is still negative after ~15 clean trades → demote to
   paper-only (option C) or retire." Don't promise it's fixed — promise a measurement.

## Pitfalls
- Don't trust a single aggregate WR/net number — it averages a healthy LONG side with a
  toxic SHORT side and hides the lever.
- Don't tweak scoring when the loss is concentrated in one direction or in counter-macro
  entries. Scoring tweaks rearrange *which* bad trades fire, not *whether* they're bad.
- Always re-check whether your LAST fix helped (before/after split). Compounding tweaks
  on a wrong premise is how a −$28 scanner becomes −$65.
- Scanner journal records feeding `binance_real_executor` MUST keep top-level `score`
  (int) — see references/adding-new-scanner-strategy.md; don't drop it while editing.
