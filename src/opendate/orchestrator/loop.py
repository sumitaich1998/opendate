"""The runtime loop: Sync -> Screen -> Decide -> Generate -> Voice -> Guard -> Act.

The :class:`Orchestrator` schedules actions across all matches each cycle. It is
fully async and connector-agnostic, so the same loop runs against real Tinder or
the offline mock. Risky steps are gated by the :class:`SafetyGuard` and, when
``auto_send`` is off, by human confirmation (human-in-the-loop).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
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
from .safety import SafetyGuard

__all__ = ["Orchestrator", "PlannedAction", "build_situation", "score_candidate"]

log = get_logger("orchestrator.loop")

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
    """Return ``(decision, score, reasons, open_on)`` for a candidate."""
    reasons: list[str] = []
    text = f"{candidate.bio} {' '.join(candidate.interests)}".lower()

    dealbreakers = [d.lower() for d in getattr(preferences, "dealbreakers", [])]
    for db in dealbreakers:
        if _term_in_text(db, text):
            return "pass", 0.0, [f"dealbreaker present: {db}"], None

    score = 0.5

    age_range = getattr(preferences, "age_range", None)
    if age_range is not None and candidate.age is not None:
        if age_range.contains(candidate.age):
            score += 0.1
            reasons.append("age in range")
        else:
            score -= 0.2
            reasons.append("age outside range")

    max_dist = getattr(preferences, "distance_km", None)
    if max_dist is not None and candidate.distance_km is not None:
        if candidate.distance_km <= max_dist:
            score += 0.1
        elif candidate.distance_km > max_dist * 1.5:
            score -= 0.15
            reasons.append("far away")

    traits = [t.lower() for t in getattr(preferences, "partner_traits", [])]
    trait_hits = [t for t in traits if t and t in text]
    if trait_hits:
        score += min(0.24, 0.08 * len(trait_hits))
        reasons.append("traits: " + ", ".join(trait_hits))

    interests = [i.lower() for i in getattr(preferences, "interests", [])]
    cand_interests = {i.lower() for i in candidate.interests}
    shared = [i for i in interests if i in cand_interests or i in text]
    if shared:
        score += min(0.15, 0.05 * len(shared))
        reasons.append("shared: " + ", ".join(shared))

    if candidate.bio.strip():
        score += 0.1
    else:
        score -= 0.05
        reasons.append("empty bio")

    score = max(0.0, min(1.0, score))
    decision = "like" if score >= 0.55 else "pass"

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

    return SituationContext(
        kind="match",
        has_match=True,
        has_messages=bool(messages),
        num_messages=len(messages),
        last_from_me=last_from_me,
        days_since_last=days_since_last,
        their_last_text=their_last_text,
        sentiment=sentiment,
        playful=playful,
        banter=banter,
        disinterest=disinterest,
        hard_stop=hard_stop,
        ready_for_date=ready,
        rapport_score=round(rapport, 2),
        reengage_after_days=reengage_after_days,
        deepen_after_messages=deepen_after_messages,
    )


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
        self.style = StyleTransfer(
            router=router, guidance=_skill_body(skills, "persona-style-transfer")
        )

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

        # 1) SYNC -------------------------------------------------------
        matches = await self.connector.get_matches(count=60)
        for match in matches:
            if not match.messages:
                try:
                    match.messages = await self.connector.get_messages(match.id)
                except Exception as exc:  # noqa: BLE001 - one bad thread shouldn't kill the loop
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
            action = await self._screen(candidate)
            actions.append(action)

        # 3-7) DECIDE / GENERATE / VOICE / GUARD / ACT ------------------
        acted = 0
        for match in matches:
            if acted >= self.config.max_actions_per_cycle:
                break
            action = await self._handle_match(match)
            actions.append(action)
            if action.kind != "skip":
                acted += 1

        self._render_summary(actions)
        return actions

    # ------------------------------------------------------------------ #
    # Screening
    # ------------------------------------------------------------------ #
    async def _screen(self, candidate: Candidate) -> PlannedAction:
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
        )
        if open_on:
            action.reason += f" | open on {open_on}"
        await self._act_swipe(action, candidate)
        return action

    async def _act_swipe(self, action: PlannedAction, candidate: Candidate) -> None:
        verb = "Like" if action.kind == "like" else "Pass on"
        if self.config.auto_send:
            await self._execute_swipe(action)
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
            await self._execute_swipe(action)

    async def _execute_swipe(self, action: PlannedAction) -> None:
        try:
            if action.kind == "like":
                await self.connector.like(action.target_id)
            else:
                await self.connector.pass_(action.target_id)
            action.sent = True
            log.info("%s %s", action.kind, action.target_name or action.target_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("Swipe failed for %s: %s", action.target_id, exc)

    # ------------------------------------------------------------------ #
    # Per-match messaging
    # ------------------------------------------------------------------ #
    async def _handle_match(self, match: Match) -> PlannedAction:
        ctx = build_situation(
            match,
            reengage_after_days=getattr(self.config, "reengage_after_days", 3.0),
            deepen_after_messages=6,
        )
        should, why = self._should_message(match, ctx)
        if not should:
            return PlannedAction(
                kind="skip",
                target_id=match.id,
                target_name=match.name,
                reason=why,
            )

        selection = self.skills.select(ctx)
        draft = await self._generate(match, ctx, selection)
        voiced = self.style.transfer(draft, self.persona)

        decision = self.safety.check_message(voiced, ctx)
        action = PlannedAction(
            kind="send",
            target_id=match.id,
            target_name=match.name,
            skill=selection.primary.name,
            text=voiced,
            reason=selection.reason,
        )
        if decision.blocked:
            action.kind = "backoff" if decision.severity != "hard" else "blocked"
            action.blocked = True
            action.block_reason = "; ".join(decision.reasons)
            log.info(
                "Guard %s message to %s: %s",
                action.kind,
                match.name,
                action.block_reason,
            )
            return action

        await self._maybe_send(action, match)
        return action

    def _should_message(self, match: Match, ctx: SituationContext) -> tuple[bool, str]:
        if not ctx.has_messages:
            return True, "fresh match — time for an opener"
        if ctx.hard_stop:
            return False, "they asked to stop — backing off"
        if ctx.last_from_me:
            if (ctx.days_since_last or 0) >= ctx.reengage_after_days:
                return True, f"stalled ~{ctx.days_since_last:.0f}d — re-engage"
            return False, "waiting on their reply (won't double-text)"
        return True, "their message is unanswered"

    async def _generate(
        self, match: Match, ctx: SituationContext, selection: SkillSelection
    ) -> str:
        system = self._system_prompt(selection, ctx)
        user = self._user_prompt(match, ctx, selection)
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
            "Active skills (playbooks below): " + ", ".join(selection.skill_names),
            selection.combined_playbook(),
            "User preferences:\n" + self._preferences_brief(),
            "Write in this person's voice:\n" + self.persona.style_brief(),
            "Hard rule: be honest, respectful, and never pressure anyone. If they "
            "seem uninterested, ease off.",
        ]
        intent = getattr(prefs, "looking_for", None)
        if intent is not None:
            parts.append(f"Relationship intent: {getattr(intent, 'value', intent)}")
        return "\n\n".join(parts)

    def _user_prompt(
        self, match: Match, ctx: SituationContext, selection: SkillSelection
    ) -> str:
        lines = [f"RECIPIENT: {match.name or 'your match'}"]
        if match.bio:
            lines.append(f"Their bio: {match.bio}")
        lines.append(f"Situation: {selection.reason}")
        if ctx.has_messages:
            lines.append("\nConversation so far (oldest first):")
            lines.append(self._conversation_block(match))
        else:
            lines.append("\nThere are no messages yet — this is the opener.")
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
    async def _maybe_send(self, action: PlannedAction, match: Match) -> None:
        if self.config.auto_send:
            await self._execute_send(action, match)
            return
        self.console.print(
            Panel(
                f"[bold]To {match.name or match.id}[/]  "
                f"[dim](skill: {action.skill})[/]\n"
                f"[dim]{action.reason}[/]\n\n{action.text}",
                title="Proposed message (not sent)",
                border_style="green",
            )
        )
        if self.interactive and self._ask(f"Send this to {match.name}?"):
            await self._execute_send(action, match)

    async def _execute_send(self, action: PlannedAction, match: Match) -> None:
        try:
            await self.connector.send_message(match.id, action.text or "")
            action.sent = True
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
        table = Table(title="Cycle summary", show_lines=False)
        table.add_column("Action")
        table.add_column("Who")
        table.add_column("Skill")
        table.add_column("Status")
        table.add_column("Detail", overflow="fold", max_width=60)
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
                a.skill or "-",
                status,
                (detail or "")[:200],
            )
        self.console.print(table)


def _skill_body(skills: SkillsEngine, name: str) -> str:
    skill = skills.get_or_none(name)
    return skill.body if skill else ""
