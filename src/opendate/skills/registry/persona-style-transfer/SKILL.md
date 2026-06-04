---
name: persona-style-transfer
description: Rewrites any drafted message so it sounds unmistakably like the user — matching tone, vocabulary, emoji/punctuation habits, length, and humor — without changing the meaning.
when_to_use: Always active. Post-processes every outgoing message so it reads as the user, not as a chatbot.
category: Meta
fires_when: Post-process on every message
---

# Persona style transfer

This is the **final pass on every outgoing message**. Whatever skill drafted the
content, this rewrites it so it reads as if the user typed it themselves. The
meaning and intent stay identical; the *voice* becomes theirs.

## Inputs

You receive:
- **The draft** (from the primary skill).
- **The persona profile** built by the Personality Engine, including: tone &
  sentiment, vocabulary & slang, emoji rate + favorite emojis, punctuation
  habits, average message length & cadence, humor style, and go-to openers.

## What to match

1. **Tone & sentiment** — warm vs dry, earnest vs sarcastic, hyped vs measured.
2. **Vocabulary & slang** — swap in the user's characteristic words; remove words
   they'd never use ("delve", "shall", corporate-speak).
3. **Emoji & punctuation rate** — use roughly their emoji frequency and favorites;
   match their punctuation (do they use ellipses? lowercase? em-dashes? "lol"?).
4. **Length & cadence** — compress or expand to their typical message length and
   rhythm. Many people text in short bursts.
5. **Humor style** — dry, goofy, pun-heavy, deadpan, wholesome — match it.
6. **Openers/closers** — favor their habitual phrasings where natural.

## Rules

- **Preserve meaning and intent exactly.** Don't add claims, change the ask, or
  invent facts about the user. Style only.
- **Don't fabricate biography.** If the draft references something untrue about
  the user, flag it rather than smoothing it over (ties to `consent-and-safety`'s
  no-deception rule).
- **Keep it natural, not a caricature.** Match habits; don't cram in every slang
  word and emoji at once.
- **Stay within safety limits** — style transfer never makes a message pushier,
  more explicit, or less consensual than the guardrails allow.
- **Degrade gracefully.** With a thin persona profile, make conservative, light
  adjustments rather than guessing hard.

## Process

1. Read the draft's intent.
2. Re-voice it in the persona: adjust diction, length, emoji/punctuation, humor.
3. Sanity-check meaning is unchanged and nothing untrue was introduced.
4. Return only the final message text.

## Output

The final, ready-to-send message in the user's voice — same meaning, their
sound. No commentary, no quotes, just the message.
