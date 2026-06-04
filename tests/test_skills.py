"""Skills engine: loading, parsing, and situational selection."""

from __future__ import annotations

from opendate.skills.engine import (
    ALWAYS_ACTIVE,
    SituationContext,
    SkillsEngine,
    parse_skill_md,
)

EXPECTED = {
    "profile-screening",
    "opener",
    "approaching",
    "flirting",
    "banter",
    "rapport-building",
    "storytelling",
    "relationship-intent-matching",
    "proposing-a-date",
    "number-exchange",
    "re-engagement",
    "conversation-recovery",
    "persona-style-transfer",
    "consent-and-safety",
}


def test_all_fourteen_skills_load(skills_engine: SkillsEngine):
    loaded = skills_engine.load_all()
    assert len(loaded) == 14
    assert set(loaded) == EXPECTED
    # Every skill has real frontmatter + a non-trivial playbook body.
    for skill in loaded.values():
        assert skill.description
        assert len(skill.body) > 200
        assert skill.category


def test_parse_skill_md_roundtrip():
    text = (
        "---\n"
        "name: demo\n"
        "description: A demo skill.\n"
        "when_to_use: Whenever.\n"
        "category: Test\n"
        "---\n"
        "# Body\nDo the thing.\n"
    )
    skill = parse_skill_md(text)
    assert skill.name == "demo"
    assert skill.description == "A demo skill."
    assert skill.when_to_use == "Whenever."
    assert skill.category == "Test"
    assert "Do the thing." in skill.body


def test_modifiers_always_active(skills_engine: SkillsEngine):
    mods = {m.name for m in skills_engine.modifiers()}
    assert set(ALWAYS_ACTIVE).issubset(mods)


def test_select_candidate_screens(skills_engine: SkillsEngine):
    sel = skills_engine.select(SituationContext(kind="candidate"))
    assert sel.primary.name == "profile-screening"


def test_select_fresh_match_opener(skills_engine: SkillsEngine):
    sel = skills_engine.select(
        SituationContext(kind="match", has_messages=False)
    )
    assert sel.primary.name == "opener"
    # Always-active modifiers are layered on (minus any that equals primary).
    names = sel.skill_names
    assert "consent-and-safety" in names
    assert "persona-style-transfer" in names


def test_select_reengagement(skills_engine: SkillsEngine):
    sel = skills_engine.select(
        SituationContext(
            has_messages=True,
            last_from_me=True,
            days_since_last=5,
            reengage_after_days=3,
        )
    )
    assert sel.primary.name == "re-engagement"


def test_select_recovery_on_negative(skills_engine: SkillsEngine):
    sel = skills_engine.select(
        SituationContext(has_messages=True, last_from_me=False, sentiment="negative")
    )
    assert sel.primary.name == "conversation-recovery"


def test_select_banter_and_flirting(skills_engine: SkillsEngine):
    banter = skills_engine.select(
        SituationContext(has_messages=True, last_from_me=False, banter=True)
    )
    assert banter.primary.name == "banter"
    flirt = skills_engine.select(
        SituationContext(has_messages=True, last_from_me=False, playful=True)
    )
    assert flirt.primary.name == "flirting"


def test_select_proposing_and_number(skills_engine: SkillsEngine):
    propose = skills_engine.select(
        SituationContext(has_messages=True, last_from_me=False, ready_for_date=True, rapport_score=0.7)
    )
    assert propose.primary.name == "proposing-a-date"
    number = skills_engine.select(
        SituationContext(has_messages=True, last_from_me=False, ready_for_date=True, rapport_score=0.85)
    )
    assert number.primary.name == "number-exchange"


def test_select_disinterest_recovers(skills_engine: SkillsEngine):
    sel = skills_engine.select(
        SituationContext(has_messages=True, last_from_me=False, disinterest=True)
    )
    assert sel.primary.name == "conversation-recovery"


# --- smarter selection: stage, signals, confidence, tie-break --------------
def test_select_returns_confidence_and_reason(skills_engine: SkillsEngine):
    sel = skills_engine.select(SituationContext(kind="match", has_messages=False))
    assert 0.0 < sel.confidence <= 1.0
    assert sel.reason
    assert sel.decided_by == "heuristic"


def test_select_approaching_in_early_stage(skills_engine: SkillsEngine):
    sel = skills_engine.select(
        SituationContext(
            has_messages=True, last_from_me=False, num_messages=2, stage="opened"
        )
    )
    assert sel.primary.name == "approaching"


def test_select_storytelling_when_deep(skills_engine: SkillsEngine):
    sel = skills_engine.select(
        SituationContext(has_messages=True, last_from_me=False, num_messages=8)
    )
    assert sel.primary.name == "storytelling"


def test_select_layers_all_modifiers(skills_engine: SkillsEngine):
    sel = skills_engine.select(
        SituationContext(has_messages=True, last_from_me=False, num_messages=4)
    )
    names = sel.skill_names
    assert "consent-and-safety" in names
    assert "relationship-intent-matching" in names
    assert "persona-style-transfer" in names


def test_llm_tiebreak_overrides_low_confidence(skills_engine: SkillsEngine):
    class FakeRouter:
        is_stub = False

        def chat_json(self, system, user, **kw):
            return {"skill": "storytelling"}

    sel = skills_engine.select(
        SituationContext(
            has_messages=True, last_from_me=False, num_messages=2, stage="opened"
        ),
        router=FakeRouter(),
    )
    assert sel.primary.name == "storytelling"
    assert sel.decided_by == "llm-tiebreak"


def test_stub_router_skips_tiebreak(skills_engine: SkillsEngine, stub_router):
    sel = skills_engine.select(
        SituationContext(
            has_messages=True, last_from_me=False, num_messages=2, stage="opened"
        ),
        router=stub_router,
    )
    assert sel.decided_by == "heuristic"  # offline stub never makes a network call


def test_high_confidence_branch_ignores_tiebreak(skills_engine: SkillsEngine):
    class LoudRouter:
        is_stub = False

        def chat_json(self, system, user, **kw):  # pragma: no cover - must not run
            raise AssertionError("tie-break should not fire for clear situations")

    sel = skills_engine.select(
        SituationContext(kind="match", has_messages=False), router=LoudRouter()
    )
    assert sel.primary.name == "opener"
