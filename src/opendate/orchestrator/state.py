"""Per-match conversation memory + a conversation stage machine.

OpenDate runs as a loop, often across many short sessions. To behave like a
thoughtful human rather than a goldfish, it needs to *remember* each thread:
what stage it's in, what we last said, when we last sent, and whether we're
repeating ourselves. :class:`ConversationStore` persists that to a small JSON
file under a (git-ignored) data directory so memory survives across runs.

The stage machine encodes the natural arc of a dating conversation::

    matched -> opened -> rapport -> flirting -> proposing -> number_exchanged
                   \\-> stalled / ghosted -> recovering -/

Stages are computed from cheap, deterministic signals so everything works
offline; the orchestrator feeds the resolved stage back into skill selection.
"""

from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from ..utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..skills.engine import SituationContext

__all__ = [
    "ConversationStage",
    "ConversationState",
    "ConversationStore",
    "compute_stage",
    "normalize_text",
]

log = get_logger("orchestrator.state")

_STORE_VERSION = 1
_HISTORY_LIMIT = 10
_APOSTROPHE_RE = re.compile(r"['\u2019]")
_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)


class ConversationStage(str, Enum):
    """Where a thread sits along the dating arc."""

    MATCHED = "matched"
    OPENED = "opened"
    RAPPORT = "rapport"
    FLIRTING = "flirting"
    PROPOSING = "proposing"
    NUMBER_EXCHANGED = "number_exchanged"
    STALLED = "stalled"
    GHOSTED = "ghosted"
    RECOVERING = "recovering"
    CLOSED = "closed"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_text(text: str) -> str:
    """Lowercase, fold contractions, drop punctuation — for repeat detection.

    Apostrophes are removed (not spaced) so ``what's`` == ``whats``.
    """
    cleaned = _APOSTROPHE_RE.sub("", (text or "").lower())
    return " ".join(_PUNCT_RE.sub(" ", cleaned).split())


class ConversationState(BaseModel):
    """Everything we remember about one match between runs."""

    match_id: str
    name: str = ""
    stage: ConversationStage = ConversationStage.MATCHED
    message_count: int = 0
    sent_count: int = 0
    followups_without_reply: int = 0

    last_action: str = ""
    last_skill: str | None = None
    last_decision_reason: str = ""
    last_outgoing_text: str = ""
    last_their_text: str = ""
    last_seen_message_id: str | None = None

    last_sent_at: datetime | None = None
    first_seen_at: datetime = Field(default_factory=_utcnow)
    last_updated: datetime = Field(default_factory=_utcnow)

    # Recent outgoing messages (normalized), newest last — used to avoid repeats.
    outgoing_history: list[str] = Field(default_factory=list)

    def record_outgoing(self, text: str, *, skill: str | None, now: datetime | None = None) -> None:
        """Record that we sent ``text`` (updates cooldown + repeat history)."""
        now = now or _utcnow()
        self.last_outgoing_text = text
        self.last_skill = skill
        self.last_sent_at = now
        self.sent_count += 1
        norm = normalize_text(text)
        if norm:
            self.outgoing_history.append(norm)
            del self.outgoing_history[:-_HISTORY_LIMIT]
        self.touch(now)

    def is_repeat(self, text: str, *, threshold: float = 0.8) -> bool:
        """True if ``text`` closely matches something we've already sent."""
        candidate = normalize_text(text)
        if not candidate:
            return False
        cand_words = set(candidate.split())
        for prior in self.outgoing_history:
            if prior == candidate:
                return True
            prior_words = set(prior.split())
            if not prior_words or not cand_words:
                continue
            overlap = len(cand_words & prior_words) / len(cand_words | prior_words)
            if overlap >= threshold:
                return True
        return False

    def cooldown_remaining(self, cooldown_hours: float, now: datetime | None = None) -> float:
        """Hours left before we may message again (0 if clear)."""
        if not self.last_sent_at or cooldown_hours <= 0:
            return 0.0
        now = now or _utcnow()
        elapsed = (now - self.last_sent_at).total_seconds() / 3600.0
        return max(0.0, cooldown_hours - elapsed)

    def touch(self, now: datetime | None = None) -> None:
        self.last_updated = now or _utcnow()


