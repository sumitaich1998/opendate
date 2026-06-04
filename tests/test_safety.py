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
