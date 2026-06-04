---
name: relationship-intent-matching
description: Aligns tone, pacing, and topics to the user's relationship intent (casual, dating, or long-term) and reads the other person's intent signals — an always-on modifier.
when_to_use: Always active. Applies the user's intent to every message and watches for the other person's intent signals.
category: Meta
fires_when: Modifier on every turn
---

# Relationship-intent matching

This is an **always-on modifier**: it shapes *how* every other skill expresses
itself so the conversation moves at the right pace toward the right thing. It
also listens for the other person's intent and surfaces mismatches early —
because aligned intent is the kindest, most effective filter there is.

## Tune by the user's `looking_for`

**Casual**
- Tone: light, fun, low-stakes, in the moment.
- Pace: can move to meeting up quickly; keep it breezy.
- Topics: shared fun, chemistry, plans. Don't over-index on future-building.

**Dating** (getting to know someone, open to where it goes)
- Tone: warm, curious, genuinely interested but unhurried.
- Pace: a few good exchanges, then suggest a low-key date.
- Topics: values and lifestyle alongside fun; balance depth and play.

**Long-term**
- Tone: sincere and warm, still playful — depth signals seriousness.
- Pace: invest in real rapport before pushing to meet; quality over speed.
- Topics: values, life direction, how they treat people — woven in naturally,
  never as an interrogation.

## Read *their* intent

Watch for signals and mirror or surface honestly:

- **Casual signals:** fast escalation, "no expectations", late-night energy,
  reluctance to plan ahead.
- **Serious signals:** asking about values/future, slower deliberate pace,
  references to past relationships and lessons.
- **Mismatch:** if their intent clearly differs from the user's, don't paper
  over it. A short, honest check-in ("I'm actually looking for something real —
  where's your head at?") saves everyone time and is always allowed.

## Rules

- **Never misrepresent the user's intent** to get a result. Honesty about what
  the user wants is non-negotiable (see `consent-and-safety`).
- **Pace follows intent.** Don't rush a long-term seeker or stall a casual one.
- **Surface big mismatches early** rather than hoping they resolve.

## Output (as a modifier)

Don't produce a standalone message. Instead, constrain the primary skill's draft:
adjust warmth, depth, and pacing to the intent, and flag any intent mismatch the
user should know about.
