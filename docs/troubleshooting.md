# Troubleshooting

Concrete errors and how to fix them. For conceptual questions, see the
[FAQ](faq.md). Tip: run with `--log-level DEBUG` for more detail (secrets stay
redacted).

- [A bare `opendate run` just hangs](#a-bare-opendate-run-just-hangs)
- [No credentials for provider](#no-credentials-for-provider)
- [No `TINDER_AUTH_TOKEN` found](#no-tinder_auth_token-found)
- [Tinder API call failed (401/429/5xx)](#tinder-api-call-failed)
- [Unknown provider](#unknown-provider)
- [Config file not found / not a mapping](#config-file-issues)
- [No persona / empty persona](#no-persona--empty-persona)
- [Nothing gets sent](#nothing-gets-sent)
- [Install issues](#install-issues)
- [`command not found: opendate`](#command-not-found-opendate)

---

## A bare `opendate run` just hangs

**Symptom:** `opendate run` (or with a real config) appears to freeze after
printing proposed messages.

**Cause:** `run` is **interactive** by default — it blocks on a yes/no `Confirm`
prompt before each proposed send.

**Fix:** for scripted/offline checks, always pass `--no-interactive` (proposes,
never sends):

```bash
opendate --mock --config examples/config.demo.yaml run --cycles 1 --no-interactive
```

For interactive use, just answer the prompts. In a non-TTY/piped context the
confirm is treated as "no", so nothing is sent.

---

## No credentials for provider

**Symptom:**

```text
RuntimeError: No credentials found for provider 'openai'. Set the required
environment variable (see `opendate providers`) or run with --mock to use the
offline stub LLM.
```

**Cause:** a non-mock run (`run` / `persona build`) calls
`router.ensure_ready(...)`, which checks the **primary** provider's credentials.

**Fix:** set the matching API key in `.env` (see `opendate providers` for which
env var), or run with `--mock`:

```bash
opendate providers              # find the API key env for your provider
echo 'OPENAI_API_KEY=sk-...' >> .env
# or just try it offline:
opendate --mock run --cycles 1 --no-interactive
```

For **Azure** you also need `AZURE_API_BASE`; for **Bedrock**, the AWS
credentials trio. See [Providers → per-provider setup](providers.md#per-provider-setup-notes).

---

## No `TINDER_AUTH_TOKEN` found

**Symptom:**

```text
RuntimeError: No TINDER_AUTH_TOKEN found. Set it in your environment/.env, or run
with --mock to use the offline demo connector.
```

**Cause:** `source: tinder` (the default) but no token is available.

**Fix:** add your token to `.env`, or use the mock:

```bash
echo 'TINDER_AUTH_TOKEN=your-x-auth-token' >> .env
# or run offline:
opendate --mock run --cycles 1 --no-interactive
```

See [Connectors → Getting an X-Auth-Token](connectors.md#getting-an-x-auth-token).

---

## Tinder API call failed

**Symptom:** something like
`RuntimeError: Tinder API GET /v2/matches failed (401).` or a "failed after 3
attempts" message.

**Causes & fixes:**

- **401 Unauthorized** → your token is invalid or expired. Capture a fresh
  `X-Auth-Token` from an authenticated session and update `.env`. OpenDate has no
  token-refresh flow yet.
- **429 / 5xx** → rate-limited or a transient server error. The connector already
  retries these with exponential backoff (`429, 500, 502, 503, 504`, default 3
  attempts); persistent failures usually mean you're being rate-limited — slow
  down (raise `pacing.cooldown_hours`, lower `max_daily_actions`) or pause.
- **Network/timeout** → check connectivity; the connector raises a clear
  `RuntimeError` after exhausting retries rather than a raw `httpx` error.

> Remember: the Tinder API is unofficial and may change/break, and automation is
> ToS-sensitive. See [Safety → Tinder ToS risk](safety.md#tinder-tos-risk).

---

## Unknown provider

**Symptom (config validation):**

```text
ValueError: Unknown provider 'gpt4'. Known: anthropic, azure, baidu, bedrock,
cohere, deepseek, doubao, gemini, groq, hunyuan, minimax, mistral, moonshot,
openai, qwen, together, xai, yi, zhipu
```

**Cause:** `llm.provider` (or a fallback's `provider`, or `--provider`) isn't a
registry **key**. Note keys are the friendly names (e.g. `openai`, not a model
name like `gpt-4o`).

**Fix:** use a valid key from `opendate providers`. The **model** goes in
`llm.model`; the **provider** is the key:

```yaml
llm:
  provider: openai      # a registry key
  model: gpt-4o-mini    # the model name
```

---

## Config file issues

- **`FileNotFoundError: Config file not found: <path>`** — you passed
  `--config <path>` but the file doesn't exist. Check the path, or omit
  `--config` to use auto-discovery (`opendate.config.yaml`, `opendate.yaml`,
  `config.yaml`) / built-in defaults.
- **`ValueError: Config file <path> must contain a YAML mapping`** — the YAML
  parsed to something that isn't a top-level mapping (e.g. a list or scalar).
  Ensure the file is a set of `key: value` sections like
  [`config.example.yaml`](../config.example.yaml).
- **A pydantic validation error** (e.g. `age_range.min must be <= age_range.max`,
  or an out-of-range value) — fix the offending field per
  [Configuration](configuration.md).

With no config file at all, OpenDate uses defaults — which is why the `--mock`
quickstart works with nothing configured.

---

## No persona / empty persona

- **`No persona at <path>. Run \`opendate persona build\`.`** (`persona show`
  exits 1) — build one first:

  ```bash
  opendate persona build
  ```

- **Persona looks generic / empty.** Likely your source files weren't found or
  matched. `ingest_paths` **skips missing files with a warning** and degrades to
  your stated `voice`. Check that:
  - `persona.social_posts` / `persona.chat_history` paths exist (relative to your
    current directory — run from the repo root for the bundled examples);
  - `persona.my_names` includes the name/handle that marks **your** lines in chat
    exports (otherwise only unattributed/`me`-style lines are kept);
  - your JSON shape matches one of the [supported shapes](persona.md#accepted-input-formats).

- **`LLM-refined: False`.** Expected under `--mock` (the stub doesn't refine).
  With a real provider configured, refinement runs and reports `True`; if it
  still says `False`, the LLM call failed and OpenDate kept the heuristic profile
  (check logs).

---

## Nothing gets sent

If a run completes but no messages go out, that's usually **by design**:

- You're in the default human-in-the-loop mode (`auto_send: false`) and didn't
  approve, or you used `--no-interactive` (a dry run).
- A [pacing](safety.md#pacing-cooldowns-daily-cap-no-double-text) rule applied
  (cooldown, daily cap, never-double-text).
- The [safety guard](safety.md#what-it-blocks-and-when) blocked or backed off.
- The draft would repeat an earlier message.

The cycle summary table and `data/decisions.jsonl` show the exact reason per
match. To actually send, set `auto_send: true` (or `--auto-send`) and run
interactively/approve. See [Orchestrator](orchestrator.md).

---

## Install issues

- **`requires-python` / syntax errors** → you're on Python < 3.11. Check
  `python3 --version` and create the venv with a 3.11+ interpreter.
- **`litellm` import errors at call time** → it's imported lazily by the real
  backend; if you only installed `requirements.txt` this is fine for `--mock`
  (the stub never imports it). Ensure your install succeeded:
  `pip install -e ".[dev]"`.
- **Dependency resolution** → upgrade pip (`pip install -U pip`) and reinstall.
  The pinned lower bounds are in [`pyproject.toml`](../pyproject.toml).

---

## `command not found: opendate`

The console script is installed by `pip install -e ".[dev]"`. If it's missing
(e.g. you used `requirements.txt` only, or the venv isn't active):

```bash
source .venv/bin/activate          # activate the venv
python -m opendate --help          # always works without the script
pip install -e ".[dev]"            # (re)installs the `opendate` console script
```

`python -m opendate ...` is exactly equivalent to `opendate ...`.

---

## Next steps

- **Conceptual questions** → [FAQ](faq.md)
- **Set things up correctly** → [Getting started](getting-started.md) · [Configuration](configuration.md)
- **Understand a skip/backoff** → [Orchestrator](orchestrator.md) · [Safety](safety.md)
