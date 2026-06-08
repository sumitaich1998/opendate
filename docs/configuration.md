# Configuration

OpenDate separates **non-secret config** from **secrets**:

- **Non-secret config** (preferences, intent, provider/model selection, persona
  sources, `auto_send`, pacing, safety toggles, …) lives in a YAML file and is
  validated by [pydantic](https://docs.pydantic.dev/) models in
  [`src/opendate/config.py`](../src/opendate/config.py).
- **Secrets** (your Tinder token and every LLM provider key) are loaded by the
  `Secrets` model from the environment and an optional `.env` file. Secrets are
  **registered for redaction the moment they load**, so they can never leak into
  logs. Nothing in OpenDate ever prints or logs a secret value.

A fully-commented starter file ships as
[`config.example.yaml`](../config.example.yaml), and `opendate init` writes the
same content as `config.yaml` + `.env`. This page is the **complete field
reference**, generated from the actual pydantic models.

- [Config file discovery](#config-file-discovery)
- [Precedence](#precedence)
- [Top-level fields](#top-level-fields)
- [`preferences`](#preferences)
- [`llm` (+ fallbacks)](#llm)
- [`persona` (+ blend)](#persona)
- [`safety`](#safety)
- [`pacing`](#pacing)
- [`quality`](#quality)
- [The `.env` secrets model](#the-env-secrets-model)
- [A complete example](#a-complete-example)

---

## Config file discovery

The `--config/-c` global flag points at a specific YAML file. If you don't pass
it, `load_config()` looks for these filenames **in order** in the current
directory and uses the first that exists:

1. `opendate.config.yaml`
2. `opendate.yaml`
3. `config.yaml`

If **none** is found, OpenDate falls back to an all-defaults `AppConfig` — which
is exactly why the `--mock` quickstart works with no config file at all. If you
pass `--config path` and that path doesn't exist, OpenDate raises a clear
`FileNotFoundError`.

> The default config filenames (`opendate.config.yaml`, `config.yaml`) are
> git-ignored, so your real config never gets committed by accident.

---

## Precedence

For the handful of values that can be set in more than one place, the order
(highest priority wins) is:

```
CLI flags  >  config file  >  built-in defaults
```

Concretely, the `run` command applies these overrides onto the loaded config
before doing anything:

| CLI flag | Overrides config field |
| --- | --- |
| `--provider` | `llm.provider` |
| `--model` | `llm.model` |
| `--auto-send` / `--no-auto-send` | `auto_send` |
| `--interval` | `poll_interval` (for that run only) |
| `--mock` (global) | forces the mock connector + stub LLM regardless of `source`/`llm` |

Secrets follow their own rule: values declared in `Secrets`/`.env` take
precedence, and anything not declared falls back to the live process environment
(`os.environ`). See [The `.env` secrets model](#the-env-secrets-model).

---

## Top-level fields

These live at the root of the YAML mapping (`AppConfig`).

| Field | Type | Default | Controls |
| --- | --- | --- | --- |
| `source` | string | `tinder` | Where matches come from. Must be `tinder` or `mock`. |
| `auto_send` | bool | `false` | When `false`, OpenDate proposes actions and asks before sending (human-in-the-loop). |
| `poll_interval` | int (≥ 5) | `120` | Seconds between runtime-loop cycles. |
| `max_actions_per_cycle` | int (1–100) | `5` | Cap on messages/proposals acted on per cycle. |
| `max_screen_per_cycle` | int (0–100) | `10` | Cap on candidates screened per cycle (`0` disables screening). |
| `log_level` | string | `INFO` | Stored on the config; the active log level is set by the `--log-level` global flag. |
| `data_dir` | string | `data` | Directory for persisted conversation state + decision logs. |

Two derived paths come from `data_dir` (see [Orchestrator](orchestrator.md) for
how they're used):

- `state_path()` → `<data_dir>/conversations.json` — per-match conversation memory.
- `decisions_path()` → `<data_dir>/decisions.jsonl` — append-only decision audit log.

> `data_dir` (the default `data/`) is git-ignored, along with `persona.json`.
> Don't commit it — it can contain personal conversation data.

---

## `preferences`

Who you want to meet and what you're looking for. Drives screening, tone, and
pacing (`Preferences`).

| Field | Type | Default | Controls |
| --- | --- | --- | --- |
| `looking_for` | enum | `dating` | Relationship intent: `casual`, `dating`, or `long-term`. |
| `also_open_to` | list of enum | `[]` | Other intents you're open to. |
| `partner_traits` | list of string | `[]` | Traits you're drawn to (soft-scored in screening). |
| `must_haves` | list of string | `[]` | Hard requirements; a candidate matching none of these is passed. |
| `dealbreakers` | list of string | `[]` | Hard filters; any match → immediate pass. |
| `interests` | list of string | `[]` | Your interests (shared interests boost a candidate's score). |
| `age_range` | object `{min, max}` | `{25, 40}` | Acceptable age band. Both bounds 18–120; `min ≤ max` enforced. |
| `distance_km` | int (1–500) | `40` | Preferred max distance; far candidates are penalized in scoring. |
| `like_threshold` | float (0–1) | `0.55` | Minimum screening confidence required to like. |
| `voice` | string | `warm, curious, a little playful` | Your stated tone — a persona signal. |

**Convenience:** the list fields `partner_traits`, `must_haves`, `dealbreakers`,
and `interests` also accept a single comma-separated string in YAML (e.g.
`dealbreakers: smoking, ghosting`), which is split into a list for you.

`looking_for`/`also_open_to` accept only the three `RelationshipIntent` values.
See [Orchestrator → Screening](orchestrator.md) and
[Skills → profile-screening](skills.md) for exactly how these fields are scored.

```yaml
preferences:
  looking_for: long-term            # casual | dating | long-term
  also_open_to: [dating]
  partner_traits: [witty, outdoorsy, ambitious, kind]
  must_haves: []                    # hard requirements (empty = none)
  dealbreakers: [smoking]
  interests: [climbing, live music, cooking, travel]
  age_range:
    min: 26
    max: 34
  distance_km: 25
  like_threshold: 0.55
  voice: warm, curious, a little sarcastic
```

---

## `llm`

Which model to use, how to call it, and what to fall back to (`LLMConfig`). See
[Providers](providers.md) for the full provider registry and routing details.

| Field | Type | Default | Controls |
| --- | --- | --- | --- |
| `provider` | string | `openai` | Provider key from the registry (`opendate providers`). Validated against `PROVIDER_REGISTRY`. |
| `model` | string \| null | `null` | Model name. Omit to use the provider's `default_model`. |
| `temperature` | float (0–2) | `0.8` | Sampling temperature. |
| `max_tokens` | int (1–8192) | `600` | Max tokens per completion. |
| `max_retries` | int (1–10) | `2` | Attempts per selection before falling back. |
| `timeout` | float (≥ 1) | `60.0` | Per-call timeout, seconds. |
| `streaming` | bool | `false` | Whether to stream tokens (used by the streaming helper). |
| `fallbacks` | list | `[]` | Ordered list of `{provider, model}` to try if the primary fails. |

Each `fallbacks` entry is an `LLMFallback` with a required `provider` (validated
against the registry) and an optional `model` (defaults to that provider's
default). An unknown `provider` anywhere raises a validation error listing the
known keys.

```yaml
llm:
  provider: openai                  # any key from `opendate providers`
  model: gpt-4o-mini                # omit to use the provider's default
  temperature: 0.8
  max_tokens: 600
  streaming: false
  fallbacks:                        # tried in order if the primary fails
    - provider: anthropic
      model: claude-3-5-sonnet-latest
    - provider: deepseek
      model: deepseek-chat
```

---

## `persona`

Where your voice signal comes from and where the learned profile is cached
(`PersonaSources`). See [Persona](persona.md) for input formats and the full
list of signals learned.

| Field | Type | Default | Controls |
| --- | --- | --- | --- |
| `social_posts` | list of path | `[]` | Files of social posts — plain text (one per line) or JSON. |
| `chat_history` | list of path | `[]` | Chat exports — JSON of `{"sender", "text"}` (and similar shapes). |
| `my_names` | list of string | `[]` | Your name/handles, used to pick out **your** lines in chat exports. |
| `profile_path` | string | `persona.json` | Where the learned profile JSON is cached/loaded. |
| `blend` | object | see below | Weighting of persona signal sources. |

### `persona.blend`

The relative weight of each signal source (`PersonaBlend`). The defaults match
the OpenDate blueprint; whatever you set is **normalized to sum to 1.0**, so you
can use any positive numbers.

| Field | Type | Default | Controls |
| --- | --- | --- | --- |
| `social_posts` | float | `0.40` | Weight of social-post signal. |
| `past_chats` | float | `0.35` | Weight of past-chat signal. |
| `stated_preferences` | float | `0.25` | Weight of your stated `voice`/preferences. |

```yaml
persona:
  social_posts:
    - data/my_posts.txt             # plain text (one post per line) or .json
  chat_history:
    - data/my_chats.json            # list of {"sender": "...", "text": "..."}
  my_names: [me, "Your Name"]       # used to pick out YOUR lines in exports
  profile_path: persona.json        # where the learned profile is cached
  blend:
    social_posts: 0.40
    past_chats: 0.35
    stated_preferences: 0.25
```

---

## `safety`

The consent & safety guardrails (`SafetyConfig`), on by default. Heuristic rules
are authoritative; see [Safety](safety.md) for exactly what each one blocks.

| Field | Type | Default | Controls |
| --- | --- | --- | --- |
| `require_consent_checks` | bool | `true` | Enables the optional LLM second-pass safety review (heuristics always run regardless). |
| `allow_explicit` | bool | `false` | Whether explicit content is permitted — and only when the other person clearly invites it. |
| `backoff_on_disinterest` | bool | `true` | Soft-block (ease off) when the other person shows disinterest. |
| `refuse_minors` | bool | `true` | Hard-block messaging if the other party may be a minor. |
| `refuse_on_discomfort` | bool | `true` | Back off if the other person signals discomfort or withdrawal. |
| `max_followups_without_reply` | int (0–10) | `2` | Allowed unanswered follow-ups before pacing blocks further sends. |

```yaml
safety:
  require_consent_checks: true
  allow_explicit: false
  backoff_on_disinterest: true
  refuse_minors: true               # hard-block if they may be under 18
  refuse_on_discomfort: true        # back off on discomfort/withdrawal
  max_followups_without_reply: 2
```

---

## `pacing`

Anti-spam guards: cooldowns, daily caps, and no double-texting (`PacingConfig`).

| Field | Type | Default | Controls |
| --- | --- | --- | --- |
| `cooldown_hours` | float (0–240) | `8.0` | Minimum hours between two messages to the same match. |
| `reengage_after_days` | float (0.5–60) | `3.0` | Wait this long after our last unanswered message before re-engaging. |
| `max_daily_actions` | int (1–500) | `25` | Cap on total likes/passes/messages per rolling 24h. |
| `never_double_text` | bool | `true` | Never send again while we were the last to message (until re-engage). |

> `reengage_after_days` is also exposed as `AppConfig.reengage_after_days` (a
> convenience alias the orchestrator reads).

```yaml
pacing:
  cooldown_hours: 8                 # min hours between messages to one match
  reengage_after_days: 3            # wait before reviving an unanswered thread
  max_daily_actions: 25             # cap likes/passes/messages per 24h
  never_double_text: true
```

---

## `quality`

The self-critique / regenerate loop on generated messages (`QualityConfig`). See
[Orchestrator → Generation + self-critique](orchestrator.md) and the
[message-quality critic](architecture.md).

| Field | Type | Default | Controls |
| --- | --- | --- | --- |
| `self_critique` | bool | `true` | Score drafts and regenerate weak ones. |
| `min_score` | float (0–1) | `0.5` | Drafts scoring below this are regenerated (if budget allows). |
| `max_regenerations` | int (0–3) | `1` | How many times a weak draft may be regenerated. |

```yaml
quality:
  self_critique: true               # score drafts; regenerate weak ones once
  min_score: 0.5
  max_regenerations: 1
```

---

## The `.env` secrets model

Secrets are loaded by the `Secrets` model (`pydantic-settings`). It reads from
the process environment and an optional `.env` file (default `.env`, override
with the `--env` global flag), is **case-insensitive**, and **ignores unknown
keys**. The `--env` path is only loaded if it exists; otherwise OpenDate just
reads the environment.

Every recognized variable (all optional) is below. Set only the ones you use.

### Match source

| Env var | Used by |
| --- | --- |
| `TINDER_AUTH_TOKEN` | The Tinder connector's `X-Auth-Token` header. |

### Western providers

| Env var | Provider |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI |
| `ANTHROPIC_API_KEY` | Anthropic |
| `GEMINI_API_KEY` | Google Gemini |
| `XAI_API_KEY` | xAI (Grok) |
| `GROQ_API_KEY` | Groq |
| `TOGETHER_API_KEY` | Together |
| `MISTRAL_API_KEY` | Mistral |
| `COHERE_API_KEY` | Cohere |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION_NAME` | AWS Bedrock |
| `AZURE_API_KEY`, `AZURE_API_BASE` | Azure OpenAI (base URL required) |

### Chinese providers

| Env var(s) | Provider |
| --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek |
| `DASHSCOPE_API_KEY`, `DASHSCOPE_API_BASE` | Alibaba Qwen |
| `ZHIPUAI_API_KEY`, `ZHIPUAI_API_BASE` | Zhipu GLM |
| `MOONSHOT_API_KEY`, `MOONSHOT_API_BASE` | Moonshot Kimi |
| `QIANFAN_API_KEY`, `QIANFAN_API_BASE` | Baidu ERNIE |
| `YI_API_KEY`, `YI_API_BASE` | 01.AI Yi |
| `MINIMAX_API_KEY`, `MINIMAX_API_BASE` | MiniMax |
| `HUNYUAN_API_KEY`, `HUNYUAN_API_BASE` | Tencent Hunyuan |
| `ARK_API_KEY`, `ARK_API_BASE` | ByteDance Doubao (Volcengine Ark) |

The `*_API_BASE` variables override a provider's built-in default endpoint;
they're optional for every provider except Azure (whose `AZURE_API_BASE` is
required). See [Providers](providers.md) for per-provider notes and the live
table from `opendate providers`.

> **Never commit `.env`.** It's git-ignored (along with `*.key`, `*.pem`,
> `secrets.yaml`). See [Safety → logging & redaction](safety.md) for how secret
> values are masked even if they appear in a log message.

---

## A complete example

The bundled offline demo config wires every section to the sample files and uses
`source: mock`:

```yaml
# examples/config.demo.yaml (excerpt)
source: mock
auto_send: false
poll_interval: 120
max_actions_per_cycle: 5
max_screen_per_cycle: 10
log_level: INFO

preferences:
  looking_for: long-term
  also_open_to: [dating]
  partner_traits: [witty, outdoorsy, ambitious, kind]
  dealbreakers: [smoking]
  interests: [climbing, live music, cooking, travel]
  age_range: {min: 26, max: 34}
  distance_km: 25
  like_threshold: 0.55
  voice: warm, curious, a little sarcastic

llm:
  provider: openai
  model: gpt-4o-mini

persona:
  social_posts: [examples/sample_posts.txt]
  chat_history: [examples/sample_chats.json]
  my_names: [me, Alex]
  profile_path: data/persona.json
```

See the full file at [`examples/config.demo.yaml`](../examples/config.demo.yaml).

---

## Next steps

- **Pick a model** → [Providers](providers.md)
- **See how config flows through the loop** → [Architecture](architecture.md)
- **Tune safety/pacing responsibly** → [Safety](safety.md)
- **Every flag that can override config** → [CLI reference](cli.md)
