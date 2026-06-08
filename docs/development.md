# Development

This guide is for working **on** OpenDate — setting up a dev environment, running
the tests + lint, understanding the layout, and the offline-first testing
philosophy. It complements [`CONTRIBUTING.md`](../CONTRIBUTING.md) (the canonical
contributor guide) and the per-subsystem "add a …" tutorials in
[Providers](providers.md#add-a-new-provider), [Skills](skills.md#author-a-new-skill),
and [Connectors](connectors.md#add-a-new-connector).

- [Dev environment](#dev-environment)
- [Tests + lint](#tests--lint)
- [Makefile shortcuts](#makefile-shortcuts)
- [Continuous integration](#continuous-integration)
- [Project layout](#project-layout)
- [Testing philosophy](#testing-philosophy)
- [How to add tests](#how-to-add-tests)
- [Conventions](#conventions)
- [Releases & CHANGELOG](#releases--changelog)
- [Optional: a docs site (mkdocs)](#optional-a-docs-site-mkdocs)

---

## Dev environment

OpenDate targets **Python 3.11+** and is developed with an editable install:

```bash
git clone https://github.com/sumitaich1998/OpenDate.git
cd OpenDate
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

The `dev` extra adds `pytest`, `pytest-asyncio`, and `ruff` (see
[`pyproject.toml`](../pyproject.toml)). Everything runs **fully offline** — the
connector defaults to a mock and the LLM to a deterministic stub — so you never
need real credentials to develop or test.

---

## Tests + lint

The whole suite is offline and fast (well under a second). Before opening a PR,
make sure both pass — these are the exact commands CI runs:

```bash
ruff check .          # lint
pytest -q             # tests (all offline)
```

`pytest` is configured in `pyproject.toml`: `asyncio_mode = "auto"` (so
`async def test_...` functions run without explicit markers, via
`pytest-asyncio`), `testpaths = ["tests"]`, `addopts = "-q"`, and
DeprecationWarnings filtered. Ruff uses `line-length = 100`, `target-version =
"py311"`, and excludes `.venv`/`build`/`dist`.

Auto-format with:

```bash
ruff format .
```

---

## Makefile shortcuts

The [`Makefile`](../Makefile) wraps the common tasks:

| Target | Runs |
| --- | --- |
| `make install` | `pip install -e ".[dev]"` |
| `make test` | `python -m pytest -q` |
| `make lint` | `python -m ruff check .` |
| `make format` | `python -m ruff format .` |
| `make demo` | `python -m opendate --mock run --cycles 1 --no-interactive` |
| `make clean` | Remove caches and build artifacts |

---

## Continuous integration

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs on every push to
`main`/`master` and on every pull request, across a matrix of **Python 3.11 and
3.12**. Each job: checkout → set up Python → `pip install -e ".[dev]"` →
`ruff check .` → `pytest -q`. So the local commands above are exactly what gates a
PR.

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
  utils/         logging.py                            # rich logs + secret redaction
tests/           # fully offline pytest suite
examples/        # sample inputs + walkthrough
config.example.yaml · .env.example · requirements.txt · pyproject.toml
```

See [Architecture](architecture.md) for the full module map (responsibilities +
key classes/functions).

---

## Testing philosophy

OpenDate is built to be **exercisable offline**, and the test suite leans on two
substitutions (both wired up in [`tests/conftest.py`](../tests/conftest.py)):

- **Stub LLM** — `EchoBackend` is a deterministic, network-free backend. A router
  built with `stub=True` reports `is_stub == True`, which makes persona, style,
  skill tie-break, safety review, and quality code take their heuristic paths.
  The `stub_router` fixture (and `make_stub_router(responder=...)` helper) provide
  one.
- **Mock connector** — `MockConnector` is an in-memory `MatchSource` with seed
  data covering every interesting situation (fresh match, banter, stalled,
  proposing, fading). The `mock_connector` fixture provides one.

Other shared fixtures: `skills_engine` (a loaded `SkillsEngine`), `persona` (an
analyzed `PersonaProfile` built with `router=None`), and `app_config` (a
`source="mock"` `AppConfig`). New behavior should be reachable through these — no
test should require a real network or credentials.

The Tinder connector is tested without a network too, by injecting an
`httpx.MockTransport` (see `tests/test_connectors_tinder.py`) so real auth
headers are set but no request leaves the process.

---

## How to add tests

The `tests/` directory mirrors the modules:

```text
tests/
  conftest.py                  # shared offline fixtures
  test_cli.py                  # CLI commands (via Typer's CliRunner)
  test_config.py               # config + secrets validation
  test_connectors_mock.py      # mock connector behavior
  test_connectors_tinder.py    # tinder connector via MockTransport
  test_llm.py                  # router, providers, fallback, stub
  test_orchestrator.py         # the loop end-to-end (offline)
  test_persona.py              # ingest + analyze + style
  test_quality.py              # the message critic
  test_safety.py               # the safety/pacing guard
  test_skills.py               # loading + selection
  test_state.py                # state store + stage machine
```

To add a test:

1. Put it in the matching `test_*.py` (or add a new one).
2. Reuse the offline fixtures; for async code just write `async def test_...`
   (asyncio auto-mode handles it).
3. Keep it deterministic and offline — use the stub router and mock connector.
4. Run `pytest -q` and `ruff check .`.

Examples worth copying: `tests/test_llm.py::test_add_provider_is_one_entry` (the
pattern for a new provider) and the selection tests in `tests/test_skills.py`
(the pattern for a new skill).

---

## Conventions

- **No secrets, ever.** Nothing should print or log a token/key. The logging layer
  has a [redaction filter](safety.md#logging--redaction); keep it that way.
- **Stay offline-testable.** New behavior should be exercisable with the mock
  connector + stub LLM. Add or extend a test.
- **Heuristics stay authoritative for safety & quality.** An LLM may *refine* a
  decision but must never *un-block* something the heuristics blocked.
- **Graceful degradation.** Anything that calls an LLM should degrade to
  deterministic behaviour when `router.is_stub` or no router is available.

---

## Releases & CHANGELOG

[`CHANGELOG.md`](../CHANGELOG.md) follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The current
version is **0.1.0** (in `pyproject.toml`). When you change behavior, flags, or
config:

1. Add an entry under `## [Unreleased]` in `CHANGELOG.md` (Added / Changed /
   Fixed / …).
2. Update the relevant docs (these pages) and the README if a flag/field changed
   — that's on the [PR checklist](../CONTRIBUTING.md#pull-request-checklist).
3. For a release, bump the version in `pyproject.toml`, move `Unreleased` items
   under the new version + date, and tag.

---

## Optional: a docs site (mkdocs)

These docs are plain Markdown and read well on GitHub as-is. If you want a
hosted, searchable site, [mkdocs-material](https://squidfunk.github.io/mkdocs-material/)
is a clean, **optional** add-on. A minimal `mkdocs.yml` could wire the nav to the
pages in `docs/` (index, getting-started, configuration, architecture, cli,
providers, skills, persona, connectors, safety, orchestrator, faq,
troubleshooting, development, glossary). It's intentionally **not** part of the
repo's required tooling — skip it unless you specifically want a docs website, so
there's nothing extra to keep in sync.

---

## Next steps

- **Contributor guide** → [`CONTRIBUTING.md`](../CONTRIBUTING.md)
- **Add a provider / skill / connector** → [Providers](providers.md#add-a-new-provider) · [Skills](skills.md#author-a-new-skill) · [Connectors](connectors.md#add-a-new-connector)
- **Understand the internals** → [Architecture](architecture.md) · [Orchestrator](orchestrator.md)
