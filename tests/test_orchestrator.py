"""Orchestrator loop tests: screening, situation analysis, and the full cycle."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest
from rich.console import Console

from opendate.connectors.base import Candidate, Match, Message
from opendate.connectors.mock import MockConnector
from opendate.orchestrator.loop import Orchestrator, build_situation, score_candidate
from opendate.orchestrator.safety import SafetyGuard


def _quiet_console() -> Console:
    return Console(file=io.StringIO())


def _make_orchestrator(connector, router, skills_engine, persona, config) -> Orchestrator:
    return Orchestrator(
        connector=connector,
        router=router,
        skills=skills_engine,
        persona=persona,
        config=config,
        safety=SafetyGuard(config.safety),
        console=_quiet_console(),
        interactive=False,
    )


# --- screening -------------------------------------------------------------
def test_score_candidate_dealbreaker(app_config):
    cand = Candidate(id="x", name="Sam", age=28, bio="social smoker who loves music")
    decision, score, reasons, _ = score_candidate(cand, app_config.preferences)
    assert decision == "pass"
    assert score == 0.0
    assert any("dealbreaker" in r for r in reasons)


def test_score_candidate_age_out_of_range(app_config):
    cand = Candidate(id="y", name="Jo", age=19, bio="hello world")
    decision, _, _, _ = score_candidate(cand, app_config.preferences)
    assert decision == "pass"


def test_score_candidate_good_match(app_config):
    cand = Candidate(
        id="z",
        name="Maya",
        age=29,
        bio="witty outdoorsy climber who loves live music",
        interests=["climbing", "live music"],
    )
    decision, score, reasons, open_on = score_candidate(cand, app_config.preferences)
    assert decision == "like"
    assert score >= 0.55
    assert open_on


# --- situation analysis ----------------------------------------------------
@pytest.mark.asyncio
async def test_build_situation_for_seed_matches():
    conn = MockConnector()
    matches = await conn.get_matches()
    by_id = {m.id: m for m in matches}

    fresh = build_situation(by_id["match-maya"])
    assert fresh.has_messages is False

    active = build_situation(by_id["match-priya"])
    assert active.has_messages is True
    assert active.last_from_me is False
    assert active.playful or active.banter

    stalled = build_situation(by_id["match-lena"])
    assert stalled.last_from_me is True
    assert (stalled.days_since_last or 0) >= 3


# --- full cycle ------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_once_proposes_without_sending(
    mock_connector, stub_router, skills_engine, persona, app_config
):
    orch = _make_orchestrator(
        mock_connector, stub_router, skills_engine, persona, app_config
    )
    actions = await orch.run_once()
    sends = [a for a in actions if a.kind == "send"]
    assert sends, "expected at least one proposed message"
    assert all(a.text for a in sends)
    # auto_send is off and non-interactive -> nothing actually sent.
    assert mock_connector.sent == []
    assert all(a.sent is False for a in sends)


@pytest.mark.asyncio
async def test_run_once_auto_send_sends(
    mock_connector, stub_router, skills_engine, persona, app_config
):
    config = app_config.model_copy(update={"auto_send": True})
    orch = _make_orchestrator(
        mock_connector, stub_router, skills_engine, persona, config
    )
    actions = await orch.run_once()
    sent_actions = [a for a in actions if a.kind == "send" and a.sent]
    assert sent_actions
    assert mock_connector.sent  # messages really went out (to the mock)


@pytest.mark.asyncio
async def test_loop_backs_off_on_disinterest(
    stub_router, skills_engine, persona, app_config
):
    now = datetime.now(timezone.utc)
    match = Match(
        id="match-flat",
        person_id="p-flat",
        name="Flat",
        messages=[
            Message(id="a", match_id="match-flat", sender="them", text="hey", sent_at=now - timedelta(hours=3)),
            Message(id="b", match_id="match-flat", sender="me", text="hey! how's your week going?", sent_at=now - timedelta(hours=2)),
            Message(id="c", match_id="match-flat", sender="them", text="k", sent_at=now - timedelta(hours=1)),
        ],
    )
    conn = MockConnector(candidates=[], matches=[match])
    orch = _make_orchestrator(conn, stub_router, skills_engine, persona, app_config)
    actions = await orch.run_once()
    flat = next(a for a in actions if a.target_id == "match-flat")
    assert flat.kind == "backoff"
    assert flat.blocked is True
    assert conn.sent == []


@pytest.mark.asyncio
async def test_does_not_double_text(
    stub_router, skills_engine, persona, app_config
):
    now = datetime.now(timezone.utc)
    match = Match(
        id="m-wait",
        person_id="p",
        name="Waiting",
        messages=[
            Message(id="a", match_id="m-wait", sender="them", text="hey there", sent_at=now - timedelta(hours=5)),
            Message(id="b", match_id="m-wait", sender="me", text="hey! what's up", sent_at=now - timedelta(hours=1)),
        ],
    )
    conn = MockConnector(candidates=[], matches=[match])
    orch = _make_orchestrator(conn, stub_router, skills_engine, persona, app_config)
    actions = await orch.run_once()
    wait = next(a for a in actions if a.target_id == "m-wait")
    assert wait.kind == "skip"  # we recently messaged; don't double-text
