"""TinderConnector tests using httpx.MockTransport (no real network)."""

from __future__ import annotations

import json

import httpx
import pytest

from opendate.connectors.tinder import TinderConnector


def _make_connector(captured: list[httpx.Request]) -> TinderConnector:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = request.url.path
        if path == "/profile":
            return httpx.Response(200, json={"data": {"_id": "me-123"}})
        if path == "/v2/recs/core":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "results": [
                            {
                                "distance_mi": 5,
                                "user": {
                                    "_id": "u1",
                                    "name": "Rec User",
                                    "bio": "climber and coffee snob",
                                    "birth_date": "1995-01-01T00:00:00.000Z",
                                    "photos": [{"url": "https://img/1.jpg"}],
                                    "user_interests": {
                                        "selected_interests": [{"name": "climbing"}]
                                    },
                                    "selected_descriptors": [
                                        {
                                            "name": "My vibe",
                                            "choice_selections": [{"name": "chill"}],
                                        }
                                    ],
                                },
                            }
                        ]
                    }
                },
            )
        if path.startswith("/like/"):
            return httpx.Response(200, json={"match": False})
        if path.startswith("/pass/"):
            return httpx.Response(200, json={"status": 200})
        if path == "/v2/matches":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "matches": [
                            {
                                "_id": "m1",
                                "person": {
                                    "_id": "p1",
                                    "name": "Pat",
                                    "bio": "hi there",
                                    "photos": [{"url": "https://img/p.jpg"}],
                                },
                                "created_date": "2026-01-01T00:00:00.000Z",
                                "last_activity_date": "2026-01-02T00:00:00.000Z",
                            }
                        ]
                    }
                },
            )
        if path == "/v2/matches/m1/messages":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "messages": [
                            {
                                "_id": "msg2",
                                "message": "hi back",
                                "from": "me-123",
                                "to": "p1",
                                "sent_date": "2026-01-02T10:00:00.000Z",
                            },
                            {
                                "_id": "msg1",
                                "message": "hey",
                                "from": "p1",
                                "to": "me-123",
                                "sent_date": "2026-01-02T09:00:00.000Z",
                            },
                        ]
                    }
                },
            )
        if path == "/user/matches/m1":
            body = json.loads(request.content.decode())
            return httpx.Response(
                200,
                json={
                    "_id": "new1",
                    "message": body["message"],
                    "from": "me-123",
                    "to": "p1",
                    "sent_date": "2026-01-02T11:00:00.000Z",
                },
            )
        return httpx.Response(404, json={})  # pragma: no cover

    transport = httpx.MockTransport(handler)
    return TinderConnector(auth_token="secret-token", transport=transport)


@pytest.mark.asyncio
async def test_recommendations_parsed():
    captured: list[httpx.Request] = []
    conn = _make_connector(captured)
    try:
        recs = await conn.get_recommendations()
        assert len(recs) == 1
        cand = recs[0]
        assert cand.id == "u1"
        assert cand.name == "Rec User"
        assert cand.age and cand.age >= 30
        assert "climbing" in cand.interests
        assert cand.prompts.get("My vibe") == "chill"
        assert cand.distance_km == pytest.approx(8.0, abs=0.1)
        # Auth header is sent on every request.
        assert captured[-1].headers.get("X-Auth-Token") == "secret-token"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_like_and_pass_paths():
    captured: list[httpx.Request] = []
    conn = _make_connector(captured)
    try:
        await conn.like("u1")
        assert captured[-1].url.path == "/like/u1"
        await conn.pass_("u2")
        assert captured[-1].url.path == "/pass/u2"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_matches_and_message_sender_labeling():
    captured: list[httpx.Request] = []
    conn = _make_connector(captured)
    try:
        matches = await conn.get_matches()
        assert matches[0].name == "Pat"
        messages = await conn.get_messages("m1")
        # Sorted oldest -> newest; sender labeled relative to self id.
        assert [m.text for m in messages] == ["hey", "hi back"]
        assert messages[0].sender == "them"
        assert messages[1].sender == "me"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_send_message_posts_body():
    captured: list[httpx.Request] = []
    conn = _make_connector(captured)
    try:
        await conn.get_matches()  # warms self-id
        sent = await conn.send_message("m1", "hello!")
        assert sent.text == "hello!"
        last = captured[-1]
        assert last.method == "POST"
        assert last.url.path == "/user/matches/m1"
        assert json.loads(last.content.decode()) == {"message": "hello!"}
    finally:
        await conn.close()


