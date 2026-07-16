# Skill Publishing to GitHub

The Furina skill lives locally at
`~/.hermes/skills/finance/furina-trading-agent/` (SKILL.md + references/).
It is published to a public GitHub repo so it can be forked,
version-controlled, and re-installed on a fresh box.

**Standing repo:** `https://github.com/rexxlite/furina-skill` (public).
Path inside the repo: `skills/finance/furina-trading-agent/`.

## Step 0 — Check for the standing repo BEFORE asking how to package

When the user says "push ke github" / "update githubnya dengan skill kamu",
do NOT open a `clarify()` with packaging-format options
(markdown-only vs full-code vs code+journals). A standing repo already
exists. Check memory + session_search for the repo URL first, then just
clone-and-update.

This session the user was asked a 4-option packaging question and replied
"dulu sudah pernah kita push ke github … update githubnya dengan skill
kamu dari scanner yang baru" — i.e. the repo is known, just update it.
Asking packaging questions when a repo exists frustrates the user.
Only ask format questions if NO prior repo is found in memory or
session history.

## Step 1 — Clone the repo

```bash
cd /tmp && rm -rf furina-skill && \
  git clone https://github.com/rexxlite/furina-skill.git
```

## Step 2 — Sanitize a STAGING copy (never copy the live skill straight in)

The live skill files contain PII and private identifiers that must not
reach a public repo. Copy to a staging dir first and redact there:

```bash
mkdir -p /tmp/furina-skill-staging
cp -r ~/.hermes/skills/finance/furina-trading-agent /tmp/furina-skill-staging/
cd /tmp/furina-skill-staging/furina-trading-agent

# 1. Telegram chat ID (private group identifier) -> redact
grep -rl "CHATID_REDACTED" . | \
  xargs -I{} sed -i 's/-100XXXXXXXXXX/-100XXXXXXXXXX/g' {}

# 2. Operator Telegram username "operator" -> "operator"
grep -rl "operator" --include="*.md" | \
  xargs -I{} sed -i \
    "s/operator's group/operator's group/g; \
     s/user (operator)/user (operator)/g; \
     s/when the operator says/when the operator says/g" {}
```

**KEEP (not secret):** filesystem paths like
`/root/.hermes/secrets/binance_real.env`. These are paths on the server,
not credential values, and the skill is useless without them as
operational anchors. Redact secret *contents*; never redact the paths.

**Public third-party handles are fine to keep** — e.g. the source
inspiration channel `@yourlittlething` is a public Telegram channel;
redacting it would erase attribution and methodology provenance.

**Verify clean before committing (exit 1 = no match = clean):**

```bash
grep -rE "CHATID_REDACTED|operator" . ; echo "GREP_EXIT=$?"
# also scan for any token pasted this session:
grep -rE "github_pat_|sk-[A-Za-z0-9]{20}" . ; echo "GREP_EXIT=$?"
```

Note: example Binance algo/order IDs like `1000000077795130` in
references are NOT secrets — they are illustrative placeholders. The
grep for `100[0-9]{10}` will match them; that is expected and harmless.
Only treat chat IDs and usernames as PII to redact.

## Step 3 — Replace the repo copy and commit

```bash
cd /tmp/furina-skill
rm -rf skills/finance/furina-trading-agent
cp -r /tmp/furina-skill-staging/furina-trading-agent skills/finance/furina-trading-agent
git add -A
git status --short | head -50   # eyeball the file list
git -c user.name="Furina Agent" -c user.email="furina@agent.local" \
  commit -m "feat(furina): <one-line summary>

- <bullet of what changed>
- Sanitized: Telegram chat IDs redacted, operator username redacted."
```

## Step 4 — Push with a ONE-SHOT token (fine-grained PAT, scope: repo)

The user pastes a GitHub PAT. Use it ONLY via the remote URL, then strip
it immediately. Do NOT persist it in env files or git config.

```bash
export GH_TOKEN='<paste>'
cd /tmp/furina-skill
git remote set-url origin \
  "https://x-access-token:${GH_TOKEN}@github.com/rexxlite/furina-skill.git"
git push origin HEAD
# Strip the token from the remote URL IMMEDIATELY after push
git remote set-url origin "https://github.com/rexxlite/furina-skill.git"
unset GH_TOKEN
```

The terminal security scan will flag the PAT as
`[HIGH] GitHub Fine-Grained PAT detected` and require approval — that
is expected and correct; approve it. The approval is per-command and
does not persist the token anywhere.

## Step 5 — Verify the push landed (don't trust local git exit code alone)

```bash
# Latest commit on GitHub
curl -s "https://api.github.com/repos/rexxlite/furina-skill/commits?per_page=1" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); \
    print(d[0]['sha'][:7], '-', d[0]['commit']['message'].split(chr(10))[0])"

# Reference file count on GitHub (should match local count)
curl -s "https://api.github.com/repos/rexxlite/furina-skill/contents/skills/finance/furina-trading-agent/references" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d), 'ref files live')"
```

Match the SHA prefix against the local `git log --oneline -1` output.
If the counts or SHA don't match, the push did not land — re-push.

## Step 6 — Clean up server-side traces

```bash
sed -i '/github_pat_/d' ~/.bash_history 2>/dev/null; history -c 2>/dev/null
rm -rf /tmp/furina-skill /tmp/furina-skill-staging
# Restore cwd if the rm left the shell in a deleted dir:
cd /root && pwd
```

## Security reminder for the user (do this EVERY time)

A PAT pasted into a Telegram chat persists in the user's chat history on
their device. Server-side cleanup (Step 6) does NOT erase that. After
every push, explicitly remind the user to **revoke the token** at
`github.com/settings/tokens` and generate a fresh one next time.
Fine-grained PATs with scope `repo` (Contents: R/W, Metadata: R) are
sufficient and least-privilege.

## What to publish vs. what to keep private

**Publish** — `SKILL.md` + the entire `references/` directory. These are
methodology and operational knowledge, safe to publicize once sanitized.

**Do NOT publish:**
- `scripts/` — executor/reconciler/scanner Python with live wiring,
  internal paths, cron job IDs tied to this deployment
- Trading journals (`automatic_signal_real_journal.json`, alpha journal,
  `manual_trades.json`, `paper_trades.json`) — trade history + balance
- Any env / secrets file — credential values
- `real_risk_state.json` or any state file with balances

## Pitfalls

- **Don't ask packaging-format questions when a standing repo exists.**
  Check memory + session_search first (Step 0). The repo is the format.
- **Don't skip the staging-copy step.** Running sed directly on the live
  skill would corrupt the operational files the agent uses in-session.
  Always copy to /tmp first, sanitize the copy, then copy the copy into
  the cloned repo.
- **Don't trust `head`'s exit code for the leak grep.** Piping grep
  through `head` always exits 0. Run grep raw and read `GREP_EXIT`
  (1 = clean, 0 = leak found).
- **Don't leave the token in the remote URL.** A subsequent
  `git remote -v` by anyone (or a future session) would print it. Strip
  it in the same command block as the push.
- **`rm -rf /tmp/furina-skill` while cwd is inside it** leaves the shell
  pointing at a deleted directory; the next command fails with
  `getcwd: cannot access parent directories`. `cd /root` to recover.

## Historical precedent

- 2026-06-29: full skill re-publish — SKILL.md (1281 lines) + 39
  references pushed as commit `9a4d4c3`. Sanitized chat ID + operator
  username; kept secret paths + public channel handle. Token used
  once via remote URL, stripped, history cleaned, user reminded to
  revoke.
