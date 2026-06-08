# LLM providers & the router

OpenDate talks to **19 provider routes** — 10 Western and 9 Chinese — through a
single `LLMRouter`. You pick one by `key` in `config.yaml` under `llm.provider`
and set the matching API key env var; everything else (model-string formatting,
base URLs, retries, fallbacks) is handled for you. The two relevant modules are
[`llm/providers.py`](../src/opendate/llm/providers.py) (the registry) and
[`llm/router.py`](../src/opendate/llm/router.py) (the router).

- [The router in one paragraph](#the-router-in-one-paragraph)
- [The full provider table](#the-full-provider-table)
- [Integration modes: native vs openai_compatible](#integration-modes)
- [Per-provider setup notes](#per-provider-setup-notes)
- [Fallbacks, retries, timeouts & usage](#fallbacks-retries-timeouts--usage)
- [The offline stub](#the-offline-stub)
- [Add a new provider](#add-a-new-provider)

---

## The router in one paragraph

`LLMRouter` holds an ordered list of model *selections* — the primary plus any
configured fallbacks — each resolved by `resolve_model(...)` into concrete
`litellm` kwargs. On a call it tries the primary, **retrying it up to
`max_retries` times** with exponential backoff, then **falls back** to the next
selection, and so on. It's backed by one of two backends: `LiteLLMBackend`
(real calls via `litellm`, imported lazily so the rest of OpenDate stays
offline) or `EchoBackend` (a deterministic, network-free stub used by `--mock`
and the tests). A stub-backed router reports `is_stub == True`, which the
persona, style, safety, and quality code use to fall back to heuristics instead
of round-tripping a fake LLM.

---

## The full provider table

This is the complete registry from `PROVIDER_REGISTRY`. Run
`opendate providers` for the same data live (with a ✓ where credentials are
present). "Base URL (default)" applies only to `openai_compatible` providers and
is overridable via the listed env var.

### Western / American (native)

| Key | Provider | Mode | API key env | Default model |
| --- | --- | --- | --- | --- |
| `openai` | OpenAI | native | `OPENAI_API_KEY` | `gpt-4o-mini` |
| `anthropic` | Anthropic | native | `ANTHROPIC_API_KEY` | `claude-3-5-sonnet-latest` |
| `gemini` | Google (Gemini) | native | `GEMINI_API_KEY` | `gemini-1.5-flash` |
| `xai` | xAI (Grok) | native | `XAI_API_KEY` | `grok-2-latest` |
| `groq` | Groq (Meta Llama) | native | `GROQ_API_KEY` | `llama-3.3-70b-versatile` |
| `together` | Together (Meta Llama) | native | `TOGETHER_API_KEY` | `meta-llama/Llama-3.3-70B-Instruct-Turbo` |
| `mistral` | Mistral | native | `MISTRAL_API_KEY` | `mistral-large-latest` |
| `cohere` | Cohere | native | `COHERE_API_KEY` | `command-r-plus` |
| `bedrock` | AWS Bedrock | native | `AWS_ACCESS_KEY_ID` | `anthropic.claude-3-5-sonnet-20240620-v1:0` |
| `azure` | Azure OpenAI | native | `AZURE_API_KEY` | `gpt-4o` |

### Chinese

| Key | Provider | Mode | API key env | Base URL (default) | Base URL env | Default model |
| --- | --- | --- | --- | --- | --- | --- |
| `deepseek` | DeepSeek | native | `DEEPSEEK_API_KEY` | — | — | `deepseek-chat` |
| `qwen` | Alibaba Qwen (DashScope) | openai_compatible | `DASHSCOPE_API_KEY` | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | `DASHSCOPE_API_BASE` | `qwen-plus` |
| `zhipu` | Zhipu AI (GLM) | openai_compatible | `ZHIPUAI_API_KEY` | `https://open.bigmodel.cn/api/paas/v4` | `ZHIPUAI_API_BASE` | `glm-4-plus` |
| `moonshot` | Moonshot (Kimi) | openai_compatible | `MOONSHOT_API_KEY` | `https://api.moonshot.cn/v1` | `MOONSHOT_API_BASE` | `moonshot-v1-8k` |
| `baidu` | Baidu (ERNIE) | openai_compatible | `QIANFAN_API_KEY` | `https://qianfan.baidubce.com/v2` | `QIANFAN_API_BASE` | `ernie-4.0-8k` |
| `yi` | 01.AI (Yi) | openai_compatible | `YI_API_KEY` | `https://api.lingyiwanwu.com/v1` | `YI_API_BASE` | `yi-large` |
| `minimax` | MiniMax | openai_compatible | `MINIMAX_API_KEY` | `https://api.minimax.chat/v1` | `MINIMAX_API_BASE` | `abab6.5s-chat` |
| `hunyuan` | Tencent (Hunyuan) | openai_compatible | `HUNYUAN_API_KEY` | `https://api.hunyuan.cloud.tencent.com/v1` | `HUNYUAN_API_BASE` | `hunyuan-standard` |
| `doubao` | ByteDance (Doubao) | openai_compatible | `ARK_API_KEY` | `https://ark.cn-beijing.volces.com/api/v3` | `ARK_API_BASE` | `doubao-pro-32k` |

> All Western providers are `native`; `azure` requires a base URL
> (`AZURE_API_BASE`). Among the Chinese providers, `deepseek` is `native` and the
> other eight are `openai_compatible` with sane default base URLs baked in.

Each `ProviderSpec` also carries `example_models` (shown in the registry) — e.g.
`openai` suggests `gpt-4o`, `gpt-4.1`, `o3-mini`; `deepseek` suggests
`deepseek-chat`, `deepseek-reasoner`. Inspect them in code or via the examples.

---

## Integration modes

`resolve_model(provider, model, secrets)` turns a `(provider, model)` pair into a
`ResolvedModel` (concrete `litellm` kwargs), branching on the spec's `mode`:

- **`native`** — `litellm` has first-class support. The model string becomes
  `"{litellm_prefix}/{model}"` (e.g. `anthropic/claude-3-5-sonnet-latest`,
  `gemini/gemini-1.5-flash`), with the API key passed explicitly and the base URL
  set only if the spec defines one.
- **`openai_compatible`** — the provider exposes an OpenAI-compatible endpoint.
  The model string becomes `"openai/{model}"` and requests route through
  litellm's OpenAI handler with the provider's `base_url` (or the override from
  `base_url_env`) and API key.

`provider_ready(provider, secrets)` returns whether the credentials needed for a
provider are present (and, for Azure, whether the required base URL is set). The
`run`/`persona build` commands call `router.ensure_ready(...)` for non-mock runs,
which raises a clear error if the **primary** provider has no credentials.

---

## Per-provider setup notes

Most providers need only their API key. The exceptions:

- **AWS Bedrock (`bedrock`)** — uses standard AWS credentials, not a single key:
  `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_REGION_NAME`. Set `model`
  to a Bedrock model id (e.g. `anthropic.claude-3-5-sonnet-20240620-v1:0`).
- **Azure OpenAI (`azure`)** — requires `AZURE_API_BASE` in addition to
  `AZURE_API_KEY`; `model` is your Azure **deployment** name.
- **Alibaba Qwen (`qwen`)** — the default base URL is the international DashScope
  endpoint (`dashscope-intl...`). If you use the mainland endpoint, override
  `DASHSCOPE_API_BASE`.
- **ByteDance Doubao (`doubao`)** — served through Volcengine Ark; `model` is your
  endpoint id, and `ARK_API_KEY` / `ARK_API_BASE` configure it.
- **Chinese `openai_compatible` providers in general** — each has a working
  default `base_url`; override it with the corresponding `*_API_BASE` env var if
  your account uses a different region/host.

The simplest setup is one provider key:

```dotenv
# .env
OPENAI_API_KEY=sk-...
```

```yaml
# config.yaml
llm:
  provider: openai
  model: gpt-4o-mini   # omit to use the provider default
```

---

## Fallbacks, retries, timeouts & usage

`LLMRouter.from_config(...)` builds the selection list as
`[primary, *fallbacks]`, resolving each through the registry, and registers every
resolved API key for log redaction.

- **Retries.** Each selection is attempted up to `max_retries` times (config
  default `2`). Between attempts the router sleeps with exponential backoff
  (`retry_backoff * 2^(attempt-1)`, default base `0.5s`).
- **Fallbacks.** When a selection exhausts its retries, the router logs the
  fallback and moves to the next selection. If **all** selections fail, it raises
  a `RuntimeError` carrying the last error.
- **Timeouts.** Each call passes `timeout` (config default `60.0s`) through to
  `litellm`.
- **Streaming.** `LLMRouter.stream(...)` streams tokens from the **primary**
  selection only (no mid-stream fallback).
- **Usage accounting.** The router accumulates `calls`, `prompt_tokens`,
  `completion_tokens`, and `total_tokens` across its lifetime (when the provider
  returns usage), logged at debug level.
- **Structured JSON.** `complete_json(...)` / `chat_json(...)` run a completion
  and parse the first JSON object out of the reply (tolerating code fences and
  chatty preambles via `extract_json`), returning a `default` on any failure —
  used by the skill tie-break, safety review, and quality critic.

```yaml
llm:
  provider: openai
  model: gpt-4o-mini
  max_retries: 2
  timeout: 60.0
  fallbacks:
    - {provider: anthropic, model: claude-3-5-sonnet-latest}
    - {provider: deepseek,  model: deepseek-chat}
```

---

## The offline stub

`EchoBackend` is a deterministic backend used whenever `--mock` is active (and in
tests). Its default responder reads a `PRIMARY_SKILL:` hint that the orchestrator
embeds in the system prompt and returns a canned, skill-appropriate draft from
`_STUB_DRAFTS` (e.g. an `opener`, `banter`, or `proposing-a-date` line); it also
echoes back text delimited by `<<<DRAFT>>>...<<<END>>>` so the style-transfer
path stays coherent offline. This is why the keyless quickstart produces
sensible, varied messages with no network or API key.

A stub router sets `is_stub = True`. Code that would otherwise call an LLM for
*refinement* (persona refine, LLM style transfer, skill tie-break, safety review,
quality sharpening) checks this flag and falls back to heuristics — so offline
behaviour is fully deterministic.

---

## Add a new provider

Adding a provider is intentionally **one entry**. This mirrors the steps in
[`CONTRIBUTING.md`](../CONTRIBUTING.md#how-to-add-a-new-llm-provider).

1. **Append a `ProviderSpec`** to `_PROVIDERS` in
   [`llm/providers.py`](../src/opendate/llm/providers.py):

   ```python
   ProviderSpec(
       key="acme",
       label="Acme AI",
       region="Western",                  # or "Chinese"
       mode="openai_compatible",          # or "native"
       api_key_env="ACME_API_KEY",
       base_url="https://api.acme.ai/v1", # for openai_compatible
       base_url_env="ACME_API_BASE",      # optional override
       default_model="acme-large",
       example_models=("acme-large", "acme-mini"),
   )
   ```

   - For **native** providers, set `litellm_prefix` (the model is built as
     `"{prefix}/{model}"`) instead of `base_url`.
   - For providers where the base URL is mandatory (like Azure), set
     `requires_api_base=True`.

2. **Add the matching env var(s)** to the `Secrets` model in
   [`config.py`](../src/opendate/config.py) and to
   [`.env.example`](../.env.example) so they're recognized and documented.

3. **Add a test** in `tests/test_llm.py` (see `test_add_provider_is_one_entry`).

That's it — `opendate providers`, config validation, the env-var mapping, and the
README/docs provider tables all pick it up from the registry automatically.

---

## Next steps

- **Select & tune the model in config** → [Configuration → `llm`](configuration.md#llm)
- **How generation uses the router each cycle** → [Orchestrator](orchestrator.md)
- **Contribute a provider** → [Development](development.md)
