"""Load, list, and *select* dating skills.

A skill is a folder with a ``SKILL.md`` that looks like::

    ---
    name: opener
    description: Writes a personalized first message ...
    when_to_use: Fresh match, no messages yet
    category: Opening
    ---
    # Opener playbook
    ...markdown body...

The engine parses the YAML frontmatter + markdown body, exposes the skills, and
maps a :class:`SituationContext` to the right primary skill plus the
always-active modifier skills (consent/safety, persona style transfer, and
relationship-intent matching).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import yaml

from ..utils.logging import get_logger

__all__ = [
    "Skill",
    "SkillSelection",
    "SituationContext",
    "SkillsEngine",
    "ALWAYS_ACTIVE",
]

log = get_logger("skills.engine")

# Skills that are *always* layered on top of whatever the primary skill is.
ALWAYS_ACTIVE: tuple[str, ...] = (
    "relationship-intent-matching",
    "persona-style-transfer",
    "consent-and-safety",
)


@dataclass(frozen=True)
class Skill:
    """A single loaded skill: frontmatter metadata + markdown playbook."""

    name: str
    description: str
    body: str
    when_to_use: str | None = None
    category: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    path: Path | None = None

    @property
    def fires_when(self) -> str:
        return str(self.metadata.get("fires_when", self.when_to_use or ""))

    def playbook(self) -> str:
        """The full playbook text used to steer the LLM (header + body)."""
        header = f"## Skill: {self.name}\n{self.description}\n"
        return header + "\n" + self.body.strip()


@dataclass(frozen=True)
class SituationContext:
    """A snapshot of a conversation moment, used to pick a skill.

    The orchestrator computes these fields (mostly via simple heuristics) before
    asking the engine to :meth:`SkillsEngine.select` a skill.
    """

    kind: str = "match"  # "candidate" (screening) or "match" (messaging)
    has_match: bool = True
    has_messages: bool = False
    num_messages: int = 0
    last_from_me: bool = False
    days_since_last: float | None = None
    their_last_text: str | None = None
    sentiment: str = "neutral"  # positive | neutral | negative
    playful: bool = False
    banter: bool = False
    disinterest: bool = False
    hard_stop: bool = False
    ready_for_date: bool = False
    rapport_score: float = 0.0
    reengage_after_days: float = 3.0
    deepen_after_messages: int = 6


@dataclass(frozen=True)
class SkillSelection:
    """The result of selection: a primary skill + always-active modifiers."""

    primary: Skill
    modifiers: tuple[Skill, ...]
    reason: str

    def all_skills(self) -> list[Skill]:
        ordered: list[Skill] = [self.primary]
        for mod in self.modifiers:
            if mod.name != self.primary.name:
                ordered.append(mod)
        return ordered

    def combined_playbook(self) -> str:
        return "\n\n---\n\n".join(s.playbook() for s in self.all_skills())

    @property
    def skill_names(self) -> list[str]:
        return [s.name for s in self.all_skills()]


def _default_registry_dir() -> Path:
    return Path(__file__).resolve().parent / "registry"


def parse_skill_md(text: str, path: Path | None = None) -> Skill:
    """Parse a ``SKILL.md`` string (YAML frontmatter + markdown body)."""
    frontmatter: dict[str, object] = {}
    body = text
    stripped = text.lstrip()
    if stripped.startswith("---"):
        # Split on the closing '---' fence.
        after = stripped[3:]
        end = after.find("\n---")
        if end != -1:
            raw_fm = after[:end]
            body = after[end + 4 :]
            loaded = yaml.safe_load(raw_fm) or {}
            if isinstance(loaded, dict):
                frontmatter = loaded
    name = str(frontmatter.get("name") or (path.parent.name if path else "unknown"))
    description = str(frontmatter.get("description", "")).strip()
    when_to_use = frontmatter.get("when_to_use")
    category = frontmatter.get("category")
    return Skill(
        name=name,
        description=description,
        body=body.strip(),
        when_to_use=str(when_to_use) if when_to_use is not None else None,
        category=str(category) if category is not None else None,
        metadata=frontmatter,
        path=path,
    )


class SkillsEngine:
    """Discovers and serves skills, and selects one per conversation moment."""

    def __init__(self, registry_dir: str | Path | None = None) -> None:
        self.registry_dir = (
            Path(registry_dir) if registry_dir else _default_registry_dir()
        )
        self._skills: dict[str, Skill] = {}
        self._loaded = False

    # ------------------------------------------------------------------ #
    # Loading / access
    # ------------------------------------------------------------------ #
    def load_all(self, *, reload: bool = False) -> dict[str, Skill]:
        if self._loaded and not reload:
            return self._skills
        self._skills.clear()
        if not self.registry_dir.exists():
            log.warning("Skills registry not found at %s", self.registry_dir)
            self._loaded = True
            return self._skills
        for skill_md in sorted(self.registry_dir.glob("*/SKILL.md")):
            try:
                skill = parse_skill_md(
                    skill_md.read_text(encoding="utf-8"), path=skill_md
                )
            except Exception as exc:  # noqa: BLE001 - keep loading the rest
                log.warning("Failed to load skill at %s: %s", skill_md, exc)
                continue
            self._skills[skill.name] = skill
        self._loaded = True
        log.debug("Loaded %d skills from %s", len(self._skills), self.registry_dir)
        return self._skills

    @property
    def skills(self) -> dict[str, Skill]:
        return self.load_all()

    def names(self) -> list[str]:
        return sorted(self.skills)

    def get(self, name: str) -> Skill:
        skills = self.load_all()
        if name not in skills:
            raise KeyError(f"Unknown skill {name!r}. Loaded: {', '.join(sorted(skills))}")
        return skills[name]

    def get_or_none(self, name: str) -> Skill | None:
        return self.load_all().get(name)

    def __iter__(self) -> Iterator[Skill]:
        return iter(self.load_all().values())

    def __len__(self) -> int:
        return len(self.load_all())

    def modifiers(self) -> tuple[Skill, ...]:
        return tuple(
            s for n in ALWAYS_ACTIVE if (s := self.get_or_none(n)) is not None
        )

    # ------------------------------------------------------------------ #
    # Selection
    # ------------------------------------------------------------------ #
    def _primary_name(self, ctx: SituationContext) -> tuple[str, str]:
        """Return ``(skill_name, reason)`` for the primary skill."""
        if ctx.kind == "candidate":
            return "profile-screening", "New candidate to evaluate against preferences."

        if not ctx.has_messages:
            return "opener", "Fresh match with no messages — write the first line."

        if ctx.disinterest:
            return (
                "conversation-recovery",
                "Signs of disinterest — recover gracefully and ease off.",
            )

        if ctx.last_from_me and (ctx.days_since_last or 0) >= ctx.reengage_after_days:
            return (
                "re-engagement",
                f"No reply for {ctx.days_since_last:.0f}+ days — revive the thread.",
            )

        if ctx.sentiment == "negative":
            return (
                "conversation-recovery",
                "Flat or negative reply — repair before continuing.",
            )

        if ctx.ready_for_date:
            if ctx.rapport_score >= 0.8:
                return (
                    "number-exchange",
                    "Strong rapport and momentum — move off-app naturally.",
                )
            return "proposing-a-date", "Strong rapport detected — suggest meeting up."

        if ctx.banter:
            return "banter", "They're matching your energy — keep the volley going."
        if ctx.playful:
            return "flirting", "Conversation is warming up — add charm and spark."
        if ctx.num_messages >= ctx.deepen_after_messages:
            return "storytelling", "Time to deepen the connection with a story."
        return "rapport-building", "Getting to know each other — build common ground."

    def select(self, ctx: SituationContext) -> SkillSelection:
        """Choose the primary skill for ``ctx`` plus always-active modifiers."""
        skills = self.load_all()
        name, reason = self._primary_name(ctx)
        primary = skills.get(name)
        if primary is None:
            # Degrade gracefully if a skill file is missing.
            fallback_name = "rapport-building" if "rapport-building" in skills else next(
                iter(skills), None
            )
            if fallback_name is None:
                raise RuntimeError("No skills are loaded; cannot select a skill.")
            log.warning("Skill %r missing; falling back to %r", name, fallback_name)
            primary = skills[fallback_name]
            reason += f" (fell back to {fallback_name})"
        modifiers = tuple(m for m in self.modifiers() if m.name != primary.name)
        return SkillSelection(primary=primary, modifiers=modifiers, reason=reason)
