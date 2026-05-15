# Telegram Topic Workflows

Use this when a user wants to command Hermes from DM while execution/output happens in Telegram groups or forum topics.

## Key model

- Telegram DM, group, and forum topics are separate conversation contexts.
- Instructions given in DM do not automatically become visible inside a group topic.
- A forum-topic target should be stored as `telegram:<chat_id>:<thread_id>`.
- For supergroups, `chat_id` often starts with `-100`; `thread_id` is the topic/message_thread_id.

## Setup pattern

1. Ask the user to add the bot to the group/supergroup.
2. For each topic, collect the target id:
   - `chat_id` = supergroup id
   - `thread_id` = topic id
   - canonical target = `telegram:<chat_id>:<thread_id>`
3. Ask the user what each topic is for, then persist durable mappings in memory only if they will be reused.
4. Seed the topic with a short rules message so the topic-local context matches the DM plan.
5. When the user commands from DM, route output to the mapped target.

## Common topic split for trading workflows

- `Alert Market`: scheduled market overview, top gainers/losers, and separate large volume-breakout alerts.
- `Crypto`: concise technical analysis, entry areas, SL/TP, support-resistance, watchlists, setup follow-up.
- `Deep Research`: longer thesis work: narratives, fundamentals, tokenomics, macro, repo/tool reviews, post-mortems.

## Pitfalls

- Do not assume a group topic knows a DM-only instruction. Either seed the topic or include the instruction in the sent output.
- Keep topic roles distinct. Do not mix automated alerts into a technical-analysis topic unless the user explicitly wants that.
- If a Telegram bot does not respond in a group, ask the user to mention/reply to it or check BotFather privacy mode.
- For scheduled messages, verify the exact `telegram:<chat_id>:<thread_id>` target before creating cron jobs.
