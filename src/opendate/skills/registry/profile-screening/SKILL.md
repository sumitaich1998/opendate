---
name: profile-screening
description: Scores a potential date against the user's stated preferences (traits, dealbreakers, age range, distance, intent) and returns a like/pass decision with reasons.
when_to_use: A new recommendation/candidate appears and you must decide whether to like or pass.
category: Discovery
fires_when: New recommendation appears
---

# Profile screening

Decide, quickly and fairly, whether a candidate is worth a *like*. You are the
front door: a good screen protects the user's time and keeps later
conversations authentic, because every match is someone they actually want to
talk to.

## Principles

- **Dealbreakers are absolute.** If a profile clearly violates a dealbreaker,
  pass — no matter how strong everything else is.
- **Hard filters first, vibe second.** Check age range and distance, then weigh
  traits, interests, and the *intent* signal (casual / dating / long-term).
- **Reward signal, don't punish silence.** A thin profile is a mild negative,
  not a dealbreaker. Missing data (e.g. no listed age) should lower confidence,
  not auto-pass.
- **Look for genuine overlap.** Shared interests and complementary traits beat
  a long bio of buzzwords. One specific hook you could open on is worth a lot.
- **No superficial bias.** Judge on compatibility signals, not on attributes
  irrelevant to the user's stated preferences.

## Scoring rubric (0.0 – 1.0)

Start at 0.5 and adjust:

| Signal | Effect |
| --- | --- |
| Any dealbreaker present | hard pass (score 0.0) |
| Age inside `age_range` | +0.1 · outside: −0.2 |
| Distance within `distance_km` | +0.1 · well beyond: −0.15 |
| Each matching `partner_trait` | +0.08 (cap +0.24) |
| Each shared interest | +0.05 (cap +0.15) |
| Clear, specific bio with a hook | +0.1 |
| Empty / generic bio | −0.05 |
| Intent signals align with `looking_for` | +0.1 |

Decision: **like** when score ≥ 0.55, otherwise **pass**. When it's a coin
flip and the user's intent is long-term, lean pass; when casual, lean like.

## Output format

Return a single JSON object and nothing else:

```json
{
  "decision": "like",
  "score": 0.72,
  "reasons": ["climbing + live music overlap", "age and distance in range"],
  "open_on": "the bouldering line in her bio"
}
```

- `decision`: `"like"` or `"pass"`.
- `score`: float 0–1.
- `reasons`: 1–3 short, concrete justifications.
- `open_on`: the single best hook to open with if liked (or `null`).

## Do / Don't

- Do pass fast on dealbreakers; don't rationalize them away.
- Do note the *one* best opener hook for the next skill to use.
- Don't like everyone "to keep options open" — that dilutes the user's voice
  and attention later.
