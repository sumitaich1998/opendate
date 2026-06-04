"""Conversation memory + stage machine tests (offline)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from opendate.orchestrator.state import (
    ConversationStage,
    ConversationState,
    ConversationStore,
    compute_stage,
    normalize_text,
)
from opendate.skills.engine import SituationContext


def _ctx(**kw) -> SituationContext:
    base = dict(has_messages=True, last_from_me=False, num_messages=4)
    base.update(kw)
    return SituationContext(**base)


def test_normalize_text_strips_punct_and_case():
    assert normalize_text("Hey, THERE!!  ") == "hey there"


def test_repeat_detection():
    state = ConversationState(match_id="m")
    state.record_outgoing("What's your go-to karaoke song?", skill="opener")
    assert state.is_repeat("whats your go to karaoke song")
    assert not state.is_repeat("totally different question about hiking")


def test_outgoing_history_is_capped():
    state = ConversationState(match_id="m")
    for i in range(20):
        state.record_outgoing(f"message number {i}", skill="x")
    assert len(state.outgoing_history) <= 10
    assert state.sent_count == 20


def test_cooldown_remaining():
    state = ConversationState(match_id="m")
    now = datetime.now(timezone.utc)
    state.record_outgoing("hi", skill="x", now=now)
    assert state.cooldown_remaining(8.0, now) == 8.0
    later = now + timedelta(hours=8)
    assert state.cooldown_remaining(8.0, later) == 0.0


def test_compute_stage_progression():
    assert compute_stage(SituationContext(has_messages=False)) is ConversationStage.MATCHED
    assert compute_stage(_ctx(num_messages=1)) is ConversationStage.OPENED
    assert compute_stage(_ctx(num_messages=4, banter=True)) is ConversationStage.FLIRTING
    assert compute_stage(_ctx(ready_for_date=True)) is ConversationStage.PROPOSING
    assert compute_stage(_ctx(disinterest=True)) is ConversationStage.RECOVERING


def test_compute_stage_stalled_then_ghosted():
    stalled = compute_stage(
        _ctx(last_from_me=True, days_since_last=4, reengage_after_days=3)
    )
    assert stalled is ConversationStage.STALLED
    ghosted = compute_stage(
        _ctx(last_from_me=True, days_since_last=12, reengage_after_days=3)
    )
    assert ghosted is ConversationStage.GHOSTED


def test_compute_stage_number_exchanged_wins():
    stage = compute_stage(_ctx(num_messages=5), number_shared=True)
    assert stage is ConversationStage.NUMBER_EXCHANGED


def test_store_persists_and_reloads(tmp_path):
    path = tmp_path / "nested" / "conversations.json"
    store = ConversationStore(path)
    state = store.get("m1", "Maya")
    state.stage = ConversationStage.FLIRTING
    state.record_outgoing("hey you", skill="banter")
    store.record_action()
    store.save()

    reopened = ConversationStore(path)
    loaded = reopened.get("m1")
    assert loaded.name == "Maya"
    assert loaded.stage is ConversationStage.FLIRTING
    assert loaded.sent_count == 1
    assert reopened.actions_in_last(24) == 1


def test_in_memory_store_does_not_write(tmp_path):
    store = ConversationStore()  # no path -> ephemeral
    store.get("m").record_outgoing("x", skill="y")
    store.save()  # no-op, should not raise
    assert list(tmp_path.iterdir()) == []


def test_daily_budget_left():
    store = ConversationStore()
    now = datetime.now(timezone.utc)
    for _ in range(3):
        store.record_action(now)
    assert store.daily_budget_left(25, now) == 22
    # Old actions outside the 24h window don't count.
    store.record_action(now - timedelta(hours=30))
    assert store.daily_budget_left(25, now) == 22
