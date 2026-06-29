# Real-time Trade Monitoring via Binance WebSocket Daemon

When the user complains that HIT ENTRY / TP / SL notifications arrive late
("notifikasi telat, pair sudah hit duluan baru notif masuk"), the cause is
almost always **cron polling cadence**. The default cron monitors run every
5 minutes — worst case lag from a 30m Aggressive setup tagging the entry
zone to the alert hitting Telegram is ~5 minutes, by which point a fast pair
has already moved 0.2-0.5%.

The fix is event-driven: a persistent daemon subscribed to Binance fapi
`markPrice@1s` stream that handles transitions inline, with the cron
monitor demoted to a safety-net role.

## Architecture (3 layers)

```
[Binance fapi WS]──> binance_ws_monitor.py (daemon, persistent)
                       ├─ markPrice@1s for every active journal symbol
                       ├─ inline file-locked journal update
                       └─ direct Telegram HTML send
                       
[cron 1m]───────────> binance_ws_monitor_watchdog.py
                       └─ silent if healthy, respawns daemon if pidfile dead
                       
[cron 5m, existing]──> automatic_signal_monitor.py + binance_alpha_signal_monitor.py
                       └─ safety net (idempotent — daemon already advances status,
                          so cron sees "no transition" and stays silent)
```

## Key files

- `/root/.hermes/scripts/binance_ws_monitor.py` — the daemon. Imports
  `automatic_signal_monitor` and `binance_alpha_signal_monitor` so the
  notification format and transition logic stay 100% identical to cron
  output (call `note_hit_entry`, `note_tp`, `note_sl` from the modules).
- `/root/.hermes/scripts/binance_ws_monitor_watchdog.py` — minimal cron
  script (no_agent=true). Reads pidfile, `os.kill(pid, 0)` to check, spawns
  via `subprocess.Popen([sys.executable, daemon_path], start_new_session=True)`
  and writes new pid. Silent on healthy state; only emits when respawning.
- `/root/.hermes/binance_ws_monitor.pid` — pidfile written by daemon.
- `/root/.hermes/WS_MONITOR_KILL` — touch this to stop watchdog from
  respawning. Operator-controlled kill switch.
- `/root/.hermes/logs/binance_ws_monitor.log` — daemon stdout/stderr.

## Critical implementation pitfalls

1. **File lock around journal updates.** Cron monitor + daemon both write
   the same JSON. Use `fcntl.flock(fh, fcntl.LOCK_EX)` around read-modify-
   write. Without this, you'll lose status transitions when daemon and cron
   both fire on the same record.

2. **Subscription refresh, not restart.** New signals appear every 15-30
   minutes via scanners. Run a refresher thread that diffs
   `collect_active_symbols()` against `state["subscribed"]` every 30s and
   sends `SUBSCRIBE`/`UNSUBSCRIBE` payloads on the same socket. Restarting
   the WS for every new signal causes reconnect storms and Binance rate
   limits.

3. **Symbol normalization.** Alpha journal stores `symbol` as the BASE
   token (`"INX"`), automatic-signal journal stores it as the pair
   (`"INXUSDT"`). The daemon must look at `executor.futures_symbol` first
   (canonical pair set by executor) and fall back to appending `USDT`.
   Same logic the executor itself uses — see pitfall #9 in
   `binance-testnet-executor` skill.

4. **Telegram parse_mode markdown vs HTML.** The notif helpers produce
   markdown (`## header`, `**bold**`, ` `code` `). Telegram's `MarkdownV2`
   is brittle (escape requirements). Convert to HTML before send:

   ```python
   def md_to_html(text):
       text = text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
       text = re.sub(r"^## (.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
       text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
       text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
       return text
   ```

   Then `parse_mode=HTML` on `sendMessage`.

5. **Background spawn from Hermes.** `nohup ... &` is rejected by the
   terminal tool. Use `terminal(background=true)` for the initial spawn,
   then watchdog uses plain `subprocess.Popen(..., start_new_session=True)`
   for respawns (watchdog itself runs under cron so isn't subject to the
   tool restriction).

6. **Reconnect loop.** Wrap `ws.run_forever()` in `while not stop:` with a
   5s backoff. On reconnect, clear `state["subscribed"]` so on_open
   resubscribes everything. `ping_interval=180, ping_timeout=10` is
   appropriate for fstream.

7. **Notification format parity.** When a record's status changes, prefer
   calling the existing module's `note_*` helper instead of duplicating
   format logic. That way the user sees identical formatting whether the
   alert came from the WS daemon or the cron safety-net, and any format
   improvement made to the cron module flows through automatically on
   daemon restart.

## When NOT to use

- For Spot prices the spot WS endpoint is `wss://stream.binance.com:9443/stream`
  with `markPrice` not available — use `<symbol>@ticker` instead. But
  Furina's monitors run on USDT-M perp, so fapi is correct.
- For Binance Alpha-only tokens not listed on USDⓈ-M futures, the WS
  daemon can't help — those have no perp price feed. The cron
  `binance_alpha_signal_monitor.py` already polls Alpha's REST API
  directly; leave it on its own cadence.

## Cost / footprint

- LLM credits: **zero**. Watchdog cron is `no_agent=true`. Daemon is pure
  Python with `urllib`/`websocket-client`.
- Network: ~3-8 KB/s steady streaming, one TLS connection.
- Memory: ~30-50 MB for the daemon process.
- Latency: sub-second from mark-price tick to Telegram alert delivery.

## Cron credit cost — user-facing fact

Hermes cron jobs flagged `no_agent=true` (which run a Python script, not a
prompt) cost **zero LLM tokens**. The 1-minute vs 5-minute schedule
question is purely about API rate limits to Binance and request budget,
not LLM credits. When the user worries about "boros credit", verify whether
the cron is `no_agent` first — if yes, cadence change is free.

LLM credits ARE consumed when:
- Cron runs without `no_agent=true` (full agent loop fires).
- Cron triggers a `delegate_task` or otherwise spawns sub-agents.
- Watchdog itself emits an LLM-driven response (avoid: keep watchdog
  output to plain `print()` strings, never agent-prompt-based).

## Verification commands

```bash
# Daemon health
ps -p $(cat /root/.hermes/binance_ws_monitor.pid) -o pid,etime,cmd

# Tail log (subscribe / unsubscribe events visible)
tail -50 /root/.hermes/logs/binance_ws_monitor.log

# Watchdog dry run (silent = healthy, prints "respawned" on dead)
python3 /root/.hermes/scripts/binance_ws_monitor_watchdog.py

# Stop and prevent respawn
touch /root/.hermes/WS_MONITOR_KILL
kill $(cat /root/.hermes/binance_ws_monitor.pid)

# Resume
rm /root/.hermes/WS_MONITOR_KILL
# (watchdog will respawn on next minute)
```
