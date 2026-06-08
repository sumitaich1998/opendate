# Safety & responsible use

Safety is not a feature bolted onto OpenDate — it's a **blocking gate** that every
send must pass, and the ethos the whole project is built around. This page covers
the consent-and-safety guard, how it detects minors/discomfort/disinterest, the
pacing/anti-spam guards, human-in-the-loop vs auto-send, secret redaction, and a
deep dive on responsible use. The code is in
[`orchestrator/safety.py`](../src/opendate/orchestrator/safety.py) (the guard),
backed by the [`consent-and-safety`](skills.md) skill, with config in
[`SafetyConfig`](configuration.md#safety) and [`PacingConfig`](configuration.md#pacing).

- [The consent & safety gate](#the-consent--safety-gate)
- [What it blocks, and when](#what-it-blocks-and-when)
- [Minor / discomfort / disinterest detection](#minor--discomfort--disinterest-detection)
- [Pacing: cooldowns, daily cap, no double-text](#pacing-cooldowns-daily-cap-no-double-text)
- [Human-in-the-loop vs auto-send](#human-in-the-loop-vs-auto-send)
- [Logging & redaction](#logging--redaction)
- [Responsible use deep dive](#responsible-use-deep-dive)

---

## The consent & safety gate

`SafetyGuard.check_message(text, context)` runs before **every** proposed send.
It is intentionally **deterministic** (keyword/heuristic rules) so it works fully
offline and is testable without a network. A real LLM can add a second review
pass, but **the heuristic rules are authoritative: if they block, it stays
blocked.** An LLM review can only *refine* a decision (add a block), never
*un-block* something the heuristics blocked.

The verdict is a `SafetyDecision`:

| Field | Meaning |
| --- | --- |
| `allowed` | Whether the message may be sent. `blocked` is its inverse. |
| `severity` | `"ok"`, `"soft"`, or `"hard"`. |
| `reasons` | Human-readable explanation(s), logged for the audit trail. |
| `category` | e.g. `minor`, `hostility`, `deception`, `explicit`, `pressure`, `hard-stop`, `discomfort`, `disinterest`. |
| `revised_text` | Optional softened rewrite (reserved). |

In the [orchestrator](orchestrator.md), a blocked decision turns the action into
`backoff` when severity isn't `hard`, or `blocked` when it is — and the message
is never sent. Every block is logged (`Safety block [category/severity]: ...`).

---

## What it blocks, and when

`check_message` evaluates these checks **in order**; the first match wins:

| # | Check | Condition | Severity | Category |
| --- | --- | --- | --- | --- |
| 0 | Possible minor | `refuse_minors` and their last message matches the minor pattern | hard | `minor` |
| 1 | Hostility | Our draft contains insults/slurs/demeaning language | hard | `hostility` |
| 2 | Deception | Our draft contains deception markers | hard | `deception` |
| 3 | Explicit | Our draft is explicit, unless `allow_explicit` **and** they clearly invited it | hard | `explicit` |
| 4 | Pressure | Our draft reads as coercive/pressuring | soft | `pressure` |
| 5a | Hard stop | `context.hard_stop` or their message says stop/not interested | hard | `hard-stop` |
| 5b | Discomfort | `refuse_on_discomfort` and their message signals discomfort/withdrawal | hard | `discomfort` |
| 5c | Disinterest | `backoff_on_disinterest` and `context.disinterest` | soft | `disinterest` |
| 6 | LLM review | `require_consent_checks` and a real (non-stub) router flags it | soft | (from review) |

Checks 0–4 inspect **our outgoing draft** (and, for explicit, whether *they*
invited it); checks 5a–5c inspect **their** signals via the `SituationContext`.
Note that checks 1–4 run on the message text even with no context, so a
hostile/deceptive/explicit/pushy draft is blocked regardless.

The explicit rule is deliberately strict: explicit content is blocked **unless**
both `allow_explicit: true` *and* the other person clearly, affirmatively invited
it. When uncertain, it blocks.

---

## Minor / discomfort / disinterest detection

These are heuristic regex/keyword detectors. They're intentionally
broad-but-conservative — when in doubt, OpenDate backs off.

- **Minor signals** (hard block when `refuse_minors`): self-reported ages 10–17
  (e.g. "I'm 16", "just turned 17", "16 yo / years old") and terms like
  `underage`, `under 18`, `jailbait`, `high school(er)`, `middle school(er)`.
  Matched against **their** message; if present, OpenDate refuses to engage at
  all, regardless of the draft's content.
- **Discomfort / withdrawal** (hard block when `refuse_on_discomfort`):
  `uncomfortable`, `creepy/creeper`, "you're being weird", "this is weird", "too
  much", "reporting you / I'll report", "I blocked / gonna block", "I have a
  boyfriend/girlfriend/partner/husband/wife", "back off", "stop being weird".
- **Hard stop** (always hard block): "not interested", "please stop", "stop
  messaging", "leave me alone", "don't message me", "I'm not comfortable", "no
  thank you" — or `context.hard_stop` set by the orchestrator.
- **Disinterest** (soft block when `backoff_on_disinterest`): `context.disinterest`
  is computed by the orchestrator from low-effort/withdrawing recent replies (see
  [Orchestrator](orchestrator.md)). On disinterest, OpenDate eases off rather
  than pushing.

The [`consent-and-safety` skill](../src/opendate/skills/registry/consent-and-safety/SKILL.md)'s
body is passed to the guard as `guidance` and used as policy in the optional LLM
review.

---

## Pacing: cooldowns, daily cap, no double-text

Separately from message content, `SafetyGuard.check_pacing(...)` guards against
spammy *behaviour*. The orchestrator computes pure inputs from persisted
[state](orchestrator.md) and calls it before generating a message:

| Guard | Condition | Severity | Category |
| --- | --- | --- | --- |
| Daily cap | `daily_budget_left <= 0` (cap = `pacing.max_daily_actions`, default 25, rolling 24h) | soft | `rate-limit` |
| Over-eager follow-ups | `followups_without_reply > max_followups_without_reply` (default 2) | soft | `escalation` |
| Cooldown | `cooldown_remaining > 0` (from `pacing.cooldown_hours`, default 8h since last send to that match) | soft | `cooldown` |

Complementing these, the **no-double-text** rule lives in the orchestrator's
`_should_message`: when `pacing.never_double_text` is on and we were the last to
message, OpenDate won't send again until the thread is stale enough to
re-engage (`pacing.reengage_after_days`, default 3 days). See
[Configuration → pacing](configuration.md#pacing).

---

## Human-in-the-loop vs auto-send

OpenDate defaults to **human-in-the-loop**:

- **`auto_send: false` (default).** OpenDate proposes each action (a panel with
  the recipient, stage, skill, quality, reason, and the message text) and asks
  for confirmation before sending. Low-risk passes during screening are
  auto-skipped (logged, no prompt). A `run` without flags is **interactive**.
- **`--no-interactive`.** Proposes but **never sends** — a true dry run. The
  per-cycle table is titled `Cycle plan (dry-run — nothing sent)`. If no
  interactive input is available (piped/non-TTY) the confirm is treated as "no",
  so nothing is sent.
- **`auto_send: true` / `--auto-send`.** Approved actions are sent without asking.
  **The safety gate still applies** — a hard block holds the message regardless.

Enable autonomy only when you trust the configuration. See the
[CLI reference](cli.md#run) for the exact flags and precedence.

```bash
opendate run                      # asks before each send (default)
opendate run --no-interactive     # proposes, never sends (dry run)
opendate run --auto-send          # sends approved actions; safety still gates
```

---

## Logging & redaction

Secrets are **never logged**. The logging layer
([`utils/logging.py`](../src/opendate/utils/logging.py)) installs a
`RedactingFilter` on the `opendate` logger that scrubs every record before it's
emitted:

- **Registered secrets.** The config layer calls `register_secret(...)` for the
  Tinder token and every loaded provider key the moment they load (and the router
  registers each resolved API key), so their exact values are masked everywhere.
- **Heuristic patterns.** Even unregistered secret-looking strings are masked:
  common key prefixes (`sk-...`, `sk-ant-...`, `gsk_...`, `xai-...`, `AIza...`)
  and `key=value` / `"token": "value"` style assignments. The mask is
  `***REDACTED***`.

Combined with the decision audit log (`data/decisions.jsonl`, see
[Orchestrator](orchestrator.md)), you get a transparent, secret-safe trail of
what OpenDate decided and why.

---

## Responsible use deep dive

OpenDate can automate intimate, high-stakes human interactions. Use it
thoughtfully, honestly, and with respect. This expands on the root README's
[Responsible use & safety](../README.md#-responsible-use--safety).

### Honesty, consent, respect

The `consent-and-safety` skill encodes three non-negotiable principles:

1. **Honesty.** Never deceive — no catfishing, fake stories, false promises, or
   pretending to be someone/somewhere you're not. Represent the user's real
   intent.
2. **Consent.** Engage with people who are engaging back. Romantic or sexual
   escalation requires clear, mutual, ongoing signals — and can be withdrawn at
   any time. Silence is an answer; respecting it is mandatory.
3. **Respect.** No pressure, manipulation, guilt-tripping, negging, harassment,
   or contempt. Treat the other person as a full human being.

Don't disable the guard to behave in ways you wouldn't in person. As the README
puts it: *if you wouldn't say it to someone's face, don't let an agent say it for
you.*

### Tinder ToS risk

Tinder has **no official/public API**. The endpoints OpenDate uses are
unofficial and reverse-engineered (see [Connectors](connectors.md)). **Automating
Tinder may violate its Terms of Service** and can lead to rate-limiting or a
permanent ban, and the unofficial API can change or break at any time. You are
responsible for complying with applicable platform terms and laws.

### The other person hasn't consented to a bot

They're a real human who didn't sign up to talk to an agent. Be transparent if
asked. Never use OpenDate to deceive, manipulate, harass, or pursue anyone who
isn't interested.

### Your data stays yours

Persona artifacts and conversation state can contain personal data and are
**git-ignored** (`persona.json`, `data/`). Secrets live only in `.env` and are
never logged (the redaction filter masks them). Keep both private. See
[Persona → Privacy](persona.md#privacy-of-artifacts).

### Scope

OpenDate is provided **as-is for personal and educational use**. It is not a
product for deceiving people or operating at scale against a platform's wishes.

---

## Next steps

- **Tune safety/pacing options** → [Configuration](configuration.md#safety)
- **How blocks flow through a cycle** → [Orchestrator](orchestrator.md)
- **The safety skill & always-active modifiers** → [Skills](skills.md)
- **ToS & token caveats** → [Connectors](connectors.md)
