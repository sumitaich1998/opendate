# CLI reference

OpenDate's command-line interface is built with [Typer](https://typer.tiangolo.com/)
and lives in [`src/opendate/cli.py`](../src/opendate/cli.py). Invoke it as the
installed console script `opendate` or as a module — they're identical:

```bash
opendate --help
python -m opendate --help
```

- [Global options](#global-options)
- [`init`](#init)
- [`providers`](#providers)
- [`skills`](#skills)
- [`persona build` / `persona show`](#persona)
- [`screen`](#screen)
- [`run`](#run)

The top-level help:

```text
 Usage: python -m opendate [OPTIONS] COMMAND [ARGS]...

 OpenDate — a vibe-dating AI agent. Use --mock to run offline.

╭─ Commands ─────────────────────────────────────────────────────╮
│ init       Write a starter config.yaml and .env you can fill in.│
│ providers  List every supported LLM provider (Western+Chinese). │
│ skills     List the loaded dating skills.                       │
│ screen     Preview like/pass decisions on current recs.         │
│ run        Run the OpenDate loop.                               │
│ persona    Build and inspect your persona profile.              │
╰─────────────────────────────────────────────────────────────────╯
```

---

## Global options

These come **before** the command (e.g. `opendate --mock run ...`). They're
defined on the Typer app callback and stored for every command to use.

| Option | Type | Default | Meaning |
| --- | --- | --- | --- |
| `--config`, `-c` | path | auto-found | Path to the config YAML. If omitted, OpenDate looks for `opendate.config.yaml`, `opendate.yaml`, `config.yaml` (then falls back to defaults). |
| `--env` | path | `.env` | Path to the `.env` file with secrets (loaded only if it exists). |
| `--mock` | flag | off | Use the offline mock connector + stub LLM — no real credentials needed. |
| `--log-level` | string | `INFO` | Logging level (upper-cased and applied to the `opendate` logger). |
| `--version` | flag | — | Print `OpenDate <version>` and exit. |
| `--help` | flag | — | Show help and exit. |

```bash
opendate --version
# OpenDate 0.1.0
```

---

## `init`

Write a starter `config.yaml` and `.env` you can fill in.

```text
Usage: opendate init [DIRECTORY]

Arguments:
  DIRECTORY   Where to write config.yaml and .env.  [default: .]

Options:
  --force     Overwrite existing files.
```

The content is the single source of truth shared with `config.example.yaml` /
`.env.example` (`EXAMPLE_CONFIG_YAML` and `EXAMPLE_ENV` in `config.py`). Existing
files are skipped unless you pass `--force`.

```bash
opendate init .
# wrote config.yaml
# wrote .env
#
# Next: put your secrets in .env, edit config.yaml, then run
# opendate --mock run to try it offline.
```

---

## `providers`

List every supported LLM provider (Western + Chinese), with a ✓ in the **Cfg**
column when the required credentials are present in your environment/`.env`.

```bash
opendate providers
```

```text
                            Supported LLM providers
┏━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━┓
┃ Key       ┃ Provider   ┃ Region  ┃ Mode       ┃ API key…  ┃ Default…   ┃ Cfg ┃
┡━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━┩
│ openai    │ OpenAI     │ Western │ native     │ OPENAI_A… │ gpt-4o-mi… │  —  │
│ anthropic │ Anthropic  │ Western │ native     │ ANTHROPI… │ claude-3-… │  —  │
│ …         │ …          │ …       │ …          │ …         │ …          │  …  │
└───────────┴────────────┴─────────┴────────────┴───────────┴────────────┴─────┘
19 provider routes. Set the matching API key env var (see .env.example), then
select one in config.yaml under llm.provider.
```

The full table (10 Western + 9 Chinese) and per-provider setup are documented in
[Providers](providers.md).

---

## `skills`

List the loaded dating skills (there are 14).

```text
Usage: opendate skills [OPTIONS]

Options:
  --verbose, -v   Show playbooks (prints each skill's full body).
```

```bash
opendate skills        # the table
opendate skills -v     # table + every skill's playbook in a panel
```

```text
                               Loaded skills (14)
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┓
┃ Skill               ┃ Category  ┃ Fires when           ┃ What it does        ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━┩
│ approaching         │ Opening   │ Match made, first…   │ Breaks the ice…     │
│ banter              │ Building  │ They match your…     │ Witty, fast…        │
│ …                   │ …         │ …                    │ …                   │
└─────────────────────┴───────────┴──────────────────────┴─────────────────────┘
```

The table is generated from each skill's YAML frontmatter. See
[Skills](skills.md) for the full list and the `SKILL.md` format.

---

## `persona`

A sub-app with two commands. Both load your config (and build the router); see
[Persona](persona.md) for input formats and what's learned.

### `persona build`

Ingest your posts/chats and build (and save) a persona profile to
`persona.profile_path`.

```bash
opendate persona build
opendate --mock --config examples/config.demo.yaml persona build
```

```text
╭────────────────────────── Persona profile ──────────────────────────╮
│ Tone: warm, curious, a little sarcastic                              │
│ Humor: sarcastic, warm                                               │
│ Cadence: medium-length texts (~16 words/msg)                         │
│ Emoji: rarely/never                                                  │
│ Characteristic words: from, after, three, one, worth, made, …        │
│ Go-to openers: finally nailed the; hot take a; spent the weekend; …  │
│ Sample lines: …                                                      │
╰──────────────────────────────────────────────────────────────────────╯
Saved persona to data/persona.json (LLM-refined: False)
```

`LLM-refined: False` indicates the deterministic heuristics ran without an LLM
(expected under `--mock`). With a real provider configured, it reads `True`.

### `persona show`

Show the saved persona profile (a voice card + the detailed style brief). Exits
with code 1 if no profile exists yet.

```bash
opendate persona show
```

---

## `screen`

Preview like/pass decisions on current recommendations — **read-only**, it never
swipes. Useful to sanity-check your `preferences` before running the loop.

```text
Usage: opendate screen [OPTIONS]

Options:
  --limit INTEGER   How many candidates to screen.  [default: 10]
```

```bash
opendate --mock --config examples/config.demo.yaml screen
```

```text
                               Screening preview
┏━━━━━━━━━━━┳━━━━━┳━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Candidate ┃ Age ┃ Decision ┃ Score ┃ Why                                     ┃
┡━━━━━━━━━━━╇━━━━━╇━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Maya      │ 29  │ like     │ 0.98  │ age in range; traits: kind; shared:…    │
│ Priya     │ 31  │ like     │ 0.96  │ age in range; shared: live music,…      │
│ Sam       │ 27  │ pass     │ 0.0   │ dealbreaker present: smoking            │
│ Alex      │ 33  │ like     │ 0.84  │ age in range; shared: climbing          │
│ Jordan    │ 23  │ pass     │ 0.36  │ age outside range                       │
└───────────┴─────┴──────────┴───────┴─────────────────────────────────────────┘
```

Scores and reasons come straight from `score_candidate(...)`; see
[Orchestrator → Screening](orchestrator.md) for the scoring rubric.

---

## `run`

Run the OpenDate loop: **Sync → Screen → Decide → Generate → Voice → Guard → Act**.

```text
Usage: opendate run [OPTIONS]

Options:
  --cycles INTEGER                    Loop cycles (0 = run forever).  [default: 1]
  --interval FLOAT                    Seconds between cycles (defaults to config).
  --interactive / --no-interactive    Prompt before sending. --no-interactive
                                      never sends (dry run).  [default: interactive]
  --auto-send / --no-auto-send        Override config auto_send (send without asking).
  --provider TEXT                     Override LLM provider.
  --model TEXT                        Override LLM model.
```

| Option | Default | Behaviour |
| --- | --- | --- |
| `--cycles` | `1` | Number of loop iterations. `0` runs forever (until you stop it). |
| `--interval` | from config | Seconds to sleep between cycles (defaults to `poll_interval`). |
| `--interactive` / `--no-interactive` | interactive | When interactive, you're asked before each send. `--no-interactive` proposes but **never sends** (a true dry run). |
| `--auto-send` / `--no-auto-send` | from config | Overrides `auto_send`. With auto-send, approved messages are sent without asking (the safety guard still applies). |
| `--provider` | from config | Overrides `llm.provider` for this run. |
| `--model` | from config | Overrides `llm.model` for this run. |

> **A bare `opendate run` waits for input.** It defaults to interactive mode and
> blocks on a yes/no confirm before each proposed send. For scripted/offline
> checks always use `--cycles 1 --no-interactive`. See
> [Troubleshooting](troubleshooting.md#a-bare-opendate-run-just-hangs).

### Examples

```bash
# Offline dry run, one cycle, nothing sent
opendate --mock run --cycles 1 --no-interactive

# Real run, human-in-the-loop (asks before each send)
opendate run

# Autonomous, continuous, with a model override
opendate run --auto-send --cycles 0 --provider anthropic --model claude-3-5-sonnet-latest
```

A `run` opens with a banner showing the source, the resolved LLM (and whether
it's the stub), and the send mode:

```text
╭──────────────────────────── OpenDate run ────────────────────────────╮
│ Source: MOCK   LLM: openai:openai/gpt-4o-mini (stub)                  │
│ Mode: human-in-the-loop (no auto-send)   Interactive: False           │
╰────────────────────────────────────────────────────────────────────────╯
```

…and closes each cycle with a plan/summary table. In dry-run mode it's titled
`Cycle plan (dry-run — nothing sent)`. See [Orchestrator](orchestrator.md) for
what each row means.

---

## Next steps

- **Every config field these flags can override** → [Configuration](configuration.md)
- **Pick a provider/model** → [Providers](providers.md)
- **What `run` actually does each cycle** → [Orchestrator](orchestrator.md)
