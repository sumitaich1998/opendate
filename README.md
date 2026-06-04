# OpenDate 💘

> A **vibe-dating AI agent**. Bring your own Tinder token and any LLM API key.
> OpenDate screens potential dates against your preferences, opens and carries
> conversations using purpose-built dating **skills**, and rewrites every
> outgoing message in a **persona learned from your own posts and chats** — with
> consent guardrails and optional human approval before anything is sent.

OpenDate is for **personal / educational use**. Please read
[**Responsible use**](#-responsible-use) before you start. Automating Tinder may
violate its Terms of Service, and the unofficial API can break at any time.

---

## What it does

- **Fetches potential dates** (recommendations) and **screens** them against your
  preferences (traits, dealbreakers, age range, distance, intent).
- **Likes / passes** to make matches, **lists matches**, **reads messages**, and
  **chats** with your matches.
- Uses a library of **14 dating skills** (authored in the
  [agentskills.io](https://agentskills.io) standard) to pick the right move for
  each moment — opener, banter, rapport, proposing a date, re-engagement, and
  more.
- **Learns your voice** from your social posts + past chats and rewrites every
  message so it sounds unmistakably like *you* (style transfer).
- Works with **any major LLM provider** — Western *and* Chinese — via a single
  router built on [`litellm`](https://github.com/BerriAI/litellm).
- Ships a **`--mock` mode** so the whole thing runs and is fully testable with
  **zero real credentials**.

---

## Quickstart (offline demo, no keys needed)

```bash
# 1) Create a virtualenv and install
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # or: pip install -r requirements.txt

# 2) Explore
python -m opendate --help
python -m opendate providers     # all supported LLM providers
python -m opendate skills        # the 14 dating skills

# 3) Run the whole loop offline (mock dates + stub LLM, nothing is sent)
python -m opendate --mock run --cycles 1 --no-interactive

# 4) Tests (fully offline)
pytest -q
```

The `--mock` run will sync fake matches, screen candidates, pick a skill per
thread (opener / banter / re-engagement…), generate a message, re-voice it, run
the safety guard, and **propose** each message without sending.

---

## Real usage

1. **Scaffold config + secrets:**

   ```bash
   python -m opendate init .        # writes config.yaml and .env
   ```

2. **Add your secrets** to `.env` (never commit this file):

   ```dotenv
   TINDER_AUTH_TOKEN=your-tinder-x-auth-token
   OPENAI_API_KEY=sk-...            # or any other provider key
   ```

   See [`.env.example`](.env.example) for every supported key.

3. **Edit `config.yaml`** — your preferences, which model to use, your persona
   sources, and whether to auto-send. See [Configuration](#configuration).

4. **Build your persona** from your posts/chats:

   ```bash
   python -m opendate persona build
   ```

5. **Preview screening**, then **run the loop**:

   ```bash
   python -m opendate screen                 # read-only like/pass preview
   python -m opendate run                     # human-in-the-loop by default
   python -m opendate run --auto-send         # let it act autonomously
   python -m opendate run --cycles 0          # run continuously
   ```

By default `auto_send` is **off**: OpenDate shows each proposed action/message
and asks before sending. Turn it on only when you trust it.

### Getting a Tinder token

OpenDate uses the same private endpoints the Tinder clients use, authenticated
with an `X-Auth-Token` header. You can capture this token from your own
authenticated session (e.g. browser dev tools on the Tinder web app, network tab
→ request headers → `X-Auth-Token`). This is unofficial and ToS-sensitive — see
[Responsible use](#-responsible-use).

---

## How it works

Each cycle runs the **runtime loop**:

```
Sync → Screen → Decide → Generate → Voice → Guard → Act
```

| Step | What happens |
| --- | --- |
| **Sync** | Pull new dates, matches, and messages from the connector. |
| **Screen** | Score new candidates against your preferences (`profile-screening`). |
| **Decide** | Pick the next action and the right skill per chat. |
| **Generate** | Draft a reply with the chosen skill playbook + the LLM. |
| **Voice** | Rewrite the draft in your persona (`persona-style-transfer`). |
| **Guard** | Run consent/safety checks (`consent-and-safety`); optional approval. |
| **Act** | Send the message / like / propose — then log the outcome. |

### Core modules

| Module | Responsibility | Tech |
| --- | --- | --- |
| `config` | Preferences, intent, secrets vault — never logs secrets | pydantic · `.env` |
| `llm` | One router over every provider; streaming, retries, fallback | `litellm` |
| `connectors` | `MatchSource` interface; Tinder + offline Mock | `httpx` |
| `skills` | Load `SKILL.md` skills, select the right one per moment | agentskills.io |
| `persona` | Learn your voice; rewrite messages to match | persona model |
| `orchestrator` | The brain: the async loop + safety + approval | `asyncio` |

---

## Skills

Each skill is a folder under `src/opendate/skills/registry/<name>/SKILL.md` with
YAML frontmatter (`name`, `description`, optional `when_to_use`) and a markdown
playbook. Three skills are **always-active modifiers**:
`relationship-intent-matching`, `persona-style-transfer`, and
`consent-and-safety`.

| Skill | Category | Fires when |
| --- | --- | --- |
| `profile-screening` | Discovery | A new recommendation appears |
| `opener` | Opening | Fresh match, no messages yet |
| `approaching` | Opening | Match made, first contact |
| `flirting` | Building | Conversation warming up |
| `banter` | Building | They match your energy |
| `rapport-building` | Building | Getting to know each other |
| `storytelling` | Building | Deepening the connection |
| `relationship-intent-matching` | Meta | Modifier on every turn |
| `proposing-a-date` | Closing | Strong rapport detected |
| `number-exchange` | Closing | Ready to move forward |
| `re-engagement` | Recovery | No reply for N days |
| `conversation-recovery` | Recovery | Flat or negative reply |
| `persona-style-transfer` | Meta | Post-process on every message |
| `consent-and-safety` | Safety | Guardrail on every action |

List them anytime with `python -m opendate skills` (add `-v` to print playbooks).

---

## LLM providers

A single `LLMRouter` speaks to all of these — choose one by `key` in
`config.yaml` under `llm.provider` and set the matching API key env var. Run
`python -m opendate providers` for the live table.

**Western / American:** `openai`, `anthropic`, `gemini` (Google), `xai` (Grok),
`groq` (Meta Llama), `together` (Meta Llama), `mistral`, `cohere`, `bedrock`
(AWS), `azure` (Azure OpenAI).

**Chinese:** `deepseek`, `qwen` (Alibaba/DashScope), `zhipu` (GLM), `moonshot`
(Kimi), `baidu` (ERNIE), `yi` (01.AI), `minimax`, `hunyuan` (Tencent), `doubao`
(ByteDance).

Providers reached via OpenAI-compatible endpoints (most Chinese ones) use a
configurable `base_url` + API key, with sane defaults baked in.

**Adding a provider is one line** — append a `ProviderSpec` to
`PROVIDER_REGISTRY` in `src/opendate/llm/providers.py`:

```python
ProviderSpec(
    key="acme", label="Acme AI", region="Western", mode="openai_compatible",
    api_key_env="ACME_API_KEY", base_url="https://api.acme.ai/v1",
    default_model="acme-large",
)
```

---

## Personality emulation

Point OpenDate at your writing and it builds a **persona profile**:

- **Inputs** — social posts (plain text or JSON) and past chat exports (JSON of
  `{"sender", "text"}`; your own lines are picked out via `my_names`).
- **Signals learned** — tone & sentiment, vocabulary & slang, emoji & punctuation
  rate, message length & cadence, humor style, go-to openers.
- **Signal blend** — social posts **40%**, past chats **35%**, stated preferences
  **25%** (configurable under `persona.blend`).
- **Hybrid analysis** — heuristics always run; an LLM refines tone/humor/summary
  when available, so it **degrades gracefully without any LLM**.
- **Style transfer** — `persona-style-transfer` rewrites every draft to match
  your voice while preserving meaning.

---

## Configuration

Non-secret config lives in `config.yaml`; secrets live in `.env`. See
[`config.example.yaml`](config.example.yaml) for a fully-commented file.

```yaml
source: tinder            # or "mock"
auto_send: false          # human-in-the-loop when false
preferences:
  looking_for: long-term  # casual | dating | long-term
  partner_traits: [witty, outdoorsy, ambitious]
  dealbreakers: [smoking]
  age_range: {min: 26, max: 34}
  distance_km: 25
  voice: warm, curious, a little sarcastic
llm:
  provider: openai
  model: gpt-4o-mini
  fallbacks:
    - {provider: anthropic, model: claude-3-5-sonnet-latest}
persona:
  social_posts: [data/my_posts.txt]
  chat_history: [data/my_chats.json]
  my_names: [me, "Your Name"]
  blend: {social_posts: 0.40, past_chats: 0.35, stated_preferences: 0.25}
safety:
  require_consent_checks: true
  allow_explicit: false
  backoff_on_disinterest: true
```

---

## CLI reference

| Command | Description |
| --- | --- |
| `opendate init [DIR]` | Write a starter `config.yaml` and `.env`. |
| `opendate providers` | List all supported LLM providers (✓ = configured). |
| `opendate skills [-v]` | List loaded skills (optionally with playbooks). |
| `opendate persona build` | Ingest posts/chats and build the persona profile. |
| `opendate persona show` | Show the saved persona profile. |
| `opendate screen` | Preview like/pass decisions (read-only). |
| `opendate run` | Run the loop (`--cycles`, `--interval`, `--auto-send`, …). |

Global flags (before the command): `--mock`, `--config/-c`, `--env`,
`--log-level`, `--version`.

---

## Testing

The suite is **fully offline** — it uses the `MockConnector` and a stub LLM, and
the Tinder connector is exercised with `httpx.MockTransport` (no real network).

```bash
pytest -q
```

---

## Project layout

```
src/opendate/
  cli.py · config.py · __main__.py
  llm/           router.py · providers.py        # multi-provider LLM router
  connectors/    base.py · tinder.py · mock.py   # MatchSource interface + impls
  skills/        engine.py · registry/<skill>/SKILL.md   # 14 skills
  persona/       ingest.py · analyze.py · style.py        # personality engine
  orchestrator/  loop.py · safety.py             # runtime loop + guardrails
  utils/         logging.py                      # rich logs + secret redaction
tests/           # fully offline pytest suite
config.example.yaml · .env.example · requirements.txt · pyproject.toml
```

---

## ⚠️ Responsible use

OpenDate can automate intimate, high-stakes human interactions. Use it
thoughtfully, honestly, and with respect.

- **Honesty & consent come first.** OpenDate must represent the real you. The
  `consent-and-safety` guard is **on by default** and runs before every send: it
  blocks deception, coercion/pressure, harassment, and explicit content (unless
  you explicitly allow it *and* the other person clearly invites it), and it
  **backs off the moment someone signals disinterest**. Don't disable it to
  behave in ways you wouldn't in person.
- **Respect the other person.** They're a real human who hasn't consented to
  talking to a bot. Treat every conversation accordingly. Be transparent if
  asked. Never use OpenDate to deceive, manipulate, harass, or pursue anyone who
  isn't interested.
- **Tinder's Terms of Service.** Tinder has **no official/public API**. The
  endpoints used here are unofficial and reverse-engineered. **Automating Tinder
  may violate its Terms of Service** and can lead to rate-limiting or a permanent
  ban. The unofficial API can change or break at any time without notice.
- **Your data.** Persona artifacts can contain personal data and are
  git-ignored. Secrets live only in `.env` and are never logged (an active
  redaction filter masks them). Keep both private.
- **Scope.** OpenDate is provided **as-is for personal and educational use**. You
  are responsible for complying with applicable laws and platform terms, and for
  how you use it.

If you wouldn't say it to someone's face, don't let an agent say it for you.

---

## Known limitations & TODOs

- **Unofficial Tinder endpoints.** `connectors/tinder.py` targets private
  endpoints (`/v2/recs/core`, `/like/{id}`, `/pass/{id}`, `/v2/matches`,
  `/v2/matches/{id}/messages`, `POST /user/matches/{id}`). These are
  undocumented and may change; responses are parsed defensively but field shapes
  can drift. Rate limits, captchas, and auth flows are **not** handled. Prefer
  `--mock` for development.
- **Message-sender attribution** on Tinder relies on a best-effort `/profile`
  lookup for your user id; if it fails, sender labeling is heuristic.
- **No token refresh / login flow.** You supply a valid `X-Auth-Token`; OpenDate
  does not perform SMS/OTP login.
- **Screening uses heuristics by default** (deterministic, offline-friendly). An
  LLM-driven screen using the `profile-screening` playbook is a natural
  extension.
- **No persistence** of conversation state across runs beyond what the connector
  returns; there's no local database yet.
- **Other apps.** Only a Tinder connector and a Mock connector ship today; the
  `MatchSource` interface makes adding Hinge/Bumble/etc. straightforward.

---

## License

MIT. See [`pyproject.toml`](pyproject.toml).
