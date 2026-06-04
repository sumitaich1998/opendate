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

# Discomfort / withdrawal signals — back off even if not a hard "stop".
_DISCOMFORT = re.compile(
    r"\b(uncomfortable|creep(?:y|er)?|you'?re\s+being\s+weird|this\s+is\s+weird|"
    r"too\s+much|reporting\s+you|i'?ll\s+report|i\s+blocked|gonna\s+block|"
    r"i\s+have\s+a\s+(?:boyfriend|girlfriend|partner|husband|wife)|"
    r"back\s+off|stop\s+being\s+weird)\b",
    re.IGNORECASE,
)

# Signals the other person may be a minor (hard block when refuse_minors).
_MINOR = re.compile(
    r"\b(?:i'?m|i\s+am|im|only|turning|just\s+turned)\s*(1[0-7])\b"
    r"|\b(1[0-7])\s*(?:yo|y/?o|years?\s*old)\b"
    r"|\b(underage|under\s*18|jailbait|high\s*school(?:er)?|highschool|"
    r"middle\s*school(?:er)?)\b",
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
    category: str = ""  # e.g. minor | explicit | pressure | discomfort | cooldown

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
        """Check a proposed outgoing message. Heuristics are authoritative.

        This is a *blocking gate*: every send must pass it. Each block is logged
        with its reason and category for an auditable trail.
        """
        text = text or ""
        their = getattr(context, "their_last_text", None) if context else None

        allow_explicit = getattr(self.config, "allow_explicit", False)
        backoff = getattr(self.config, "backoff_on_disinterest", True)
        refuse_minors = getattr(self.config, "refuse_minors", True)
        refuse_discomfort = getattr(self.config, "refuse_on_discomfort", True)

        # 0) Possible minor -> hard block, regardless of message content.
        if refuse_minors and their and _MINOR.search(their or ""):
            return self._block(
                "hard",
                ["The other person may be a minor — refusing to engage."],
                "minor",
            )

        # 1) Hostility -> always a hard block.
        if _HOSTILE.search(text):
            return self._block(
                "hard", ["Message contains hostile or demeaning language."], "hostility"
            )

        # 2) Deception markers -> hard block.
        if _DECEPTION.search(text):
            return self._block(
                "hard",
                ["Message appears deceptive; OpenDate must stay honest."],
                "deception",
            )

        # 3) Explicit content -> blocked unless allowed AND clearly invited.
        if _EXPLICIT.search(text):
            invited = bool(their and _INVITE.search(their or ""))
            if not (allow_explicit and invited):
                return self._block(
                    "hard",
                    [
                        "Explicit content blocked (not allowed and/or not clearly "
                        "consented to)."
                    ],
                    "explicit",
                )

        # 4) Pressure / coercion -> soft block (don't send; needs a rewrite).
        if _PRESSURE.search(text):
            return self._block(
                "soft", ["Message reads as pressuring; easing off instead."], "pressure"
            )

        # 5) Back off on the other person's signals.
        if context is not None:
            if getattr(context, "hard_stop", False) or (their and _HARD_STOP.search(their)):
                return self._block(
                    "hard",
                    ["They asked to stop / aren't interested — backing off."],
                    "hard-stop",
                )
            if refuse_discomfort and their and _DISCOMFORT.search(their):
                return self._block(
                    "hard",
                    ["They signaled discomfort or withdrawal — backing off."],
                    "discomfort",
                )
            if backoff and getattr(context, "disinterest", False):
                return self._block(
                    "soft",
                    ["Signs of disinterest — backing off rather than pushing."],
                    "disinterest",
                )

        # 6) Optional LLM second-pass review (only refines; never un-blocks above).
        if (
            getattr(self.config, "require_consent_checks", True)
            and self.router is not None
            and not getattr(self.router, "is_stub", False)
        ):
            verdict = self._llm_review(text, context)
            if verdict is not None and not verdict.allowed:
                log.warning("Safety LLM-review block: %s", "; ".join(verdict.reasons))
                return verdict

        return SafetyDecision(allowed=True, severity="ok", reasons=["ok"])

    def _block(self, severity: str, reasons: list[str], category: str) -> SafetyDecision:
        """Build a blocked decision and log it (auditable trail)."""
        log.warning("Safety block [%s/%s]: %s", category, severity, "; ".join(reasons))
        return SafetyDecision(
            allowed=False, severity=severity, reasons=reasons, category=category
        )

    # ------------------------------------------------------------------ #
    # Pacing / rate limits (escalation guard)
    # ------------------------------------------------------------------ #
    def check_pacing(
        self,
        *,
        cooldown_remaining: float = 0.0,
        followups_without_reply: int = 0,
        daily_budget_left: int = 1,
    ) -> SafetyDecision:
        """Block sends that would be spammy (cooldown / daily cap / over-eager).

        Pure inputs (computed by the orchestrator from persisted state) keep the
        guard decoupled from storage while still owning the rate-limit policy.
        """
        if daily_budget_left <= 0:
            return self._block(
                "soft", ["Daily action limit reached — pausing for now."], "rate-limit"
            )
        max_follow = getattr(self.config, "max_followups_without_reply", 2)
        if followups_without_reply > max_follow:
            return self._block(
                "soft",
                [f"Already followed up {followups_without_reply}x without a reply."],
                "escalation",
            )
        if cooldown_remaining > 0:
            return self._block(
                "soft",
                [f"Cooldown active (~{cooldown_remaining:.1f}h before next message)."],
                "cooldown",
            )
        return SafetyDecision(allowed=True, severity="ok", reasons=["pace ok"])

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