def compute_stage(
    ctx: "SituationContext",
    *,
    previous: ConversationStage | None = None,
    proposed_date: bool = False,
    number_shared: bool = False,
) -> ConversationStage:
    """Resolve the conversation stage from a situation snapshot.

    Deterministic and side-effect free so it's identical online and offline.
    ``previous`` lets us prefer "recovering" over a cold "stalled" once we've
    already started a re-engagement.
    """
    if not ctx.has_messages:
        return ConversationStage.MATCHED

    # Off-app / closing stages take priority — they're milestones.
    if number_shared:
        return ConversationStage.NUMBER_EXCHANGED

    days_idle = ctx.days_since_last or 0.0
    if ctx.last_from_me and days_idle >= ctx.reengage_after_days:
        # We reached out and got silence. Very long = ghosted, else stalled,
        # and once we've sent a revival it's "recovering".
        if previous in (ConversationStage.RECOVERING, ConversationStage.STALLED):
            return ConversationStage.RECOVERING
        return (
            ConversationStage.GHOSTED
            if days_idle >= ctx.reengage_after_days * 3
            else ConversationStage.STALLED
        )

    if ctx.disinterest or ctx.sentiment == "negative":
        return ConversationStage.RECOVERING

    if proposed_date or ctx.ready_for_date:
        return ConversationStage.PROPOSING

    if ctx.banter or ctx.playful or ctx.rapport_score >= 0.55:
        return ConversationStage.FLIRTING

    if ctx.num_messages >= 3:
        return ConversationStage.RAPPORT

    return ConversationStage.OPENED


class ConversationStore:
    """Loads/saves :class:`ConversationState` records plus a global action log.

    With ``path=None`` the store is purely in-memory (used by tests and any
    ephemeral run); with a path it persists atomically to JSON. The action log
    is a flat list of timestamps used to enforce a rolling daily action cap.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._states: dict[str, ConversationState] = {}
        self._actions: list[datetime] = []
        if self.path is not None:
            self.load()

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Could not read conversation store %s: %s", self.path, exc)
            return
        convos = raw.get("conversations", {}) if isinstance(raw, dict) else {}
        for match_id, data in convos.items():
            try:
                self._states[match_id] = ConversationState.model_validate(data)
            except Exception as exc:  # noqa: BLE001 - skip a corrupt record
                log.warning("Skipping corrupt state for %s: %s", match_id, exc)
        for stamp in raw.get("actions", []) if isinstance(raw, dict) else []:
            parsed = _parse_dt(stamp)
            if parsed is not None:
                self._actions.append(parsed)

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _STORE_VERSION,
            "saved_at": _utcnow().isoformat(),
            "conversations": {
                mid: json.loads(state.model_dump_json())
                for mid, state in self._states.items()
            },
            "actions": [dt.isoformat() for dt in self._prune_actions()],
        }
        # Atomic write so a crash mid-save never corrupts the store.
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with open(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
            Path(tmp).replace(self.path)
        except OSError as exc:  # pragma: no cover - disk failure
            log.warning("Could not persist conversation store: %s", exc)
            Path(tmp).unlink(missing_ok=True)

    # ------------------------------------------------------------------ #
    # Access
    # ------------------------------------------------------------------ #
    def get(self, match_id: str, name: str = "") -> ConversationState:
        state = self._states.get(match_id)
        if state is None:
            state = ConversationState(match_id=match_id, name=name)
            self._states[match_id] = state
        elif name and not state.name:
            state.name = name
        return state

    def all(self) -> dict[str, ConversationState]:
        return dict(self._states)

    # ------------------------------------------------------------------ #
    # Daily action accounting
    # ------------------------------------------------------------------ #
    def record_action(self, now: datetime | None = None) -> None:
        self._actions.append(now or _utcnow())

    def actions_in_last(self, hours: float = 24.0, now: datetime | None = None) -> int:
        now = now or _utcnow()
        cutoff = now - timedelta(hours=hours)
        return sum(1 for dt in self._actions if dt >= cutoff)

    def daily_budget_left(self, cap: int, now: datetime | None = None) -> int:
        return max(0, cap - self.actions_in_last(24.0, now))

    def _prune_actions(self, now: datetime | None = None) -> list[datetime]:
        now = now or _utcnow()
        cutoff = now - timedelta(hours=48)
        self._actions = [dt for dt in self._actions if dt >= cutoff]
        return self._actions


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
