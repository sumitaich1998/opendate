"""Style transfer: rewrite a draft so it sounds like the user.

Two paths, mirroring the rest of the persona engine:

* **LLM path** — when a real router is available, ask the model to re-voice the
  draft using the persona profile (and the ``persona-style-transfer`` playbook
  as guidance), preserving meaning exactly.
* **Heuristic path** — when there's no LLM (or a stub), apply light,
  meaning-preserving touches (casing, emoji frequency, exclamation habits) so
  the pipeline still works fully offline.
"""

from __future__ import annotations

import re
from typing import Any

from ..utils.logging import get_logger
from .analyze import PersonaProfile, _EMOJI_RE

__all__ = ["StyleTransfer"]

log = get_logger("persona.style")


class StyleTransfer:
    """Rewrites drafts into the user's voice (LLM-backed, heuristic fallback)."""

    def __init__(self, router: Any | None = None, guidance: str = "") -> None:
        self.router = router
        self.guidance = guidance

    def transfer(
        self,
        draft: str,
        persona: PersonaProfile,
        *,
        router: Any | None = None,
        guidance: str | None = None,
    ) -> str:
        draft = (draft or "").strip()
        if not draft:
            return draft
        active_router = router if router is not None else self.router
        active_guidance = guidance if guidance is not None else self.guidance
        if active_router is not None and not getattr(active_router, "is_stub", False):
            try:
                return self._llm_transfer(draft, persona, active_router, active_guidance)
            except Exception as exc:  # noqa: BLE001 - fall back to heuristics
                log.warning("LLM style transfer failed, using heuristics: %s", exc)
        return self._heuristic_transfer(draft, persona)

    # ------------------------------------------------------------------ #
    # LLM path
    # ------------------------------------------------------------------ #
    def _llm_transfer(
        self,
        draft: str,
        persona: PersonaProfile,
        router: Any,
        guidance: str,
    ) -> str:
        system_parts = [
            "You rewrite a dating-app message so it sounds exactly like a specific "
            "person, preserving the meaning and intent precisely. Change only the "
            "voice — never add facts, claims, or change the ask. Return ONLY the "
            "rewritten message, with no quotes or commentary.",
        ]
        if guidance:
            system_parts.append("Playbook:\n" + guidance)
        system_parts.append("The person's voice:\n" + persona.style_brief())
        system = "\n\n".join(system_parts)
        user = (
            "Rewrite this draft in the person's voice (same meaning, their sound):\n"
            f"<<<DRAFT>>>{draft}<<<END>>>"
        )
        result = router.chat(system, user, temperature=0.7, max_tokens=400)
        return self._clean(result, fallback=draft)

    @staticmethod
    def _clean(text: str, *, fallback: str) -> str:
        text = (text or "").strip()
        if not text:
            return fallback
        # Strip code fences and surrounding quotes if the model added them.
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text).strip()
        if len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]:
            text = text[1:-1].strip()
        # Drop a leading "Sure, here's ..." style preface if present.
        lowered = text.lower()
        for prefix in ("sure,", "here's", "here is", "rewritten:", "message:"):
            if lowered.startswith(prefix):
                # Only strip if there's a clear sentence after a colon/newline.
                parts = re.split(r"[:\n]", text, maxsplit=1)
                if len(parts) == 2 and parts[1].strip():
                    text = parts[1].strip()
                break
        return text or fallback

    # ------------------------------------------------------------------ #
    # Heuristic path
    # ------------------------------------------------------------------ #
    def _heuristic_transfer(self, draft: str, persona: PersonaProfile) -> str:
        text = draft.strip()

        # Casing: mirror a strongly lowercase texter.
        if persona.lowercase_ratio >= 0.7:
            text = self._soft_lowercase(text)

        # Exclamation habits.
        if persona.exclamation_rate < 0.15 and text.endswith("!"):
            text = text[:-1] + "."
        elif persona.exclamation_rate >= 0.7 and text.endswith("."):
            text = text[:-1] + "!"

        # Emoji frequency.
        has_emoji = bool(_EMOJI_RE.search(text))
        if persona.emoji_rate < 0.1 and has_emoji:
            text = _EMOJI_RE.sub("", text).strip()
            text = re.sub(r"\s{2,}", " ", text)
        elif persona.emoji_rate >= 0.6 and not has_emoji and persona.emojis:
            text = f"{text} {persona.emojis[0]}"

        return text.strip()

    @staticmethod
    def _soft_lowercase(text: str) -> str:
        """Lowercase the text but keep the solo pronoun 'I' and 'I'm' natural."""
        lowered = text.lower()
        # Restore standalone "i" -> "I" only if the persona would (most lowercase
        # texters keep it lowercase, so we leave it lowercase deliberately).
        return lowered
