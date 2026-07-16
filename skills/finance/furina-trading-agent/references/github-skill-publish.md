# Publishing the Furina Skill to GitHub

Workflow for syncing the local `furina-trading-agent` skill (+ scanner scripts)
to the public repo `github.com/rexxlite/furina-skill`. Use when the user asks to
"push skill ke github", "update repo", or after substantial scanner/skill changes
that should be reflected in the public mirror.

## Repo layout (target)

```
skills/finance/furina-trading-agent/   # SKILL.md + references/ (the skill)
scripts/                                # standalone Python scanner scripts
docs/diagrams/                          # Mermaid flow diagrams
README.md                               # English overview, references all diagrams
```

## Sanitize BEFORE staging — every time

The skill and scripts reference operator-specific identifiers that must NOT go
public. Grep + redact before copying into the repo staging dir:

- **Telegram chat ID** `-100XXXXXXXXXX` → `-100XXXXXXXXXX` (private group ID).
  Hits: SKILL.md, references/spot-paper-trading-system.md,
  references/automatic-signal-system.md, references/adding-new-scanner-strategy.md,
  references/bulk-market-scanning.md.
- **Operator username** `operator` → `operator` (or `the operator`).
  Hits: references/operational-systems.md, references/real-mainnet-switch.md, SKILL.md.
- **Secret file PATHS** (`/root/.hermes/secrets/binance_real.env`) → **KEEP**.
  These are server paths only, not secret values. Needed for operational context.
- **API keys / tokens / passwords** → must not appear at all. Grep for
  `api[_-]?key`, `api[_-]?secret`, `sk-`, `github_pat_`, `TELEGRAM_BOT_TOKEN`,
  `password =`. If any real value leaks, do NOT push.

Sanitize command pattern:
```bash
grep -rl "CHATID_REDACTED" <staging>/ | xargs -I{} sed -i 's/-100XXXXXXXXXX/-100XXXXXXXXXX/g' {}
grep -rl "operator" <staging>/ --include="*.md" | xargs -I{} sed -i 's/operator/operator/g' {}
```
Then verify clean: `grep -rE "CHATID_REDACTED|operator" <staging>/` must return nothing.

## Workflow

```bash
# 1. Clone fresh to a staging dir
cd /tmp && rm -rf furina-skill-up && git clone https://github.com/rexxlite/furina-skill.git furina-skill-up

# 2. Copy sanitized skill + scripts into the clone
cp -r /root/.hermes/skills/finance/furina-trading-agent/<files> furina-skill-up/skills/finance/furina-trading-agent/
cp /root/.hermes/scripts/<scanner>.py furina-skill-up/scripts/

# 3. Run the sanitize grep+sed above, verify clean.

# 4. Commit
cd /tmp/furina-skill-up
git -c user.name="Furina Agent" -c user.email="furina@agent.local" commit -am "<message>"

# 5. Push using a fine-grained PAT via remote URL (one-shot, then strip)
git remote set-url origin "https://rexxlite:<PAT>@github.com/rexxlite/furina-skill.git"
git push origin HEAD
git remote set-url origin "https://github.com/rexxlite/furina-skill.git"  # strip token

# 6. Verify via GitHub API (no auth needed for public repo reads)
curl -s "https://api.github.com/repos/rexxlite/furina-skill/commits?per_page=1" | python3 -c "..."
curl -s "https://api.github.com/repos/rexxlite/furina-skill/contents/<path>" | python3 -c "..."

# 7. Cleanup
rm -rf /tmp/furina-skill-up
sed -i '/github_pat_/d' ~/.bash_history
```

## Auth

The operator provides a fine-grained PAT (scope: `repo` or `Contents: write` on
the single repo). Pass it via the remote URL for the push, then immediately strip
it from the remote URL and delete it from shell history. Do NOT store it in git
config, netrc, or env persistently.

## Security note for the operator

When the PAT is shared in a Telegram chat, it persists in chat history which the
agent cannot delete. **Always recommend the operator revoke the token after the
push** at `github.com/settings/tokens` and generate a fresh one next time. A
short-lived token (7-day expiry) is safer than a long-lived one.

## Commit conventions

- Author: `Furina Agent <furina@agent.local>` (via `-c user.name/email` flags —
  do not set global git config for this).
- Message prefix by type: `feat(...)` for new scripts/refs, `docs(...)` for
  README/diagram changes, `fix(...)` for corrections.
- One logical change per commit (skill expansion, README rewrite, scanner batch).

## Mermaid diagram pitfall

When writing Mermaid flowcharts in `docs/diagrams/`, avoid raw `<` `>` `>=` `<=`
inside node labels — they can break the Mermaid parser. Use words: "at least",
"below", "past". Grep for stray `<`/`>` in labels before pushing.

## Per-scanner reference docs

When publishing scanner scripts, also write a per-scanner reference
(`references/scanner-<name>.md`) with: thesis, parameters (all CAPS constants),
scoring breakdown (N points, need M), confirmation gates, tuning history,
performance (net + WR from eval), bucket/leverage. The script is the source of
truth for parameters; the reference is the reasoning layer for future sessions.
