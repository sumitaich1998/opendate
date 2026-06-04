"""Consent & safety guard tests (deterministic, offline)."""

from __future__ import annotations

from opendate.config import SafetyConfig
from opendate.orchestrator.safety import SafetyGuard
from opendate.skills.engine import SituationContext


def guard(**overrides) -> SafetyGuard:
    return SafetyGuard(SafetyConfig(**overrides))


def test_allows_clean_message():
    decision = guard().check_message("Hey! Loved your taco take. Coffee this week?")
    assert decision.allowed is True


def test_blocks_hostility():
    decision = guard().check_message("you're an idiot and ugly")
    assert decision.blocked
    assert decision.severity == "hard"


def test_blocks_pressure():
    decision = guard().check_message("come on, just give me your number already")
    assert decision.blocked
    assert decision.severity == "soft"


def test_blocks_explicit_by_default():
    decision = guard().check_message("send nudes")
    assert decision.blocked
    assert decision.severity == "hard"


def test_explicit_allowed_when_enabled_and_invited():
    ctx = SituationContext(their_last_text="i want you, send me something")
    decision = guard(allow_explicit=True).check_message("how about some nudes", ctx)
    assert decision.allowed is True


def test_blocks_deception():
    decision = guard().check_message("trust me i'm definitely who i say i am, this isn't a scam")
    assert decision.blocked


def test_backs_off_on_disinterest():
    ctx = SituationContext(disinterest=True, their_last_text="k")
    decision = guard().check_message("hey want to hang out this weekend?", ctx)
    assert decision.blocked
    assert decision.severity == "soft"


def test_hard_stop_blocks():
    ctx = SituationContext(hard_stop=True, their_last_text="please stop messaging me")
    decision = guard().check_message("but wait", ctx)
    assert decision.blocked
    assert decision.severity == "hard"


# --- hardening: minors, discomfort, pacing ---------------------------------
def test_blocks_possible_minor():
    ctx = SituationContext(their_last_text="hey im 17, still in high school lol")
    decision = guard().check_message("what are you up to this weekend?", ctx)
    assert decision.blocked
    assert decision.severity == "hard"
    assert decision.category == "minor"


def test_minor_block_can_be_disabled():
    ctx = SituationContext(their_last_text="im 17")
    decision = guard(refuse_minors=False).check_message("hello there", ctx)
    assert decision.allowed  # the message itself is clean


def test_blocks_discomfort_signal():
    ctx = SituationContext(their_last_text="honestly this is getting kinda creepy")
    decision = guard().check_message("come hang out", ctx)
    assert decision.blocked
    assert decision.category == "discomfort"


def test_detects_their_hard_stop_text_without_flag():
    ctx = SituationContext(their_last_text="please stop messaging me")
    decision = guard().check_message("one more thing", ctx)
    assert decision.blocked
    assert decision.category == "hard-stop"


def test_pacing_cooldown_blocks():
    decision = guard().check_pacing(cooldown_remaining=4.0)
    assert decision.blocked
    assert decision.category == "cooldown"


def test_pacing_daily_cap_blocks():
    decision = guard().check_pacing(daily_budget_left=0)
    assert decision.blocked
    assert decision.category == "rate-limit"


def test_pacing_blocks_excess_followups():
    decision = guard(max_followups_without_reply=2).check_pacing(
        followups_without_reply=3, cooldown_remaining=0.0, daily_budget_left=5
    )
    assert decision.blocked
    assert decision.category == "escalation"


def test_pacing_allows_when_clear():
    decision = guard().check_pacing(
        cooldown_remaining=0.0, daily_budget_left=5, followups_without_reply=0
    )
    assert decision.allowed
