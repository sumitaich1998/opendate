# Glossary

Definitions of the terms used throughout OpenDate and these docs. Each links to
where the concept is covered in depth.

| Term | Definition |
| --- | --- |
| **Candidate** | A potential date — a recommendation fetched before any like/pass decision. The `Candidate` model carries id, name, age, bio, distance, photos, prompts, interests, jobs, schools. See [Connectors](connectors.md#data-models). |
| **Match** | A mutual match you can message. The `Match` model carries id, person, bio, photos, timestamps, and the message thread. See [Connectors](connectors.md#data-models). |
| **Message** | One chat message in a thread, with a `sender` of `me` or `them`. See [Connectors](connectors.md#data-models). |
| **Connector** | A data source implementing the `MatchSource` interface (e.g. Tinder or the offline mock). See [Connectors](connectors.md). |
| **`MatchSource`** | The async Protocol every connector implements (get recommendations/matches/messages, like, pass, send, close). See [Connectors](connectors.md#the-matchsource-interface). |
| **Mock connector** | A deterministic, in-memory `MatchSource` with seed data, used by `--mock` and tests — no credentials, no network. See [Connectors](connectors.md#the-mock-connector). |
| **Stub LLM** | `EchoBackend` — a deterministic, network-free LLM backend used by `--mock` and tests. A router on it reports `is_stub == True`. See [Providers](providers.md#the-offline-stub). |
| **Router** | `LLMRouter` — one interface over every provider, with retries, fallback, and usage accounting. See [Providers](providers.md). |
| **Provider / route** | One LLM vendor entry (a `ProviderSpec`) in the registry, selected by `key`. OpenDate ships 19 routes. See [Providers](providers.md). |
| **Native vs openai_compatible** | The two integration modes: `native` (litellm first-class, `prefix/model`) vs `openai_compatible` (OpenAI-style endpoint via a base URL). See [Providers](providers.md#integration-modes). |
| **Fallback** | An ordered alternate provider/model the router tries if the primary fails. See [Providers](providers.md#fallbacks-retries-timeouts--usage). |
| **Skill** | A unit of dating behaviour defined by a `SKILL.md` (frontmatter + playbook). OpenDate ships 14. See [Skills](skills.md). |
| **Playbook** | A skill's markdown body — the do-this/not-that guidance fed to the LLM. See [Skills](skills.md#the-skillmd-format). |
| **Modifier (always-active skill)** | A skill layered on top of every primary: `relationship-intent-matching`, `persona-style-transfer`, `consent-and-safety`. See [Skills](skills.md#always-active-modifiers). |
| **Skill selection** | Choosing the primary skill for a moment via heuristics over the `SituationContext`, with an optional LLM tie-break. See [Skills](skills.md#how-selection-works). |
| **`SituationContext`** | A flat snapshot of a conversation moment (sentiment, interest, playful/banter/disinterest, rapport, stage, …) that drives selection. See [Architecture](architecture.md#data-flow--models). |
| **Persona** | A learned model of the user's texting voice (`PersonaProfile`), built from their posts and chats. See [Persona](persona.md). |
| **Voice card** | A compact, at-a-glance summary of the persona (tone, humor, cadence, emoji, sample line). See [Persona](persona.md#the-voice-card--style-brief). |
| **Style brief** | The fuller, prompt-ready persona description injected into generation/style-transfer prompts. See [Persona](persona.md#the-voice-card--style-brief). |
| **Style transfer** | Rewriting a draft so it sounds like the user, preserving meaning (the `persona-style-transfer` runtime). See [Persona](persona.md#style-transfer). |
| **Blend** | The weighting of persona signal sources (default 40% posts / 35% chats / 25% stated preferences). See [Persona](persona.md#the-blend). |
| **`my_names`** | The user's names/handles, used to pick out their own lines in chat exports. See [Persona](persona.md#accepted-input-formats). |
| **Exemplars** | Representative real user lines used as few-shot voice examples in prompts. See [Persona](persona.md#signals-learned). |
| **Orchestrator** | The async brain that runs the loop across all matches each cycle. See [Orchestrator](orchestrator.md). |
| **The loop** | One cycle of Sync → Screen → Decide → Generate → Voice → Guard → Act. See [Architecture](architecture.md#the-runtime-loop-step-by-step). |
| **Screening** | Scoring a candidate against your preferences into a like/pass decision (`score_candidate`). See [Orchestrator](orchestrator.md#screening). |
| **Stage** | Where a thread sits along the dating arc: `matched`, `opened`, `rapport`, `flirting`, `proposing`, `number_exchanged`, `stalled`, `ghosted`, `recovering`, `closed`. See [Orchestrator](orchestrator.md#the-stage-machine). |
| **Stage machine** | The deterministic function (`compute_stage`) that resolves a thread's stage from signals. See [Orchestrator](orchestrator.md#the-stage-machine). |
| **`PlannedAction`** | One decision the orchestrator made this cycle (`like`/`pass`/`send`/`skip`/`backoff`/`blocked`) with its skill, text, stage, confidence, and quality. See [Orchestrator](orchestrator.md#per-match-handling). |
| **Conversation store** | `ConversationStore` — persists per-match `ConversationState` + the daily action log to `data/conversations.json`. See [Orchestrator](orchestrator.md#where-state--decision-logs-live). |
| **Decision log** | The append-only JSONL audit trail at `data/decisions.jsonl`. See [Orchestrator](orchestrator.md#where-state--decision-logs-live). |
| **Safety guard** | `SafetyGuard` — the blocking consent/safety + pacing gate run before every send. See [Safety](safety.md). |
| **Hard vs soft block** | A `hard` block never sends (becomes `blocked`); a `soft` block eases off (becomes `backoff`). See [Safety](safety.md#what-it-blocks-and-when). |
| **Pacing** | Anti-spam guards: cooldowns, the rolling daily action cap, and no-double-text. See [Safety](safety.md#pacing-cooldowns-daily-cap-no-double-text). |
| **Human-in-the-loop** | The default mode (`auto_send: false`): propose each action and ask before sending. See [Safety](safety.md#human-in-the-loop-vs-auto-send). |
| **Auto-send** | `auto_send: true` / `--auto-send`: send approved actions without asking (the safety gate still applies). See [Safety](safety.md#human-in-the-loop-vs-auto-send). |
| **Quality critic** | The self-critique pass (`critique_message`) that scores drafts and triggers a single regeneration of weak ones. See [Orchestrator](orchestrator.md#generation--self-critique). |
| **Redaction** | The logging filter that masks secret values everywhere in logs. See [Safety](safety.md#logging--redaction). |
| **`--mock`** | The global flag that forces the offline mock connector + stub LLM. See [CLI](cli.md#global-options). |
| **`X-Auth-Token`** | The Tinder auth header value you supply via `TINDER_AUTH_TOKEN`. See [Connectors](connectors.md#getting-an-x-auth-token). |

---

## Next steps

- **See these terms in action** → [Architecture](architecture.md)
- **Back to the index** → [docs/README.md](README.md)
