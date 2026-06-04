"""The runtime loop: Sync -> Screen -> Decide -> Generate -> Voice -> Guard -> Act.

The :class:`Orchestrator` schedules actions across all matches each cycle. It is
fully async and connector-agnostic, so the same loop runs against real Tinder or
the offline mock. Risky steps are gated by the :class:`SafetyGuard` and, when
``auto_send`` is off, by human confirmation (human-in-the-loop).
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..connectors.base import Candidate, Match, MatchSource
from ..persona.analyze import PersonaProfile
from ..persona.style import StyleTransfer
from ..skills.engine import SituationContext, SkillsEngine, SkillSelection
from ..utils.logging import get_logger
from .quality import critique_message
from .safety import SafetyGuard
from .state import ConversationState, ConversationStore, compute_stage

__all__ = ["Orchestrator", "PlannedAction", "build_situation", "score_candidate"]

log = get_logger("orchestrator.loop")

# Off-app transition markers (used to detect the number_exchanged milestone).
_NUMBER_SHARED = re.compile(
    r"\b(my\s+number\s+is|here'?s\s+my\s+number|text\s+me\s+at|"
    r"\d[\d\s\-]{6,}\d|@[\w.]+\s*(?:on\s+(?:insta|ig|snap)))\b",
    re.IGNORECASE,
)

# --- lightweight heuristics for reading a conversation ---------------------
_EMOJI_HINT = re.compile(r"[\U0001f300-\U0001fAFF\U00002600-\U000027BF\U0001f1e6-\U0001f1ff]")
_POSITIVE = re.compile(
    r"\b(haha+|lol|lmao|love|yes+|yeah|omg|can'?t\s+wait|definitely|same|"
    r"exactly|cute|fun|great|awesome|nice)\b",
    re.IGNORECASE,
)
_NEGATIVE = re.compile(
    r"\b(busy|whatever|meh|idk|nvm|not\s+really|maybe\s+later|tired|nope?)\b",
    re.IGNORECASE,
)
_BANTER = re.compile(
    r"\b(rude|fight\s+me|bold\s+of\s+you|prove\s+it|you\s+wish|oh\s+please|"
    r"one\s+point|revoke|insufferable)\b",
    re.IGNORECASE,
)
_HARD_STOP = re.compile(
    r"\b(not\s+interested|please\s+stop|stop\s+messaging|leave\s+me\s+alone|"
    r"don'?t\s+message\s+me|no\s+thank\s*you)\b",
    re.IGNORECASE,
)
_DATEY = re.compile(
    r"\b(grab\s+(?:a\s+)?(?:drink|coffee|bite)|go\s+out|meet\s+up|dinner|"
    r"your\s+number|let'?s\s+(?:meet|do))\b",
    re.IGNORECASE,
)


@dataclass
class PlannedAction:
    """One action the orchestrator decided on this cycle."""

    kind: str  # like | pass | send | skip | backoff | blocked
    target_id: str
    target_name: str = ""
    skill: str | None = None
    text: str | None = None
    reason: str = ""
    score: float | None = None
    sent: bool = False
    blocked: bool = False
    block_reason: str | None = None
    stage: str = ""
    confidence: float | None = None
    quality: float | None = None

    def to_record(self) -> dict[str, Any]:
        """A flat dict for structured (JSONL) decision logging."""
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": self.kind,
            "target_id": self.target_id,
            "target": self.target_name,
            "stage": self.stage,
            "skill": self.skill,
            "confidence": self.confidence,
            "quality": self.quality,
            "sent": self.sent,
            "blocked": self.blocked,
            "reason": self.block_reason or self.reason,
            "text": self.text,
        }


# ---------------------------------------------------------------------------
# Screening (heuristic; mirrors the profile-screening rubric, no LLM required)
# ---------------------------------------------------------------------------
def _term_in_text(term: str, text: str) -> bool:
    """Match a term in text, tolerant of simple inflections (smoking↔smoker)."""
    term = term.strip().lower()
    if not term:
        return False
    if term in text:
        return True
    stem = re.sub(r"(ings?|ed|ers?|s)$", "", term)
    return len(stem) >= 4 and stem in text


def score_candidate(
    candidate: Candidate, preferences: Any
) -> tuple[str, float, list[str], str | None]:
    """Return ``(decision, confidence, reasons, open_on)`` for a candidate.

    Two layers:

    * **Hard filters** (return ``pass`` with confidence ``0.0`` immediately):
      dealbreakers, a candidate who appears to be a minor, and any unmet
      ``must_haves``.
    * **Weighted soft scoring** folded into a 0-1 *confidence*: age fit,
      distance, desired traits, shared interests, and bio quality. The decision
      is ``like`` when confidence clears ``preferences.like_threshold``.
    """
    reasons: list[str] = []
    text = f"{candidate.bio} {' '.join(candidate.interests)}".lower()
    cand_interests = {i.lower() for i in candidate.interests}

    # --- Hard filters --------------------------------------------------- #
    dealbreakers = [d.lower() for d in getattr(preferences, "dealbreakers", [])]
    for db in dealbreakers:
        if _term_in_text(db, text):
            return "pass", 0.0, [f"dealbreaker present: {db}"], None

    if candidate.age is not None and candidate.age < 18:
        return "pass", 0.0, ["candidate appears to be under 18"], None

    must_haves = [m.lower() for m in getattr(preferences, "must_haves", [])]
    missing = [
        m for m in must_haves if not (_term_in_text(m, text) or m in cand_interests)
    ]
    if must_haves and missing:
        return "pass", 0.0, ["missing must-have: " + ", ".join(missing)], None

    # --- Weighted soft scoring ----------------------------------------- #
    score = 0.5

    age_range = getattr(preferences, "age_range", None)
    if age_range is not None and candidate.age is not None:
        if age_range.contains(candidate.age):
            score += 0.12
            reasons.append("age in range")
        else:
            score -= 0.30
            reasons.append("age outside range")

    max_dist = getattr(preferences, "distance_km", None)
    if max_dist is not None and candidate.distance_km is not None:
        if candidate.distance_km <= max_dist:
            score += 0.08
        elif candidate.distance_km > max_dist * 1.5:
            score -= 0.15
            reasons.append("far away")

    traits = [t.lower() for t in getattr(preferences, "partner_traits", [])]
    trait_hits = [t for t in traits if t and t in text]
    if trait_hits:
        score += min(0.24, 0.08 * len(trait_hits))
        reasons.append("traits: " + ", ".join(trait_hits))

    interests = [i.lower() for i in getattr(preferences, "interests", [])]
    shared = [i for i in interests if i in cand_interests or i in text]
    if shared:
        score += min(0.18, 0.06 * len(shared))
        reasons.append("shared: " + ", ".join(shared))

    if must_haves:  # specified and (per above) all satisfied
        score += 0.1
        reasons.append("meets must-haves")

    if candidate.bio.strip():
        score += 0.08
    else:
        score -= 0.05
        reasons.append("empty bio")

    score = max(0.0, min(1.0, score))
    threshold = float(getattr(preferences, "like_threshold", 0.55))
    decision = "like" if score >= threshold else "pass"

    open_on = None
    if decision == "like":
        if shared:
            open_on = f"your shared love of {shared[0]}"
        elif candidate.prompts:
            key = next(iter(candidate.prompts))
            open_on = f"their prompt: {key}"
        elif candidate.bio:
            open_on = "their bio"
    if not reasons:
        reasons.append("balanced profile")
    return decision, round(score, 2), reasons, open_on


# ---------------------------------------------------------------------------
# Situation analysis
# ---------------------------------------------------------------------------
def _sentiment(text: str) -> str:
    if not text:
        return "neutral"
    stripped = text.strip().lower()
    if _HARD_STOP.search(stripped) or _NEGATIVE.search(stripped):
        return "negative"
    if len(stripped.split()) <= 1 and stripped in {"k", "ok", "kk", "fine", "sure"}:
        return "negative"
    if _EMOJI_HINT.search(text) or _POSITIVE.search(text) or "!" in text:
        return "positive"
    return "neutral"


def _disinterest(their_messages: list) -> bool:
    """True if the last couple of their messages look low-effort / withdrawing."""
    recent = their_messages[-2:]
    if not recent:
        return False
    low_effort = 0
    for msg in recent:
        words = len((msg.text or "").split())
        if words <= 2 and not _EMOJI_HINT.search(msg.text or ""):
            low_effort += 1
        if _NEGATIVE.search(msg.text or ""):
            low_effort += 1
    return low_effort >= 2


def build_situation(
    match: Match,
    *,
    reengage_after_days: float = 3.0,
    deepen_after_messages: int = 6,
) -> SituationContext:
    """Compute a :class:`SituationContext` from a match's message history."""
    messages = match.messages
    their = [m for m in messages if not m.from_me]
    last = match.last_message
    last_from_me = bool(last and last.from_me)
    their_last = next((m for m in reversed(messages) if not m.from_me), None)
    their_last_text = their_last.text if their_last else None

    days_since_last: float | None = None
    if last and last.sent_at:
        delta = datetime.now(timezone.utc) - last.sent_at
        days_since_last = max(0.0, delta.total_seconds() / 86400.0)

    sentiment = _sentiment(their_last_text or "")
    playful = bool(
        their_last_text
        and (_EMOJI_HINT.search(their_last_text) or _POSITIVE.search(their_last_text))
    )
    banter = bool(their_last_text and _BANTER.search(their_last_text))
    hard_stop = bool(their_last_text and _HARD_STOP.search(their_last_text))
    disinterest = _disinterest(their) and not banter

    rapport = _rapport(match)
    ready = rapport >= 0.7 and len(messages) >= deepen_after_messages and not _already_pursued(
        match
    )

    their_msg_words = len((their_last_text or "").split())
    their_asked_question = "?" in (their_last_text or "")
    reply_latency_hours = (
        days_since_last * 24.0 if (days_since_last is not None and not last_from_me) else None
    )
    interest = _interest(
        sentiment=sentiment,
        banter=banter,
        playful=playful,
        disinterest=disinterest,
        asked=their_asked_question,
        words=their_msg_words,
    )

    return SituationContext(
        kind="match",
        has_match=True,
        has_messages=bool(messages),
        num_messages=len(messages),
        num_their_messages=len(their),
        last_from_me=last_from_me,
        days_since_last=days_since_last,
        reply_latency_hours=reply_latency_hours,
        their_last_text=their_last_text,
        their_msg_words=their_msg_words,
        their_asked_question=their_asked_question,
        sentiment=sentiment,
        interest=interest,
        playful=playful,
        banter=banter,
        disinterest=disinterest,
        hard_stop=hard_stop,
        ready_for_date=ready,
        rapport_score=round(rapport, 2),
        reengage_after_days=reengage_after_days,
        deepen_after_messages=deepen_after_messages,
    )


