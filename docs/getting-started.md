# Getting started

This guide takes you from zero to a running OpenDate loop. You can complete the
whole **quickstart with no credentials at all** — OpenDate ships an offline mock
connector and a deterministic stub LLM so the entire pipeline is demoable and
testable without a Tinder token or an API key.

- [Prerequisites](#prerequisites)
- [Install](#install)
- [Keyless quickstart (`--mock`)](#keyless-quickstart---mock)
- [Verifying the install](#verifying-the-install)
- [First real setup](#first-real-setup)
- [Where to go next](#where-to-go-next)

---

## Prerequisites

- **Python 3.11 or newer.** OpenDate sets `requires-python = ">=3.11"` in
  [`pyproject.toml`](../pyproject.toml) and CI runs on 3.11 and 3.12.
- **`git`** to clone the repository.
- (For real runs only) a **Tinder `X-Auth-Token`** and at least one **LLM
  provider API key**. Neither is needed for the mock quickstart or the tests.

Runtime dependencies (installed automatically) are `litellm`, `httpx`,
`pydantic`, `pydantic-settings`, `pyyaml`, `rich`, and `typer`. See
[`requirements.txt`](../requirements.txt) and `pyproject.toml` for the pinned
lower bounds.

---

## Install

Clone the repo, create a virtual environment, and install OpenDate in editable
mode with the dev extras (pytest + ruff):

```bash
git clone https://github.com/sumitaich1998/OpenDate.git
cd OpenDate
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Two equivalent alternatives to the editable install:

```bash
pip install -r requirements.txt   # runtime deps only (no dev tools)
make install                      # same as: pip install -e ".[dev]"
```

The project installs a console script named `opendate`, so after installing you
can run either of these (they are identical):

```bash
opendate --help
python -m opendate --help
```

> Throughout the docs we write `opendate ...`. If you didn't install the console
> script (e.g. you used `requirements.txt` only), use `python -m opendate ...`.

---

## Keyless quickstart (`--mock`)

The global `--mock` flag swaps in the offline `MockConnector` and the stub LLM,
so the whole loop runs locally and **nothing is ever sent**:

```bash
# Explore
opendate --help
opendate providers          # all 19 LLM provider routes
opendate skills             # the 14 dating skills (add -v to print playbooks)

# Run one loop cycle offline — proposes messages, sends nothing
opendate --mock run --cycles 1 --no-interactive
```

A `--mock` cycle syncs fake matches, screens candidates against the default
preferences, picks a skill per thread based on its stage, generates and
re-voices a message, runs the safety guard, and **proposes** each action in a
dry-run plan. You'll see panels like:

```text
╭──────────────────────── Proposed message (not sent) ─────────────────────────╮
│ To Priya  (stage: flirting · skill: banter · quality: 1.00)                  │
│ They're matching your energy — keep the volley going.                        │
│                                                                              │
│ Bold of you to assume I'll back down from this one. Okay, one point to you — │
│ but I'm coming for it.                                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

> **Always pass `--cycles 1 --no-interactive` in scripts.** A bare `opendate run`
> defaults to `--cycles 1` but stays **interactive**, so it will block waiting for
> a yes/no confirmation before each proposed send. See
> [Troubleshooting](troubleshooting.md#a-bare-opendate-run-just-hangs).

### Try the bundled example

The repo ships sample posts/chats and a ready-to-run demo config under
[`examples/`](../examples/). Run from the repository root so the relative paths
resolve:

```bash
opendate --mock --config examples/config.demo.yaml persona build
opendate --mock --config examples/config.demo.yaml persona show
opendate --mock --config examples/config.demo.yaml screen
opendate --mock --config examples/config.demo.yaml run --cycles 1 --no-interactive
```

See [Persona](persona.md) for a full worked example of what `persona build`
learns from those files.

---

## Verifying the install

Run the offline test suite — it needs no credentials and takes well under a
second:

```bash
pytest -q          # or: make test
```

You should see a line like `124 passed`. Then confirm the CLI surfaces the
expected counts:

```bash
opendate providers   # footer reads "19 provider routes."
opendate skills       # title reads "Loaded skills (14)"
opendate --version    # prints: OpenDate 0.1.0
```

Lint is also part of the standard check (you won't have touched code, but it's
the same gate CI uses):

```bash
ruff check .         # or: make lint
```

---

## First real setup

When you're ready to use OpenDate against real Tinder with a real model:

1. **Scaffold a config + secrets file** in the current directory:

   ```bash
   opendate init .          # writes config.yaml and .env (use --force to overwrite)
   ```

2. **Add your secrets** to `.env` (this file is git-ignored — never commit it):

   ```dotenv
   TINDER_AUTH_TOKEN=your-tinder-x-auth-token
   OPENAI_API_KEY=sk-...    # or any other provider key from `opendate providers`
   ```

   See [Connectors → Getting a Tinder token](connectors.md#getting-an-x-auth-token)
   for how to obtain the token, and [`.env.example`](../.env.example) for every
   supported key.

3. **Edit `config.yaml`** — your preferences, which model to use, your persona
   sources, and whether to `auto_send`. Every field is documented in
   [Configuration](configuration.md).

4. **Build your persona** from your posts/chats:

   ```bash
   opendate persona build
   opendate persona show
   ```

5. **Preview screening, then run the loop:**

   ```bash
   opendate screen          # read-only like/pass preview
   opendate run             # human-in-the-loop by default (asks before sending)
   opendate run --auto-send # let it act without asking (only when you trust it)
   opendate run --cycles 0  # run continuously
   ```

> `auto_send` is **off** by default: OpenDate shows each proposed action and asks
> before sending. Even with `auto_send` on, the [safety guard](safety.md) can
> still block a send. Read [Safety](safety.md) before enabling autonomous
> behaviour.

---

## Where to go next

- **Configure every option** → [Configuration](configuration.md)
- **Pick and set up a model** → [Providers](providers.md)
- **Understand the moving parts** → [Architecture](architecture.md)
- **Stay safe and respectful** → [Safety](safety.md)
- **Hit a snag?** → [Troubleshooting](troubleshooting.md) · [FAQ](faq.md)
