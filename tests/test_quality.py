"""Message self-critique tests (deterministic, offline)."""

from __future__ import annotations

from opendate.orchestrator.quality import critique_message
from opendate.orchestrator.state import ConversationState
from opendate.persona.analyze import PersonaProfile
from opendate.skills.engine import SituationContext


def test_good_grounded_message_passes():
    ctx = SituationContext(
        has_messages=True,
        their_last_text="just got back from a climbing trip in Spain",
        their_msg_words=9,
    )
    crit = critique_message(
        "A climbing trip in Spain?! Costa Blanca or somewhere wilder?",
        ctx=ctx,
        skill="banter",
        reference_text="climbing trip in Spain",
    )
    assert crit.passed
    assert crit.score >= 0.8


def test_generic_message_fails():
    crit = critique_message(
        "Hey! Tell me more, how are you doing?",
        skill="rapport-building",
        reference_text="I just ran my first marathon",
    )
    assert not crit.passed
    assert any("generic" in i for i in crit.issues)


def test_cringe_message_fails():
    crit = critique_message("did it hurt when you fell from heaven?", skill="flirting")
    assert not crit.passed
    assert any("cringe" in i for i in crit.issues)


def test_repeat_message_fails():
    state = ConversationState(match_id="m")
    state.record_outgoing("what's your go-to karaoke song", skill="opener")
    crit = critique_message("What's your go-to karaoke song?", state=state)
    assert not crit.passed
    assert any("repeat" in i for i in crit.issues)


def test_empty_message_fails():
    crit = critique_message("")
    assert not crit.passed
    assert crit.score == 0.0


def test_missing_question_penalized_for_opener():
    no_q = critique_message("your dog is extremely cute and I respect the commitment", skill="opener")
    with_q = critique_message(
        "your dog is extremely cute — what's the story behind the name?", skill="opener"
    )
    assert with_q.score > no_q.score


def test_emoji_mismatch_flagged_for_plain_persona():
    persona = PersonaProfile(emoji_rate=0.0)
    crit = critique_message("haha yeah for sure, sounds like a plan 😄🔥", persona=persona)
    assert any("emoji" in i for i in crit.issues)


def test_interview_energy_penalized():
    crit = critique_message("Where? When? Who with? Why though?")
    assert any("question" in i for i in crit.issues)
