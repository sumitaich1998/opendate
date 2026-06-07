# Contributing to OpenDate

Thanks for your interest in making OpenDate better! 💘 This project thrives on
tasteful, consent-first contributions. Whether you're fixing a bug, adding a
dating skill, or wiring up a new LLM provider, this guide will get you productive
fast.

By participating, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

---

## Dev setup

OpenDate targets **Python 3.11+** and is developed with an editable install.

```bash
git clone https://github.com/sumitaich1998/OpenDate.git
cd OpenDate
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Everything runs **fully offline** — the connector defaults to a mock and the LLM
to a deterministic stub — so you never need real credentials to develop or test.

---

## Run tests + lint

The whole suite is offline and fast. Before opening a PR, make sure both pass:

```bash
ruff check .          # lint
pytest -q             # tests (all offline)
```

Or use the Makefile shortcuts:

```bash
make install          # editable install with dev extras
make lint             # ruff check .
make test             # pytest -q
make format           # ruff format .
make demo             # python -m opendate --mock run --cycles 1 --no-interactive
```

CI runs `ruff check .` and `pytest` on Python 3.11 and 3.12 for every push and
pull request — the exact commands above.

---

## Project layout

```text
src/opendate/
  cli.py · config.py · __main__.py
  llm/           router.py · providers.py              # multi-provider LLM router
  connectors/    base.py · tinder.py · mock.py         # MatchSource interface + impls
  skills/        engine.py · registry/<skill>/SKILL.md # 14 skills
  persona/       ingest.py · analyze.py · style.py     # personality engine
  orchestrator/  loop.py · safety.py · state.py · quality.py
  utils/         logging.py
tests/           # fully offline pytest suite
examples/        # sample inputs + walkthrough
```

A few conventions:

- **No secrets, ever.** Nothing should print or log a token/key. The logging layer
  has a redaction filter; keep it that way.
- **Stay offline-testable.** New behavior should be exercisable with the mock
  connector + stub LLM. Add or extend a test in `tests/`.
- **Keep the heuristics authoritative for safety.** An LLM may *refine* a safety
  or quality decision, but must never *un-block* something the heuristics blocked.

---

## How to add a new dating skill

This is a great **good first issue**. A skill is just a folder with a `SKILL.md`.

1. Create `src/opendate/skills/registry/<your-skill>/SKILL.md` with YAML
   frontmatter and a playbook body:

   ```markdown
   ---
   name: your-skill
   description: One crisp sentence describing what this skill does.
   when_to_use: The situation in which this skill should fire.
   category: Building            # Discovery | Opening | Building | Closing | Recovery | Meta | Safety
   ---
   # Your skill playbook

   Concrete, do-this / not-that guidance the LLM follows. Aim for a real,
   non-trivial playbook (the loader expects a substantive body).
   ```

2. If the skill should be **selected automatically**, add a branch in
   `SkillsEngine._primary_name` (`src/opendate/skills/engine.py`) keyed off the
   `SituationContext`. If it's an **always-active modifier**, add its name to
   `ALWAYS_ACTIVE`.

3. (Optional) Add a deterministic stub draft for the offline demo in
   `_STUB_DRAFTS` (`src/opendate/llm/router.py`) so `--mock` produces a sensible
   message for the new skill.

4. Add a test in `tests/test_skills.py` asserting your skill loads and is selected
   for the right `SituationContext`. Run `pytest -q`.

The skills table in the [README](README.md#skills-library) and the `opendate
skills` command are generated from the frontmatter — no extra wiring needed.

---

## How to add a new LLM provider

Also a friendly **good first issue** — it's intentionally one entry.

1. Append a `ProviderSpec` to `PROVIDER_REGISTRY` in
   `src/opendate/llm/providers.py`:

   ```python
   ProviderSpec(
       key="acme",
       label="Acme AI",
       region="Western",                 # or "Chinese"
       mode="openai_compatible",         # or "native" (litellm has first-class support)
       api_key_env="ACME_API_KEY",
       base_url="https://api.acme.ai/v1",  # for openai_compatible
       default_model="acme-large",
       example_models=("acme-large", "acme-mini"),
   )
   ```

   - **native**: litellm supports it directly — set `litellm_prefix` and the
     model is built as `"{prefix}/{model}"`.
   - **openai_compatible**: the provider exposes an OpenAI-compatible endpoint —
     set `base_url` (and optionally `base_url_env`); requests route through
     litellm's OpenAI handler.

2. Add the matching env var(s) to `Secrets` in `src/opendate/config.py` and to
   [`.env.example`](.env.example).

3. Add a test in `tests/test_llm.py` (see `test_add_provider_is_one_entry`).

That's it — `opendate providers` and the README provider tables pick it up
automatically.

---

## Pull request checklist

- [ ] `ruff check .` passes.
- [ ] `pytest -q` passes (and you added/updated a test).
- [ ] No secrets, tokens, or personal data committed.
- [ ] Docs/README updated if behavior or flags changed.
- [ ] The change is tasteful and consistent with OpenDate's consent-first ethos.

Open your PR against `main` with a clear description of the *why*. Thank you for
contributing! 🙌
