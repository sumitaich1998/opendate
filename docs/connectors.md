# Connectors

A **connector** is OpenDate's data source: it fetches potential dates and
matches, likes/passes, and reads/sends messages. Every connector implements the
same `MatchSource` interface, so the [orchestrator](orchestrator.md) never knows
(or cares) whether it's talking to real Tinder or the offline mock. The code is
in [`connectors/base.py`](../src/opendate/connectors/base.py) (interface +
models), [`connectors/tinder.py`](../src/opendate/connectors/tinder.py), and
[`connectors/mock.py`](../src/opendate/connectors/mock.py).

- [The `MatchSource` interface](#the-matchsource-interface)
- [Data models](#data-models)
- [Choosing a connector (`build_connector`)](#choosing-a-connector)
- [The Tinder connector](#the-tinder-connector)
- [Getting an X-Auth-Token](#getting-an-x-auth-token)
- [The mock connector](#the-mock-connector)
- [Add a new connector (Hinge/Bumble)](#add-a-new-connector)

---

## The `MatchSource` interface

`MatchSource` is a `runtime_checkable` `Protocol` — every method is **async**:

| Method | Returns | Purpose |
| --- | --- | --- |
| `get_recommendations(limit=10)` | `list[Candidate]` | Fetch potential dates to screen. |
| `like(candidate_id)` | `dict` | Like a candidate (response may include a match). |
| `pass_(candidate_id)` | `dict` | Pass on a candidate. |
| `get_matches(count=60)` | `list[Match]` | List current matches. |
| `get_messages(match_id, count=100)` | `list[Message]` | Read a match's messages (oldest → newest). |
| `send_message(match_id, text)` | `Message` | Send a message to a match. |
| `close()` | `None` | Release resources (e.g. the HTTP client). |

Because it's a Protocol, a connector doesn't subclass anything — it just needs
these methods. That's what makes new connectors and testing straightforward.

---

## Data models

Three [pydantic](https://docs.pydantic.dev/) models (in `base.py`) carry data
through the loop. Every connector produces these, so downstream code is uniform.
Each keeps the provider's original payload in `raw` (excluded from `repr`).

### `Candidate` — a potential date (pre-decision)

| Field | Type | Default |
| --- | --- | --- |
| `id` | str | required |
| `name` | str | `""` |
| `age` | int \| None | `None` |
| `bio` | str | `""` |
| `distance_km` | float \| None | `None` |
| `photos` | list[str] | `[]` |
| `prompts` | dict[str, str] | `{}` |
| `interests` | list[str] | `[]` |
| `jobs` | list[str] | `[]` |
| `schools` | list[str] | `[]` |
| `raw` | dict | `{}` |

`profile_text()` renders a compact, prompt-friendly summary (name/age, distance,
work, school, bio, interests, prompts).

### `Match` — a mutual match you can message

| Field | Type | Default |
| --- | --- | --- |
| `id` | str | required |
| `person_id` | str | `""` |
| `name` | str | `""` |
| `photos` | list[str] | `[]` |
| `bio` | str | `""` |
| `created_at` | datetime \| None | `None` |
| `last_activity_at` | datetime \| None | `None` |
| `messages` | list[Message] | `[]` |
| `raw` | dict | `{}` |

Helpers: `has_messages`, `last_message`, and `awaiting_their_reply` (true if the
most recent message was from us).

### `Message` — one chat message

| Field | Type | Default |
| --- | --- | --- |
| `id` | str | required |
| `match_id` | str | required |
| `sender` | `"me"` \| `"them"` | required |
| `text` | str | required |
| `sent_at` | datetime \| None | `None` |
| `raw` | dict | `{}` |

Helper: `from_me` (true when `sender == "me"`).

---

## Choosing a connector

`build_connector(config, secrets=None, *, force_mock=False)` decides which
connector to construct:

- If `force_mock` (the CLI `--mock` flag) **or** `config.source == "mock"`, it
  returns a `MockConnector`.
- Otherwise it returns a `TinderConnector` built from
  `secrets.tinder_auth_token`. If no token is present, it raises a clear
  `RuntimeError` telling you to set `TINDER_AUTH_TOKEN` or run with `--mock`.

```python
# Effective logic
if force_mock or config.source == "mock":
    return MockConnector()
token = secrets.tinder_auth_token if secrets else None
if not token:
    raise RuntimeError("No TINDER_AUTH_TOKEN found. ... or run with --mock ...")
return TinderConnector(auth_token=token)
```

See [`source`](configuration.md#top-level-fields) and the `--mock` flag in the
[CLI reference](cli.md#global-options).

---

## The Tinder connector

> [!WARNING]
> **Tinder has no official/public API.** The endpoints below are the private
> endpoints the mobile/web clients use, reverse-engineered by the community. They
> can change or break without notice, and **automating Tinder may violate its
> Terms of Service** and get your account rate-limited or banned. OpenDate ships
> this connector for **personal/educational use only** — you are responsible for
> how you use it. For demos and tests, prefer `--mock`. See
> [Safety → Responsible use](safety.md#responsible-use-deep-dive).

`TinderConnector` is a defensive async `httpx` client. Base URL:
`TINDER_BASE_URL = "https://api.gotinder.com"`.

### Endpoints actually used

All requests carry the `X-Auth-Token` header:

| Action | Method & path |
| --- | --- |
| Recommendations (dates) | `GET /v2/recs/core` |
| Like | `GET /like/{id}` |
| Pass | `GET /pass/{id}` |
| Matches | `GET /v2/matches?count=60` |
| Messages | `GET /v2/matches/{match_id}/messages?count=100` |
| Send message | `POST /user/matches/{match_id}` with body `{"message": "..."}` |
| Self profile (for sender id) | `GET /profile` |

### Headers

The client sets these on every request:

```text
X-Auth-Token: <your token>
Content-Type: application/json
Accept: application/json
platform: android
User-Agent: Tinder/14.0.0 (OpenDate)
```

The `platform` / `User-Agent` headers mimic an app-ish client and are harmless if
ignored.

### Construction

`TinderConnector(auth_token, *, base_url=TINDER_BASE_URL, client=None,
transport=None, timeout=30.0, max_retries=3, retry_backoff=0.5)`. It raises
`ValueError` if `auth_token` is empty. The `transport` parameter lets tests
inject an `httpx.MockTransport` while the connector still sets its own auth
headers (no real network) — see `tests/test_connectors_tinder.py`.

### Retry / backoff

`_request(...)` issues each call with retry + exponential backoff:

- Retries on transport errors (timeouts/connect errors) and on the transient
  HTTP statuses `429, 500, 502, 503, 504` (`_RETRY_STATUS`).
- Backoff between attempts is `retry_backoff * 2^(attempt-1)` (default base
  `0.5s`), up to `max_retries` (default `3`) attempts.
- It **never leaks a raw `httpx` error to callers** — a failed request surfaces a
  clear `RuntimeError` describing the method, path, and status/attempts.

### Pagination

- **Matches** (`get_matches`): first resolves your own user id (via `/profile`,
  best-effort, to label message senders), then follows `next_page_token` from
  `data.next_page_token`, fetching `min(count, 60)` per page until it has enough
  or runs out of pages.
- **Messages** (`get_messages`): similarly follows `next_page_token`, fetching
  `min(count, 100)` per page. Tinder returns newest-first; the connector sorts to
  **oldest-first** for natural reading.

### Defensive parsing

Tinder's unofficial payloads drift and often send `null` where an object/array is
expected. Internal `_obj` / `_arr` helpers coerce those to empty containers so a
single missing field never aborts a parse. Ages are derived from `birth_date`,
distances converted from miles to km (`_MILES_TO_KM = 1.60934`), and message
senders are labeled `me`/`them` using your self id and the match's `person_id`
(falling back gracefully when the self id isn't known yet).

---

## Getting an X-Auth-Token

OpenDate uses the same private endpoints the Tinder clients use, authenticated
with an `X-Auth-Token` header. You supply a valid token from **your own**
authenticated session:

1. Log into the Tinder web app in your browser.
2. Open dev tools → **Network** tab.
3. Trigger any in-app action and inspect a request to `api.gotinder.com`.
4. Copy the **`X-Auth-Token`** request header value.

Put it in `.env` as `TINDER_AUTH_TOKEN=...` (this file is git-ignored — never
commit it). OpenDate does **not** implement a login / token-refresh flow today;
you provide a valid token (a token-refresh / SMS-OTP login flow is on the
[roadmap](../README.md#roadmap)).

> This is unofficial and ToS-sensitive. Read
> [Safety → Responsible use](safety.md#responsible-use-deep-dive) first.

---

## The mock connector

`MockConnector` is a deterministic, in-memory `MatchSource` that lets the whole
pipeline (and the test suite) run with **zero credentials and zero network**. The
seed data is chosen to exercise every interesting situation. It seeds:

**5 candidates** — `Maya`, `Priya`, `Sam` (a `smoking` dealbreaker), `Alex`, and
`Jordan` (age 23, below the demo range) — to exercise like/pass screening.

**5 matches**, each hitting a different conversation stage / skill:

| Match | Situation | Drives |
| --- | --- | --- |
| `match-maya` | fresh, no messages | `opener` |
| `match-priya` | active, playful banter | `flirting` / `banter` |
| `match-lena` | stalled (we messaged last, 4 days ago) | `re-engagement` |
| `match-noah` | strong rapport, warming toward a meetup | `proposing-a-date` |
| `match-rob` | replies gone flat ("busy", "k") | `conversation-recovery` + safety back-off |

In the mock, a `like()` **always becomes a match** so downstream flows run. The
connector also tracks `liked`, `passed`, and `sent` lists for assertions in tests
(`tests/test_connectors_mock.py`). You can construct it with your own
`candidates`/`matches` for custom scenarios.

Run any command against it with the global `--mock` flag (or `source: mock` in
config):

```bash
opendate --mock --config examples/config.demo.yaml run --cycles 1 --no-interactive
```

---

## Add a new connector

To support another app (Hinge, Bumble, …), implement the `MatchSource` Protocol
and teach `build_connector` to construct it. There's nothing to subclass.

1. **Create** `src/opendate/connectors/<app>.py` with a class implementing all
   seven async methods, returning the shared `Candidate` / `Match` / `Message`
   models:

   ```python
   from .base import Candidate, Match, Message

   class HingeConnector:
       def __init__(self, auth_token: str) -> None:
           ...  # set up an httpx.AsyncClient with the app's auth headers

       async def get_recommendations(self, limit: int = 10) -> list[Candidate]: ...
       async def like(self, candidate_id: str) -> dict: ...
       async def pass_(self, candidate_id: str) -> dict: ...
       async def get_matches(self, count: int = 60) -> list[Match]: ...
       async def get_messages(self, match_id: str, count: int = 100) -> list[Message]: ...
       async def send_message(self, match_id: str, text: str) -> Message: ...
       async def close(self) -> None: ...
   ```

   Reuse the `TinderConnector` patterns: a defensive `_request` with retry/backoff
   that raises `RuntimeError` (never a raw client error), `_obj`/`_arr`-style
   coercion for drifty payloads, and oldest-first message ordering.

2. **Allow the new `source`** value: extend the `source` validator in
   `AppConfig` (`config.py`) to accept your key, and add any required secret(s) to
   the `Secrets` model + [`.env.example`](../.env.example).

3. **Wire `build_connector`** (`connectors/base.py`) to construct your connector
   when `config.source == "<app>"`, pulling its token from `secrets`.

4. **Test it offline** like the Tinder connector does: inject an
   `httpx.MockTransport` (or your client's equivalent) so the tests need no
   network. Add a `tests/test_connectors_<app>.py`.

> Keep the same consent-first ethos and ToS caveats — any real-platform
> automation carries the same risks described in [Safety](safety.md).

---

## Next steps

- **How the loop drives a connector each cycle** → [Orchestrator](orchestrator.md)
- **The `source` config field & token secret** → [Configuration](configuration.md)
- **ToS & responsible use** → [Safety](safety.md#responsible-use-deep-dive)
