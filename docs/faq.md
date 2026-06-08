# FAQ

Common questions about OpenDate. For concrete errors and fixes, see
[Troubleshooting](troubleshooting.md).

---

### Does this need an API key to try?

No. The whole pipeline runs offline with the global `--mock` flag (mock connector
+ deterministic stub LLM), and the entire test suite is offline too:

```bash
opendate --mock run --cycles 1 --no-interactive
pytest -q
```

See [Getting started → keyless quickstart](getting-started.md#keyless-quickstart---mock).

---

### Will it message people without my say-so?

Only if you set `auto_send: true` (or pass `--auto-send`). By default OpenDate is
**human-in-the-loop**: it proposes each action and asks before sending. And even
with auto-send on, the [safety guard](safety.md) can still block a send. See
[Safety → human-in-the-loop vs auto-send](safety.md#human-in-the-loop-vs-auto-send).

---

### Which LLM should I use?

Any of the [19 provider routes](providers.md). `gpt-4o-mini`,
`claude-3-5-sonnet-latest`, or `deepseek-chat` are all solid starting points. Set
`llm.fallbacks` for resilience — the [router](providers.md#fallbacks-retries-timeouts--usage)
will try them in order if the primary fails.

---

### How do I switch providers or models?

Set `llm.provider` / `llm.model` in `config.yaml`, or override per run with
`--provider` / `--model`. List everything (and see which are configured) with
`opendate providers`. Set the matching API key env var in `.env`. See
[Configuration → llm](configuration.md#llm) and [Providers](providers.md).

---

### Are Chinese providers supported?

Yes — 9 of the 19 routes are Chinese (DeepSeek, Qwen, Zhipu, Moonshot, Baidu,
Yi, MiniMax, Hunyuan, Doubao). DeepSeek is native; the rest are
OpenAI-compatible with sane default base URLs you can override via `*_API_BASE`.
See the [full provider table](providers.md#the-full-provider-table).

---

### How does it learn my voice?

You point `persona.social_posts` / `persona.chat_history` at your writing and run
`opendate persona build`. It measures tone, vocabulary, slang, emoji/punctuation
rate, length/cadence, humor, and go-to openers, blends the sources (40% posts /
35% chats / 25% stated preferences by default), and re-voices every message via
style transfer. Full detail in [Persona](persona.md).

---

### Is automating Tinder allowed?

It may violate Tinder's Terms of Service and risks your account (Tinder has no
official API; the endpoints are unofficial). OpenDate is for **personal /
educational use**. Read [Safety → Responsible use](safety.md#responsible-use-deep-dive)
and [Connectors](connectors.md) before using the real connector.

---

### Where do I get a Tinder token?

Capture the `X-Auth-Token` header from your own authenticated Tinder web session
(browser dev tools → Network tab → a request to `api.gotinder.com` → request
headers). OpenDate has no login/refresh flow yet — you provide a valid token. See
[Connectors → Getting an X-Auth-Token](connectors.md#getting-an-x-auth-token).

---

### Where is my data stored?

Persona profiles and conversation state live under git-ignored paths
(`persona.json`, `data/conversations.json`, `data/decisions.jsonl`). Secrets stay
in `.env` and are never logged (an active redaction filter masks them). See
[Safety → logging & redaction](safety.md#logging--redaction) and
[Persona → Privacy](persona.md#privacy-of-artifacts).

---

### What's the difference between `--mock`, `--no-interactive`, and `auto_send`?

- `--mock` (global): use the offline connector + stub LLM (no credentials, never
  touches a real network or account).
- `--no-interactive` (on `run`): propose actions but **never send** — a true dry
  run, regardless of `auto_send`.
- `auto_send` (config / `--auto-send`): when on, approved actions are sent without
  asking (the safety gate still applies).

These are independent; `--mock --no-interactive` is the safest combination for
experimentation.

---

### How many cycles does `run` do, and how do I run it continuously?

`run` defaults to `--cycles 1`. Use `--cycles N` for N iterations or `--cycles 0`
to run forever (sleeping `poll_interval`, or `--interval`, between cycles). See
[CLI → run](cli.md#run).

---

### Why did it skip / back off on a match?

Common reasons: it's waiting on their reply (won't double-text), a cooldown or
daily cap is active, the draft would repeat an earlier message, or the safety
guard detected disinterest/discomfort/a hard stop. The cycle summary table and
`data/decisions.jsonl` record the exact reason. See
[Orchestrator](orchestrator.md) and [Safety](safety.md).

---

### Can I add a new skill / provider / connector?

Yes — all three are designed to be easy. See
[Skills → author a new skill](skills.md#author-a-new-skill),
[Providers → add a new provider](providers.md#add-a-new-provider), and
[Connectors → add a new connector](connectors.md#add-a-new-connector), plus
[Development](development.md) and [`CONTRIBUTING.md`](../CONTRIBUTING.md).

---

### What Python version do I need?

Python **3.11+** (CI runs 3.11 and 3.12). See
[Getting started → prerequisites](getting-started.md#prerequisites).

---

## Next steps

- **Hitting an error?** → [Troubleshooting](troubleshooting.md)
- **Set it up properly** → [Getting started](getting-started.md) · [Configuration](configuration.md)