def _interest(
    *,
    sentiment: str,
    banter: bool,
    playful: bool,
    disinterest: bool,
    asked: bool,
    words: int,
) -> str:
    """Coarse read of how interested the other person seems."""
    if disinterest or sentiment == "negative":
        return "low"
    if banter or (sentiment == "positive" and (asked or words >= 6)):
        return "high"
    if playful or asked or words >= 5:
        return "medium"
    return "low" if words <= 2 else "medium"


def _rapport(match: Match) -> float:
    messages = match.messages
    their = [m for m in messages if not m.from_me]
    mine = [m for m in messages if m.from_me]
    if not their:
        return 0.0
    score = min(0.5, 0.12 * len(their))
    if their and _sentiment(their[-1].text) == "positive":
        score += 0.2
    if mine and their:
        score += 0.1  # two-sided
    avg_words = sum(len((m.text or "").split()) for m in their) / len(their)
    if avg_words > 6:
        score += 0.1
    if any(_EMOJI_HINT.search(m.text or "") or _BANTER.search(m.text or "") for m in their):
        score += 0.1
    return max(0.0, min(1.0, score))


def _already_pursued(match: Match) -> bool:
    """Have we already proposed a date / asked for a number in this thread?"""
    return any(m.from_me and _DATEY.search(m.text or "") for m in match.messages)


