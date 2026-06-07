"""Tinder connector (UNOFFICIAL API — read the warnings).

.. warning::

   Tinder has **no public/official API**. The endpoints used here are the
   private endpoints the mobile/web clients use, reverse-engineered by the
   community. They can change or break without notice, and **automating Tinder
   may violate its Terms of Service** and get your account rate-limited or
   banned. OpenDate ships this connector for personal/educational use only; you
   are responsible for how you use it. For demos and tests, prefer ``--mock``.

Endpoints used (all relative to ``https://api.gotinder.com``), authenticated
with the ``X-Auth-Token`` header:

==========================  ============================================
Action                      Endpoint
==========================  ============================================
Recommendations (dates)     ``GET /v2/recs/core``
Like / Pass                 ``GET /like/{id}`` · ``GET /pass/{id}``
Matches                     ``GET /v2/matches?count=60``
Messages                    ``GET /v2/matches/{match_id}/messages?count=100``
Send message                ``POST /user/matches/{match_id}``  ``{"message": "..."}``
Self profile (for sender)   ``GET /profile``
==========================  ============================================
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from ..utils.logging import get_logger
from .base import Candidate, Match, Message

__all__ = ["TinderConnector", "TINDER_BASE_URL"]

log = get_logger("connectors.tinder")

TINDER_BASE_URL = "https://api.gotinder.com"
_MILES_TO_KM = 1.60934
# Transient HTTP statuses worth retrying (rate-limit + server errors).
_RETRY_STATUS = {429, 500, 502, 503, 504}
_MATCH_PAGE = 60
_MESSAGE_PAGE = 100


def _obj(value: Any) -> dict[str, Any]:
    """Coerce a possibly-``null`` JSON value to a dict (field-drift safe)."""
    return value if isinstance(value, dict) else {}


def _arr(value: Any) -> list[Any]:
    """Coerce a possibly-``null`` JSON value to a list (field-drift safe)."""
    return value if isinstance(value, list) else []


def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_from_birthdate(value: Any) -> int | None:
    birth = _parse_dt(value)
    if birth is None:
        return None
    now = datetime.now(timezone.utc)
    years = now.year - birth.year
    if (now.month, now.day) < (birth.month, birth.day):
        years -= 1
    return years if 0 < years < 130 else None


class TinderConnector:
    """A defensive async client for Tinder's unofficial endpoints."""

    def __init__(
        self,
        auth_token: str,
        *,
        base_url: str = TINDER_BASE_URL,
        client: httpx.AsyncClient | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_backoff: float = 0.5,
    ) -> None:
        if not auth_token:
            raise ValueError("TinderConnector requires an auth token")
        self._auth_token = auth_token
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max(1, max_retries)
        self._retry_backoff = max(0.0, retry_backoff)
        self._self_id: str | None = None
        self._owns_client = client is None
        # ``transport`` lets tests inject an httpx.MockTransport while the
        # connector still sets its own auth headers (no real network).
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            transport=transport,
            headers={
                "X-Auth-Token": auth_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
                # Mimic an app-ish client; harmless if ignored.
                "platform": "android",
                "User-Agent": "Tinder/14.0.0 (OpenDate)",
            },
        )

    # ------------------------------------------------------------------ #
    # Low-level helpers
    # ------------------------------------------------------------------ #
    async def _get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return await self._request("GET", path, **kwargs)

    async def _post(self, path: str, json: Any) -> dict[str, Any]:
        return await self._request("POST", path, json=json)

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Issue a request with retry + exponential backoff on transient errors.

        Retries network/transport errors and ``429/5xx`` responses; surfaces a
        clear :class:`RuntimeError` (never a raw httpx error) to callers.
        """
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                response = await self._client.request(method, path, **kwargs)
            except httpx.TransportError as exc:  # incl. timeouts/connect errors
                last_error = exc
                log.warning(
                    "Tinder %s %s transport error (attempt %d/%d): %s",
                    method, path, attempt, self._max_retries, exc,
                )
            else:
                if (
                    response.status_code in _RETRY_STATUS
                    and attempt < self._max_retries
                ):
                    last_error = httpx.HTTPStatusError(
                        f"HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                    log.warning(
                        "Tinder %s %s -> %d, retrying (%d/%d)",
                        method, path, response.status_code, attempt, self._max_retries,
                    )
                else:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        raise RuntimeError(
                            f"Tinder API {method} {path} failed "
                            f"({response.status_code})."
                        ) from exc
                    return self._json(response)
            if attempt < self._max_retries and self._retry_backoff > 0:
                await asyncio.sleep(self._retry_backoff * (2 ** (attempt - 1)))
        raise RuntimeError(
            f"Tinder API {method} {path} failed after {self._max_retries} attempts: "
            f"{last_error}"
        )

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {"data": data}

    async def _self_user_id(self) -> str | None:
        """Best-effort fetch of our own user id, to label message senders."""
        if self._self_id is not None:
            return self._self_id or None
        try:
            data = await self._get("/profile")
            self._self_id = (
                data.get("data", {}).get("_id")
                or data.get("_id")
                or ""
            )
        except Exception as exc:  # noqa: BLE001 - non-fatal; sender stays best-effort
            log.debug("Could not fetch self profile id: %s", exc)
            self._self_id = ""
        return self._self_id or None

    # ------------------------------------------------------------------ #
    # Parsing
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_candidate(result: dict[str, Any]) -> Candidate:
        # Tinder's unofficial payloads drift and frequently send ``null`` where
        # an object/array is expected. ``_obj`` / ``_arr`` coerce those to empty
        # containers so a single missing field never aborts the whole parse.
        user = _obj(result.get("user")) or result
        distance_mi = result.get("distance_mi", user.get("distance_mi"))
        distance_km = (
            round(distance_mi * _MILES_TO_KM, 1)
            if isinstance(distance_mi, (int, float)) and not isinstance(distance_mi, bool)
            else None
        )
        photos = [
            p.get("url")
            for p in _arr(user.get("photos"))
            if isinstance(p, dict) and p.get("url")
        ]
        interests = [
            i.get("name")
            for i in _arr(_obj(user.get("user_interests")).get("selected_interests"))
            if isinstance(i, dict) and i.get("name")
        ]
        prompts: dict[str, str] = {}
        for desc in _arr(user.get("selected_descriptors")):
            if not isinstance(desc, dict):
                continue
            name = desc.get("name") or _obj(desc.get("prompt")).get("name")
            choices = _arr(desc.get("choice_selections"))
            answer = ", ".join(
                c.get("name", "") for c in choices if isinstance(c, dict)
            )
            if name and answer:
                prompts[str(name)] = answer
        jobs = [
            _obj(j.get("company")).get("name")
            or _obj(j.get("title")).get("name")
            or ""
            for j in _arr(user.get("jobs"))
            if isinstance(j, dict)
        ]
        schools = [
            s.get("name", "")
            for s in _arr(user.get("schools"))
            if isinstance(s, dict) and s.get("name")
        ]
        return Candidate(
            id=str(user.get("_id") or result.get("_id") or ""),
            name=user.get("name", ""),
            age=_age_from_birthdate(user.get("birth_date")),
            bio=user.get("bio", "") or "",
            distance_km=distance_km,
            photos=[p for p in photos if p],
            prompts=prompts,
            interests=[i for i in interests if i],
            jobs=[j for j in jobs if j],
            schools=[s for s in schools if s],
            raw=result,
        )

    def _parse_match(self, raw: dict[str, Any]) -> Match:
        person = _obj(raw.get("person"))
        photos = [
            p.get("url")
            for p in _arr(person.get("photos"))
            if isinstance(p, dict) and p.get("url")
        ]
        match = Match(
            id=str(raw.get("_id") or raw.get("id") or ""),
            person_id=str(person.get("_id", "")),
            name=person.get("name", ""),
            bio=person.get("bio", "") or "",
            photos=[p for p in photos if p],
            created_at=_parse_dt(raw.get("created_date")),
            last_activity_at=_parse_dt(raw.get("last_activity_date")),
            raw=raw,
        )
        embedded = raw.get("messages")
        if isinstance(embedded, list) and embedded:
            match.messages = [
                self._parse_message(m, match.id, match.person_id) for m in embedded
            ]
        return match

    def _parse_message(
        self, raw: dict[str, Any], match_id: str, person_id: str
    ) -> Message:
        sender_id = str(raw.get("from", ""))
        if self._self_id and sender_id == self._self_id:
            sender = "me"
        elif person_id and sender_id == person_id:
            sender = "them"
        elif self._self_id:
            sender = "them"
        else:
            # Without a known self id, assume inbound (safer: we won't think we
            # already replied). Sender detection improves once /profile loads.
            sender = "them" if sender_id == person_id or not person_id else "me"
        return Message(
            id=str(raw.get("_id") or raw.get("id") or ""),
            match_id=match_id or str(raw.get("match_id", "")),
            sender=sender,  # type: ignore[arg-type]
            text=raw.get("message", "") or "",
            sent_at=_parse_dt(raw.get("sent_date") or raw.get("created_date")),
            raw=raw,
        )

    # ------------------------------------------------------------------ #
    # MatchSource interface
    # ------------------------------------------------------------------ #
    async def get_recommendations(self, limit: int = 10) -> list[Candidate]:
        data = await self._get("/v2/recs/core")
        results = data.get("data", {}).get("results", []) or []
        candidates = [self._parse_candidate(r) for r in results if isinstance(r, dict)]
        return candidates[:limit] if limit else candidates

    async def like(self, candidate_id: str) -> dict[str, Any]:
        return await self._get(f"/like/{candidate_id}")

    async def pass_(self, candidate_id: str) -> dict[str, Any]:
        return await self._get(f"/pass/{candidate_id}")

    async def get_matches(self, count: int = 60) -> list[Match]:
        await self._self_user_id()
        matches: list[Match] = []
        page_token: str | None = None
        # Follow ``next_page_token`` until we have enough (or run out of pages).
        while len(matches) < count:
            params: dict[str, Any] = {"count": min(count, _MATCH_PAGE)}
            if page_token:
                params["page_token"] = page_token
            data = await self._get("/v2/matches", params=params)
            block = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
            raw_matches = block.get("matches", []) or []
            matches.extend(
                self._parse_match(m) for m in raw_matches if isinstance(m, dict)
            )
            page_token = block.get("next_page_token")
            if not page_token or not raw_matches:
                break
        return matches[:count]

    async def get_messages(self, match_id: str, count: int = 100) -> list[Message]:
        await self._self_user_id()
        person_id = ""
        collected: list[Message] = []
        page_token: str | None = None
        while len(collected) < count:
            params: dict[str, Any] = {"count": min(count, _MESSAGE_PAGE)}
            if page_token:
                params["page_token"] = page_token
            data = await self._get(
                f"/v2/matches/{match_id}/messages", params=params
            )
            block = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
            raw_messages = block.get("messages", []) or []
            collected.extend(
                self._parse_message(m, match_id, person_id)
                for m in raw_messages
                if isinstance(m, dict)
            )
            page_token = block.get("next_page_token")
            if not page_token or not raw_messages:
                break
        # Tinder returns newest-first; expose oldest-first for natural reading.
        collected.sort(
            key=lambda m: m.sent_at or datetime.min.replace(tzinfo=timezone.utc)
        )
        return collected[:count]

    async def send_message(self, match_id: str, text: str) -> Message:
        data = await self._post(f"/user/matches/{match_id}", json={"message": text})
        payload = data.get("data", data)
        if isinstance(payload, dict) and (payload.get("_id") or payload.get("message")):
            return self._parse_message(payload, match_id, "")
        # Fall back to a synthesized record if the response shape is unexpected.
        return Message(
            id=str(payload.get("_id", "")) if isinstance(payload, dict) else "",
            match_id=match_id,
            sender="me",
            text=text,
            sent_at=datetime.now(timezone.utc),
            raw=data,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
