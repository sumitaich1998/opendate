# OpenDate examples

Wholesome sample inputs and a fully offline walkthrough — **no API keys, no
Tinder token, nothing is ever sent.** Everything here runs against the mock
connector and the deterministic stub LLM.

## Files

| File | What it is |
| --- | --- |
| `sample_posts.txt` | Example social posts (one per line) used to learn a voice. |
| `sample_chats.json` | Example chat export (`{"sender", "text"}` objects). Lines from `Alex` are treated as "you". |
| `config.demo.yaml` | A ready-to-run config wired to the sample files, with `source: mock`. |

## 1. Install (editable, with dev extras)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## 2. Build a persona from the samples

Run from the repository root so the relative paths resolve:

```bash
python -m opendate --mock --config examples/config.demo.yaml persona build
python -m opendate --mock --config examples/config.demo.yaml persona show
```

This ingests `sample_posts.txt` + `sample_chats.json`, learns a voice card
(tone, vocabulary, emoji/punctuation rate, length & cadence, humor, go-to
openers), and caches it to `data/persona.json` (git-ignored). Because this is a
`--mock` run, the stub LLM is used and the result is fully deterministic.

## 3. Run one loop cycle offline (proposes, sends nothing)

```bash
python -m opendate --mock --config examples/config.demo.yaml run --cycles 1 --no-interactive
```

You'll see OpenDate sync mock matches, screen candidates, pick a skill per
conversation stage, generate and re-voice a message, run the safety guard, and
**propose** each action in a dry-run plan — without sending anything.

## 4. Preview screening only

```bash
python -m opendate --mock --config examples/config.demo.yaml screen
```

## Bring your own voice

Swap in your real data by editing `config.demo.yaml` (or your own `config.yaml`):
point `persona.social_posts` / `persona.chat_history` at your exports and set
`persona.my_names` to the names/handles that identify **you** in those chats.
Keep real exports out of git — `data/` and `persona.json` are already ignored.
