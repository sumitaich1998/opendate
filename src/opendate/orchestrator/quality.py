"""Message quality control — a lightweight self-critique pass.

After a draft is generated and re-voiced, OpenDate scores it before proposing
or sending. The goal is to catch the things that make AI dating messages feel
*off*: genericness, pick-up-line cringe, repeating yourself, energy/length
mismatch, interview-mode over-questioning, and safety smells.

The critic is deterministic (works offline, used in tests) and can optionally
be sharpened by an LLM reviewer. If a draft scores below the configured
threshold, the orchestrator regenerates once with the feedback folded into the
prompt and keeps the better attempt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..persona.analyze import PersonaProfile
    from ..skills.engine import SituationContext
    from .state import ConversationState

__all__ = ["MessageCritique", "critique_message", "SKILLS_EXPECTING_QUESTION"]

log = get_logger("orchestrator.quality")

# Skills where ending without an inviting question usually falls flat.
SKILLS_EXPECTING_QUESTION = {
    "opener",
    "approaching",
    "rapport-building",
    "re-engagement",
    "conversation-recovery",
}

_EMOJI_RE = re.compile(
    "[\U0001f300-\U0001fAFF\U00002600-\U000027BF\U0001f1e6-\U0001f1ff]"
)

_GENERIC = re.compile(
    r"\b(tell me more|how'?s your day|how is your day|how are you doing|"
    r"how'?s it going|how is it going|what'?s up|whats up|nice to meet you|"
    r"what do you do for fun|got any (?:fun )?plans|sounds good|that'?s cool|"
    r"thats cool|just wanted to say hi|get to know (?:you|each other) better|"
    r"hope you'?re having a good)\b",
    re.IGNORECASE,
)

_CRINGE = re.compile(
    r"\b(did it hurt when you fell|from heaven|are you a magician|"
    r"running through my mind|brings all the boys|wifi|"
    r"hey (?:beautiful|gorgeous|sexy|cutie)|marry me|"
    r"you'?re the most beautiful (?:woman|girl|person))\b",
    re.IGNORECASE,
)

_PRESSURE = re.compile(
    r"\b(come on|don'?t ignore me|you owe me|just give me your number|"
    r"why won'?t you|you have to|stop playing)\b",
    re.IGNORECASE,
)

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for", "is",
    "are", "was", "im", "i", "you", "your", "youre", "me", "my", "we", "they",
    "it", "its", "this", "that", "do", "did", "does", "have", "has", "so",
    "just", "with", "as", "at", "not", "no", "yes", "ok", "okay", "what", "how",
    "when", "where", "why", "who", "can", "will", "would", "should", "could",
    "get", "got", "go", "going", "like", "really", "very", "too", "all", "by",
    "be", "been", "about", "if", "then", "than", "out", "up", "one", "from",
    "into", "more", "some", "any", "what's", "lets", "let", "make", "want",
}


@dataclass
class MessageCritique:
    """Verdict on a drafted message."""

    score: float
    passed: bool
    issues: list[str] = field(default_factory=list)
    feedback: str = ""

    def as_log(self) -> str:
        tag = "ok" if self.passed else "weak"
        return f"quality={self.score:.2f} ({tag})" + (
            f": {'; '.join(self.issues)}" if self.issues else ""
        )


def _content_words(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def critique_message(
    text: str,
    *,
    ctx: "SituationContext | None" = None,
    persona: "PersonaProfile | None" = None,
    state: "ConversationState | None" = None,
    skill: str | None = None,
    reference_text: str = "",
    min_score: float = 0.5,
    router: Any | None = None,
) -> MessageCritique:
    """Score ``text`` for genericness / cringe / repetition / fit (0..1)."""
    issues: list[str] = []
    score = 1.0
    stripped = (text or "").strip()
    words = stripped.split()
    n = len(words)

    if n == 0:
        return MessageCritique(0.0, False, ["empty draft"], "Write an actual message.")
    if n < 3:
        score -= 0.35
        issues.append("too short / low-effort")

    if _GENERIC.search(stripped):
        score -= 0.45
        issues.append("generic / low-effort phrasing")
    if _CRINGE.search(stripped):
        score -= 0.6
        issues.append("cringe / pick-up-line vibe")
    if _PRESSURE.search(stripped):
        score -= 0.45
        issues.append("reads as pushy")

    # Repeating ourselves is a fast way to look like a bot.
    if state is not None and state.is_repeat(stripped):
        score -= 0.55
        issues.append("repeats an earlier message")

    # Interview energy: a wall of questions.
    if stripped.count("?") >= 3:
        score -= 0.2
        issues.append("too many questions (interview energy)")

    # Energy / length mirroring against their last message.
    their_words = ctx.their_msg_words if ctx else 0
    if their_words:
        if n > max(40, their_words * 3):
            score -= 0.2
            issues.append("much longer than their message")
        elif their_words >= 6 and n <= 2:
            score -= 0.2
            issues.append("too curt vs their message")

    # Should this skill be asking something?
    expects_q = (skill in SKILLS_EXPECTING_QUESTION) if skill else False
    if expects_q and "?" not in stripped:
        score -= 0.15
        issues.append("no question to keep it going")

    # Specificity / anti-generic: does it reference anything concrete they said?
    ref = reference_text or (ctx.their_last_text if ctx else "") or ""
    if ref:
        shared = _content_words(stripped) & _content_words(ref)
        if shared:
            score += 0.1  # rewarded for grounding in their words
        elif _GENERIC.search(stripped):
            score -= 0.1
            issues.append("not grounded in anything specific")

    # Emoji habit mismatch (style transfer should handle, but flag it).
    if persona is not None and persona.emoji_rate < 0.1 and _EMOJI_RE.search(stripped):
        score -= 0.1
        issues.append("emoji unlike the user's style")

    score = max(0.0, min(1.0, score))

    # Optional LLM sharpening (best-effort; never raises).
    if (
        router is not None
        and not getattr(router, "is_stub", False)
        and score >= min_score  # only spend a call on borderline-or-better drafts
    ):
        llm = _llm_critique(text, ref, router)
        if llm is not None:
            score = min(score, llm[0])
            issues.extend(llm[1])

    feedback = "; ".join(issues) if issues else ""
    return MessageCritique(
        score=round(score, 2),
        passed=score >= min_score,
        issues=issues,
        feedback=feedback,
    )


def _llm_critique(
    text: str, reference: str, router: Any
) -> tuple[float, list[str]] | None:
    system = (
        "You rate a dating-app reply for quality. Consider genericness, "
        "authenticity, whether it's grounded in the conversation, and respect. "
        'Respond ONLY with JSON: {"score": 0.0-1.0, "issues": [..]}.'
    )
    user = f"Their last message: {reference!r}\nProposed reply: {text!r}"
    try:
        data = router.chat_json(system, user, temperature=0.0, max_tokens=150)
    except Exception as exc:  # noqa: BLE001 - critique is best-effort
        log.debug("LLM critique skipped: %s", exc)
        return None
    if not isinstance(data, dict) or "score" not in data:
        return None
    try:
        score = float(data["score"])
    except (TypeError, ValueError):
        return None
    raw_issues = data.get("issues") or []
    issues = [str(i) for i in raw_issues if i] if isinstance(raw_issues, list) else []
    return max(0.0, min(1.0, score)), issues