def _number_shared(match: Match) -> bool:
    """Has a phone number / off-app handle been exchanged in this thread?"""
    return any(_NUMBER_SHARED.search(m.text or "") for m in match.messages)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
class Orchestrator:
    """Runs the OpenDate runtime loop across all matches."""

    def __init__(
        self,
        *,
        connector: MatchSource,
        router: Any,
        skills: SkillsEngine,
        persona: PersonaProfile,
        config: Any,
        safety: SafetyGuard | None = None,
        console: Console | None = None,
        interactive: bool = True,
        confirm: Callable[[str], bool] | None = None,
        store: ConversationStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.connector = connector
        self.router = router
        self.skills = skills
        self.persona = persona
        self.config = config
        self.safety = safety or SafetyGuard(
            config.safety,
            router=router,
            guidance=_skill_body(skills, "consent-and-safety"),
        )
        self.console = console or Console()
        self.interactive = interactive
        self._confirm = confirm
        # Conversation memory: in-memory by default (tests), persistent via CLI.
        self.store = store if store is not None else ConversationStore()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.style = StyleTransfer(
            router=router, guidance=_skill_body(skills, "persona-style-transfer")
        )

    @property
    def pacing(self) -> Any:
        return getattr(self.config, "pacing", None)

    @property
    def quality_cfg(self) -> Any:
        return getattr(self.config, "quality", None)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def run(self, cycles: int = 1, interval: float | None = None) -> list[PlannedAction]:
        """Run ``cycles`` loop iterations (``cycles<=0`` runs until cancelled)."""
        interval = self.config.poll_interval if interval is None else interval
        all_actions: list[PlannedAction] = []
        cycle = 0
        while cycles <= 0 or cycle < cycles:
            cycle += 1
            self.console.rule(f"[bold]OpenDate cycle {cycle}")
            actions = await self.run_once()
            all_actions.extend(actions)
            if cycles > 0 and cycle >= cycles:
                break
            await asyncio.sleep(interval)
        return all_actions

    async def run_once(self) -> list[PlannedAction]:
        actions: list[PlannedAction] = []
        now = self._clock()

        # 1) SYNC -------------------------------------------------------
        try:
            matches = await self.connector.get_matches(count=60)
        except Exception as exc:  # noqa: BLE001 - a sync failure ends the cycle cleanly
            log.warning("Could not fetch matches: %s", exc)
            matches = []
        for match in matches:
            if not match.messages:
                try:
                    match.messages = await self.connector.get_messages(match.id)
                except Exception as exc:  # noqa: BLE001 - one bad thread won't kill the loop
                    log.warning("Could not load messages for %s: %s", match.id, exc)
        recs: list[Candidate] = []
        if self.config.max_screen_per_cycle:
            try:
                recs = await self.connector.get_recommendations(
                    self.config.max_screen_per_cycle
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not fetch recommendations: %s", exc)
        log.info("Synced %d matches and %d candidates", len(matches), len(recs))

        # 2) SCREEN -----------------------------------------------------
        for candidate in recs[: self.config.max_screen_per_cycle]:
            if self._daily_budget_left(now) <= 0:
                log.info("Daily action cap reached — skipping further screening.")
                break
            try:
                action = await self._screen(candidate, now)
            except Exception as exc:  # noqa: BLE001 - isolate one bad candidate
                log.warning("Screening failed for %s: %s", candidate.id, exc)
                continue
            actions.append(action)

        # 3-7) DECIDE / GENERATE / VOICE / GUARD / ACT ------------------
        # Prioritise across matches so the per-cycle budget targets the best
        # opportunities (people waiting on us first), then act with isolation.
        prepared = [(m, *self._prepare_match(m, now)) for m in matches]
        prepared.sort(key=lambda t: t[3], reverse=True)  # by priority desc

        acted = 0
        for match, ctx, state, _priority_score in prepared:
            if acted >= self.config.max_actions_per_cycle:
                break
            try:
                action = await self._handle_match(match, ctx, state, now)
            except Exception as exc:  # noqa: BLE001 - one match never crashes the loop
                log.warning("Handling match %s failed: %s", match.id, exc)
                action = PlannedAction(
                    kind="skip",
                    target_id=match.id,
                    target_name=match.name,
                    reason=f"error: {exc}",
                    stage=state.stage.value,
                )
            actions.append(action)
            self._record_decision(action)
            if action.kind != "skip":
                acted += 1

        self._persist_state()
        self._render_summary(actions)
        return actions

    # ------------------------------------------------------------------ #
    # Prioritisation + memory
    # ------------------------------------------------------------------ #
    def _prepare_match(
        self, match: Match, now: datetime
    ) -> tuple[SituationContext, ConversationState, float]:
        """Build the situation + load/refresh persisted state for a match."""
        ctx = build_situation(
            match,
            reengage_after_days=self.config.reengage_after_days,
            deepen_after_messages=6,
        )
        state = self.store.get(match.id, match.name)
        stage = compute_stage(
            ctx,
            previous=state.stage,
            proposed_date=_already_pursued(match),
            number_shared=_number_shared(match),
        )
        ctx = replace(ctx, stage=stage.value)
        state.stage = stage
        state.message_count = ctx.num_messages
        state.last_their_text = ctx.their_last_text or state.last_their_text
        last = match.last_message
        state.last_seen_message_id = last.id if last else state.last_seen_message_id
        # Their reply clears our "unanswered follow-ups" counter.
        if ctx.has_messages and not ctx.last_from_me:
            state.followups_without_reply = 0
        state.touch(now)
        return ctx, state, self._priority(ctx)

    @staticmethod
    def _priority(ctx: SituationContext) -> float:
        """Higher = act sooner. People waiting on us rank highest."""
        if not ctx.has_messages:
            return 0.8  # fresh match — a good opener is high value
        if ctx.hard_stop:
            return 0.0
        if ctx.last_from_me:
            stalled = (ctx.days_since_last or 0) >= ctx.reengage_after_days
            return 0.5 if stalled else 0.1  # else we're just waiting (will skip)
        if ctx.ready_for_date:
            return 0.9
        if ctx.disinterest or ctx.sentiment == "negative":
            return 0.3
        base = 1.0  # their message is unanswered — top priority
        return base + (0.05 if ctx.interest == "high" else 0.0)

    def _daily_budget_left(self, now: datetime) -> int:
        cap = getattr(self.pacing, "max_daily_actions", 25) if self.pacing else 25
        return self.store.daily_budget_left(cap, now)

    def _persist_state(self) -> None:
        try:
            self.store.save()
        except Exception as exc:  # noqa: BLE001 - persistence is best-effort
            log.warning("Could not persist conversation state: %s", exc)

    # ------------------------------------------------------------------ #
    # Screening
    # ------------------------------------------------------------------ #
    async def _screen(self, candidate: Candidate, now: datetime) -> PlannedAction:
        decision, score, reasons, open_on = score_candidate(
            candidate, self.config.preferences
        )
        action = PlannedAction(
            kind=decision,
            target_id=candidate.id,
            target_name=candidate.name,
            skill="profile-screening",
            reason="; ".join(reasons),
            score=score,
            confidence=score,
        )
        if open_on:
            action.reason += f" | open on {open_on}"
        await self._act_swipe(action, candidate, now)
        return action

    async def _act_swipe(
        self, action: PlannedAction, candidate: Candidate, now: datetime
    ) -> None:
        verb = "Like" if action.kind == "like" else "Pass on"
        if self.config.auto_send:
            await self._execute_swipe(action, now)
            return
        # Human-in-the-loop: passes are low-risk, auto-skip the prompt for them.
        if action.kind == "pass":
            log.info("Proposed pass on %s (%s)", candidate.name, action.reason)
            return
        self.console.print(
            Panel(
                f"[bold]{verb} {candidate.name or candidate.id}[/]\n"
                f"score={action.score}  •  {action.reason}",
                title="Screen (proposed)",
                border_style="cyan",
            )
        )
        if self.interactive and self._ask(f"{verb} {candidate.name}?"):
            await self._execute_swipe(action, now)

    async def _execute_swipe(self, action: PlannedAction, now: datetime) -> None:
        try:
            if action.kind == "like":
                await self.connector.like(action.target_id)
            else:
                await self.connector.pass_(action.target_id)
            action.sent = True
            self.store.record_action(now)
            log.info("%s %s", action.kind, action.target_name or action.target_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("Swipe failed for %s: %s", action.target_id, exc)

    # ------------------------------------------------------------------ #
    # Per-match messaging
    # ------------------------------------------------------------------ #
    async def _handle_match(
        self,
        match: Match,
        ctx: SituationContext,
        state: ConversationState,
        now: datetime,
    ) -> PlannedAction:
        should, why = self._should_message(match, ctx)
        if not should:
            state.last_action = "skip"
            state.last_decision_reason = why
            return PlannedAction(
                kind="skip",
                target_id=match.id,
                target_name=match.name,
                reason=why,
                stage=state.stage.value,
            )

        # Pacing / rate-limit gate (cooldown, daily cap, over-eager follow-ups).
        pace = self._check_pace(state, now)
        if pace is not None and pace.blocked:
            reason = "; ".join(pace.reasons)
            state.last_action = "skip"
            state.last_decision_reason = reason
            return PlannedAction(
                kind="skip",
                target_id=match.id,
                target_name=match.name,
                reason=reason,
                stage=state.stage.value,
            )

        selection = self.skills.select(ctx, router=self.router)
        voiced, critique = await self._generate_quality(match, ctx, selection, state)

        action = PlannedAction(
            kind="send",
            target_id=match.id,
            target_name=match.name,
            skill=selection.primary.name,
            text=voiced,
            reason=selection.reason,
            stage=state.stage.value,
            confidence=selection.confidence,
            quality=critique.score,
        )

        if not voiced:
            action.kind = "skip"
            action.reason = "generation produced nothing — skipping"
            state.last_action = "skip"
            state.last_decision_reason = action.reason
            return action

        # Never send the same line twice.
        if state.is_repeat(voiced):
            action.kind = "skip"
            action.blocked = True
            action.block_reason = "would repeat an earlier message"
            state.last_action = "skip"
            state.last_decision_reason = action.block_reason
            log.info("Skipping near-duplicate message to %s", match.name)
            return action

        # Blocking safety gate — every send must pass.
        decision = self.safety.check_message(voiced, ctx)
        if decision.blocked:
            action.kind = "backoff" if decision.severity != "hard" else "blocked"
            action.blocked = True
            action.block_reason = "; ".join(decision.reasons)
            state.last_action = action.kind
            state.last_decision_reason = action.block_reason
            log.info(
                "Guard %s message to %s: %s",
                action.kind,
                match.name,
                action.block_reason,
            )
            return action

        await self._maybe_send(action, match, state, now)
        state.last_action = action.kind
        state.last_skill = action.skill
        state.last_decision_reason = action.reason
        return action

    def _check_pace(self, state: ConversationState, now: datetime):
        if not self.pacing:
            return None
        cooldown_remaining = state.cooldown_remaining(
            getattr(self.pacing, "cooldown_hours", 0.0), now
        )
        return self.safety.check_pacing(
            cooldown_remaining=cooldown_remaining,
            followups_without_reply=state.followups_without_reply,
            daily_budget_left=self._daily_budget_left(now),
        )

    def _should_message(self, match: Match, ctx: SituationContext) -> tuple[bool, str]:
        if not ctx.has_messages:
            return True, "fresh match — time for an opener"
        if ctx.hard_stop:
            return False, "they asked to stop — backing off"
        if ctx.last_from_me:
            never_double = getattr(self.pacing, "never_double_text", True) if self.pacing else True
            if (ctx.days_since_last or 0) >= ctx.reengage_after_days:
                return True, f"stalled ~{ctx.days_since_last:.0f}d — re-engage"
            if never_double:
                return False, "waiting on their reply (won't double-text)"
            return True, "following up"
        return True, "their message is unanswered"

    # ------------------------------------------------------------------ #
    # Generation + self-critique
    # ------------------------------------------------------------------ #
    async def _generate_quality(
        self,
        match: Match,
        ctx: SituationContext,
        selection: SkillSelection,
        state: ConversationState,
    ) -> tuple[str, Any]:
        """Generate → voice → self-critique, regenerating once if it's weak."""
        q = self.quality_cfg
        self_critique = getattr(q, "self_critique", True) if q else True
        min_score = getattr(q, "min_score", 0.5) if q else 0.5
        max_regen = getattr(q, "max_regenerations", 1) if q else 1
        avoid = list(state.outgoing_history)
        reference = ((ctx.their_last_text or "") + " " + (match.bio or "")).strip()

        attempts = 1 + (max_regen if self_critique else 0)
        feedback = ""
        best: tuple[str, Any] | None = None
        for attempt in range(attempts):
            draft = await self._generate(
                match, ctx, selection, feedback=feedback, avoid=avoid
            )
            voiced = self.style.transfer(draft, self.persona) if draft else ""
            crit = critique_message(
                voiced,
                ctx=ctx,
                persona=self.persona,
                state=state,
                skill=selection.primary.name,
                reference_text=reference,
                min_score=min_score,
                router=self.router,
            )
            if best is None or crit.score > best[1].score:
                best = (voiced, crit)
            if crit.passed or not self_critique:
                break
            feedback = crit.feedback
            if attempt + 1 < attempts:
                log.info("Regenerating reply to %s (%s)", match.name, crit.as_log())
        return best if best is not None else ("", None)

    async def _generate(
        self,
        match: Match,
        ctx: SituationContext,
        selection: SkillSelection,
        *,
        feedback: str = "",
        avoid: list[str] | None = None,
    ) -> str:
        system = self._system_prompt(selection, ctx)
        user = self._user_prompt(match, ctx, selection, feedback=feedback, avoid=avoid)
        try:
            result = await self.router.acomplete(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]
            )
            return result.text.strip()
        except Exception as exc:  # noqa: BLE001 - never let one draft crash the loop
            log.warning("Generation failed for %s: %s", match.name, exc)
            return ""

    def _system_prompt(self, selection: SkillSelection, ctx: SituationContext) -> str:
        prefs = self.config.preferences
        parts = [
            "You are helping the user write the next message on a dating app. "
            "Write ONLY the message text — no preamble, no quotes, no explanation. "
            "Keep it natural, concise, and human.",
            # Hints the offline stub reads; harmless to a real model.
            f"PRIMARY_SKILL: {selection.primary.name}",
            f"STAGE: {ctx.stage or 'unknown'}",
            "Active skills (playbooks below): " + ", ".join(selection.skill_names),
            selection.combined_playbook(),
            "User preferences:\n" + self._preferences_brief(),
            "Write in this person's voice:\n" + self.persona.style_brief(),
            self._quality_rules(ctx),
            "Hard rule: be honest, respectful, and never pressure anyone. If they "
            "seem uninterested, ease off.",
        ]
        exemplars = self.persona.exemplar_block()
        if exemplars:
            parts.append(
                "Examples of how the user actually texts (mimic the sound, not the "
                "content):\n" + exemplars
            )
        intent = getattr(prefs, "looking_for", None)
        if intent is not None:
            parts.append(f"Relationship intent: {getattr(intent, 'value', intent)}")
        return "\n\n".join(parts)

    @staticmethod
    def _quality_rules(ctx: SituationContext) -> str:
        rules = [
            "Quality bar:",
            "- Reference something specific they said or showed — never generic.",
            "- Match their message length and energy; mirror their emoji use.",
            "- Don't repeat anything already said in the thread.",
            "- Sound like a real person, not a chatbot. No pick-up lines.",
        ]
        if ctx.their_asked_question:
            rules.append("- They asked something — answer it, then keep it flowing.")
        if ctx.num_messages and not ctx.their_asked_question:
            rules.append("- End with one easy, specific question when it feels natural.")
        return "\n".join(rules)

    def _user_prompt(
        self,
        match: Match,
        ctx: SituationContext,
        selection: SkillSelection,
        *,
        feedback: str = "",
        avoid: list[str] | None = None,
    ) -> str:
        lines = [f"RECIPIENT: {match.name or 'your match'}"]
        if match.bio:
            lines.append(f"Their bio: {match.bio}")
        lines.append(f"Situation: {selection.reason}")
        if ctx.has_messages:
            lines.append("\nConversation so far (oldest first):")
            lines.append(self._conversation_block(match))
            if ctx.their_last_text:
                lines.append(f'\nTheir latest message: "{ctx.their_last_text}"')
        else:
            lines.append("\nThere are no messages yet — this is the opener.")
        if avoid:
            recent = " | ".join(avoid[-5:])
            lines.append(f"\nDo NOT repeat or paraphrase these earlier lines: {recent}")
        if feedback:
            lines.append(
                f"\nThe previous draft was weak ({feedback}). Fix those issues."
            )
        lines.append(
            "\nWrite the single next message to send"
            + (" them." if match.name else ".")
        )
        return "\n".join(lines)

    def _conversation_block(self, match: Match, limit: int = 12) -> str:
        rows = []
        for msg in match.messages[-limit:]:
            who = "You" if msg.from_me else (match.name or "Them")
            rows.append(f"{who}: {msg.text}")
        return "\n".join(rows)

    def _preferences_brief(self) -> str:
        p = self.config.preferences
        intent = getattr(p, "looking_for", "")
        intent = getattr(intent, "value", intent)
        bits = [f"looking for: {intent}"]
        if p.partner_traits:
            bits.append("drawn to: " + ", ".join(p.partner_traits))
        if p.dealbreakers:
            bits.append("dealbreakers: " + ", ".join(p.dealbreakers))
        if p.interests:
            bits.append("interests: " + ", ".join(p.interests))
        bits.append(f"age {p.age_range.min}-{p.age_range.max}, within {p.distance_km}km")
        if p.voice:
            bits.append(f"voice: {p.voice}")
        return "; ".join(bits)

    # ------------------------------------------------------------------ #
    # Acting (with human-in-the-loop)
    # ------------------------------------------------------------------ #
    async def _maybe_send(
        self,
        action: PlannedAction,
        match: Match,
        state: ConversationState,
        now: datetime,
    ) -> None:
        if self.config.auto_send:
            await self._execute_send(action, match, state, now)
            return
        meta = f"stage: {action.stage} · skill: {action.skill}"
        if action.quality is not None:
            meta += f" · quality: {action.quality:.2f}"
        self.console.print(
            Panel(
                f"[bold]To {match.name or match.id}[/]  [dim]({meta})[/]\n"
                f"[dim]{action.reason}[/]\n\n{action.text}",
                title="Proposed message (not sent)",
                border_style="green",
            )
        )
        if self.interactive and self._ask(f"Send this to {match.name}?"):
            await self._execute_send(action, match, state, now)

    async def _execute_send(
        self,
        action: PlannedAction,
        match: Match,
        state: ConversationState,
        now: datetime,
    ) -> None:
        try:
            await self.connector.send_message(match.id, action.text or "")
            action.sent = True
            state.record_outgoing(action.text or "", skill=action.skill, now=now)
            state.followups_without_reply += 1
            self.store.record_action(now)
            log.info("Sent to %s (%s): %s", match.name, action.skill, action.text)
        except Exception as exc:  # noqa: BLE001
            log.warning("Send failed for %s: %s", match.name, exc)

    def _ask(self, prompt: str) -> bool:
        if self._confirm is not None:
            return self._confirm(prompt)
        if not self.interactive:
            return False
        from rich.prompt import Confirm

        return Confirm.ask(prompt, default=False, console=self.console)

    # ------------------------------------------------------------------ #
    # Reporting
    # ------------------------------------------------------------------ #
    def _render_summary(self, actions: list[PlannedAction]) -> None:
        if not actions:
            self.console.print("[dim]No actions this cycle.[/]")
            return
        dry_run = not self.config.auto_send
        title = "Cycle plan (dry-run — nothing sent)" if dry_run else "Cycle summary"
        table = Table(title=title, show_lines=False)
        table.add_column("Action")
        table.add_column("Who")
        table.add_column("Stage")
        table.add_column("Skill")
        table.add_column("Q", justify="right")
        table.add_column("Status")
        table.add_column("Detail", overflow="fold", max_width=52)
        for a in actions:
            if a.sent:
                status = "[green]sent[/]"
            elif a.blocked:
                status = "[red]blocked[/]"
            elif a.kind == "skip":
                status = "[dim]skipped[/]"
            else:
                status = "[yellow]proposed[/]"
            detail = a.block_reason or a.text or a.reason
            table.add_row(
                a.kind,
                a.target_name or a.target_id,
                a.stage or "-",
                a.skill or "-",
                f"{a.quality:.2f}" if a.quality is not None else "-",
                status,
                (detail or "")[:200],
            )
        self.console.print(table)
        if dry_run:
            proposed = sum(1 for a in actions if a.kind in {"send", "like"} and not a.sent)
            self.console.print(
                f"[dim]Dry-run: {proposed} action(s) proposed. "
                "Re-run with --auto-send (or approve interactively) to act.[/]"
            )

    # ------------------------------------------------------------------ #
    # Structured decision logging
    # ------------------------------------------------------------------ #
    def _record_decision(self, action: PlannedAction) -> None:
        """Log every decision (structured) and append to a JSONL audit trail."""
        log.info(
            "decision target=%s stage=%s kind=%s skill=%s conf=%s quality=%s sent=%s",
            action.target_name or action.target_id,
            action.stage or "-",
            action.kind,
            action.skill or "-",
            action.confidence,
            action.quality,
            action.sent,
        )
        # Only write a file when the store is persistent (keeps tests clean).
        if getattr(self.store, "path", None) is None:
            return
        path = None
        try:
            path = self.config.decisions_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(action.to_record()) + "\n")
        except Exception as exc:  # noqa: BLE001 - audit log is best-effort
            log.debug("Could not append decision to %s: %s", path, exc)


def _skill_body(skills: SkillsEngine, name: str) -> str:
    skill = skills.get_or_none(name)
    return skill.body if skill else ""
