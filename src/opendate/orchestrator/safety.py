"""The consent & safety guard — enforced before *every* send.

This is the code that backs the ``consent-and-safety`` skill. It is intentionally
deterministic (keyword/heuristic rules) so it works fully offline and is testable
without a network. When a real LLM is available it can add a second review pass,
but the heuristic rules are authoritative: if they block, it stays blocked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..utils.logging import get_logger

__all__ = ["SafetyDecision", "SafetyGuard"]

log = get_logger("orchestrator.safety")


# Clearly explicit/sexual terms. Blocked unless the user allows explicit content
# AND the other person clearly invited it (the latter is enforced upstream).
_EXPLICIT = re.compile(
    r"\b(nudes?|sext(?:ing)?|horny|h[o0]rny|send\s+pics|dick\s+pic|"
    r"netflix\s+and\s+chill|hook\s*up\s+tonight|naked|aroused)\b",
    re.IGNORECASE,
)

# Coercion / pressure phrasing.
_PRESSURE = re.compile(
    r"\b(come\s+on|don'?t\s+be\s+like\s+that|why\s+won'?t\s+you|you\s+owe\s+me|"
    r"stop\s+playing|don'?t\s+ignore\s+me|you\s+have\s+to|i\s+insist|"
    r"just\s+give\s+me\s+your\s+number|just\s+send|you\s+should\s+be\s+grateful)\b",
    re.IGNORECASE,
)

# Hostility / disrespect.
_HOSTILE = re.compile(
    r"\b(idiot|stupid|loser|ugly|shut\s+up|pathetic|whore|slut|bitch|"
    r"worthless|disgusting)\b",
    re.IGNORECASE,
)

# Crude deception markers (best-effort; honesty is mainly enforced by intent).
_DECEPTION = re.compile(
    r"\b(i'?m\s+a\s+(millionaire|model|doctor)\s+btw|trust\s+me\s+i'?m|"
    r"i\s+swear\s+i'?m\s+not\s+lying|this\s+isn'?t\s+a\s+scam)\b",
    re.IGNORECASE,
)

# The other person clearly asking to stop / not interested (hard back-off).
_HARD_STOP = re.compile(
    r"\b(not\s+interested|please\s+stop|stop\s+messaging|leave\s+me\s+alone|"
    r"don'?t\s+message\s+me|i'?m\s+not\s+comfortable|no\s+thank\s*you)\b",
    re.IGNORECASE,
)

# The other person inviting escalation (used to permit allowed explicit content).
_INVITE = re.compile(
    r"\b(send\s+me|i\s+want\s+you|come\s+over|let'?s\s+(?:meet|hook)|"
    r"i'?m\s+into\s+you)\b",
    re.IGNORECASE,
)


@dataclass
class SafetyDecision:
    """The verdict for a proposed message/action."""

    allowed: bool
    severity: str = "ok"  # "ok" | "soft" | "hard"
    reasons: list[str] = field(default_factory=list)
    revised_text: str | None = None

    @property
    def blocked(self) -> bool:
        return not self.allowed


class SafetyGuard:
    """Runs consent/safety checks before anything is sent."""

    def __init__(
        self,
        config: "SafetyConfigLike",
        router: Any | None = None,
        guidance: str = "",
    ) -> None:
        self.config = config
        self.router = router
        self.guidance = guidance

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def check_message(self, text: str, context: Any | None = None) -> SafetyDecision:
        """Check a proposed outgoing message. Heuristics are authoritative."""
        reasons: list[str] = []
        text = text or ""

        allow_explicit = getattr(self.config, "allow_explicit", False)
        backoff = getattr(self.config, "backoff_on_disinterest", True)

        # 1) Hostility -> always a hard block.
        if _HOSTILE.search(text):
            return SafetyDecision(
                allowed=False,
                severity="hard",
                reasons=["Message contains hostile or demeaning language."],
            )

        # 2) Deception markers -> hard block.
        if _DECEPTION.search(text):
            return SafetyDecision(
                allowed=False,
                severity="hard",
                reasons=["Message appears deceptive; OpenDate must stay honest."],
            )

        # 3) Explicit content -> blocked unless allowed AND clearly invited.
        if _EXPLICIT.search(text):
            invited = bool(context and getattr(context, "their_last_text", None) and
                           _INVITE.search(context.their_last_text or ""))
            if not (allow_explicit and invited):
                return SafetyDecision(
                    allowed=False,
                    severity="hard",
                    reasons=[
                        "Explicit content blocked (not allowed and/or not clearly "
                        "consented to)."
                    ],
                )

        # 4) Pressure / coercion -> soft block (don't send; needs a rewrite).
        if _PRESSURE.search(text):
            reasons.append("Message reads as pressuring; easing off instead.")
            return SafetyDecision(allowed=False, severity="soft", reasons=reasons)

        # 5) Back off on disinterest from the other person.
        if context is not None and backoff:
            if getattr(context, "hard_stop", False):
                return SafetyDecision(
                    allowed=False,
                    severity="hard",
                    reasons=["They asked to stop / aren't interested — backing off."],
                )
            if getattr(context, "disinterest", False):
                return SafetyDecision(
                    allowed=False,
                    severity="soft",
                    reasons=["Signs of disinterest — backing off rather than pushing."],
                )

        # 6) Optional LLM second-pass review (only refines; never un-blocks above).
        if (
            getattr(self.config, "require_consent_checks", True)
            and self.router is not None
            and not getattr(self.router, "is_stub", False)
        ):
            verdict = self._llm_review(text, context)
            if verdict is not None and not verdict.allowed:
                return verdict

        return SafetyDecision(allowed=True, severity="ok", reasons=reasons or ["ok"])

    # ------------------------------------------------------------------ #
    # Optional LLM review
    # ------------------------------------------------------------------ #
    def _llm_review(self, text: str, context: Any | None) -> SafetyDecision | None:
        import json

        system = (
            "You are a dating-safety reviewer. Decide if a message to send is "
            "honest, respectful, non-coercive, and consensual. Respond ONLY with "
            "JSON: {\"allowed\": bool, \"reason\": string}."
        )
        if self.guidance:
            system += "\n\nPolicy:\n" + self.guidance
        their = getattr(context, "their_last_text", None) if context else None
        user = f"Their last message: {their!r}\nProposed reply: {text!r}"
        try:
            raw = self.router.chat(system, user, temperature=0.0, max_tokens=200)
        except Exception as exc:  # noqa: BLE001 - review is best-effort
            log.debug("Safety LLM review skipped: %s", exc)
            return None
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        if data.get("allowed") is False:
            return SafetyDecision(
                allowed=False,
                severity="soft",
                reasons=[str(data.get("reason", "Flagged by safety review."))],
            )
        return SafetyDecision(allowed=True, severity="ok", reasons=["llm: ok"])


# Structural typing only.
class SafetyConfigLike:  # pragma: no cover - typing only
    require_consent_checks: bool
    allow_explicit: bool
    backoff_on_disinterest: bool
    max_followups_without_reply: int
