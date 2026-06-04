"""Orchestrator loop tests: screening, situation analysis, and the full cycle."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest
from rich.console import Console

from opendate.connectors.base import Candidate, Match, Message
from opendate.connectors.mock import MockConnector
from opendate.llm.providers import resolve_model
from opendate.llm.router import EchoBackend, LLMRouter
from opendate.orchestrator.loop import Orchestrator, build_situation, score_candidate
from opendate.orchestrator.safety import SafetyGuard
from opendate.orchestrator.state import ConversationStage, ConversationStore
from opendate.skills.engine import SituationContext


def _quiet_console() -> Console:
    return Console(file=io.StringIO())


def _make_orchestrator(
    connector, router, skills_engine, persona, config, store=None, clock=None
) -> Orchestrator:
    return Orchestrator(
        connector=connector,
        router=router,
        skills=skills_engine,
        persona=persona,
        config=config,
        safety=SafetyGuard(config.safety),
        console=_quiet_console(),
        interactive=False,
        store=store,
        clock=clock,
    )


def _responder_router(responder) -> LLMRouter:
    return LLMRouter(
        EchoBackend(responder=responder),
        [resolve_model("openai", "gpt-4o-mini", {})],
        is_stub=True,
        retry_backoff=0,
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


# --- weighted screening: hard filters + configurable threshold -------------
def test_score_candidate_must_have_missing(app_config):
    prefs = app_config.preferences.model_copy(update={"must_haves": ["vegan"]})
    cand = Candidate(id="x", name="Sam", age=29, bio="loves climbing and bbq")
    decision, score, reasons, _ = score_candidate(cand, prefs)
    assert decision == "pass"
    assert score == 0.0
    assert any("must-have" in r for r in reasons)


def test_score_candidate_threshold_is_configurable(app_config):
    cand = Candidate(id="z", name="Ada", age=29, bio="just a fairly normal person")
    strict = app_config.preferences.model_copy(update={"like_threshold": 0.95})
    decision, _, _, _ = score_candidate(cand, strict)
    assert decision == "pass"  # clears the old 0.55 bar but not 0.95


def test_score_candidate_blocks_minor(app_config):
    cand = Candidate(id="m", name="Kid", age=16, bio="witty and outdoorsy")
    decision, score, reasons, _ = score_candidate(cand, app_config.preferences)
    assert decision == "pass"
    assert score == 0.0
    assert any("18" in r for r in reasons)


# --- prioritisation --------------------------------------------------------
def test_priority_orders_waiting_people_first():
    unanswered = build_situation(
        Match(
            id="u",
            messages=[Message(id="1", match_id="u", sender="them", text="hey you!")],
        )
    )
    fresh = SituationContext(has_messages=False)
    waiting = SituationContext(has_messages=True, last_from_me=True, days_since_last=0)
    assert Orchestrator._priority(unanswered) > Orchestrator._priority(fresh)
    assert Orchestrator._priority(fresh) > Orchestrator._priority(waiting)


# --- conversation memory persists across cycles ----------------------------
@pytest.mark.asyncio
async def test_state_persists_across_runs(
    stub_router, skills_engine, persona, app_config, tmp_path
):
    store = ConversationStore(tmp_path / "conversations.json")
    config = app_config.model_copy(update={"auto_send": True})
    conn = MockConnector()
    orch = _make_orchestrator(
        conn, stub_router, skills_engine, persona, config, store=store
    )
    await orch.run_once()

    # Reload from disk in a brand-new store: memory survived.
    reloaded = ConversationStore(tmp_path / "conversations.json")
    priya = reloaded.get("match-priya")
    assert priya.stage in {ConversationStage.FLIRTING, ConversationStage.RAPPORT}
    assert priya.sent_count >= 1
    assert priya.last_skill is not None


# --- pacing: cooldown blocks a too-soon re-message -------------------------
@pytest.mark.asyncio
async def test_cooldown_blocks_when_we_messaged_recently(
    stub_router, skills_engine, persona, app_config
):
    now = datetime.now(timezone.utc)
    match = Match(
        id="m-cool",
        person_id="p",
        name="Cool",
        messages=[
            Message(id="a", match_id="m-cool", sender="me", text="hey what's your favorite trail?", sent_at=now - timedelta(hours=1)),
            Message(id="b", match_id="m-cool", sender="them", text="ooh probably the coastal one, you?", sent_at=now - timedelta(minutes=30)),
        ],
    )
    conn = MockConnector(candidates=[], matches=[match])
    config = app_config.model_copy(update={"auto_send": True})
    store = ConversationStore()
    store.get("m-cool").last_sent_at = now - timedelta(hours=1)  # inside 8h cooldown
    orch = _make_orchestrator(
        conn, stub_router, skills_engine, persona, config, store=store, clock=lambda: now
    )
    actions = await orch.run_once()
    cool = next(a for a in actions if a.target_id == "m-cool")
    assert cool.kind == "skip"
    assert "cooldown" in cool.reason.lower()
    assert conn.sent == []


# --- self-critique regenerates a weak first draft --------------------------
@pytest.mark.asyncio
async def test_self_critique_regenerates_weak_draft(
    skills_engine, persona, app_config
):
    calls = {"n": 0}

    def responder(messages):
        calls["n"] += 1
        if calls["n"] == 1:
            return "Hey! Tell me more, how are you doing?"  # generic -> fails
        return "your bio says coffee snob — most pretentious order you secretly love?"

    router = _responder_router(responder)
    fresh = Match(id="m-fresh", person_id="p", name="Fresh", bio="coffee snob", messages=[])
    conn = MockConnector(candidates=[], matches=[fresh])
    orch = _make_orchestrator(conn, router, skills_engine, persona, app_config)
    actions = await orch.run_once()
    send = next(a for a in actions if a.target_id == "m-fresh")
    assert calls["n"] == 2  # regenerated exactly once
    assert "coffee" in (send.text or "").lower()
    assert "tell me more" not in (send.text or "").lower()


# --- per-match error isolation ---------------------------------------------
@pytest.mark.asyncio
async def test_one_bad_match_does_not_crash_the_loop(
    stub_router, skills_engine, persona, app_config
):
    class ExplodingOrch(Orchestrator):
        async def _handle_match(self, match, ctx, state, now):
            if match.id == "match-priya":
                raise RuntimeError("kaboom")
            return await super()._handle_match(match, ctx, state, now)

    conn = MockConnector()
    orch = ExplodingOrch(
        connector=conn,
        router=stub_router,
        skills=skills_engine,
        persona=persona,
        config=app_config,
        safety=SafetyGuard(app_config.safety),
        console=_quiet_console(),
        interactive=False,
    )
    actions = await orch.run_once()  # must not raise
    priya = next(a for a in actions if a.target_id == "match-priya")
    assert priya.kind == "skip"
    assert "error" in priya.reason.lower()
    # Other matches were still handled.
    assert any(a.kind == "send" for a in actions if a.target_id != "match-priya")