# --- robustness: pagination, retry/backoff, clear errors -------------------
@pytest.mark.asyncio
async def test_matches_pagination_follows_token():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/profile":
            return httpx.Response(200, json={"data": {"_id": "me"}})
        if request.url.path == "/v2/matches":
            token = request.url.params.get("page_token")
            if token is None:
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "matches": [{"_id": "m1", "person": {"_id": "p1", "name": "A"}}],
                            "next_page_token": "pg2",
                        }
                    },
                )
            return httpx.Response(
                200,
                json={
                    "data": {
                        "matches": [{"_id": "m2", "person": {"_id": "p2", "name": "B"}}]
                    }
                },
            )
        return httpx.Response(404, json={})

    conn = TinderConnector(auth_token="t", transport=httpx.MockTransport(handler))
    try:
        matches = await conn.get_matches(count=60)
        assert [m.name for m in matches] == ["A", "B"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_retries_transient_5xx_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/recs/core":
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503, json={})
            return httpx.Response(200, json={"data": {"results": []}})
        return httpx.Response(404, json={})

    conn = TinderConnector(
        auth_token="t", transport=httpx.MockTransport(handler), retry_backoff=0
    )
    try:
        recs = await conn.get_recommendations()
        assert recs == []
        assert calls["n"] == 2  # retried the 503 once
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_field_drift_null_objects_do_not_crash():
    """Real Tinder payloads often send ``null`` where an object/array is
    expected. Defensive parsing must coerce those rather than crash."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/recs/core":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "results": [
                            {
                                "distance_mi": None,
                                "user": {
                                    "_id": "drift1",
                                    "name": "Drift",
                                    "bio": None,
                                    "photos": None,
                                    "user_interests": None,
                                    "selected_descriptors": [
                                        {
                                            "prompt": None,
                                            "choice_selections": [{"name": "x"}],
                                        }
                                    ],
                                    "jobs": [{"company": None, "title": None}],
                                    "schools": None,
                                },
                            },
                            {"user": None},  # whole user object missing
                        ]
                    }
                },
            )
        return httpx.Response(404, json={})

    conn = TinderConnector(auth_token="t", transport=httpx.MockTransport(handler))
    try:
        recs = await conn.get_recommendations()
        # Both candidates parse without raising; null fields become empties.
        assert len(recs) == 2
        assert recs[0].id == "drift1"
        assert recs[0].photos == [] and recs[0].interests == [] and recs[0].jobs == []
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_match_with_null_person_does_not_crash():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/profile":
            return httpx.Response(200, json={"data": {"_id": "me"}})
        if request.url.path == "/v2/matches":
            return httpx.Response(
                200,
                json={"data": {"matches": [{"_id": "m1", "person": None}]}},
            )
        return httpx.Response(404, json={})

    conn = TinderConnector(auth_token="t", transport=httpx.MockTransport(handler))
    try:
        matches = await conn.get_matches()
        assert matches[0].id == "m1"
        assert matches[0].name == "" and matches[0].photos == []
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_raises_clear_error_after_exhausting_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    conn = TinderConnector(
        auth_token="t",
        transport=httpx.MockTransport(handler),
        retry_backoff=0,
        max_retries=2,
    )
    try:
        with pytest.raises(RuntimeError, match="Tinder API"):
            await conn.get_recommendations()
    finally:
        await conn.close()
