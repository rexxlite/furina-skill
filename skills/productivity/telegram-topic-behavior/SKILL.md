---
name: telegram-topic-behavior
description: Handling Telegram thread/topic-specific user instructions, especially silence/no-reply requests and topic routing preferences.
---

# Telegram Topic Behavior

Use this skill when the user gives instructions that apply to a specific Telegram topic/thread, such as: do not reply here, only post certain content in this topic, route alerts to a topic, or avoid off-topic responses.

## Core rule: topic-scoped instructions are operational constraints

1. Identify whether the user instruction is scoped to the current Telegram topic/thread.
2. If the user says not to reply in a topic, **do not send any explanatory acknowledgement in that same topic**.
3. Persist the preference compactly in memory if it is durable, then remain silent.
4. If future messages arrive in that same no-reply topic, ignore them unless the user explicitly revokes the silence rule or asks for a response in a different allowed context.

## No-reply topic pitfall

When the user says “jangan reply apapun di topic ini” / “do not reply anything in this topic”, replying with “okay, I won’t reply” still violates the instruction. The correct behavior is:

- Save durable preference if needed.
- Send no final answer content.
- Do not justify, apologize, or restate the rule in that topic.

## Revocation / override

Only respond again in a no-reply topic if the user clearly revokes the prior rule, for example:

- “Mulai sekarang boleh reply di topic ini.”
- “Override: jawab pesan ini.”
- “Furina, jawab khusus untuk ini.”

Ambiguous or filler messages such as “halo”, “test”, “swws”, or new content drops are **not** revocation.

## Topic routing reminders

- Keep topic-specific preferences separate from global user preferences.
- Do not mix automated alerts, research, trading setups, and casual/NFT waitlist posts if the user has assigned separate Telegram topics for them.
- If asked to update memory or skills from a no-reply topic, perform the tool updates but avoid normal conversational acknowledgement unless the user explicitly asks for a reply.

## Verification before sending

Before producing a final answer in Telegram, check:

1. Is this topic marked no-reply?
2. Did the latest user message explicitly revoke the no-reply rule?
3. If not revoked, should the response be empty/silent?

If yes, do not send a visible reply.