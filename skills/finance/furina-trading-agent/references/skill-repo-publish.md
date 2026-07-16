# Publishing the Furina Skill to the Public GitHub Repo

The operator maintains a public mirror of this skill at
`https://github.com/rexxlite/furina-skill`. The task recurs (skill expands,
scanners get tuned, references get added), so this is the canonical publish
workflow. It is NOT a one-off.

## Repo layout (mirror of local skill)

```
skills/finance/furina-trading-agent/SKILL.md
skills/finance/furina-trading-agent/references/*.md   # all reference files
docs/diagrams/*.md                                     # Mermaid pipeline diagrams
README.md                                              # repo front page
scripts/*.py                                           # read-only automation scripts
```

The mirror copies `~/.hermes/skills/finance/furina-trading-agent/` (SKILL.md +
references/) into `skills/finance/furina-trading-agent/` in the repo.

## Sanitization — MANDATORY before every push

The skill files contain operator-identifying material. Scrub it in a staging
copy, never edit the live skill in place. Run a final grep and require
zero matches before committing.

1. **Telegram chat ID** `-100XXXXXXXXXX` → `-100XXXXXXXXXX`. Appears in SKILL.md
   and several references (cron targets, topic router). Use sed across all
   staged `.md` files.
2. **Operator username** `operator` → `operator`. Appears in operational notes
   ("operator's group", "when the operator says", "user (operator)").
3. **Secret file PATHS are kept** (`/root/.hermes/secrets/binance_real.env`).
   These are paths only, never contents — they are needed for the skill to make
   sense. NEVER paste API keys, secrets, or token values into any file.
4. **Verify before push**:
   ```bash
   grep -rE "(-100[0-9]{10}|operator|github_pat_|api[_-]?secret|sk-)" --include="*.md" \
     /tmp/staging/furina-trading-agent/   # must return nothing
   ```

## Content language — English only (operator preference)

ALL repo-facing content must be in English: README, diagram files, commit
messages, code comments in scripts. The live skill internally mixes
Indonesian/English (operator's working language), but the public mirror is
English-only. Before pushing README/diagrams, grep for Indonesian stopwords
to catch leaks:

```bash
grep -rEni "(bukan nasihat|yang mulia|kamu|aku|adalah|untuk|seperti|kalau|jangan|sudah|belum|perbaiki|tambahin)" \
  README.md docs/diagrams/   # must return nothing
```

## Push workflow

```bash
# 1. Clone (token used once via remote URL, then scrubbed)
git clone https://rexxlite:<PAT>@github.com/rexxlite/furina-skill.git /tmp/furina-skill

# 2. Stage sanitized copy
cp -r ~/.hermes/skills/finance/furina-trading-agent /tmp/staging/
# ...apply sanitization sed rules to /tmp/staging/...
cp -r /tmp/staging/furina-trading-agent /tmp/furina-skill/skills/finance/

# 3. Commit (English message)
git -c user.name="Furina Agent" -c user.email="furina@agent.local" commit -m "feat(furina): ..."

# 4. Push, then SCRUB token from remote URL + shell history
git push origin HEAD
git remote set-url origin "https://github.com/rexxlite/furina-skill.git"
sed -i '/github_pat_/d' ~/.bash_history
```

## Mermaid diagram pitfalls

When adding/editing `docs/diagrams/*.md`:

- **`<` and `>` inside node labels break Mermaid parsing.** Comparison
  operators like `>=`, `< 6`, `age >= threshold` get misread as XML/HTML tags.
  Replace with words: `>=` → "at least", `< 6` → "below 6", `age >= threshold`
  → "age past threshold". Grep for ` >= | < | > ` in diagram files before push.
- `<br/>` for line breaks inside labels is fine (it is valid Mermaid).
- Em-dash `—` in labels is fine.

## Token safety

The operator shares GitHub PATs via Telegram chat. After pushing:
- Scrub the token from the git remote URL and shell history (see workflow).
- Remind the operator to **revoke the token** at github.com/settings/tokens,
  because it persists in Telegram chat history. Generate a fresh token next
  time rather than reusing.

## When to update the mirror

Push when the skill meaningfully expands: new references, scanner tuning that
changes behavior, new diagrams, or README/structural changes. Small memory-only
or session-state changes do not need a push. Commit author is always
`Furina Agent <furina@agent.local>`.
