"""MockConnector behavior tests (offline)."""

from __future__ import annotations

import pytest

from opendate.connectors.base import MatchSource
from opendate.connectors.mock import MockConnector


def test_mock_is_a_matchsource():
    assert isinstance(MockConnector(), MatchSource)


@pytest.mark.asyncio
async def test_recommendations_and_swiping():
    conn = MockConnector()
    recs = await conn.get_recommendations(limit=10)
    assert recs and all(r.id for r in recs)
    first = recs[0]

    result = await conn.like(first.id)
    assert result["match"]  # a like becomes a match in the mock
    assert first.id in conn.liked

    # Swiped candidates no longer appear in recommendations.
    recs_after = await conn.get_recommendations(limit=10)
    assert first.id not in {r.id for r in recs_after}


@pytest.mark.asyncio
async def test_pass_records():
    conn = MockConnector()
    recs = await conn.get_recommendations()
    await conn.pass_(recs[0].id)
    assert recs[0].id in conn.passed


@pytest.mark.asyncio
async def test_matches_and_messages():
    conn = MockConnector()
    matches = await conn.get_matches()
    assert matches
    active = next(m for m in matches if m.id == "match-priya")
    messages = await conn.get_messages(active.id)
    assert messages
    assert messages[-1].sender in {"me", "them"}


@pytest.mark.asyncio
async def test_send_message_appends():
    conn = MockConnector()
    sent = await conn.send_message("match-maya", "hello there")
    assert sent.from_me is True
    assert sent.text == "hello there"
    msgs = await conn.get_messages("match-maya")
    assert msgs[-1].text == "hello there"
    assert conn.sent and conn.sent[-1].text == "hello there"
